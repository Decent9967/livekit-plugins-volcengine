import asyncio
import json
import struct
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from livekit.agents import APIConnectionError, APIConnectOptions, APIStatusError, APITimeoutError
from test_tts_protocol import response

from livekit.plugins.volcengine import TTS

OPTIONS = APIConnectOptions(max_retry=0, timeout=1.0)
PCM = b"\x00\x01" * 4800


def request(data):
    event = int.from_bytes(data[4:8], "big")
    offset, sid = 8, ""
    if event >= 100:
        size = int.from_bytes(data[offset : offset + 4], "big")
        offset += 4
        sid = data[offset : offset + size].decode()
        offset += size
    return event, sid, json.loads(data[offset + 4 :])


class Server:
    def __init__(self, fault=None):
        self.fault = fault
        self.connections = 0
        self.requests = []
        self.headers = []
        self.closed = asyncio.Event()
        self.text_received = asyncio.Event()

    async def handle(self, req):
        ws = web.WebSocketResponse()
        ws.headers["x-tt-logid"] = "test-logid"
        await ws.prepare(req)
        self.connections += 1
        connection = self.connections
        self.headers.append(dict(req.headers))
        try:
            async for message in ws:
                if message.type != aiohttp.WSMsgType.BINARY:
                    continue
                event, sid, payload = request(message.data)
                self.requests.append((connection, event, sid, payload))
                if event == 1:
                    if self.fault != "connection_timeout":
                        await ws.send_bytes(response(50, identifier="connection"))
                elif event == 100:
                    if self.fault == "start_timeout":
                        continue
                    if self.fault == "error_frame":
                        raw = b"Invalid voice test-key"
                        await ws.send_bytes(
                            b"\x11\xf0\x00\x00" + struct.pack(">II", 45000001, len(raw)) + raw
                        )
                    elif self.fault == "status":
                        await ws.send_bytes(response(153, b'{"status_code":45000001}'))
                    else:
                        await ws.send_bytes(response(150, identifier=sid))
                elif event == 200:
                    self.text_received.set()
                    if self.fault in ("subtitle_bad", "subtitle_wrong_session"):
                        await ws.send_bytes(
                            response(
                                364,
                                b"[]" if self.fault == "subtitle_bad" else b"{}",
                                identifier="another-session"
                                if self.fault == "subtitle_wrong_session"
                                else sid,
                            )
                        )
                    if self.fault == "subtitle":
                        await ws.send_bytes(
                            response(
                                364,
                                json.dumps(
                                    {
                                        "text": "Price",
                                        "words": [
                                            {
                                                "word": "Price",
                                                "startTime": 0.1,
                                                "endTime": 0.3,
                                                "confidence": 0.9,
                                            }
                                        ],
                                    }
                                ).encode(),
                                identifier=sid,
                            )
                        )
                    if self.fault == "retry" and connection == 1:
                        await ws.close()
                    elif self.fault != "silent":
                        pcm = b"\x00\x02" * 4800 if connection > 1 else PCM
                        await ws.send_bytes(response(352, pcm, identifier=sid, audio=True))
                        if self.fault == "partial":
                            await ws.close()
                elif event == 102:
                    if self.fault == "finish_status":
                        await ws.send_bytes(
                            response(152, b'{"status_code":45000001}', identifier=sid)
                        )
                        continue
                    await ws.send_bytes(
                        response(152, b'{"usage":{"text_words":5}}', identifier=sid)
                    )
                    if self.fault == "idle_close":
                        req.transport.close()
                        break
                elif event == 101:
                    # Audio may already be queued upstream when cancellation arrives.
                    await ws.send_bytes(response(352, PCM, identifier=sid, audio=True))
                    await ws.send_bytes(response(151, identifier=sid))
                elif event == 2:
                    await ws.send_bytes(response(52, identifier="connection"))
                    await ws.close()
        finally:
            self.closed.set()
        return ws


