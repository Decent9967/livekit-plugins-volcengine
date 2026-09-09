import asyncio
import contextlib
import gzip
import json
import logging
import struct
from types import SimpleNamespace

import aiohttp
import pytest
from livekit.agents import APIConnectionError, APIConnectOptions, APIStatusError
from livekit.agents.utils import aio

from livekit import rtc
from livekit.plugins.volcengine._transcript import TranscriptMapper
from livekit.plugins.volcengine.stt import STT, SpeechStream


class FakeSpeechStream:
    """Offline stand-in exposing real mapping logic without the network.

    The real base class starts its main task (and the WebSocket connection) on
    construction, so state-machine tests run against this stub instead. It
    carries a real ``TranscriptMapper`` — the same class the production stream
    uses — plus only the attributes the transport code touches.
    """

    def __init__(self) -> None:
        self._event_ch = aio.Chan()
        self._request_id = "test-req"
        self._transcript = TranscriptMapper(self._event_ch, self._request_id)
        self.start_time_offset = 0.0
        self.language = "zh-CN"
        self._FlushSentinel = SpeechStream._FlushSentinel
        self._log = logging.LoggerAdapter(
            logging.getLogger("test.livekit.plugins.volcengine"),
            {"request_id": self._request_id},
        )

    def emit(self, result: dict) -> None:
        self._transcript.handle_result(
            result, start_time_offset=self.start_time_offset, language=self.language
        )

    def commit_pending(self) -> None:
        self._transcript.commit_pending(
            start_time_offset=self.start_time_offset, language=self.language
        )


@pytest.fixture
async def stream_emitter():
    fake = FakeSpeechStream()
    collected: list = []

    async def collect():
        async for event in fake._event_ch:
            collected.append(event)

    task = asyncio.get_running_loop().create_task(collect())
    yield fake, collected
    fake._event_ch.close()
    await task


async def flush() -> None:
    """Let the collector task drain queued events before asserting."""
    for _ in range(3):
        await asyncio.sleep(0)


async def test_interim_then_final_flow(stream_emitter):
    stream, collected = stream_emitter

    stream.emit(
        {
            "text": "你",
            "utterances": [{"text": "你", "definite": False, "start_time": 0, "end_time": 200}],
        }
    )
    stream.emit(
        {
            "text": "你好",
            "utterances": [{"text": "你好", "definite": True, "start_time": 0, "end_time": 500}],
        }
    )
    await flush()

    types = [e.type.name for e in collected]
    assert types == [
        "START_OF_SPEECH",
        "INTERIM_TRANSCRIPT",
        "FINAL_TRANSCRIPT",
        "END_OF_SPEECH",
    ]


async def test_empty_definite_still_ends_utterance(stream_emitter):
    """Empty two-pass final must close the turn — dropping it stalls detection."""
    stream, collected = stream_emitter

    stream.emit(
        {
            "text": "喂",
            "utterances": [{"text": "喂", "definite": False, "start_time": 0, "end_time": 300}],
        }
    )
    stream.emit(
        {
            "text": "",
            "utterances": [{"text": "", "definite": True, "start_time": 300, "end_time": 900}],
        }
    )
    await flush()

    types = [e.type.name for e in collected]
    assert "FINAL_TRANSCRIPT" not in types  # nothing to finalize
    assert types[-1] == "END_OF_SPEECH"


async def test_multiple_utterances_are_traversed(stream_emitter):
    """Every utterance emits, not only the first."""
    stream, collected = stream_emitter

    stream.emit(
        {
            "text": "a",
            "utterances": [
                {"text": "a", "definite": True, "start_time": 0, "end_time": 1},
                {"text": "b", "definite": True, "start_time": 2, "end_time": 3},
            ],
        }
    )
    await flush()

    finals = [e for e in collected if e.type.name == "FINAL_TRANSCRIPT"]
    assert [e.alternatives[0].text for e in finals] == ["a", "b"]


async def test_interim_without_speaking_emits_start(stream_emitter):
    """A definite-final-only flow still opens speech before closing it."""
    stream, collected = stream_emitter

    stream.emit(
        {
            "text": "直接结束",
            "utterances": [
                {"text": "直接结束", "definite": True, "start_time": 0, "end_time": 100}
            ],
        }
    )
    await flush()

    types = [e.type.name for e in collected]
    assert types == ["START_OF_SPEECH", "FINAL_TRANSCRIPT", "END_OF_SPEECH"]


