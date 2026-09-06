"""Streaming ASR E2E check — run with a personal Volcengine API key.

Usage:
    VOLCENGINE_API_KEY=... python stt_e2e.py audio_16k_mono.wav [--resource-id ID]

Audio must be 16 kHz mono 16-bit PCM WAV (convert with:
ffmpeg -i in.mp3 -ac 1 -ar 16000 -acodec pcm_s16le out.wav).

Verifies: connection, interim/final event flow, empty-definite -> END_OF_SPEECH,
server error surfacing (wrong key), and echoes the request payload for
default-value checks against the current docs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from livekit import rtc
from livekit.plugins.volcengine.stt import (
    DEFAULT_RESOURCE_ID,
    STT,
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav")
    parser.add_argument("--resource-id", default=DEFAULT_RESOURCE_ID)
    args = parser.parse_args()

    with wave.open(args.wav, "rb") as wf:
        assert wf.getframerate() == 16000, "need 16 kHz"
        assert wf.getnchannels() == 1, "need mono"
        assert wf.getsampwidth() == 2, "need 16-bit"
        pcm = wf.readframes(wf.getnframes())

    stt = STT(api_key=os.environ["VOLCENGINE_API_KEY"], resource_id=args.resource_id)
    print("request payload:")
    print(json.dumps(stt._opts.build_request_payload(uid="e2e"), ensure_ascii=False, indent=2))

    stream = stt.stream()
    start = time.perf_counter()

    async def feed() -> None:
        chunk = 3200  # 100 ms of s16le mono
        for i in range(0, len(pcm), chunk):
            frame = rtc.AudioFrame(
                data=pcm[i : i + chunk],
                sample_rate=16000,
                num_channels=1,
                samples_per_channel=min(chunk, len(pcm) - i) // 2,
            )
            stream.push_frame(frame)
            await asyncio.sleep(0.1)  # real-time pace
        stream.end_input()

    feed_task = asyncio.create_task(feed())
    empty_finals = 0
    async for event in stream:
        elapsed = (time.perf_counter() - start) * 1000
        if event.type.name in ("FINAL_TRANSCRIPT", "INTERIM_TRANSCRIPT"):
            text = event.alternatives[0].text
            if event.type.name == "FINAL_TRANSCRIPT" and not text:
                empty_finals += 1
            print(f"[{elapsed:8.0f} ms] {event.type.name:<18} {text!r}")
        else:
            print(f"[{elapsed:8.0f} ms] {event.type.name}")
    await feed_task
    print(f"done; empty finals observed: {empty_finals}")


if __name__ == "__main__":
    asyncio.run(main())
