"""Offline contract tests for the authenticated WiM audio request."""

import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "wim", "api"))
from audio_backend import AudioRequestError, MAX_AUDIO_BYTES, estimate_audio_seconds, prepare_audio_request

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



# estimate_audio_seconds: WAV reads the header, M4A estimates from size.
import struct
def _wav_bytes(seconds, rate=16000):
    data = b"\0" * int(seconds * rate * 2)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", len(data)) + data)
check("wav 2.5 s reads 2.5", estimate_audio_seconds(_wav_bytes(2.5)) == 2.5)
check("wav 390 s (12 MB cap) reads 390", estimate_audio_seconds(_wav_bytes(390)) == 390.0)
check("wav without fmt chunk is 0", estimate_audio_seconds(wav) == 0.0)
m4a = b"\0\0\0\x18ftypM4A " + b"\0" * (64_000 // 8 * 10 - 12)
check("m4a 10 s at 64 kbps estimates 10", estimate_audio_seconds(m4a) == 10.0)
check("garbage is 0", estimate_audio_seconds(b"hello") == 0.0)
check("empty is 0", estimate_audio_seconds(b"") == 0.0)

print(f"PASSED: {passed}  FAILED: {failed}")
raise SystemExit(1 if failed else 0)