async def test_new_utterance_boundary_emits_pending_end_first(stream_emitter):
    """A new utterance (new start_time) while the previous one is still pending
    must close the pending turn first — otherwise two utterances are glued in
    the event stream and downstream turn detection cannot see the boundary."""
    stream, collected = stream_emitter

    stream.emit(
        {
            "text": "a",
            "utterances": [{"text": "a", "definite": False, "start_time": 0, "end_time": 100}],
        }
    )
    stream.emit(
        {
            "text": "b",
            "utterances": [{"text": "b", "definite": False, "start_time": 5000, "end_time": 5300}],
        }
    )
    await flush()

    types = [e.type.name for e in collected]
    assert types == [
        "START_OF_SPEECH",
        "INTERIM_TRANSCRIPT",
        "END_OF_SPEECH",
        "START_OF_SPEECH",
        "INTERIM_TRANSCRIPT",
    ]
    interims = [e for e in collected if e.type.name == "INTERIM_TRANSCRIPT"]
    assert [e.alternatives[0].text for e in interims] == ["a", "b"]


async def test_same_start_time_interims_are_one_utterance(stream_emitter):
    """Incremental updates of the same utterance share start_time — no boundary."""
    stream, collected = stream_emitter

    stream.emit(
        {
            "text": "你",
            "utterances": [{"text": "你", "definite": False, "start_time": 0, "end_time": 100}],
        }
    )
    stream.emit(
        {
            "text": "你好",
            "utterances": [{"text": "你好", "definite": False, "start_time": 0, "end_time": 200}],
        }
    )
    await flush()

    types = [e.type.name for e in collected]
    assert types.count("START_OF_SPEECH") == 1
    assert "END_OF_SPEECH" not in types


async def test_stream_end_commits_pending_interim(stream_emitter):
    """A trailing interim-only utterance is committed as final on stream end,
    and the commit is idempotent."""
    stream, collected = stream_emitter

    stream.emit(
        {
            "text": "最后一句",
            "utterances": [
                {"text": "最后一句", "definite": False, "start_time": 0, "end_time": 300}
            ],
        }
    )
    await flush()
    stream.commit_pending()
    await flush()

    types = [e.type.name for e in collected]
    assert types == ["START_OF_SPEECH", "INTERIM_TRANSCRIPT", "FINAL_TRANSCRIPT", "END_OF_SPEECH"]
    final = next(e for e in collected if e.type.name == "FINAL_TRANSCRIPT")
    assert final.alternatives[0].text == "最后一句"

    stream.commit_pending()  # second call: no-op
    await flush()
    assert len(collected) == 4


def test_request_payload_defaults():
    plugin = STT(api_key="k")
    payload = plugin._opts.build_request_payload(uid="u1")

    assert payload["user"]["uid"] == "u1"
    req = payload["request"]
    assert req["model_name"] == "bigmodel"
    assert req["enable_nonstream"] is True
    assert req["enable_itn"] is True  # doc default
    assert req["result_type"] == "single"
    assert req["force_to_speech_time"] == 1000
    assert "vad_segment_duration" not in req  # only sent when explicit
    assert "language" not in req  # default zh-CN model chosen server-side


def test_extra_request_params_escape_hatch():
    plugin = STT(
        api_key="k",
        extra_request_params={"enable_speaker_info": True, "ssd_version": "200"},
    )
    req = plugin._opts.build_request_payload(uid="u")["request"]
    assert req["enable_speaker_info"] is True
    assert req["ssd_version"] == "200"


def test_sensitive_words_filter_serialized_as_string():
    plugin = STT(api_key="k", sensitive_words_filter={"system_reserved_filter": True})
    req = plugin._opts.build_request_payload(uid="u")["request"]
    assert json.loads(req["sensitive_words_filter"]) == {"system_reserved_filter": True}


def test_accelerate_score_requires_flag():
    with pytest.raises(ValueError):
        STT(api_key="k", accelerate_score=10)


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    with pytest.raises(ValueError):
        STT()


