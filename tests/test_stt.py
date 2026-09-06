import asyncio
import json
from types import SimpleNamespace

import pytest
from livekit.agents.utils import aio

from livekit.plugins.volcengine.stt import STT, SpeechStream


@pytest.fixture
async def stream_emitter():
    """A lightweight stand-in for SpeechStream exposing only what _emit_result uses.

    The real base class starts its main task (and the WebSocket connection) on
    construction, so event mapping is unit-tested against this stub instead.
    """
    events = aio.Chan()
    fake = SimpleNamespace(_event_ch=events, _speaking=False, _request_id="test-req")
    collected: list = []

    async def collect():
        async for event in events:
            collected.append(event)

    task = asyncio.get_running_loop().create_task(collect())
    yield fake, collected
    events.close()
    await task


def emit(stream, result: dict) -> None:
    SpeechStream._emit_result(stream, result)


async def flush() -> None:
    """Let the collector task drain queued events before asserting."""
    for _ in range(3):
        await asyncio.sleep(0)


async def test_interim_then_final_flow(stream_emitter):
    stream, collected = stream_emitter

    emit(
        stream,
        {
            "text": "你",
            "utterances": [{"text": "你", "definite": False, "start_time": 0, "end_time": 200}],
        },
    )
    emit(
        stream,
        {
            "text": "你好",
            "utterances": [{"text": "你好", "definite": True, "start_time": 0, "end_time": 500}],
        },
    )

    await flush()
    types = [e.type.name for e in collected]
    assert types == [
        "START_OF_SPEECH",
        "INTERIM_TRANSCRIPT",
        "FINAL_TRANSCRIPT",
        "END_OF_SPEECH",
    ]


async def test_empty_definite_still_ends_utterance(stream_emitter):
    """Empty two-pass final must close the turn — dropping it stalls detection."""
    stream, collected = stream_emitter

    emit(
        stream,
        {
            "text": "喂",
            "utterances": [{"text": "喂", "definite": False, "start_time": 0, "end_time": 300}],
        },
    )
    emit(
        stream,
        {
            "text": "",
            "utterances": [{"text": "", "definite": True, "start_time": 300, "end_time": 900}],
        },
    )

    await flush()
    types = [e.type.name for e in collected]
    assert "FINAL_TRANSCRIPT" not in types  # nothing to finalize
    assert types[-1] == "END_OF_SPEECH"


async def test_multiple_utterances_are_traversed(stream_emitter):
    """Every utterance emits, not only the first."""
    stream, collected = stream_emitter

    emit(
        stream,
        {
            "text": "a",
            "utterances": [
                {"text": "a", "definite": True, "start_time": 0, "end_time": 1},
                {"text": "b", "definite": True, "start_time": 2, "end_time": 3},
            ],
        },
    )

    await flush()
    finals = [e for e in collected if e.type.name == "FINAL_TRANSCRIPT"]
    assert [e.alternatives[0].text for e in finals] == ["a", "b"]


async def test_interim_without_speaking_emits_start(stream_emitter):
    """A definite-final-only flow still opens speech before closing it."""
    stream, collected = stream_emitter

    emit(
        stream,
        {
            "text": "直接结束",
            "utterances": [
                {"text": "直接结束", "definite": True, "start_time": 0, "end_time": 100}
            ],
        },
    )

    await flush()
    types = [e.type.name for e in collected]
    assert types == ["START_OF_SPEECH", "FINAL_TRANSCRIPT", "END_OF_SPEECH"]


def test_request_payload_defaults():
    plugin = STT(api_key="k")
    payload = plugin._opts.build_request_payload(uid="u1")

    assert payload["user"]["uid"] == "u1"
    req = payload["request"]
    assert req["model_name"] == "bigmodel"
    assert req["enable_nonstream"] is True
    assert req["enable_itn"] is True  # doc default
    assert req["result_type"] == "single"
    assert req["force_to_speech_time"] == 1000
    assert "vad_segment_duration" not in req  # only sent when explicit
    assert "language" not in req  # default zh-CN model chosen server-side


def test_extra_request_params_escape_hatch():
    plugin = STT(
        api_key="k",
        extra_request_params={"enable_speaker_info": True, "ssd_version": "200"},
    )
    req = plugin._opts.build_request_payload(uid="u")["request"]
    assert req["enable_speaker_info"] is True
    assert req["ssd_version"] == "200"


def test_sensitive_words_filter_serialized_as_string():
    plugin = STT(api_key="k", sensitive_words_filter={"system_reserved_filter": True})
    req = plugin._opts.build_request_payload(uid="u")["request"]
    assert json.loads(req["sensitive_words_filter"]) == {"system_reserved_filter": True}


def test_accelerate_score_requires_flag():
    with pytest.raises(ValueError):
        STT(api_key="k", accelerate_score=10)


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    with pytest.raises(ValueError):
        STT()
