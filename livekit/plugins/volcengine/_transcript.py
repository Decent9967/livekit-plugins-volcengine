"""Result→event mapping: volcengine result payloads into LiveKit speech events.

Pure state machine — owns the current utterance state (``_speaking`` /
``_utterance_start`` / ``_pending_interim``) and emits
START_OF_SPEECH / INTERIM / FINAL / END_OF_SPEECH. No I/O and no transport
awareness; the stream feeds it parsed payloads and receives events through the
channel it was constructed with.

Semantic rules enforced here (each backed by a unit test):

- An empty ``definite`` utterance (two-pass final with no speech) still closes
  the turn — dropping it stalls downstream turn detection.
- A new utterance (different ``start_time``) while the previous one is still
  pending closes the pending turn first, so two utterances never glue together.
- ``commit_pending`` flushes a trailing interim-only utterance as final when
  the stream ends normally, so the user's last sentence is never lost.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from livekit.agents import stt
from livekit.agents.types import TimedString
from livekit.agents.utils import aio

from .log import logger

# result-item keys this mapper reads
_CONSUMED_RESULT_KEYS = frozenset({"text", "confidence", "utterances", "additions"})
# present in responses but intentionally not mapped yet (see PARAMETERS.md);
# v0.2 mappings move keys from here to the consumed set
_KNOWN_DROPPED_RESULT_KEYS = frozenset()

# Only mappings backed by real service responses; unknown tags retain the
# caller's language. English detection does not identify a regional dialect.
_LANGUAGE_TAGS = {"speech_mand": "zh-CN", "speech_en": "en"}


def _metadata(additions: dict[str, Any]) -> dict[str, Any] | None:
    """Expose observed provider fields without copying arbitrary response data."""
    values: dict[str, Any] = {}
    for name in ("emotion", "gender", "emotion_degree", "lid_lang"):
        value = additions.get(name)
        if isinstance(value, str) and value:
            values[name] = value
    for name in (
        "speech_rate",
        "volume",
        "age",
        "emotion_score",
        "gender_score",
        "emotion_degree_score",
        "lid_lang_score",
    ):
        value = additions.get(name)
        if type(value) not in (str, int, float):
            continue
        try:
            number = float(value)
        except (ValueError, OverflowError):
            continue
        if math.isfinite(number):
            values[name] = number
    return {"volcengine": values} if values else None


def _log_unknown_result_fields(result: dict[str, Any]) -> None:
    """Make unconsumed response data observable at debug level.

    When the service gains a parameter that produces new result data, its
    shape shows up here the moment it arrives — you cannot write a consumer
    for data you cannot see. Anything outside both sets above is new.
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return
    unknown = set(result) - _CONSUMED_RESULT_KEYS - _KNOWN_DROPPED_RESULT_KEYS
    if unknown:
        logger.debug(
            "unrecognized result fields dropped: %s",
            sorted(unknown),
            extra={"lk.pii.data": {k: result[k] for k in unknown}},
        )


def _timed_words(raw_words: Any, *, start_time_offset: float) -> list[TimedString] | None:
    """Map an utterance's ``words`` list to framework TimedStrings.

    Doc timestamps are milliseconds; SpeechData expects seconds. Returns None
    when the service sent no usable word list.
    """
    if not isinstance(raw_words, list):
        return None
    words = [
        TimedString(
            text=str(w.get("text") or ""),
            start_time=float(w.get("start_time") or 0.0) / 1000 + start_time_offset,
            end_time=float(w.get("end_time") or 0.0) / 1000 + start_time_offset,
        )
        for w in raw_words
        if isinstance(w, dict)
    ]
    return words or None


