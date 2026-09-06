"""Binary framing for the Volcengine v3 ``bigmodel_async`` streaming ASR WebSocket API.

Frame layout (little-endian bitfields, big-endian integers), per the public API
reference (https://docs.volcengine.com/docs/6561/2630027) and the official
``sauc_python`` demo:

========  =====  ==========================================================
bytes     field  meaning
========  =====  ==========================================================
0         hi     protocol version (4b) | header size in 4-byte units (4b)
1         hi     message type (4b) | message-type-specific flags (4b)
2         hi     serialization method (4b) | compression (4b)
3         rsv    reserved, 0x00
========  =====  ==========================================================

After the header, ordered by the flags/message type:

- ``flags & 0x01``: 4-byte signed payload sequence
- ``flags & 0x02``: marks the last package of the stream
- ``flags & 0x04``: 4-byte event number (used by the TTS-style variants)
- ``SERVER_FULL_RESPONSE``: 4-byte payload size, then payload
- ``SERVER_ERROR_RESPONSE``: 4-byte signed error code, 4-byte payload size,
  then payload
- payload is gzip-compressed JSON when the compression nibble says so

All client requests use protocol version 1, JSON serialization and gzip
compression, matching the official demo.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass

PROTOCOL_VERSION = 0b0001
HEADER_SIZE_UNITS = 0b0001

# client message types
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_REQUEST = 0b0010

# server message types
SERVER_FULL_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111

# message-type-specific flags
FLAG_HAS_SEQUENCE = 0b01
FLAG_LAST_PACKAGE = 0b10
FLAG_HAS_EVENT = 0b100
NO_SEQUENCE = 0b0000
POS_SEQUENCE = 0b0001
NEG_WITH_SEQUENCE = 0b0011

# serialization / compression nibbles
SERIAL_JSON = 0b0001
COMPRESS_GZIP = 0b0001


def _header(
    message_type: int, flags: int, *, serial: int = SERIAL_JSON, compression: int = COMPRESS_GZIP
) -> bytes:
    return bytes(
        [
            (PROTOCOL_VERSION << 4) | HEADER_SIZE_UNITS,
            (message_type << 4) | flags,
            (serial << 4) | compression,
            0,
        ]
    )


def _wrap(message_type: int, flags: int, sequence: int, payload: bytes) -> bytes:
    frame = bytearray(_header(message_type, flags))
    frame += sequence.to_bytes(4, "big", signed=True)
    frame += len(payload).to_bytes(4, "big", signed=False)
    frame += payload
    return bytes(frame)


def build_full_client_request(payload: dict, sequence: int) -> bytes:
    """Build the initial request frame carrying the full request config as JSON."""
    return _wrap(
        FULL_CLIENT_REQUEST,
        POS_SEQUENCE,
        sequence,
        gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
    )


def build_audio_only_request(audio: bytes, sequence: int, *, last: bool) -> bytes:
    """Build an audio chunk frame; the last chunk flips the sequence negative."""
    return _wrap(
        AUDIO_ONLY_REQUEST,
        NEG_WITH_SEQUENCE if last else POS_SEQUENCE,
        -sequence if last else sequence,
        gzip.compress(audio),
    )


@dataclass(frozen=True)
class ServerMessage:
    """Parsed server frame; ``payload`` is a decoded dict when JSON, else raw bytes."""

    message_type: int
    is_last: bool
    sequence: int | None
    event: int | None
    error_code: int | None
    payload: dict | bytes | None


def parse_server_message(data: bytes) -> ServerMessage:
    header_units = data[0] & 0x0F
    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    serial = data[2] >> 4
    compression = data[2] & 0x0F
    body = data[header_units * 4 :]

    sequence: int | None = None
    event: int | None = None
    error_code: int | None = None
    is_last = bool(flags & FLAG_LAST_PACKAGE)

    if flags & FLAG_HAS_SEQUENCE:
        sequence = int.from_bytes(body[:4], "big", signed=True)
        body = body[4:]
    if flags & FLAG_HAS_EVENT:
        event = int.from_bytes(body[:4], "big", signed=True)
        body = body[4:]

    if message_type == SERVER_FULL_RESPONSE:
        size = int.from_bytes(body[:4], "big", signed=False)
        body = body[4 : 4 + size]
    elif message_type == SERVER_ERROR_RESPONSE:
        error_code = int.from_bytes(body[:4], "big", signed=True)
        size = int.from_bytes(body[4:8], "big", signed=False)
        body = body[8 : 8 + size]
    elif message_type == SERVER_ACK:
        # ack: sequence already consumed above when flagged; optional size+payload
        if len(body) >= 4:
            size = int.from_bytes(body[:4], "big", signed=False)
            body = body[4 : 4 + size]
    else:
        body = b""

    if compression == COMPRESS_GZIP and body:
        body = gzip.decompress(body)

    payload: dict | bytes | None = body
    if serial == SERIAL_JSON and body:
        payload = json.loads(body.decode("utf-8"))

    return ServerMessage(
        message_type=message_type,
        is_last=is_last,
        sequence=sequence,
        event=event,
        error_code=error_code,
        payload=payload,
    )
