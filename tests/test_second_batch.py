import json
from pathlib import Path

import pytest
from livekit.agents import stt
from livekit.agents.utils import aio

from livekit.plugins.volcengine import STT
from livekit.plugins.volcengine._transcript import TranscriptMapper

FLAGS = (
    "show_speech_rate",
    "show_volume",
    "enable_emotion_detection",
    "enable_gender_detection",
    "enable_age_detection",
)


@pytest.mark.parametrize("flag", FLAGS)
def test_metadata_option_defaults_overrides_and_updates(flag):
    assert flag not in STT(api_key="k")._opts.build_request_payload("u")["request"]
    provider = STT(api_key="k", **{flag: True})
    assert provider._opts.build_request_payload("u")["request"][flag] is True
    provider.update_options(**{flag: False})
    assert flag not in provider._opts.build_request_payload("u")["request"]
    provider = STT(api_key="k", **{flag: True}, extra_request_params={flag: False})
    assert provider._opts.build_request_payload("u")["request"][flag] is False


@pytest.mark.parametrize("definite", [False, True])
async def test_observed_metadata_survives_pending_final(definite):
    channel = aio.Chan()
    mapper = TranscriptMapper(channel, "test")
    additions = {
        "age": "43.7",
        "speech_rate": "2.65",
        "volume": "74.7",
        "gender": "female",
        "gender_score": "0.99",
        "emotion": "neutral",
        "emotion_score": "0.96",
        "emotion_degree": "weak",
        "emotion_degree_score": "0.99",
        "lid_lang": "speech_dia_cant",
        "lid_lang_score": "0.9",
        "unknown": "drop",
    }
    mapper.handle_result(
        {"utterances": [{"text": "hello", "definite": definite, "additions": additions}]},
        start_time_offset=0,
        language="en",
    )
    mapper.commit_pending(start_time_offset=0, language="en")
    channel.close()
    events = [e async for e in channel if e.alternatives]
    assert sum(e.type == stt.SpeechEventType.FINAL_TRANSCRIPT for e in events) == 1
    values = [e.alternatives[0].metadata for e in events]
    expected = {
        "volcengine": dict(
            additions,
            age=43.7,
            speech_rate=2.65,
            volume=74.7,
            gender_score=0.99,
            emotion_score=0.96,
            emotion_degree_score=0.99,
            lid_lang_score=0.9,
        )
    }
    del expected["volcengine"]["unknown"]
    assert values and all(value == expected for value in values)


@pytest.mark.parametrize("bad", [None, True, {}, [], "NaN", "Infinity", "invalid"])
async def test_bad_numeric_metadata_is_omitted(bad):
    channel = aio.Chan()
    mapper = TranscriptMapper(channel, "test")
    mapper.handle_result(
        {
            "utterances": [
                {
                    "text": "hello",
                    "definite": True,
                    "additions": {
                        "age": bad,
                        "volume": bad,
                        "speech_rate": bad,
                        "emotion_score": bad,
                    },
                }
            ]
        },
        start_time_offset=0,
        language="en",
    )
    channel.close()
    assert [e.alternatives[0].metadata async for e in channel if e.alternatives] == [None]


def test_full_profile_does_not_warn_after_live_validation(caplog):
    STT(api_key="k", result_type="full")
    assert not caplog.records


@pytest.mark.parametrize("name", ["single", "full", "full-repeat"])
async def test_live_full_and_single_have_balanced_ordered_finals(name):
    data = json.loads(
        (Path(__file__).parent / f"fixtures/batch2-{name}.json").read_text(encoding="utf-8")
    )
    channel = aio.Chan()
    mapper = TranscriptMapper(channel, "fixture")
    for response in data["responses"]:
        result = response["payload"].get("result")
        for item in [result] if isinstance(result, dict) else result or []:
            mapper.handle_result(item, start_time_offset=0, language="zh-CN")
    mapper.commit_pending(start_time_offset=0, language="zh-CN")
    channel.close()
    events = [e async for e in channel]
    expected = ["你好，请帮我推荐一件适合秋天穿的外套。", "我喜欢蓝色，预算是500元。"]
    if name == "full-repeat":
        expected *= 2
    assert [
        e.alternatives[0].text for e in events if e.type == stt.SpeechEventType.FINAL_TRANSCRIPT
    ] == expected
    starts = sum(e.type == stt.SpeechEventType.START_OF_SPEECH for e in events)
    ends = sum(e.type == stt.SpeechEventType.END_OF_SPEECH for e in events)
    assert starts == ends == len(expected)


async def test_real_metadata_fixture_reaches_final_event():
    data = json.loads(
        (Path(__file__).parent / "fixtures/batch2-metadata.json").read_text(encoding="utf-8")
    )
    channel = aio.Chan()
    mapper = TranscriptMapper(channel, "fixture")
    for response in data["responses"]:
        result = response["payload"].get("result")
        if isinstance(result, dict):
            mapper.handle_result(result, start_time_offset=0, language="zh-CN")
    channel.close()
    finals = [
        e.alternatives[0] async for e in channel if e.type == stt.SpeechEventType.FINAL_TRANSCRIPT
    ]
    assert len(finals) == 2
    first = finals[0].metadata["volcengine"]
    assert first["speech_rate"] == pytest.approx(3.2123960695389266)
    assert first["volume"] == pytest.approx(76.46910524399544)
    assert first["age"] == pytest.approx(43.143409729003906)
    assert first["gender"] == "female" and first["emotion"] == "neutral"
