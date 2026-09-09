import asyncio
import gzip
import json
import struct
from pathlib import Path

import aiohttp
import pytest
from livekit.agents import APIConnectionError, APIStatusError
from test_stt import RunFakeStream, ScriptedWS, _error_frame, _result_frame, _ws_message

from livekit import rtc
from livekit.plugins.volcengine.stt import STT, SpeechStream


def test_provider_identity_is_available_to_backend_metrics():
    provider = STT(api_key="test-key", resource_id="volc.seedasr.sauc.duration")
    assert provider.model == "volc.seedasr.sauc.duration"
    assert provider.provider == "volcengine"


@pytest.mark.parametrize("as_list", [False, True])
async def test_current_backend_and_documented_result_shapes(as_list):
    fake = RunFakeStream(ScriptedWS([]))
    result = {"utterances": [{"text": "推荐一件外套", "definite": True}]}
    fake._handle_server_message(_result_frame({"result": [result] if as_list else result}))
    fake._event_ch.close()
    events = [event async for event in fake._event_ch]
    assert [e.alternatives[0].text for e in events if e.type.name == "FINAL_TRANSCRIPT"] == [
        "推荐一件外套"
    ]


async def test_repeated_definite_does_not_submit_twice():
    fake = RunFakeStream(ScriptedWS([]))
    result = {"utterances": [{"text": "你好", "definite": True, "end_time": 800}]}
    fake.emit(result)
    fake.emit(result)
    fake._event_ch.close()
    events = [event async for event in fake._event_ch]
    assert sum(event.type.name == "FINAL_TRANSCRIPT" for event in events) == 1


async def test_same_sentence_after_reconnect_is_a_new_final():
    fake = RunFakeStream(ScriptedWS([]))
    result = {"utterances": [{"text": "你好", "definite": True, "end_time": 800}]}
    fake.emit(result)
    fake._transcript.start_connection()
    fake.emit(result)
    fake._event_ch.close()
    events = [event async for event in fake._event_ch]
    assert sum(event.type.name == "FINAL_TRANSCRIPT" for event in events) == 2


async def test_flush_at_exact_chunk_boundary_still_sends_terminal_packet():
    ws = ScriptedWS([])
    fake = RunFakeStream(ws)
    fake._input_ch.send_nowait(
        rtc.AudioFrame(
            data=b"\0" * 3200, sample_rate=16000, num_channels=1, samples_per_channel=1600
        )
    )
    fake._input_ch.send_nowait(fake._FlushSentinel())
    fake._input_ch.close()
    await SpeechStream._run(fake)
    audio_frames = ws.sent[1:]
    assert audio_frames[-1][1] & 2
    assert struct.unpack(">i", audio_frames[-1][4:8])[0] < 0
    audio = b"".join(gzip.decompress(frame[12:]) for frame in audio_frames)
    assert audio == b"\0" * 3200


async def test_socket_error_is_retryable():
    ws = ScriptedWS([_ws_message(aiohttp.WSMsgType.ERROR, None)], hold_open=True)
    fake = RunFakeStream(ws)
    with pytest.raises(APIConnectionError):
        await asyncio.wait_for(SpeechStream._run(fake), timeout=0.2)
    assert ws.closed


async def test_server_error_preserves_structured_code():
    fake = RunFakeStream(ScriptedWS([]))
    with pytest.raises(APIStatusError) as caught:
        fake._handle_server_message(_error_frame(4500003))
    assert caught.value.status_code == 4500003


async def test_empty_utterance_does_not_reuse_previous_result_text():
    fake = RunFakeStream(ScriptedWS([]))
    fake.emit({"utterances": [{"text": "嗯", "definite": False}]})
    fake.emit({"text": "嗯", "utterances": [{"text": "", "definite": True}]})
    fake._event_ch.close()
    events = [event async for event in fake._event_ch]
    assert not any(event.type.name == "FINAL_TRANSCRIPT" for event in events)
    assert events[-1].type.name == "END_OF_SPEECH"


async def test_real_service_synthetic_shopping_fixture():
    fake = RunFakeStream(ScriptedWS([]))
    records = json.loads(
        (Path(__file__).parent / "fixtures" / "synthetic-shopping.json").read_text(encoding="utf-8")
    )
    for record in records:
        fake._handle_server_message(_result_frame({"result": record["result"]}))
    fake._event_ch.close()
    events = [event async for event in fake._event_ch]
    finals = [
        event.alternatives[0].text for event in events if event.type.name == "FINAL_TRANSCRIPT"
    ]
    assert finals == [
        "你好，请帮我推荐一件适合秋天穿的外套。",
        "我喜欢蓝色，预算是500元。",
    ]
    assert sum(event.type.name == "END_OF_SPEECH" for event in events) == 2
