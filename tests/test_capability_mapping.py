import json
import logging
from pathlib import Path

import pytest
from livekit.agents import stt
from livekit.agents.utils import aio

from livekit.plugins.volcengine import STT
from livekit.plugins.volcengine._transcript import TranscriptMapper


@pytest.mark.parametrize("speaker", ["0", 0, "1", None, {}, True])
@pytest.mark.parametrize("definite", [False, True])
async def test_speaker_in_additions_survives_finalization(speaker, definite):
    channel = aio.Chan()
    mapper = TranscriptMapper(channel, "request")
    mapper.handle_result(
        {
            "utterances": [
                {"text": "hello", "definite": definite, "additions": {"speaker_id": speaker}}
            ]
        },
        start_time_offset=0,
        language="en",
    )
    mapper.commit_pending(start_time_offset=0, language="en")
    channel.close()
    events = [e async for e in channel if e.alternatives]
    expected = str(speaker) if type(speaker) in (str, int) else None
    assert events[-1].type == stt.SpeechEventType.FINAL_TRANSCRIPT
    assert all(e.alternatives[0].speaker_id == expected for e in events)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("speech_mand", "zh-CN"),
        ("speech_en", "en"),
        ("other_langs", "fr"),
        ("future_label", "fr"),
        (None, "fr"),
        ({}, "fr"),
    ],
)
async def test_detected_language_and_unknown_fallback(label, expected):
    channel = aio.Chan()
    mapper = TranscriptMapper(channel, "request")
    mapper.handle_result(
        {"utterances": [{"text": "hello", "definite": False, "additions": {"lid_lang": label}}]},
        start_time_offset=0,
        language="fr",
    )
    mapper.commit_pending(start_time_offset=0, language="de")
    channel.close()
    languages = [e.alternatives[0].language async for e in channel if e.alternatives]
    assert languages and all(value == expected for value in languages)


def test_typed_options_preserve_defaults_and_escape_override():
    request = STT(api_key="k")._opts.build_request_payload("u")["request"]
    assert "enable_speaker_info" not in request and "enable_lid" not in request
    provider = STT(
        api_key="k",
        enable_speaker_info=True,
        enable_lid=True,
        extra_request_params={"enable_lid": False},
    )
    request = provider._opts.build_request_payload("u")["request"]
    assert request["enable_speaker_info"] is True and request["enable_lid"] is False
    provider.update_options(enable_speaker_info=False, enable_lid=False)
    assert provider._opts.enable_speaker_info is False


def test_capability_updates_forward_to_existing_streams():
    class ExistingStream:
        def __init__(self):
            self.updates = []

        def update_options(self, **updates):
            self.updates.append(updates)

    provider = STT(api_key="k")
    stream = ExistingStream()
    provider._streams.add(stream)
    provider.update_options(enable_speaker_info=True, enable_lid=True)
    provider.update_options(enable_speaker_info=False, enable_lid=False)
    assert stream.updates == [
        {"enable_speaker_info": True, "enable_lid": True},
        {"enable_speaker_info": False, "enable_lid": False},
    ]


async def test_log_id_correlates_without_logging_transcript(caplog):
    mapper = TranscriptMapper(aio.Chan(), "request")
    with caplog.at_level(logging.DEBUG, logger="livekit.plugins.volcengine"):
        mapper.handle_result(
            {"additions": {"log_id": "provider-id"}, "text": "private text"},
            start_time_offset=0,
            language="en",
        )
    records = [r for r in caplog.records if getattr(r, "log_id", None) == "provider-id"]
    assert records and records[0].request_id == "request"
    assert "private text" not in caplog.text


def test_current_speaker_requirements(caplog):
    with caplog.at_level(logging.WARNING, logger="livekit.plugins.volcengine"):
        STT(api_key="k", enable_speaker_info=True)
    assert not caplog.records
    with caplog.at_level(logging.WARNING, logger="livekit.plugins.volcengine"):
        STT(api_key="k", enable_speaker_info=True, show_utterances=False)
    assert any("speaker separation" in r.message for r in caplog.records)


async def test_live_bilingual_fixture_maps_four_final_sentences():
    responses = json.loads(
        (Path(__file__).parent / "fixtures/synthetic-bilingual.json").read_text(encoding="utf-8")
    )
    channel = aio.Chan()
    mapper = TranscriptMapper(channel, "request")
    for response in responses:
        result = response.get("result")
        if isinstance(result, dict):
            mapper.handle_result(result, start_time_offset=0, language="zh-CN")
    channel.close()
    finals = [
        e.alternatives[0] async for e in channel if e.type == stt.SpeechEventType.FINAL_TRANSCRIPT
    ]
    assert [e.speaker_id for e in finals] == ["0", "0", "1", "1"]
    assert [e.language for e in finals] == ["zh-CN", "zh-CN", "en", "en"]