async def test_safe_send_ignores_connection_reset(stream_emitter):
    """A send racing a peer close is dropped, not raised — recv_task classifies."""

    class ResettingWS:
        async def send_bytes(self, data):
            raise aiohttp.ClientConnectionResetError("peer closed mid-frame")

    stream, _ = stream_emitter
    await SpeechStream._safe_send(stream, ResettingWS(), b"payload")  # must not raise


async def test_safe_send_wraps_write_errors_as_retryable(stream_emitter):
    class BrokenWS:
        async def send_bytes(self, data):
            raise aiohttp.ClientError("mid-write socket drop")

    stream, _ = stream_emitter
    with pytest.raises(APIConnectionError) as exc_info:
        await SpeechStream._safe_send(stream, BrokenWS(), b"payload")
    assert exc_info.value.retryable is True


# ---------------------------------------------------------------------------
# recv_task / send_task 分类测试：用脚本化假 ws 驱动真实 _run 流水线
# （官方模式：对象层假件，确定性断言；toxic_proxy 属集成层，收编后再用）
# ---------------------------------------------------------------------------


def _result_frame(result: dict) -> bytes:
    payload = gzip.compress(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    body = struct.pack(">i", 1) + struct.pack(">I", len(payload)) + payload
    return bytes([0x11, (9 << 4) | 0x03, 0x11, 0x00]) + body  # 正常响应 | 序号+末包


def _error_frame(code: int) -> bytes:
    payload = gzip.compress(json.dumps({"message": "quota exceeded"}).encode("utf-8"))
    body = struct.pack(">i", code) + struct.pack(">I", len(payload)) + payload
    return bytes([0x11, (15 << 4), 0x11, 0x00]) + body  # 错误响应


def _ws_message(msg_type, data):
    return SimpleNamespace(type=msg_type, data=data)


class ScriptedWS:
    """按剧本返回消息的假 WebSocket；剧本耗尽后视作对端关闭（或 hold_open 挂起）。"""

    def __init__(self, script, *, hold_open: bool = False):
        self._script = list(script)
        self._hold_open = hold_open
        self.closed = False
        self.sent: list[bytes] = []
        self.first_send = asyncio.Event()

    async def send_bytes(self, data):
        self.sent.append(data)
        self.first_send.set()

    async def receive(self):
        if self._script:
            item = self._script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self._hold_open:
            # simulates a live connection; torn down via cancellation
            await asyncio.Event().wait()
        return _ws_message(aiohttp.WSMsgType.CLOSED, None)

    async def close(self):
        self.closed = True


class _StubCollector:
    """Records what the real send path pushes/flushes, without the 5s timer."""

    def __init__(self) -> None:
        self._pending: list[float] = []
        self.flushed: list[float] = []

    def push(self, value: float) -> None:
        self._pending.append(value)

    def flush(self) -> None:
        if self._pending:
            self.flushed.extend(self._pending)
            self._pending.clear()


class RunFakeStream(FakeSpeechStream):
    """带真实 _opts/_input_ch 的假件：驱动真 _run（连接被替换为脚本 ws）。"""

    def __init__(self, ws):
        super().__init__()
        self._opts = STT(api_key="k")._opts
        self._input_ch = aio.Chan()
        self._reconnect_event = asyncio.Event()
        self._audio_duration_collector = _StubCollector()
        self._ws_queue = list(ws) if isinstance(ws, (list, tuple)) else [ws]

    async def _connect_ws(self):
        return self._ws_queue.pop(0)

    def update_options(self, **kwargs):
        SpeechStream.update_options(self, **kwargs)

    async def _safe_send(self, ws, data):
        await SpeechStream._safe_send(self, ws, data)

    def _handle_server_message(self, data):
        SpeechStream._handle_server_message(self, data)


async def test_unexpected_close_raises_retryable_error():
    """意外断线（非主动关闭）必须抛可重试的 APIConnectionError——生产重连路径的锚点。"""
    ws = ScriptedWS(
        [
            _ws_message(aiohttp.WSMsgType.BINARY, _result_frame({"result": [{"text": "你好"}]})),
            _ws_message(aiohttp.WSMsgType.CLOSED, None),
        ]
    )
    fake = RunFakeStream(ws)
    collected: list = []

    async def collect():
        async for event in fake._event_ch:
            collected.append(event)

    collector = asyncio.get_running_loop().create_task(collect())
    run_task = asyncio.create_task(SpeechStream._run(fake))

    with pytest.raises(APIConnectionError) as exc_info:
        await run_task
    assert exc_info.value.retryable is True

    fake._event_ch.close()
    await collector
    types = [e.type.name for e in collected]
    assert "INTERIM_TRANSCRIPT" in types  # 断线前的消息已被正常处理
    assert ws.closed is True
    # 输入通道保持打开：发送员只发出建流配置帧就被取消，不存在末帧
    assert len(ws.sent) == 1
    assert ws.sent[0].hex().startswith("1111110000000001")


async def test_non_binary_messages_are_skipped():
    """TEXT/PING 等非二进制消息不进拆箱，也不影响后续错误分类。"""
    ws = ScriptedWS(
        [
            _ws_message(aiohttp.WSMsgType.TEXT, "junk"),
            _ws_message(aiohttp.WSMsgType.BINARY, _result_frame({"result": [{"text": "嗯"}]})),
            _ws_message(aiohttp.WSMsgType.CLOSED, None),
        ]
    )
    fake = RunFakeStream(ws)
    collected: list = []

    async def collect():
        async for event in fake._event_ch:
            collected.append(event)

    collector = asyncio.get_running_loop().create_task(collect())
    with pytest.raises(APIConnectionError):
        await asyncio.create_task(SpeechStream._run(fake))

    fake._event_ch.close()
    await collector
    interim_texts = [
        e.alternatives[0].text for e in collected if e.type.name == "INTERIM_TRANSCRIPT"
    ]
    assert interim_texts == ["嗯"]


async def test_error_frame_raises_api_status_error():
    """服务端错误帧 → APIStatusError（默认不可重试），绝不被静默吞掉。"""
    ws = ScriptedWS([_ws_message(aiohttp.WSMsgType.BINARY, _error_frame(4500003))])
    fake = RunFakeStream(ws)

    run_task = asyncio.create_task(SpeechStream._run(fake))
    with pytest.raises(APIStatusError) as exc_info:
        await run_task
    assert "4500003" in str(exc_info.value)
    await ws.close()


class _FakeSession:
    """ws_connect stub that raises or stalls, for driving the real _connect_ws."""

    def __init__(self, exc: Exception | None = None, *, stall: float | None = None) -> None:
        self._exc = exc
        self._stall = stall

    def ws_connect(self, *args: object, **kwargs: object):
        async def _connect():
            if self._stall is not None:
                await asyncio.sleep(self._stall)
            if self._exc is not None:
                raise self._exc
            return object()

        return _connect()


def _bare_stream(session: _FakeSession, timeout: float = 1.0) -> SpeechStream:
    """A SpeechStream instance carrying only what _connect_ws touches.

    object.__new__ skips the base-class constructor, which would otherwise
    start the main task and attempt a real connection.
    """
    stream = object.__new__(SpeechStream)
    stream._session = session  # type: ignore[attr-defined]
    stream._opts = STT(api_key="k")._opts  # type: ignore[attr-defined]
    stream._request_id = "test-req"  # type: ignore[attr-defined]
    stream._conn_options = APIConnectOptions(max_retry=0, timeout=timeout)  # type: ignore[attr-defined]
    return stream


async def test_connect_ws_maps_handshake_rejection_to_status_error():
    """握手被拒（如 key 无效 401）→ APIStatusError，交由框架归类为不可重试。"""
    request_info = SimpleNamespace()
    exc = aiohttp.WSServerHandshakeError(request_info, (), status=401, message="Unauthorized")
    stream = _bare_stream(_FakeSession(exc))

    with pytest.raises(APIStatusError) as exc_info:
        await stream._connect_ws()
    assert exc_info.value.status_code == 401
    # the original error carries request headers with X-Api-Key, so it must
    # not be chained into the traceback
    assert exc_info.value.__cause__ is None


async def test_connect_ws_maps_timeout_to_connection_error():
    """连接超时 → APIConnectionError（框架重试循环可识别）。"""
    stream = _bare_stream(_FakeSession(stall=0.5), timeout=0.05)

    with pytest.raises(APIConnectionError):
        await stream._connect_ws()


def _decode_config(frame: bytes) -> dict:
    """Unwrap the first FULL_CLIENT_REQUEST frame back into its JSON payload."""
    return json.loads(gzip.decompress(frame[12:]))


async def test_events_carry_start_time_offset(stream_emitter):
    """时间轴对齐：服务端毫秒时间戳换算为秒，再加 start_time_offset。"""
    stream, collected = stream_emitter
    stream.start_time_offset = 12.5

    stream.emit(
        {
            "text": "你好",
            "utterances": [{"text": "你好", "definite": True, "start_time": 100, "end_time": 500}],
        }
    )
    await flush()

    final = next(e for e in collected if e.type.name == "FINAL_TRANSCRIPT")
    # 100 ms → 0.1 s (+12.5 s offset)
    assert final.alternatives[0].start_time == pytest.approx(12.6)
    assert final.alternatives[0].end_time == pytest.approx(13.0)


async def test_utterance_words_are_mapped_to_timed_strings(stream_emitter):
    """show_utterances 默认开启，服务端回传的 words[] 分词必须被消费而非丢弃。"""
    stream, collected = stream_emitter
    stream.start_time_offset = 1.0

    stream.emit(
        {
            "text": "你好世界",
            "utterances": [
                {
                    "text": "你好世界",
                    "definite": True,
                    "start_time": 0,
                    "end_time": 2000,
                    "words": [
                        {"text": "你好", "start_time": 0, "end_time": 800},
                        {"text": "世界", "start_time": 800, "end_time": 2000},
                    ],
                }
            ],
        }
    )
    await flush()

    final = next(e for e in collected if e.type.name == "FINAL_TRANSCRIPT")
    words = final.alternatives[0].words
    # TimedString subclasses str — the text is the value itself
    assert [str(w) for w in words] == ["你好", "世界"]
    # ms → s, plus offset
    assert words[0].start_time == pytest.approx(1.0)
    assert words[0].end_time == pytest.approx(1.8)
    assert words[1].end_time == pytest.approx(3.0)


async def test_missing_words_yields_none(stream_emitter):
    """服务端没带 words 时 SpeechData.words 为 None，不报错。"""
    stream, collected = stream_emitter

    stream.emit(
        {
            "text": "喂",
            "utterances": [{"text": "喂", "definite": True, "start_time": 0, "end_time": 100}],
        }
    )
    await flush()

    final = next(e for e in collected if e.type.name == "FINAL_TRANSCRIPT")
    assert final.alternatives[0].words is None


def test_stt_update_options_mutates_and_fans_out():
    """STT.update_options 改自身配置，并把已给字段广播给所有活流。"""
    plugin = STT(api_key="k")
    seen: list[dict] = []

    class _RecorderStream:
        def update_options(self, **kwargs):
            seen.append(kwargs)

    recorder = _RecorderStream()  # strong ref: _streams is a WeakSet
    plugin._streams.add(recorder)

    plugin.update_options(language="en-US", end_window_size=1200)
    assert plugin._opts.language == "en-US"
    assert plugin._opts.end_window_size == 1200
    # 未给的字段以 NOT_GIVEN 原样透传，流端才能区分"没改"和"改成默认"
    assert seen[0]["language"] == "en-US"
    assert seen[0]["end_window_size"] == 1200


async def test_update_options_reconnects_with_new_config():
    """热更新：改配置后活流必须重连，且新连接的首帧携带新配置。"""
    ws1 = ScriptedWS([], hold_open=True)
    ws2 = ScriptedWS([], hold_open=True)
    fake = RunFakeStream([ws1, ws2])

    run_task = asyncio.create_task(SpeechStream._run(fake))
    await flush()
    assert len(ws1.sent) == 1  # 第一条连接只发了建流配置帧

    fake.update_options(end_window_size=1000)
    try:
        # Wait for the observable reconnect, not a platform-dependent 10 ms sleep.
        await asyncio.wait_for(ws2.first_send.wait(), timeout=2)
        assert ws1.closed is True
        assert len(ws2.sent) == 1
        assert _decode_config(ws2.sent[0])["request"]["end_window_size"] == 1000
    finally:
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task
    assert ws2.closed is True


async def test_usage_events_flush_on_stream_end():
    """用量上报：发送的音频帧时长经采集器在流结束时冲账。"""
    ws = ScriptedWS([], hold_open=True)
    fake = RunFakeStream(ws)

    run_task = asyncio.create_task(SpeechStream._run(fake))
    await flush()

    frame = rtc.AudioFrame(
        data=b"\x00\x00" * 160, sample_rate=16000, num_channels=1, samples_per_channel=160
    )
    fake._input_ch.send_nowait(frame)
    await flush()
    fake._input_ch.send_nowait(fake._FlushSentinel())
    await flush()

    # sentinel 只冲刷缓冲，输入关闭才发送结束包。
    assert fake._audio_duration_collector.flushed == [pytest.approx(0.01)]
    assert len(ws.sent) == 2
    assert int.from_bytes(ws.sent[-1][4:8], "big", signed=True) > 0

    run_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await run_task


async def test_usage_callback_emits_recognition_usage(stream_emitter):
    """真采集回调：RECOGNITION_USAGE 事件带 request_id 和音频时长。"""
    stream, collected = stream_emitter

    SpeechStream._on_audio_duration_report(stream, 1.5)
    await flush()

    usage = collected[0]
    assert usage.type.name == "RECOGNITION_USAGE"
    assert usage.request_id == "test-req"
    assert usage.recognition_usage.audio_duration == pytest.approx(1.5)


def test_corpus_context_dict_auto_serialized():
    """官方要求 corpus.context 为 JSON 字符串：传 dict 时自动序列化。"""
    plugin = STT(
        api_key="k",
        corpus={
            "boosting_table_name": "商品热词",
            "context": {
                "hotwords": [{"word": "自定义热词A"}],
                "context_type": "dialog_ctx",
                "context_data": [{"speaker": "bot", "text": "上一轮回复"}],
            },
        },
    )
    corpus = plugin._opts.build_request_payload(uid="u")["request"]["corpus"]
    assert corpus["boosting_table_name"] == "商品热词"
    ctx = corpus["context"]
    assert isinstance(ctx, str)
    parsed = json.loads(ctx)
    assert parsed["hotwords"] == [{"word": "自定义热词A"}]
    assert parsed["context_type"] == "dialog_ctx"


def test_corpus_context_string_passthrough():
    """已经序列化好的 context 字符串原样透传，不做二次处理。"""
    plugin = STT(api_key="k", corpus={"context": '{"hotwords":[]}'})
    corpus = plugin._opts.build_request_payload(uid="u")["request"]["corpus"]
    assert corpus["context"] == '{"hotwords":[]}'


async def test_speech_data_language_follows_option(stream_emitter):
    """语言是适配层策略（来自 language 配置），映射层不再硬编码。"""
    stream, collected = stream_emitter
    stream.language = "en-US"

    stream.emit(
        {
            "text": "hello",
            "utterances": [{"text": "hello", "definite": True, "start_time": 0, "end_time": 300}],
        }
    )
    await flush()

    final = next(e for e in collected if e.type.name == "FINAL_TRANSCRIPT")
    assert final.alternatives[0].language == "en-US"


async def test_usage_flushes_when_connection_fails():
    """quiescence：recv 侧失败取消 send 前，已发送音频的记账不能丢。"""
    ws = ScriptedWS(
        [
            # 先回一帧识别结果，让 send_task 有时间消费音频，然后对端关闭
            _ws_message(aiohttp.WSMsgType.BINARY, _result_frame({"result": [{"text": "喂"}]})),
            _ws_message(aiohttp.WSMsgType.CLOSED, None),
        ]
    )
    fake = RunFakeStream(ws)

    run_task = asyncio.create_task(SpeechStream._run(fake))
    await flush()

    frame = rtc.AudioFrame(
        # 100 ms 整：达到 AudioByteStream 攒帧阈值，立即成帧发出
        data=b"\x00\x00" * 1600,
        sample_rate=16000,
        num_channels=1,
        samples_per_channel=1600,
    )
    fake._input_ch.send_nowait(frame)
    await flush()

    with pytest.raises(APIConnectionError):
        await run_task

    # send 侧正常 flush 不会执行（任务被取消），但连接级 teardown 兜底冲账
    assert fake._audio_duration_collector.flushed == [pytest.approx(0.1)]


def test_warns_on_event_degrading_combinations(caplog):
    """请求合法但会瘫掉事件语义的组合：构造期必须显式警告，不能静默。"""
    with caplog.at_level(logging.WARNING, logger="livekit.plugins.volcengine"):
        STT(api_key="k", enable_nonstream=False)
        STT(api_key="k", show_utterances=False)
        STT(api_key="k", result_type="full")
        STT(api_key="k", audio_format="mp3")

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    # 注册表输出：能力名 + 未满足项逐条列出
    nonstream_warnings = [m for m in warnings if "enable_nonstream=True" in m]
    assert nonstream_warnings and "turn detection" in nonstream_warnings[0]
    assert any("show_utterances=True" in m for m in warnings)
    assert any("result_type='single'" in m for m in warnings)
    assert any("audio_format" in m for m in warnings)


def test_default_combination_is_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="livekit.plugins.volcengine"):
        STT(api_key="k")
    assert caplog.records == []


