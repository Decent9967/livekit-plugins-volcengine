"""Volcengine Doubao streaming ASR (v3 ``bigmodel_async``) adapter for LiveKit Agents.

Public API reference: https://docs.volcengine.com/docs/6561/2630027

Design notes (differences from existing community adapters, verified by code
audit, see the repository README):

- Server error frames raise :class:`APIStatusError` carrying the server error
  code and payload instead of being dropped silently.
- An empty ``definite`` utterance (the two-pass model finalizing a segment with
  no speech) still emits ``END_OF_SPEECH``; dropping it stalls turn detection.
- All ``result`` entries and ``utterances`` are traversed, not only the first.
- Unexpected connection loss raises ``APIConnectionError(retryable=True)`` and
  reconnection is delegated to the framework's retry loop (``conn_options``)
  instead of a hand-rolled, untested reconnect path.
- Options cover the current public request surface plus an
  ``extra_request_params`` escape hatch, so new server-side parameters work
  without waiting for a plugin release.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import aiohttp

from livekit import rtc
from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    stt,
    utils,
)
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer

from . import protocol as asr_protocol
from .log import logger

DEFAULT_BASE_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
# 2.0 (recommended): volc.seedasr.sauc.duration / volc.seedasr.sauc.concurrent
# 1.0:               volc.bigasr.sauc.duration / volc.bigasr.sauc.concurrent
DEFAULT_RESOURCE_ID = "volc.seedasr.sauc.duration"

AudioFormat = Literal["pcm", "wav", "ogg", "mp3", "spx", "amr", "aac", "m4a"]


@dataclass
class STTOptions:
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
            request["corpus"] = self.corpus
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


class STT(stt.STT):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        resource_id: str = DEFAULT_RESOURCE_ID,
        base_url: str = DEFAULT_BASE_URL,
        model_name: str = "bigmodel",
        language: str | None = None,
        audio_format: AudioFormat = "pcm",
        codec: Literal["raw", "opus"] = "raw",
        sample_rate: int = 16000,
        bits: int = 16,
        num_channels: int = 1,
        enable_nonstream: bool = True,
        enable_itn: bool = True,
        enable_punc: bool = True,
        enable_ddc: bool = False,
        show_utterances: bool = True,
        result_type: Literal["full", "single"] = "single",
        end_window_size: int = 800,
        force_to_speech_time: int = 1000,
        vad_segment_duration: int | None = None,
        enable_accelerate_text: bool = False,
        accelerate_score: int | None = None,
        output_zh_variant: Literal["traditional", "tw", "hk"] | None = None,
        sensitive_words_filter: dict[str, Any] | None = None,
        corpus: dict[str, Any] | None = None,
        extra_request_params: dict[str, Any] | None = None,
        http_session: aiohttp.ClientSession | None = None,
        interim_results: bool = True,
    ) -> None:
        """Create a Volcengine Doubao streaming speech recognizer.

        Args:
            api_key: Volcengine API key; falls back to ``VOLCENGINE_API_KEY``.
            resource_id: Model version. 2.0 (default, recommended):
                ``volc.seedasr.sauc.duration``/``concurrent``; 1.0:
                ``volc.bigasr.sauc.duration``/``concurrent``.
            base_url: WebSocket endpoint of the bidirectional streaming API.
            model_name: Model name; the service currently only accepts
                ``bigmodel``.
            language: Recognition language. Leave unset for the default
                Chinese/English model (also required for speaker separation).
            enable_nonstream: Two-pass recognition. With it on, ``definite``
                results come from the second (non-streaming) pass, which is
                what this adapter uses for ``FINAL_TRANSCRIPT``.
            result_type: ``single`` returns incremental results per utterance
                (default, suits live captions); ``full`` returns the whole
                session text each time.
            end_window_size: VAD silence threshold in ms that closes an
                utterance (300-5000, recommended 800-1000).
            force_to_speech_time: Ms of leading audio treated as speech to
                avoid premature VAD decisions (recommended 1000).
            vad_segment_duration: Max silence for semantic segmentation in ms.
                Ignored by the service while ``end_window_size`` is set, so it
                is only sent when explicitly provided.
            enable_accelerate_text / accelerate_score: Accelerate the first
                token at a possible accuracy cost; score requires
                ``enable_accelerate_text``.
            sensitive_words_filter: Sensitive-word filtering config
                (``system_reserved_filter``/``filter_with_empty``/
                ``filter_with_signed``); serialized as the JSON string the API
                expects.
            corpus: Hotwords / replacement tables / dialog context config.
            extra_request_params: Merged into the ``request`` payload last —
                use it for service parameters this plugin does not model.
        """
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=interim_results,
                offline_recognize=False,
            )
        )

        api_key = api_key or os.environ.get("VOLCENGINE_API_KEY")
        if not api_key:
            raise ValueError("api_key is required: pass api_key or set VOLCENGINE_API_KEY")
        if accelerate_score is not None and not enable_accelerate_text:
            raise ValueError("accelerate_score requires enable_accelerate_text=True")

        self._opts = STTOptions(
            api_key=api_key,
            resource_id=resource_id,
            base_url=base_url,
            model_name=model_name,
            language=language,
            audio_format=audio_format,
            codec=codec,
            sample_rate=sample_rate,
            bits=bits,
            num_channels=num_channels,
            enable_nonstream=enable_nonstream,
            enable_itn=enable_itn,
            enable_punc=enable_punc,
            enable_ddc=enable_ddc,
            show_utterances=show_utterances,
            result_type=result_type,
            end_window_size=end_window_size,
            force_to_speech_time=force_to_speech_time,
            vad_segment_duration=vad_segment_duration,
            enable_accelerate_text=enable_accelerate_text,
            accelerate_score=accelerate_score,
            output_zh_variant=output_zh_variant,
            sensitive_words_filter=sensitive_words_filter,
            corpus=corpus,
            extra_request_params=dict(extra_request_params or {}),
        )
        self._session = http_session

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = utils.http_context.http_session()
        return self._session

    @property
    def provider(self) -> str:
        return "volcengine"

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        raise NotImplementedError(
            "Volcengine streaming ASR does not support offline recognition; use stream()"
        )

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> SpeechStream:
        return SpeechStream(
            stt=self,
            conn_options=conn_options,
            opts=self._opts,
            session=self._ensure_session(),
        )


class SpeechStream(stt.SpeechStream):
    def __init__(
        self,
        *,
        stt: STT,
        opts: STTOptions,
        conn_options: APIConnectOptions,
        session: aiohttp.ClientSession,
    ) -> None:
        # the base class resamples incoming frames to sample_rate
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=opts.sample_rate)
        self._opts = opts
        self._session = session
        self._request_id = uuid.uuid4().hex
        self._speaking = False

    async def _run(self) -> None:
        closing = False

        @utils.log_exceptions(logger=logger)
        async def send_task(ws: aiohttp.ClientWebSocketResponse) -> None:
            nonlocal closing
            seq = 1
            await ws.send_bytes(
                asr_protocol.build_full_client_request(
                    self._opts.build_request_payload(uid=self._request_id),
                    sequence=seq,
                )
            )

            bstream = utils.audio.AudioByteStream(
                sample_rate=self._opts.sample_rate,
                num_channels=self._opts.num_channels,
                samples_per_channel=self._opts.sample_rate // 10,
            )
            ended = False
            async for data in self._input_ch:
                frames: list[rtc.AudioFrame] = []
                if isinstance(data, rtc.AudioFrame):
                    frames.extend(bstream.write(data.data.tobytes()))
                elif isinstance(data, self._FlushSentinel):
                    frames.extend(bstream.flush())
                    ended = True
                for frame in frames:
                    seq += 1
                    await ws.send_bytes(
                        asr_protocol.build_audio_only_request(frame.data.tobytes(), seq, last=ended)
                    )
            # input closed without a flush sentinel: still mark the stream ended
            if not ended:
                await ws.send_bytes(asr_protocol.build_audio_only_request(b"", -seq, last=True))
            closing = True

        @utils.log_exceptions(logger=logger)
        async def recv_task(ws: aiohttp.ClientWebSocketResponse) -> None:
            while True:
                msg = await ws.receive()
                if msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    if closing:
                        return
                    # delegate reconnection to the framework retry loop
                    raise APIConnectionError(
                        "volcengine asr connection closed unexpectedly", retryable=True
                    )
                if msg.type != aiohttp.WSMsgType.BINARY or not msg.data:
                    continue
                self._handle_server_message(msg.data)

        ws = await self._connect_ws()
        try:
            tasks = [
                asyncio.create_task(send_task(ws)),
                asyncio.create_task(recv_task(ws)),
            ]
            try:
                await asyncio.gather(*tasks)
            finally:
                await utils.aio.gracefully_cancel(*tasks)
        finally:
            await ws.close()

    async def _connect_ws(self) -> aiohttp.ClientWebSocketResponse:
        return await asyncio.wait_for(
            self._session.ws_connect(
                self._opts.base_url,
                headers={
                    "X-Api-Key": self._opts.api_key,
                    "X-Api-Resource-Id": self._opts.resource_id,
                    "X-Api-Request-Id": self._request_id,
                },
                max_msg_size=10 * 1024 * 1024,
            ),
            self._conn_options.timeout,
        )

    def _handle_server_message(self, data: bytes) -> None:
        message = asr_protocol.parse_server_message(data)

        if message.message_type == asr_protocol.SERVER_ERROR_RESPONSE:
            raise APIStatusError(
                f"volcengine asr error {message.error_code}: {message.payload}",
            )

        if not isinstance(message.payload, dict):
            return
        results = message.payload.get("result")
        if not isinstance(results, list):
            return
        for result in results:
            if not isinstance(result, dict):
                continue
            self._emit_result(result)

    def _emit_result(self, result: dict[str, Any]) -> None:
        text = str(result.get("text") or "")
        utterances = result.get("utterances") or [{}]
        confidence = float(result.get("confidence") or 0.0)

        for utterance in utterances:
            if not isinstance(utterance, dict):
                continue
            u_text = str(utterance.get("text") or text)
            definite = bool(utterance.get("definite", False))
            start_time = float(utterance.get("start_time") or 0.0)
            end_time = float(utterance.get("end_time") or 0.0)

            if not definite:
                if not u_text:
                    continue
                if not self._speaking:
                    self._speaking = True
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                    )
                self._event_ch.send_nowait(
                    stt.SpeechEvent(
                        type=stt.SpeechEventType.INTERIM_TRANSCRIPT,
                        request_id=self._request_id,
                        alternatives=[
                            stt.SpeechData(
                                language="zh-CN",
                                text=u_text,
                                start_time=start_time,
                                end_time=end_time,
                                confidence=confidence,
                            )
                        ],
                    )
                )
                continue

            # definite utterance: emit final text when present, then always close
            # the utterance — an empty definite (two-pass found no speech) still
            # ends the turn, dropping it stalls downstream turn detection
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
                                language="zh-CN",
                                text=u_text,
                                start_time=start_time,
                                end_time=end_time,
                                confidence=confidence,
                            )
                        ],
                    )
                )
            if self._speaking:
                self._speaking = False
                self._event_ch.send_nowait(
                    stt.SpeechEvent(
                        type=stt.SpeechEventType.END_OF_SPEECH,
                        request_id=self._request_id,
                    )
                )
