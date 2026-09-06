"""Request assembly: plugin options → the volcengine full-request JSON payload.

Pure layer with no I/O — ``build_request_payload`` is a function of the options
alone, so payload shape is unit-testable offline. Transport lives in
``stt.py``; byte framing in ``protocol.py``; result→event mapping in
``_transcript.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

DEFAULT_BASE_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
# 2.0 (recommended): volc.seedasr.sauc.duration / volc.seedasr.sauc.concurrent
# 1.0:               volc.bigasr.sauc.duration / volc.bigasr.sauc.concurrent
DEFAULT_RESOURCE_ID = "volc.seedasr.sauc.duration"

AudioFormat = Literal["pcm", "wav", "ogg", "mp3", "spx", "amr", "aac", "m4a"]


@dataclass
class _STTOptions:
    api_key: str
    resource_id: str
    base_url: str
    model_name: str
    language: str | None
    audio_format: AudioFormat
    codec: Literal["raw", "opus"]
    sample_rate: int
    bits: int
    num_channels: int
    enable_nonstream: bool
    enable_itn: bool
    enable_punc: bool
    enable_ddc: bool
    show_utterances: bool
    result_type: Literal["full", "single"]
    end_window_size: int
    force_to_speech_time: int
    vad_segment_duration: int | None
    enable_accelerate_text: bool
    accelerate_score: int | None
    output_zh_variant: Literal["traditional", "tw", "hk"] | None
    sensitive_words_filter: dict[str, Any] | None
    corpus: dict[str, Any] | None
    # Escape hatch: merged into ``request`` last, so parameters added by the
    # service after this plugin's release remain usable without a new release.
    extra_request_params: dict[str, Any] = field(default_factory=dict)

    def build_request_payload(self, uid: str) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model_name": self.model_name,
            "enable_nonstream": self.enable_nonstream,
            "enable_itn": self.enable_itn,
            "enable_punc": self.enable_punc,
            "enable_ddc": self.enable_ddc,
            "show_utterances": self.show_utterances,
            "result_type": self.result_type,
            "end_window_size": self.end_window_size,
            "force_to_speech_time": self.force_to_speech_time,
        }
        # doc: ignored when end_window_size is set; only send when explicitly given
        if self.vad_segment_duration is not None:
            request["vad_segment_duration"] = self.vad_segment_duration
        if self.enable_accelerate_text:
            request["enable_accelerate_text"] = True
            if self.accelerate_score is not None:
                request["accelerate_score"] = self.accelerate_score
        if self.output_zh_variant is not None:
            request["output_zh_variant"] = self.output_zh_variant
        if self.language is not None:
            request["language"] = self.language
        if self.sensitive_words_filter is not None:
            # doc passes this field as a JSON string
            request["sensitive_words_filter"] = json.dumps(
                self.sensitive_words_filter, ensure_ascii=False
            )
        if self.corpus is not None:
            corpus = dict(self.corpus)
            # the API expects corpus.context as a JSON string (same treatment
            # as sensitive_words_filter); accept a dict for convenience
            if isinstance(corpus.get("context"), (dict, list)):
                corpus["context"] = json.dumps(corpus["context"], ensure_ascii=False)
            request["corpus"] = corpus
        request.update(self.extra_request_params)

        return {
            "user": {"uid": uid},
            "audio": {
                "format": self.audio_format,
                "codec": self.codec,
                "rate": self.sample_rate,
                "bits": self.bits,
                "channel": self.num_channels,
            },
            "request": request,
        }


def apply_updates(opts: _STTOptions, updates: dict[str, Any]) -> None:
    """Apply a given-only ``{field: value}`` mapping onto options.

    Single application point for every hot-swappable field, shared by
    ``STT.update_options`` and ``SpeechStream.update_options`` — adding an
    updatable field means extending the shared call sites, not copying
    per-field ``if`` blocks between two classes.
    """
    for name, value in updates.items():
        if name == "extra_request_params":
            value = dict(value)
        setattr(opts, name, value)
