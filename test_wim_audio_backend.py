"""Offline contract tests for the authenticated WiM audio request."""

import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "wim", "api"))
from audio_backend import AudioRequestError, MAX_AUDIO_BYTES, prepare_audio_request

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


wav = b"RIFF" + b"\0" * 4 + b"WAVE" + b"\0" * 92
encoded = base64.b64encode(wav).decode()

kwargs, size, model = prepare_audio_request({
    "audio_base64": encoded,
    "model": "whisper-1",
    "language": "es",
    "verbose_segments": True,
    "prompt": "Dr. Nwosu",
})
check("decodes audio", size == len(wav))
check("uses verbose JSON only for whisper-1", kwargs["response_format"] == "verbose_json")
check("passes language", kwargs["language"] == "es")
check("passes Script Prep prompt", kwargs["prompt"] == "Dr. Nwosu")
check("names upload as WAV", kwargs["file"].name.endswith(".wav"))

kwargs2, _, _ = prepare_audio_request({
    "audio_base64": encoded,
    "model": "gpt-4o-transcribe",
    "verbose_segments": True,
})
check("gpt-4o transcription avoids unsupported verbose_json", kwargs2["response_format"] == "json")

for label, body, status in [
    ("missing audio rejected", {}, 400),
    ("bad base64 rejected", {"audio_base64": "%%%"}, 400),
    ("unknown model rejected", {"audio_base64": encoded, "model": "anything"}, 400),
    ("empty audio rejected", {"audio_base64": base64.b64encode(b"").decode()}, 400),
    ("non-WAV payload rejected", {"audio_base64": base64.b64encode(b"x" * 100).decode()}, 400),
]:
    try:
        prepare_audio_request(body)
        check(label, False)
    except AudioRequestError as e:
        check(label, e.status == status)

too_large = base64.b64encode(b"x" * (MAX_AUDIO_BYTES + 1)).decode()
try:
    prepare_audio_request({"audio_base64": too_large})
    check("oversized audio rejected", False)
except AudioRequestError as e:
    check("oversized audio rejected", e.status == 413)

print(f"PASSED: {passed}  FAILED: {failed}")
raise SystemExit(1 if failed else 0)
