import gzip
import json
import struct
from pathlib import Path

import pytest

from livekit.plugins.volcengine._tts_protocol import Event, decode, encode


def response(event, payload=b"{}", *, identifier="session", audio=False, compression=0):
    raw_id = identifier.encode()
    return (
        bytes([0x11, 0xB4 if audio else 0x94, (0 if audio else 0x10) | compression, 0])
        + struct.pack(">iI", event, len(raw_id))
        + raw_id
        + struct.pack(">I", len(payload))
        + payload
    )


def test_connection_request_has_no_identifier():
    assert encode(Event.START_CONNECTION) == bytes.fromhex("1114100000000001000000027b7d")


def test_session_request_carries_id_and_utf8_payload():
    data = encode(Event.TASK_REQUEST, session_id="abc", payload={"text": "你好"})
    assert data[:15] == bytes.fromhex("11141000000000c800000003616263")
    assert json.loads(data[19:]) == {"text": "你好"}
    assert int.from_bytes(data[15:19], "big") == len(data[19:])


def test_audio_and_compressed_metadata():
    audio = decode(response(Event.TTS_RESPONSE, b"\x00\x01", audio=True))
    assert audio.is_audio and audio.payload == b"\x00\x01"
    assert audio.identifier == "session"
    meta = decode(response(Event.SESSION_FINISHED, gzip.compress(b'{"usage":{}}'), compression=1))
    assert meta.json() == {"usage": {}}


def test_error_frame_without_event_or_session():
    frame = decode(bytes.fromhex("11f01000") + struct.pack(">II", 45000001, 2) + b"{}")
    assert frame.error_code == 45000001


@pytest.mark.parametrize("length", range(0, 22))
def test_rejects_truncated_frames(length):
    with pytest.raises(ValueError):
        decode(response(Event.SESSION_STARTED)[:length])


def test_rejects_trailing_bytes_and_unsupported_compression():
    for data in (response(150) + b"x", response(150, compression=2)):
        with pytest.raises(ValueError):
            decode(data)


def test_rejects_non_object_metadata():
    with pytest.raises(ValueError):
        decode(response(150, b"[]")).json()


def test_matches_official_protocol_attachment_requests():
    fixtures = json.loads(
        (Path(__file__).parent / "fixtures/tts_official_requests.json").read_text(encoding="utf-8")
    )
    for fixture in fixtures["requests"]:
        event = Event(fixture["event"])
        sid = "fixture-session" if event >= 100 else None
        assert encode(event, session_id=sid) == bytes.fromhex(fixture["hex"])
