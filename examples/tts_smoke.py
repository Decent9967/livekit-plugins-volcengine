"""Opt-in real TTS probe. May incur provider charges; never run in CI.

Set VOLCENGINE_TTS_API_KEY, then run with --speaker and --output-dir.
Writes synthesized WAVs and metadata, never credentials. This is a provider
probe, not microphone/browser end-to-end acceptance.
"""

import argparse
import asyncio
import json
import logging
import time
import wave
from dataclasses import asdict
from pathlib import Path

import aiohttp
from livekit.agents import APIConnectOptions, APIError

from livekit.plugins.volcengine import TTS


async def run(speaker: str, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    options = APIConnectOptions(max_retry=0, timeout=15)
    async with aiohttp.ClientSession() as http:
        engine = TTS(speaker=speaker, http_session=http)
        usages = []
        engine.on("usage_collected", lambda usage: usages.append(asdict(usage)))
        try:
            for name, text in (
                ("complete", "你好，欢迎使用语音合成服务。"),
                ("incremental", "你好，我可以帮你挑选合适的衣服。"),
                ("cancel", "这是一段用于验证打断的语音。" * 6),
                ("after_cancel", "上一段已经停止，这是新的回复。"),
            ):
                frames, started, first_audio = [], time.perf_counter(), None
                stream = (
                    engine.stream(conn_options=options)
                    if name == "incremental"
                    else engine.synthesize(text, conn_options=options)
                )

                async def feed(target, input_text: str) -> None:
                    for char in input_text:
                        target.push_text(char)
                        await asyncio.sleep(0.03)
                    target.end_input()

                sender = asyncio.create_task(feed(stream, text)) if name == "incremental" else None
                try:
                    async with stream:
                        async for audio in stream:
                            if first_audio is None:
                                first_audio = time.perf_counter() - started
                            frames.append(bytes(audio.frame.data))
                            if name == "cancel":
                                break
                    if sender:
                        await sender
                finally:
                    if sender and not sender.done():
                        sender.cancel()
                        await asyncio.gather(sender, return_exceptions=True)
                raw = b"".join(frames)
                with wave.open(str(output / f"{name}.wav"), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(engine.sample_rate)
                    wav.writeframes(raw)
                reports.append(
                    {
                        "case": name,
                        "input_characters": len(text),
                        "audio_bytes": len(raw),
                        "audio_seconds": len(raw) / (engine.sample_rate * 2),
                        "first_audio_seconds": first_audio,
                    }
                )
                if not raw:
                    raise RuntimeError("No audio returned")
        except APIError as exc:
            reports.append(
                {"error": type(exc).__name__, "status_code": getattr(exc, "status_code", None)}
            )
            return_code = 1
        else:
            return_code = 0
        finally:
            await engine.aclose()
    result = {"speaker": speaker, "cases": reports, "provider_usage": usages}
    (output / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speaker", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    raise SystemExit(asyncio.run(run(args.speaker, args.output_dir)))
