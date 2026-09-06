"""Volcengine Doubao streaming ASR (v3 ``bigmodel_async``) adapter for LiveKit Agents.

Public API reference: https://docs.volcengine.com/docs/6561/2630027

Module layout — one layer per file:

- ``protocol.py``      byte framing: client frames, ``ServerMessage`` parsing
- ``_options.py``      request assembly: plugin options → full-request JSON
- ``_capabilities.py`` capability descriptors + composition-time checks
- ``_transcript.py``   result→event mapping (utterance state machine)
- ``stt.py`` (here)    transport + adapter: connection lifecycle, send/recv
                       tasks, reconnection, usage accounting

Layering rule (minimal core, decoupled extensions): modules depend downward
only. ``protocol``, ``_options`` and ``_capabilities`` are pure and
livekit-free; ``_transcript`` knows payloads and events but not sockets;
``stt`` composes them and is the only module that talks to the framework.
Capability extensions — usage accounting, hot-swappable options, the escape
hatch — attach at these seams (``PeriodicCollector``, ``apply_updates``,
``extra_request_params``, ``check_capabilities``) instead of interleaving
with the core, and capability switches that need companion settings graduate
together as one bundle.

Side-effect inventory (every effect paired with its reversal, teardown
reaches quiescence):

- WebSocket connect (``_connect_ws``) ↔ ``finally: await ws.close()`` per
  connection attempt
- send/recv tasks ↔ ``gracefully_cancel`` + gather exception retrieved
- usage accounting (``collector.push``) ↔ flush at flush-sentinel, input end,
  and connection teardown — accounting survives failure paths
- event emission ↔ one-way by contract; guarded where the channel may be
  closed (usage callback suppresses ``ChanClosed``)
- utterance state (``TranscriptMapper``) ↔ survives retries by decision (see
  its construction site), never fabricated after a failed stream
  (``commit_pending`` runs only on normal completion)

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
import contextlib
import dataclasses
import logging
import os
import uuid
import weakref
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
from livekit.agents.utils import AudioBuffer, is_given

from . import protocol as asr_protocol
from ._capabilities import check_capabilities
from ._options import (
    DEFAULT_BASE_URL,
    DEFAULT_RESOURCE_ID,
    AudioFormat,
    _STTOptions,
    apply_updates,
)
from ._transcript import TranscriptMapper
from ._utils import PeriodicCollector
from .log import logger

# spoken-language tag used in events when the language option is unset
# (the service's default model is zh/en)
_DEFAULT_LANGUAGE = "zh-CN"


def _filter_given(**kwargs: Any) -> dict[str, Any]:
    """Keep only explicitly given (not NOT_GIVEN) keyword arguments."""
    return {name: value for name, value in kwargs.items() if is_given(value)}


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
            corpus: Hotwords / replacement tables / dialog context config
                (``boosting_table_name``/``correct_table_name``/``context`` with
                ``hotwords``/``dialog_ctx``/``image_url``; context + hotwords
                capped at 100 tokens upstream). A dict ``context`` is serialized
                to the JSON string the API expects.
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

        self._opts = _STTOptions(
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

        # capability contracts: unmet requirements degrade event semantics —
        # reported at composition time instead of failing mid-conversation
        # (see _capabilities.py and DESIGN.md)
        check_capabilities(self._opts, lambda msg: logger.warning("%s", msg))
        if audio_format != "pcm":
            logger.warning(
                "audio_format=%r: frames pushed through LiveKit are raw PCM; only "
                "set a container/codec format when feeding pre-encoded payloads",
                audio_format,
            )
        self._session = http_session
        self._streams: weakref.WeakSet[SpeechStream] = weakref.WeakSet()

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
        opts = dataclasses.replace(self._opts)
        if is_given(language):
            opts.language = str(language)
        stream = SpeechStream(
            stt=self,
            conn_options=conn_options,
            opts=opts,
            session=self._ensure_session(),
        )
        self._streams.add(stream)
        return stream

    def update_options(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        corpus: NotGivenOr[dict[str, Any] | None] = NOT_GIVEN,
        end_window_size: NotGivenOr[int] = NOT_GIVEN,
        enable_itn: NotGivenOr[bool] = NOT_GIVEN,
        enable_punc: NotGivenOr[bool] = NOT_GIVEN,
        enable_ddc: NotGivenOr[bool] = NOT_GIVEN,
        extra_request_params: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> None:
        """Update recognition options and apply them to live streams.

        The full request payload is sent once per WebSocket connection, so every
        change takes effect through a reconnect of each live stream (the same
        contract as the Azure/Google/OpenAI adapters). ``extra_request_params``
        replaces the previous escape hatch wholesale.

        Args:
            language: Recognition language.
            corpus: Hotwords / replacement tables / dialog context config
                (``boosting_table_name``/``correct_table_name``/``context`` with
                ``hotwords``/``dialog_ctx``/``image_url``; context + hotwords
                capped at 100 tokens upstream). A dict ``context`` is serialized
                to the JSON string the API expects.
            end_window_size: VAD silence threshold in ms that closes an utterance.
            enable_itn / enable_punc / enable_ddc: Inverse text normalization,
                punctuation, and disfluency removal.
            extra_request_params: Escape hatch for unmodeled service parameters.
        """
        updates = _filter_given(
            language=language,
            corpus=corpus,
            end_window_size=end_window_size,
            enable_itn=enable_itn,
            enable_punc=enable_punc,
            enable_ddc=enable_ddc,
            extra_request_params=extra_request_params,
        )
        apply_updates(self._opts, updates)
        # forward the given-only mapping so streams can't confuse "unchanged"
        # with "changed to the default"
        for stream in self._streams:
            stream.update_options(**updates)


class SpeechStream(stt.SpeechStream):
    def __init__(
        self,
        *,
        stt: STT,
        opts: _STTOptions,
        conn_options: APIConnectOptions,
        session: aiohttp.ClientSession,
    ) -> None:
        # the base class resamples incoming frames to sample_rate and creates
        # _event_ch, which the mapper below feeds
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=opts.sample_rate)
        self._opts = opts
        self._session = session
        self._request_id = uuid.uuid4().hex
        self._log = logging.LoggerAdapter(logger, {"request_id": self._request_id})
        # created once per stream: utterance state deliberately survives
        # connection retries — a dropped connection's pending interim is kept
        # (its audio was really recognized) and the boundary rule closes it as
        # soon as the next connection's first utterance arrives with a
        # different start_time
        self._transcript = TranscriptMapper(self._event_ch, self._request_id)
        self._reconnect_event = asyncio.Event()
        self._audio_duration_collector = PeriodicCollector(
            callback=self._on_audio_duration_report,
            duration=5.0,
        )

    def update_options(self, **updates: Any) -> None:
        """Apply a given-only ``{field: value}`` mapping to this stream.

        The full request payload is sent once per connection, so the change
        takes effect via reconnect. Field application is shared with
        ``STT.update_options`` (see ``_options.apply_updates``).
        """
        apply_updates(self._opts, updates)
        self._reconnect_event.set()

    def _on_audio_duration_report(self, duration: float) -> None:
        with contextlib.suppress(utils.aio.ChanClosed):
            self._event_ch.send_nowait(
                stt.SpeechEvent(
                    type=stt.SpeechEventType.RECOGNITION_USAGE,
                    request_id=self._request_id,
                    recognition_usage=stt.RecognitionUsage(audio_duration=duration),
                ),
            )

    async def _run(self) -> None:
        closing = False

        @utils.log_exceptions(logger=logger)
        async def send_task(ws: aiohttp.ClientWebSocketResponse) -> None:
            nonlocal closing
            seq = 1
            await self._safe_send(
                ws,
                asr_protocol.build_full_client_request(
                    self._opts.build_request_payload(uid=self._request_id),
                    sequence=seq,
                ),
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
                    self._audio_duration_collector.push(frame.duration)
                    payload = asr_protocol.build_audio_only_request(
                        frame.data.tobytes(), seq, last=ended
                    )
                    await self._safe_send(ws, payload)
                if ended:
                    self._audio_duration_collector.flush()
            self._audio_duration_collector.flush()
            # input closed without a flush sentinel: still mark the stream ended
            if not ended:
                final_frame = asr_protocol.build_audio_only_request(b"", -seq, last=True)
                await self._safe_send(ws, final_frame)
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
                    self._log.debug("volcengine asr connection closed unexpectedly")
                    # delegate reconnection to the framework retry loop
                    raise APIConnectionError(
                        "volcengine asr connection closed unexpectedly", retryable=True
                    )
                if msg.type != aiohttp.WSMsgType.BINARY or not msg.data:
                    continue
                self._handle_server_message(msg.data)

        while True:
            closing = False
            ws = await self._connect_ws()
            try:
                tasks = [
                    asyncio.create_task(send_task(ws)),
                    asyncio.create_task(recv_task(ws)),
                ]
                tasks_group = asyncio.gather(*tasks)
                wait_reconnect_task = asyncio.create_task(self._reconnect_event.wait())
                try:
                    done, _ = await asyncio.wait(
                        (tasks_group, wait_reconnect_task),
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    # propagate send/recv failures to the framework retry loop
                    for task in done:
                        if task != wait_reconnect_task:
                            task.result()

                    if wait_reconnect_task not in done:
                        # normal completion: commit a trailing interim-only
                        # utterance so the user's last sentence is never lost
                        # as interim-only
                        self._transcript.commit_pending(
                            start_time_offset=self.start_time_offset,
                            language=self._opts.language or _DEFAULT_LANGUAGE,
                        )
                        break

                    # an option change took effect on the next connection
                    self._reconnect_event.clear()
                finally:
                    await utils.aio.gracefully_cancel(*tasks, wait_reconnect_task)
                    tasks_group.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        tasks_group.exception()  # retrieve the exception
            finally:
                await ws.close()
                # quiescence: report audio already sent even when the connection
                # failed mid-window, so usage accounting never strands the last
                # partial batch (recv failure cancels send before its own flush)
                self._audio_duration_collector.flush()

    async def _safe_send(self, ws: aiohttp.ClientWebSocketResponse, data: bytes) -> None:
        """Send while tolerating a reset that races a peer close.

        The receiving task observes the same close and classifies it
        (clean shutdown vs retryable disconnect), so a losing send race
        must not raise here.
        """
        try:
            await ws.send_bytes(data)
        except aiohttp.ClientConnectionResetError:
            # send raced a peer close — recv_task observes the same close and
            # classifies it; dropping the losing frame is correct here
            self._log.debug("send raced a peer close; dropping the frame")
        except (aiohttp.ClientError, ConnectionError) as e:
            # a mid-write socket drop must surface as a retryable APIError so
            # the framework reconnects (symmetric with recv_task)
            raise APIConnectionError("volcengine asr write failed", retryable=True) from e

    async def _connect_ws(self) -> aiohttp.ClientWebSocketResponse:
        try:
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
        except asyncio.TimeoutError:
            # a raw TimeoutError is not an APIError, so the framework retry
            # loop would not recognize it
            raise APIConnectionError("volcengine asr connection timed out") from None
        except aiohttp.WSServerHandshakeError as e:
            # a rejected handshake (bad key, quota, ...) must surface as an
            # APIStatusError or the stream dies outside the retry loop; raise
            # from None because RequestInfo carries the request headers with
            # X-Api-Key
            raise APIStatusError(
                f"volcengine asr handshake rejected ({e.status})",
                status_code=e.status,
            ) from None
        except aiohttp.ClientError as e:
            raise APIConnectionError(
                f"volcengine asr connect failed ({type(e).__name__})"
            ) from None

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
            self._transcript.handle_result(
                result,
                start_time_offset=self.start_time_offset,
                language=self._opts.language or _DEFAULT_LANGUAGE,
            )
