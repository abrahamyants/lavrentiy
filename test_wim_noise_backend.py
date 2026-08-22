"""Offline contract tests for the private WiM noise service client."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "wim", "api"))
from noise_backend import NoiseEnhancementError, enhance_audio


passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print("PASS:", label)
    else:
        failed += 1
        print("FAIL:", label)


clean_wav = b"RIFF" + b"\0" * 4 + b"WAVE" + b"\0" * 92
calls = []


class FakeResponse:
    status_code = 200
    content = clean_wav
    text = ""
    headers = {
        "X-WiM-Noise-Model": "urgent2026-bsrnn-flow",
        "X-WiM-Noise-Cache": "hit",
        "X-WiM-Noise-Ms": "17",
    }


def fake_post(url, **kwargs):
    calls.append((url, kwargs))
    return FakeResponse()


result, meta = enhance_audio(
    b"source-audio",
    "m4a",
    service_url="https://noise.example",
    post=fake_post,
    token_provider=lambda audience: "service-token",
)
check("returns clean WAV", result == clean_wav)
check("calls enhance endpoint", calls[0][0] == "https://noise.example/v1/enhance")
check("sends service token", calls[0][1]["headers"]["Authorization"] == "Bearer service-token")
check("sends source container", calls[0][1]["headers"]["X-WiM-Audio-Format"] == "m4a")
check("surfaces model metadata", meta["model"] == "urgent2026-bsrnn-flow")


class BadResponse(FakeResponse):
    content = b"not-a-wav"


try:
    enhance_audio(
        b"source-audio",
        "wav",
        service_url="https://noise.example",
        post=lambda *args, **kwargs: BadResponse(),
        token_provider=lambda audience: "service-token",
    )
    check("rejects invalid service output", False)
except NoiseEnhancementError:
    check("rejects invalid service output", True)


print(f"PASSED: {passed}  FAILED: {failed}")
raise SystemExit(1 if failed else 0)

