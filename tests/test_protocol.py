import gzip
import json
import struct

from livekit.plugins.volcengine import protocol as p


def test_full_client_request_layout():
    payload = {"user": {"uid": "u1"}, "request": {"model_name": "bigmodel"}}
    frame = p.build_full_client_request(payload, sequence=1)

    assert frame[0] >> 4 == p.PROTOCOL_VERSION
    assert frame[0] & 0x0F == 1  # header size in 4-byte units
    assert frame[1] >> 4 == p.FULL_CLIENT_REQUEST
    assert frame[1] & 0x0F == p.POS_SEQUENCE
    assert frame[2] >> 4 == p.SERIAL_JSON
    assert frame[2] & 0x0F == p.COMPRESS_GZIP

    seq = struct.unpack(">i", frame[4:8])[0]
    size = struct.unpack(">I", frame[8:12])[0]
    body = gzip.decompress(frame[12 : 12 + size])
    assert seq == 1
    assert json.loads(body) == payload


def test_audio_only_request_last_flag_flips_sequence():
    frame = p.build_audio_only_request(b"audio-bytes", sequence=7, last=True)
    assert frame[1] >> 4 == p.AUDIO_ONLY_REQUEST
    assert frame[1] & 0x0F == p.NEG_WITH_SEQUENCE
    seq = struct.unpack(">i", frame[4:8])[0]
    assert seq == -7
    assert gzip.decompress(frame[12:]) == b"audio-bytes"

    normal = p.build_audio_only_request(b"x", sequence=7, last=False)
    assert normal[1] & 0x0F == p.POS_SEQUENCE
    assert struct.unpack(">i", normal[4:8])[0] == 7


def _server_frame(message_type: int, flags: int, body: bytes) -> bytes:
    header = bytes(
        [
            (p.PROTOCOL_VERSION << 4) | 1,
            (message_type << 4) | flags,
            (p.SERIAL_JSON << 4) | p.COMPRESS_GZIP,
            0,
        ]
    )
    return header + body


def test_parse_full_response():
    payload = gzip.compress(json.dumps({"result": [{"text": "你好"}]}).encode())
    body = (
        struct.pack(">i", 3)  # payload sequence
        + struct.pack(">I", len(payload))
        + payload
    )
    frame = _server_frame(p.SERVER_FULL_RESPONSE, p.POS_SEQUENCE, body)

    msg = p.parse_server_message(frame)
    assert msg.message_type == p.SERVER_FULL_RESPONSE
    assert msg.sequence == 3
    assert not msg.is_last
    assert isinstance(msg.payload, dict)
    assert msg.payload["result"][0]["text"] == "你好"


def test_parse_last_package_flag():
    frame = _server_frame(p.SERVER_FULL_RESPONSE, p.FLAG_LAST_PACKAGE, b"")
    msg = p.parse_server_message(frame)
    assert msg.is_last


def test_parse_error_frame():
    payload = gzip.compress(json.dumps({"message": "quota exceeded"}).encode())
    body = struct.pack(">i", 4500003) + struct.pack(">I", len(payload)) + payload
    frame = _server_frame(p.SERVER_ERROR_RESPONSE, 0, body)

    msg = p.parse_server_message(frame)
    assert msg.message_type == p.SERVER_ERROR_RESPONSE
    assert msg.error_code == 4500003
    assert msg.payload == {"message": "quota exceeded"}


def test_parse_ack_without_payload():
    body = struct.pack(">i", 12)
    frame = _server_frame(p.SERVER_ACK, p.POS_SEQUENCE, body)
    msg = p.parse_server_message(frame)
    assert msg.sequence == 12
    assert msg.error_code is None
