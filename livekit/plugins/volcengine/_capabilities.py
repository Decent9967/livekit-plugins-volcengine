"""Capability contracts: what a feature needs, provides, and consumes.

A capability is the unit of graduation for this plugin: request toggles, their
companion settings, and the response fields they surface travel together as
one descriptor here, so they cannot drift apart between code and docs
(PARAMETERS.md mirrors this registry). At composition time
:func:`check_capabilities` turns unmet requirements into warnings — the
adapter degrades honestly at construction instead of failing silently
mid-conversation.

Design rule (see DESIGN.md): descriptors are plain data plus tiny predicates.
No registration framework, no hooks, no dynamic assembly — the horizontal
layers (options / transcript / transport) stay hand-written and readable;
this module only makes their contracts explicit and checkable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._options import _STTOptions


@dataclass(frozen=True)
class Requirement:
    """One predicate over the effective options (escape hatch included)."""

    describe: str  # how to satisfy it, human-readable
    met: Callable[[_STTOptions], bool]


def _effective(opts: _STTOptions, name: str) -> Any:
    # escape-hatch values win: they merge into the request payload last
    return opts.extra_request_params.get(name, getattr(opts, name, None))


def requires(name: str, value: Any, because: str) -> Requirement:
    return Requirement(
        describe=f"{name}={value!r} ({because})",
        met=lambda opts, n=name, v=value: _effective(opts, n) == v,
    )


def requires_unset(name: str, because: str) -> Requirement:
    return Requirement(
        describe=f"{name} unset ({because})",
        met=lambda opts, n=name: _effective(opts, n) is None,
    )


def requires_escape(name: str, value: Any, because: str) -> Requirement:
    return Requirement(
        describe=f"extra_request_params={{{name!r}: {value!r}}} ({because})",
        met=lambda opts, n=name, v=value: opts.extra_request_params.get(n) == v,
    )


@dataclass(frozen=True)
class Capability:
    name: str
    provides: str  # event semantics enabled when requirements hold
    requirements: tuple[Requirement, ...] = ()
    # request keys this capability will graduate from the escape hatch
    escape_hatch_fields: tuple[str, ...] = ()
    # response fields it maps into events (source of the PARAMETERS pairing table)
    consumes: tuple[str, ...] = ()
    # True: checked even when untouched — the adapter's core expectation
    always_check: bool = False


TURN_DETECTION = Capability(
    name="mid-stream turn detection",
    provides="FINAL_TRANSCRIPT + END_OF_SPEECH per utterance",
    requirements=(
        requires(
            "enable_nonstream",
            True,
            "definite finals come from the two-pass second pass",
        ),
        requires("show_utterances", True, "definite rides on utterances[]"),
        requires("result_type", "single", "the mapper assumes incremental semantics"),
    ),
    consumes=("definite", "start_time", "end_time", "words[]"),
    always_check=True,
)

SPEAKER_SEPARATION = Capability(
    name="speaker separation",
    provides="SpeechData.speaker_id per utterance (mapping lands in v0.2)",
    requirements=(
        requires_escape("enable_speaker_info", True, "the service toggle"),
        requires_escape("ssd_version", "200", "hidden flag from the pre-2.0 docs"),
        requires("show_utterances", True, "speaker_id rides on utterances[]"),
        requires_unset("language", "separation runs on the default zh/en model"),
    ),
    escape_hatch_fields=("enable_speaker_info", "ssd_version"),
    consumes=("utterances[].speaker_id",),
)

METADATA_TAGS = Capability(
    name="metadata tags",
    provides=(
        "language / emotion / gender / age / rate / volume tags "
        "(mapping lands in v0.2)"
    ),
    # each tag is independent server-side; nothing to require client-side yet
    requirements=(),
    escape_hatch_fields=(
        "enable_lid",
        "enable_emotion_detection",
        "enable_gender_detection",
        "enable_age_detection",
        "show_speech_rate",
        "show_volume",
    ),
    consumes=("additions.*",),
)

CAPABILITIES: tuple[Capability, ...] = (TURN_DETECTION, SPEAKER_SEPARATION, METADATA_TAGS)


def check_capabilities(opts: _STTOptions, warn: Callable[[str], None]) -> None:
    """Report capabilities whose requirements are unmet.

    ``always_check`` capabilities are the adapter's core expectations — every
    unmet requirement is reported even when the user touched nothing. Opt-in
    capabilities (speaker separation, metadata tags) are checked only when at
    least one of their escape-hatch fields is configured, so a partially
    wired bundle warns instead of silently doing nothing.
    """
    for cap in CAPABILITIES:
        if not cap.always_check and not any(
            f in opts.extra_request_params for f in cap.escape_hatch_fields
        ):
            continue
        unmet = [r.describe for r in cap.requirements if not r.met(opts)]
        if unmet:
            warn(
                f"{cap.name} unavailable ({cap.provides}); "
                f"unmet requirements: {'; '.join(unmet)}"
            )
