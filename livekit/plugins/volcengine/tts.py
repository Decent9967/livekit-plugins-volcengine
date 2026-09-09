"""Volcengine V3 bidirectional TTS for LiveKit Agents.

https://docs.volcengine.com/docs/6561/2532486
Uses SDK-owned input replay and audio emission. Connection/event handling was
informed by the Apache-2.0 bytedance V3 TTS adapter; see NOTICE.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
import weakref
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import aiohttp

from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tts,
    utils,
)

from ._tts_options import TTSOptions
from ._tts_protocol import MAX_PAYLOAD, Event, Frame, decode, encode
from .log import logger

DEFAULT_BASE_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"


@dataclass(frozen=True)
class TTSUsage:
    """Provider usage, separate from SDK input characters and token metrics.

    Missing usage is not zero. Only successful SessionFinished responses emit this
    event; interrupted sessions may still incur charges without returning usage.
    """

    request_id: str
    logid: str
    text_words: int | None
    usage: dict[str, Any]


@dataclass(eq=False)
class _Connection:
    ws: aiohttp.ClientWebSocketResponse
    logid: str


@dataclass(frozen=True)
class TTSSubtitle:
    """Provider subtitle payload; timestamps are not remapped to room playback time."""

    request_id: str
    logid: str
    payload: dict[str, Any]


class TTS(tts.TTS):
    """Streaming PCM synthesis. Configure a voice ID from the Volcengine console.

    ``additions`` accepts provider additions as a dict, encoded as a JSON string.
    ``extra_request_params`` accepts unmodeled req_params fields, but cannot
    override text or the named options (especially the PCM audio contract).
    ``usage_collected`` emits :class:`TTSUsage` with provider billing characters.
    """

    def __init__(
        self,
        *,
        speaker: str,
        api_key: str | None = None,
        resource_id: str = "seed-tts-2.0",
        base_url: str = DEFAULT_BASE_URL,
        sample_rate: int = 24000,
        speech_rate: int = 0,
        loudness_rate: int = 0,
        model: str | None = None,
        context_texts: list[str] | None = None,
        additions: dict[str, Any] | None = None,
        extra_request_params: dict[str, Any] | None = None,
        enable_subtitle: bool | None = None,
        max_length_to_filter_parenthesis: int | None = None,
        disable_markdown_filter: bool | None = None,
        disable_emoji_filter: bool | None = None,
        latex_parser: str | None = None,
        explicit_language: str | None = None,
        explicit_dialect: str | None = None,
        aigc_watermark: bool | None = None,
        pitch: int | None = None,
        section_id: str | None = None,
        pronunciation_dict: dict[str, list[str]] | None = None,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        api_key = (
            api_key
            or os.environ.get("VOLCENGINE_TTS_API_KEY")
            or os.environ.get("VOLCENGINE_API_KEY")
        )
        if not api_key:
            raise ValueError("api_key or VOLCENGINE_TTS_API_KEY/VOLCENGINE_API_KEY is required")
        self._opts = TTSOptions(
            speaker,
            sample_rate,
            speech_rate,
            loudness_rate,
            model,
            context_texts,
            additions or {},
            extra_request_params or {},
            enable_subtitle=enable_subtitle,
            max_length_to_filter_parenthesis=max_length_to_filter_parenthesis,
            disable_markdown_filter=disable_markdown_filter,
            disable_emoji_filter=disable_emoji_filter,
            latex_parser=latex_parser,
            explicit_language=explicit_language,
            explicit_dialect=explicit_dialect,
            aigc_watermark=aigc_watermark,
            pitch=pitch,
            section_id=section_id,
            pronunciation_dict=pronunciation_dict,
        )
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._api_key, self._resource_id, self._base_url = api_key, resource_id, base_url
        self._session = http_session
        self._closed = False
        self._streams: weakref.WeakSet[tts.SynthesizeStream | tts.ChunkedStream] = weakref.WeakSet()
        self._pool = utils.ConnectionPool[_Connection](
            # Real gateway probes reused at 10s idle but failed at 30s. Retire
            # by connection age conservatively; checked only between sessions,
            # so a long active synthesis is never interrupted by this limit.
            max_session_duration=10.0,
            connect_cb=self._connect,
            close_cb=self._close_connection,
        )

    @property
    def model(self) -> str:
        return self._opts.model or self._resource_id

    @property
    def provider(self) -> str:
        return "Volcengine"

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("TTS is closed")

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> SynthesizeStream:
        self._check_open()
        stream = SynthesizeStream(tts=self, conn_options=conn_options)
        self._streams.add(stream)
        return stream

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> ChunkedStream:
        self._check_open()
        stream = ChunkedStream(tts=self, input_text=text, conn_options=conn_options)
        self._streams.add(stream)
        return stream

    def prewarm(self) -> None:
        self._check_open()
        self._pool.prewarm()

    async def aclose(self) -> None:
        self._closed = True
        await asyncio.gather(*(stream.aclose() for stream in list(self._streams)))
        await self._pool.aclose()

    async def _receive(self, connection: _Connection, timeout: float) -> Frame:
        message = await connection.ws.receive(timeout=timeout)
        if message.type != aiohttp.WSMsgType.BINARY:
            raise APIConnectionError("TTS connection closed before session completion")
        try:
            frame = decode(message.data)
            failed_finish = frame.event == Event.SESSION_FINISHED and frame.json().get(
                "status_code", 0
            ) not in (0, 20000000)
            if (
                frame.error_code
                or failed_finish
                or frame.event
                in (
                    Event.CONNECTION_FAILED,
                    Event.SESSION_FAILED,
                )
            ):
                try:
                    meta = frame.json()
                except ValueError:
                    meta = {"message": frame.payload.decode("utf-8", errors="replace")}
                code = frame.error_code or int(meta.get("status_code", 0))
                detail = str(meta.get("message", "request failed")).replace(
                    self._api_key, "[REDACTED]"
                )[:500]
                raise APIStatusError(
                    f"Volcengine TTS: {detail}",
                    status_code=code,
                    request_id=connection.logid,
                    retryable=code >= 50000000,
                )
            return frame
        except (ValueError, TypeError) as exc:
            raise APIConnectionError("Invalid Volcengine TTS response", retryable=False) from exc

    async def _expect(
        self, connection: _Connection, event: Event, timeout: float, sid: str = ""
    ) -> Frame:
        frame = await self._receive(connection, timeout)
        if frame.event != event or (sid and frame.identifier != sid):
            raise APIConnectionError(
                "Unexpected TTS lifecycle event or session ID", retryable=False
            )
        return frame

    async def _connect(self, timeout: float) -> _Connection:
        if self._session is None:
            self._session = utils.http_context.http_session()
        ws = await asyncio.wait_for(
            self._session.ws_connect(
                self._base_url,
                max_msg_size=MAX_PAYLOAD,
                headers={
                    "X-Api-Key": self._api_key,
                    "X-Api-Resource-Id": self._resource_id,
                    "X-Api-Connect-Id": str(uuid.uuid4()),
                    "X-Control-Require-Usage-Tokens-Return": "*",
                },
                # No heartbeat: idle pooled sockets have no receive loop draining PONGs.
            ),
            timeout,
        )
        connection = _Connection(ws, ws._response.headers.get("x-tt-logid", ""))
        try:
            await asyncio.wait_for(ws.send_bytes(encode(Event.START_CONNECTION)), timeout)
            await self._expect(connection, Event.CONNECTION_STARTED, timeout)
        except BaseException:
            await ws.close()
            raise
        return connection

    async def _close_connection(self, connection: _Connection) -> None:
        if connection.ws.closed:
            return
        try:
            # Bounded shutdown, not a retry or a second synthesis deadline.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(connection.ws.send_bytes(encode(Event.FINISH_CONNECTION)), 1)
                await self._expect(connection, Event.CONNECTION_FINISHED, 1)
        finally:
            await connection.ws.close()

    async def _synthesize(
        self,
        tokens: AsyncIterator[str],
        emitter: tts.AudioEmitter,
        *,
        timeout: float,
        streaming: bool,
    ) -> None:
        sid = str(uuid.uuid4())
        emitter.initialize(
            request_id=sid,
            sample_rate=self.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
            stream=streaming,
        )
        # Wait for real text before consuming a pooled connection or opening a session.
        first = ""
        async for token in tokens:
            first += token
            if first.strip():
                break
        if not first.strip():
            return
        if streaming:
            emitter.start_segment(segment_id=sid)
        try:
            async with self._pool.connection(timeout=timeout) as connection:
                ws = connection.ws
                finished = False
                tasks: list[asyncio.Task] = []

                async def send(event: Event, text: str | None = None) -> None:
                    payload = (
                        {}
                        if event == Event.FINISH_SESSION
                        else {"event": event, "req_params": self._opts.request(text)}
                    )
                    await asyncio.wait_for(
                        ws.send_bytes(encode(event, session_id=sid, payload=payload)), timeout
                    )

                async def send_text() -> None:
                    await send(Event.TASK_REQUEST, first)
                    async for token in tokens:
                        await send(Event.TASK_REQUEST, token)
                    await send(Event.FINISH_SESSION)

                async def receive_audio() -> None:
                    nonlocal finished
                    while True:
                        frame = await self._receive(connection, timeout)
                        if frame.identifier != sid:
                            raise APIConnectionError(
                                "TTS response belongs to another session", retryable=False
                            )
                        if frame.is_audio:
                            emitter.push(frame.payload)
                        elif frame.event == Event.TTS_SUBTITLE:
                            try:
                                payload = frame.json()
                            except ValueError as exc:
                                raise APIConnectionError(
                                    "Invalid TTS subtitle", retryable=False
                                ) from exc
                            self.emit("subtitle", TTSSubtitle(sid, connection.logid, payload))
                        elif frame.event == Event.SESSION_FINISHED:
                            finished = True
                            self._emit_usage(frame, sid, connection.logid)
                            return
                        elif frame.event not in (Event.TTS_SENTENCE_START, Event.TTS_SENTENCE_END):
                            raise APIConnectionError(
                                "Unexpected TTS session event", retryable=False
                            )

                try:
                    await send(Event.START_SESSION)
                    await self._expect(connection, Event.SESSION_STARTED, timeout, sid)
                    tasks = [asyncio.create_task(send_text()), asyncio.create_task(receive_audio())]
                    await asyncio.gather(*tasks)
                finally:
                    await utils.aio.gracefully_cancel(*tasks)
                    if not finished:
                        # Do not return interrupted/failed sockets to the pool. Stop
                        # upstream generation without waiting for buffered audio to drain.
                        self._pool.remove(connection)
                        with contextlib.suppress(Exception):
                            await asyncio.wait_for(
                                ws.send_bytes(encode(Event.CANCEL_SESSION, session_id=sid)), 1
                            )
                        await ws.close()
            if streaming:
                emitter.end_segment()
        except asyncio.TimeoutError as exc:
            raise APITimeoutError("Volcengine TTS timed out") from exc
        except aiohttp.WSServerHandshakeError as exc:
            raise APIStatusError(
                "Volcengine TTS handshake failed",
                status_code=exc.status,
                retryable=exc.status == 429 or exc.status >= 500,
            ) from None
        except (aiohttp.ClientError, OSError) as exc:
            raise APIConnectionError("Volcengine TTS connection failed") from exc

    def _emit_usage(self, frame: Frame, sid: str, logid: str) -> None:
        usage = frame.json().get("usage")
        if not isinstance(usage, dict):
            return
        words = usage.get("text_words")
        words = words if type(words) is int and words >= 0 else None
        self.emit("usage_collected", TTSUsage(sid, logid, words, usage))
        logger.debug(
            "Volcengine TTS usage", extra={"request_id": sid, "logid": logid, "text_words": words}
        )


class SynthesizeStream(tts.SynthesizeStream):
    def __init__(self, *, tts: TTS, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, conn_options=conn_options)
        self._engine = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        async def tokens() -> AsyncIterator[str]:
            async for token in self._input_ch:
                if isinstance(token, self._FlushSentinel):
                    return
                self._mark_started()
                yield token

        await self._engine._synthesize(
            tokens(),
            output_emitter,
            timeout=self._conn_options.timeout,
            streaming=True,
        )


class ChunkedStream(tts.ChunkedStream):
    def __init__(self, *, tts: TTS, input_text: str, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._engine = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        async def tokens() -> AsyncIterator[str]:
            yield self._input_text

        await self._engine._synthesize(
            tokens(),
            output_emitter,
            timeout=self._conn_options.timeout,
            streaming=False,
        )