class TranscriptMapper:
    def __init__(self, event_ch: aio.Chan[stt.SpeechEvent], request_id: str) -> None:
        self._event_ch = event_ch
        self._request_id = request_id
        self._speaking = False
        self._utterance_start: float | None = None
        self._pending_interim: dict[str, Any] | None = None
        self._finalized: set[tuple[float, float, float, str]] = set()

    def start_connection(self) -> None:
        """Server timestamps restart on reconnect; deduplication is connection-local."""
        self._finalized.clear()

    def handle_result(
        self,
        result: dict[str, Any],
        *,
        start_time_offset: float,
        language: str,
    ) -> None:
        _log_unknown_result_fields(result)
        additions = result.get("additions")
        if isinstance(additions, dict) and isinstance(additions.get("log_id"), str):
            logger.debug(
                "Volcengine recognition response",
                extra={"request_id": self._request_id, "log_id": additions["log_id"]},
            )
        text = str(result.get("text") or "")
        utterances = result.get("utterances") or [{}]
        confidence = float(result.get("confidence") or 0.0)

        for utterance in utterances:
            if not isinstance(utterance, dict):
                continue
            u_text = str(utterance.get("text", text) or "")
            additions = utterance.get("additions")
            additions = additions if isinstance(additions, dict) else {}
            metadata = _metadata(additions)
            raw_speaker = additions.get("speaker_id")
            speaker_id = str(raw_speaker) if type(raw_speaker) in (str, int) else None
            lid = additions.get("lid_lang")
            detected_language = (
                _LANGUAGE_TAGS.get(lid, language) if isinstance(lid, str) else language
            )
            definite = bool(utterance.get("definite", False))
            # doc timestamps are milliseconds; SpeechData expects seconds
            start_time = float(utterance.get("start_time") or 0.0) / 1000
            end_time = float(utterance.get("end_time") or 0.0) / 1000
            words = _timed_words(utterance.get("words"), start_time_offset=start_time_offset)
            if definite and u_text:
                key = (start_time_offset, start_time, end_time, u_text)
                if key in self._finalized:
                    continue
                self._finalized.add(key)

            if not definite:
                if not u_text:
                    continue
                if not self._speaking:
                    self._speaking = True
                    self._utterance_start = start_time
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                    )
                elif start_time != self._utterance_start:
                    # the service started a new utterance without finalizing the
                    # previous one — close the pending turn so downstream does not
                    # see two utterances glued together
                    self._pending_interim = None
                    self._utterance_start = start_time
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(
                            type=stt.SpeechEventType.END_OF_SPEECH,
                            request_id=self._request_id,
                        )
                    )
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                    )
                self._pending_interim = {
                    "text": u_text,
                    "start_time": start_time,
                    "end_time": end_time,
                    "confidence": confidence,
                    "language": detected_language,
                    "speaker_id": speaker_id,
                    "metadata": metadata,
                }
                self._event_ch.send_nowait(
                    stt.SpeechEvent(
                        type=stt.SpeechEventType.INTERIM_TRANSCRIPT,
                        request_id=self._request_id,
                        alternatives=[
                            stt.SpeechData(
                                language=detected_language,
                                speaker_id=speaker_id,
                                metadata=metadata,
                                text=u_text,
                                # server timestamps are stream-relative; the
                                # framework advances start_time_offset across
                                # reconnects so consumers see one timeline
                                start_time=start_time + start_time_offset,
                                end_time=end_time + start_time_offset,
                                confidence=confidence,
                                words=words,
                            )
                        ],
                    )
                )
                continue

            # definite utterance: emit final text when present, then always close
            # the utterance — an empty definite (two-pass found no speech) still
            # ends the turn, dropping it stalls downstream turn detection
            self._pending_interim = None
            if u_text:
                if not self._speaking:
                    self._speaking = True
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                    )
                self._event_ch.send_nowait(
                    stt.SpeechEvent(
                        type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                        request_id=self._request_id,
                        alternatives=[
                            stt.SpeechData(
                                language=detected_language,
                                speaker_id=speaker_id,
                                metadata=metadata,
                                text=u_text,
                                start_time=start_time + start_time_offset,
                                end_time=end_time + start_time_offset,
                                confidence=confidence,
                                words=words,
                            )
                        ],
                    )
                )
            if self._speaking:
                self._speaking = False
                self._utterance_start = None
                self._event_ch.send_nowait(
                    stt.SpeechEvent(
                        type=stt.SpeechEventType.END_OF_SPEECH,
                        request_id=self._request_id,
                    )
                )

    def commit_pending(self, *, start_time_offset: float, language: str) -> None:
        """Commit the trailing interim-only utterance when the stream ends.

        Without this, a user's last sentence that never received a `definite`
        would be lost as interim-only. Idempotent: no pending utterance is a
        no-op, and this must never be called after a failure (fabricating a
        final on a failed stream would be worse than losing it).
        """
        pending = self._pending_interim
        if pending is None:
            return
        self._pending_interim = None
        self._utterance_start = None
        if self._speaking:
            self._speaking = False
        self._event_ch.send_nowait(
            stt.SpeechEvent(
                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                request_id=self._request_id,
                alternatives=[
                    stt.SpeechData(
                        language=pending.get("language", language),
                        speaker_id=pending.get("speaker_id"),
                        metadata=pending.get("metadata"),
                        text=str(pending.get("text") or ""),
                        start_time=float(pending.get("start_time") or 0.0) + start_time_offset,
                        end_time=float(pending.get("end_time") or 0.0) + start_time_offset,
                        confidence=float(pending.get("confidence") or 0.0),
                    )
                ],
            )
        )
        self._event_ch.send_nowait(
            stt.SpeechEvent(
                type=stt.SpeechEventType.END_OF_SPEECH,
                request_id=self._request_id,
            )
        )
