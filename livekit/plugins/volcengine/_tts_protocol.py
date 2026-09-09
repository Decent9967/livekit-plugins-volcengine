"""V3 TTS event framing, independent of ASR sequence framing.

Protocol: https://docs.volcengine.com/docs/6561/2532486
Event layout also referenced from the Apache-2.0 bytedance V3 TTS adapter.
"""

from __future__ import annotations

import gzip
import io
import json
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

MAX_PAYLOAD = 10 * 1024 * 1024


class Event(IntEnum):
    START_CONNECTION = 1
    FINISH_CONNECTION = 2
    CONNECTION_STARTED = 50
    CONNECTION_FAILED = 51
    CONNECTION_FINISHED = 52
    START_SESSION = 100
    CANCEL_SESSION = 101
    FINISH_SESSION = 102
    SESSION_STARTED = 150
    SESSION_CANCELED = 151
    SESSION_FINISHED = 152
    SESSION_FAILED = 153
    TASK_REQUEST = 200
    TTS_SENTENCE_START = 350
    TTS_SENTENCE_END = 351
    TTS_RESPONSE = 352
    TTS_SUBTITLE = 364


def encode(
    event: Event, *, session_id: str | None = None, payload: dict[str, Any] | None = None
) -> bytes:
    raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    frame = b"\x11\x14\x10\x00" + struct.pack(">i", event)
    if session_id is not None:
        identifier = session_id.encode("utf-8")
        frame += struct.pack(">I", len(identifier)) + identifier
    return frame + struct.pack(">I", len(raw)) + raw


@dataclass(frozen=True)
class Frame:
    event: int
    identifier: str
    payload: bytes
    is_audio: bool
    error_code: int = 0

    def json(self) -> dict[str, Any]:
        value = json.loads(self.payload or b"{}")
        if not isinstance(value, dict):
            raise ValueError("TTS metadata must be a JSON object")
        return value


def decode(data: bytes) -> Frame:
    if len(data) < 4 or data[0] >> 4 != 1:
        raise ValueError("Invalid TTS protocol header")
    offset = (data[0] & 15) * 4
    if offset < 4 or offset > len(data):
        raise ValueError("Invalid TTS header length")
    msg_type, flags = data[1] >> 4, data[1] & 15
    serialization, compression = data[2] >> 4, data[2] & 15
    if msg_type not in (9, 11, 15) or serialization not in (0, 1) or compression not in (0, 1):
        raise ValueError("Unsupported TTS frame encoding")

    def take(size: int) -> bytes:
        nonlocal offset
        if size > len(data) - offset:
            raise ValueError("Truncated TTS frame")
        result = data[offset : offset + size]
        offset += size
        return result

    def uint() -> int:
        return int.from_bytes(take(4), "big")

    event, identifier, error_code = 0, "", 0
    if msg_type == 15:
        error_code = uint()
    else:
        if flags != 4:
            raise ValueError("TTS response must carry an event")
        event = uint()
        identifier = take(uint()).decode("utf-8")
    payload = take(uint())
    if offset != len(data):
        raise ValueError("Trailing bytes in TTS frame")
    if compression == 1:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
                payload = compressed.read(MAX_PAYLOAD + 1)
        except (OSError, EOFError) as exc:
            raise ValueError("Invalid compressed TTS payload") from exc
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("TTS payload exceeds maximum size")
    return Frame(event, identifier, payload, msg_type == 11, error_code)