def test_speaker_without_utterances_warns(caplog):
    """当前官方前置条件是 show_utterances，不再要求旧隐藏参数。"""
    with caplog.at_level(logging.WARNING, logger="livekit.plugins.volcengine"):
        STT(api_key="k", show_utterances=False, extra_request_params={"enable_speaker_info": True})

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    speaker = [m for m in warnings if "speaker separation" in m]
    assert speaker and "show_utterances" in speaker[0]


def test_fully_wired_speaker_escape_hatch_is_silent(caplog):
    """逃生舱四件套配齐（含 language 不设、utterances 默认开）→ 零警告。"""
    with caplog.at_level(logging.WARNING, logger="livekit.plugins.volcengine"):
        STT(
            api_key="k",
            extra_request_params={"enable_speaker_info": True, "ssd_version": "200"},
        )
    assert caplog.records == []


def test_metadata_tags_escape_hatch_never_warns_yet(caplog):
    """元数据标签无客户端依赖：逃生舱设置不触发警告（映射未落地是文档事实）。"""
    with caplog.at_level(logging.WARNING, logger="livekit.plugins.volcengine"):
        STT(api_key="k", extra_request_params={"enable_lid": True})
    assert caplog.records == []


def test_escape_hatch_overrides_first_class_param():
    """逃生舱合并最后 → 同名覆盖一等参数。这是文档演化支撑的基石契约：
    服务端改参数语义时，用户当天即可用逃生舱试新值，无需等插件发版。"""
    plugin = STT(api_key="k", enable_itn=False, extra_request_params={"enable_itn": True})
    req = plugin._opts.build_request_payload(uid="u")["request"]
    assert req["enable_itn"] is True


async def test_unknown_result_fields_are_observable(stream_emitter, caplog):
    """未知响应字段必须在 debug 级可见——写消费者之前先要能看见数据形状。"""
    stream, _ = stream_emitter
    with caplog.at_level(logging.DEBUG, logger="livekit.plugins.volcengine"):
        stream.emit(
            {
                "text": "喂",
                "utterances": [{"text": "喂", "definite": True, "start_time": 0, "end_time": 100}],
                # 模拟官方新增参数产出的新数据
                "new_feature_payload": {"tags": ["x"]},
            }
        )
    debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("new_feature_payload" in m for m in debug_msgs)


async def test_known_fields_do_not_spam_debug_log(stream_emitter, caplog):
    """已知字段（含已知未消费的 additions）不刷 debug 日志。"""
    stream, _ = stream_emitter
    with caplog.at_level(logging.DEBUG, logger="livekit.plugins.volcengine"):
        stream.emit(
            {
                "text": "喂",
                "confidence": 0.9,
                "additions": {"log_id": "abc"},
                "utterances": [{"text": "喂", "definite": True, "start_time": 0, "end_time": 100}],
            }
        )
    assert not any("unrecognized result fields" in r.message for r in caplog.records)