@asynccontextmanager
async def setup(fault=None, **options):
    server = Server(fault)
    app = web.Application()
    app.router.add_get("/tts", server.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as http:
            engine = TTS(
                api_key="test-key",
                speaker="test-voice",
                http_session=http,
                base_url=f"http://127.0.0.1:{port}/tts",
                **options,
            )
            try:
                yield engine, server
            finally:
                await engine.aclose()
            assert not http.closed  # Caller owns the supplied HTTP session.
    finally:
        await runner.cleanup()


async def collect(stream):
    async with stream:
        return [audio async for audio in stream]


async def test_incremental_text_audio_usage_and_connection_reuse():
    async with setup() as (engine, server):
        usage = []
        engine.on("usage_collected", usage.append)
        stream = engine.stream(conn_options=OPTIONS)
        stream.push_text("你好，")
        # Audio must arrive before the text stream ends.
        first = await asyncio.wait_for(anext(stream), 2)
        assert first.frame.sample_rate == 24000
        stream.push_text("欢迎。")
        stream.end_input()
        rest = await collect(stream)
        assert rest[-1].is_final
        assert usage[0].text_words == 5
        assert usage[0].logid == "test-logid"
        assert usage[0].request_id == first.request_id
        assert usage[0].usage == {"text_words": 5}
        assert await collect(engine.synthesize("再次问候。", conn_options=OPTIONS))
        assert server.connections == 1
        assert server.headers[0]["X-Control-Require-Usage-Tokens-Return"] == "*"
        texts = [r[3]["req_params"]["text"] for r in server.requests if r[1] == 200]
        assert texts == ["你好，", "欢迎。", "再次问候。"]
        assert len({r[2] for r in server.requests if r[1] == 100}) == 2


async def test_flush_finishes_without_waiting_for_end_input():
    async with setup() as (engine, _):
        stream = engine.stream(conn_options=OPTIONS)
        stream.push_text("你好")
        stream.flush()
        assert await asyncio.wait_for(collect(stream), 2)


async def test_expired_connection_replaced_without_retry_or_duplicate_text(monkeypatch):
    from livekit.agents.utils import connection_pool

    now = 1000.0
    monkeypatch.setattr(
        connection_pool, "time", SimpleNamespace(time=lambda: now, perf_counter=time.perf_counter)
    )
    async with setup("idle_close") as (engine, server):
        assert await collect(engine.synthesize("First", conn_options=OPTIONS))
        await asyncio.wait_for(server.closed.wait(), 2)
        now += 30
        assert await collect(engine.synthesize("Second", conn_options=OPTIONS))
        assert server.connections == 2
        texts = [r[3]["req_params"]["text"] for r in server.requests if r[1] == 200]
        assert texts == ["First", "Second"]


async def test_connection_age_limit_does_not_interrupt_active_synthesis(monkeypatch):
    from livekit.agents.utils import connection_pool

    now = 1000.0
    monkeypatch.setattr(
        connection_pool, "time", SimpleNamespace(time=lambda: now, perf_counter=time.perf_counter)
    )
    async with setup() as (engine, server):
        stream = engine.stream(conn_options=OPTIONS)
        stream.push_text("First")
        await asyncio.wait_for(anext(stream), 2)
        now += 30
        stream.push_text(" continuation")
        stream.end_input()
        assert await collect(stream)
        assert server.connections == 1
        assert await collect(engine.synthesize("Next", conn_options=OPTIONS))
        assert server.connections == 2
        texts = [r[3]["req_params"]["text"] for r in server.requests if r[1] == 200]
        assert texts == ["First", " continuation", "Next"]


async def test_empty_input_does_not_connect():
    async with setup() as (engine, server):
        stream = engine.stream(conn_options=OPTIONS)
        stream.end_input()
        assert await collect(stream) == []
        assert await collect(engine.synthesize("", conn_options=OPTIONS)) == []
        assert server.connections == 0


async def test_cancel_discards_connection_before_next_reply():
    async with setup() as (engine, server):
        stream = engine.stream(conn_options=OPTIONS)
        stream.push_text("旧回复")
        await asyncio.wait_for(anext(stream), 2)
        await stream.aclose()
        await asyncio.wait_for(server.closed.wait(), 2)
        assert any(r[1] == 101 for r in server.requests)
        new_audio = await collect(engine.synthesize("新回复", conn_options=OPTIONS))
        assert new_audio
        assert b"".join(bytes(audio.frame.data) for audio in new_audio) == b"\x00\x02" * 4800
        assert server.connections == 2


async def test_sdk_replays_text_once_after_failure_before_audio():
    async with setup("retry") as (engine, server):
        stream = engine.stream(
            conn_options=APIConnectOptions(max_retry=1, retry_interval=0, timeout=1)
        )
        stream.push_text("重试文本")
        stream.end_input()
        assert await collect(stream)
        assert server.connections == 2
        texts = [r[3]["req_params"]["text"] for r in server.requests if r[0] == 2 and r[1] == 200]
        assert texts == ["重试文本"]


async def test_partial_audio_is_not_replayed():
    async with setup("partial") as (engine, server):
        stream = engine.stream(
            conn_options=APIConnectOptions(max_retry=1, retry_interval=0, timeout=1)
        )
        stream.push_text("已开始播放")
        with pytest.raises(APIConnectionError):
            await collect(stream)
        assert server.connections == 1


async def test_client_error_not_retried():
    async with setup("status") as (engine, server):
        with pytest.raises(APIStatusError) as exc:
            await collect(engine.synthesize("错误", conn_options=OPTIONS))
        assert exc.value.status_code == 45000001
        assert not exc.value.retryable
        assert server.connections == 1


def test_options_and_escape_hatch_preserve_audio_contract():
    options = {"context_texts": ["自然地说话"], "post_process": {"pitch": 2}}
    engine = TTS(api_key="test", speaker="voice", additions=options, speech_rate=20)
    options["post_process"]["pitch"] = 5
    params = engine._opts.request()
    assert params["audio_params"] == {
        "format": "pcm",
        "sample_rate": 24000,
        "speech_rate": 20,
        "loudness_rate": 0,
    }
    assert json.loads(params["additions"])["post_process"]["pitch"] == 2
    with pytest.raises(ValueError, match="audio_params"):
        TTS(
            api_key="test",
            speaker="voice",
            extra_request_params={"audio_params": {"format": "mp3"}},
        )


@pytest.mark.parametrize(
    "options",
    [
        {"sample_rate": 123},
        {"speech_rate": 101},
        {"loudness_rate": -51},
        {"model": "seed-tts-2.0-standard", "context_texts": ["温柔"]},
    ],
)
def test_invalid_options_fail_before_connect(options):
    with pytest.raises(ValueError):
        TTS(api_key="test", speaker="voice", **options)


async def test_plain_error_frame_keeps_code_and_redacts_key():
    async with setup("error_frame") as (engine, _):
        with pytest.raises(APIStatusError) as exc:
            await collect(engine.synthesize("test", conn_options=OPTIONS))
        assert exc.value.status_code == 45000001
        assert "test-key" not in str(exc.value)
        assert "Invalid voice" in str(exc.value)


@pytest.mark.parametrize("fault", ["connection_timeout", "start_timeout", "silent"])
async def test_session_timeout_closes_socket(fault):
    async with setup(fault) as (engine, server):
        stream = engine.stream(conn_options=APIConnectOptions(max_retry=0, timeout=0.1))
        stream.push_text("test")
        with pytest.raises(APITimeoutError):
            await collect(stream)
        await asyncio.wait_for(server.closed.wait(), 2)


async def test_engine_close_cancels_waiting_streams():
    async with setup("silent") as (engine, server):
        stream = engine.stream(conn_options=OPTIONS)
        stream.push_text("test")
        await asyncio.wait_for(server.text_received.wait(), 2)
        await asyncio.wait_for(asyncio.gather(engine.aclose(), engine.aclose()), 2)
        await asyncio.wait_for(server.closed.wait(), 2)
        assert stream._task.done()
        with pytest.raises(RuntimeError, match="closed"):
            engine.stream()


async def test_failed_finish_is_not_reported_as_success():
    async with setup("finish_status") as (engine, _):
        with pytest.raises(APIStatusError) as exc:
            await collect(engine.synthesize("test", conn_options=OPTIONS))
        assert exc.value.status_code == 45000001


async def test_send_failure_cancels_receiver_and_closes_socket(monkeypatch):
    original = aiohttp.ClientWebSocketResponse.send_bytes

    async def fail_task_request(ws, data, *args, **kwargs):
        if request(data)[0] == 200:
            raise OSError("synthetic send failure")
        return await original(ws, data, *args, **kwargs)

    monkeypatch.setattr(aiohttp.ClientWebSocketResponse, "send_bytes", fail_task_request)
    async with setup() as (engine, server):
        with pytest.raises(APIConnectionError):
            await collect(engine.synthesize("test", conn_options=OPTIONS))
        await asyncio.wait_for(server.closed.wait(), 2)


async def test_named_controls_and_subtitle_event_round_trip():
    options = dict(
        disable_markdown_filter=True,
        disable_emoji_filter=False,
        max_length_to_filter_parenthesis=120,
        latex_parser="v2",
        explicit_language="en",
        explicit_dialect="yue",
        aigc_watermark=False,
        pitch=-12,
        section_id="call-1",
        pronunciation_dict={"tone": ["omg/oh my god"]},
        enable_subtitle=True,
        additions={"disable_emoji_filter": True, "future": 1},
    )
    async with setup(fault="subtitle", **options) as (engine, server):
        subtitles = []
        engine.on("subtitle", subtitles.append)
        audio = await collect(engine.synthesize("Price $29.99", conn_options=OPTIONS))
        params = next(r[3]["req_params"] for r in server.requests if r[1] == 100)
        additions = json.loads(params["additions"])
        assert params["audio_params"]["enable_subtitle"] is True
        assert additions == {
            "disable_markdown_filter": True,
            "disable_emoji_filter": False,
            "max_length_to_filter_parenthesis": 120,
            "latex_parser": "v2",
            "explicit_language": "en",
            "explicit_dialect": "yue",
            "aigc_watermark": False,
            "post_process": {"pitch": -12},
            "section_id": "call-1",
            "pronunciation_dict": {"tone": ["omg/oh my god"]},
            "future": 1,
        }
        assert subtitles[0].request_id == audio[0].request_id
        assert subtitles[0].logid == "test-logid"
        assert subtitles[0].payload["words"][0]["startTime"] == 0.1
        assert subtitles[0].payload["text"] == "Price"
        assert await collect(engine.synthesize("Again", conn_options=OPTIONS))
        assert server.connections == 1


@pytest.mark.parametrize("fault", ["subtitle_bad", "subtitle_wrong_session"])
async def test_invalid_subtitle_fails_without_emitting_event(fault):
    async with setup(fault=fault, enable_subtitle=True) as (engine, _):
        events = []
        engine.on("subtitle", events.append)
        with pytest.raises(APIConnectionError):
            await collect(engine.synthesize("hello", conn_options=OPTIONS))
        assert events == []
