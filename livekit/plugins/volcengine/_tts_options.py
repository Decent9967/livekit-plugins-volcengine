"""PCM TTS request assembly; no LiveKit or transport dependencies."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TTSOptions:
    speaker: str
    sample_rate: int = 24000
    speech_rate: int = 0
    loudness_rate: int = 0
    model: str | None = None
    context_texts: list[str] | None = None
    additions: dict[str, Any] = field(default_factory=dict)
    extra_request_params: dict[str, Any] = field(default_factory=dict)
    enable_subtitle: bool | None = None
    max_length_to_filter_parenthesis: int | None = None
    disable_markdown_filter: bool | None = None
    disable_emoji_filter: bool | None = None
    latex_parser: str | None = None
    explicit_language: str | None = None
    explicit_dialect: str | None = None
    aigc_watermark: bool | None = None
    pitch: int | None = None
    section_id: str | None = None
    pronunciation_dict: dict[str, list[str]] | None = None

    def __post_init__(self) -> None:
        if not self.speaker.strip():
            raise ValueError("speaker must be a non-empty voice ID")
        if self.sample_rate not in (8000, 16000, 22050, 24000, 32000, 44100, 48000):
            raise ValueError("Unsupported PCM sample_rate")
        for name in ("speech_rate", "loudness_rate"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not -50 <= value <= 100:
                raise ValueError(f"{name} must be an integer between -50 and 100")
        reserved = {"text", "speaker", "audio_params", "model", "additions"}
        if reserved.intersection(self.extra_request_params):
            raise ValueError("Use named parameters for text/speaker/audio_params/model/additions")
        if self.model and (self.context_texts or self.additions.get("context_texts")):
            raise ValueError("model and context_texts cannot be combined")
        for name in ("context_texts", "additions", "extra_request_params", "pronunciation_dict"):
            object.__setattr__(self, name, copy.deepcopy(getattr(self, name)))
        # Fail before opening a socket if escape-hatch values cannot be encoded.
        self.request()

    def request(self, text: str | None = None) -> dict[str, Any]:
        request = copy.deepcopy(self.extra_request_params)
        request.update(
            speaker=self.speaker,
            audio_params={
                "format": "pcm",
                "sample_rate": self.sample_rate,
                "speech_rate": self.speech_rate,
                "loudness_rate": self.loudness_rate,
            },
        )
        if self.enable_subtitle is not None:
            if type(self.enable_subtitle) is not bool:
                raise ValueError("enable_subtitle must be a bool")
            request["audio_params"]["enable_subtitle"] = self.enable_subtitle
        if self.model:
            request["model"] = self.model
        additions = copy.deepcopy(self.additions)
        if self.context_texts is not None:
            additions["context_texts"] = self.context_texts
        for name in (
            "max_length_to_filter_parenthesis",
            "disable_markdown_filter",
            "disable_emoji_filter",
            "latex_parser",
            "explicit_language",
            "explicit_dialect",
            "aigc_watermark",
            "section_id",
            "pronunciation_dict",
        ):
            value = getattr(self, name)
            if value is not None:
                additions[name] = copy.deepcopy(value)
        if self.pitch is not None:
            post_process = additions.setdefault("post_process", {})
            if not isinstance(post_process, dict):
                raise ValueError("post_process must be an object")
            post_process["pitch"] = self.pitch
        _validate_additions(additions)
        if additions:
            request["additions"] = json.dumps(additions, ensure_ascii=False, allow_nan=False)
        if text is not None:
            request["text"] = text
        json.dumps(request, allow_nan=False)
        return request


def _validate_additions(values: dict[str, Any]) -> None:
    for name in ("disable_markdown_filter", "disable_emoji_filter", "aigc_watermark"):
        if name in values and type(values[name]) is not bool:
            raise ValueError(f"{name} must be a bool")
    length = values.get("max_length_to_filter_parenthesis")
    if length is not None and (type(length) is not int or length < 0):
        raise ValueError("max_length_to_filter_parenthesis must be a non-negative integer")
    if "latex_parser" in values:
        if values["latex_parser"] != "v2" or values.get("disable_markdown_filter") is not True:
            raise ValueError("latex_parser requires v2 and disable_markdown_filter=True")
    languages = {
        "zh-cn",
        "en",
        "ja",
        "es-mx",
        "id",
        "pt-br",
        "pt",
        "ko",
        "it",
        "de",
        "fr",
        "th",
        "vi",
        "ru",
        "fil",
        "ms",
        "ar",
        "pl",
        "tr",
        "sv",
    }
    dialects = {"beijing", "dongbei", "henan", "shaanxi", "shanghai", "sichuan", "tianjin", "yue"}
    for name, allowed in (("explicit_language", languages), ("explicit_dialect", dialects)):
        if name in values and (not isinstance(values[name], str) or values[name] not in allowed):
            raise ValueError(f"Unsupported {name}")
    if "section_id" in values and (
        not isinstance(values["section_id"], str) or not values["section_id"].strip()
    ):
        raise ValueError("section_id must be a non-empty string")
    if "post_process" in values:
        post = values["post_process"]
        if not isinstance(post, dict):
            raise ValueError("post_process must be an object")
        if "pitch" in post and (type(post["pitch"]) is not int or not -12 <= post["pitch"] <= 12):
            raise ValueError("pitch must be an integer between -12 and 12")
    if "pronunciation_dict" in values:
        dictionary = values["pronunciation_dict"]
        if not isinstance(dictionary, dict) or set(dictionary) != {"tone"}:
            raise ValueError("pronunciation_dict must contain tone rules")
        rules = dictionary["tone"]
        if not isinstance(rules, list) or len(rules) > 5000:
            raise ValueError("tone must be a list of at most 5000 rules")
        seen: set[str] = set()
        for rule in rules:
            if not isinstance(rule, str) or "/" not in rule:
                raise ValueError("tone rules must use source/target")
            source, target = rule.split("/", 1)
            if (
                not source
                or len(source) > 9
                or any(c.isspace() for c in source)
                or source in seen
                or not target.strip()
            ):
                raise ValueError("Invalid or duplicate pronunciation source/target")
            seen.add(source)
