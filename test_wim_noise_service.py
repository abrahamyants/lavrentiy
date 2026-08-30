"""Small contract tests for the FlowSE HTTP service without loading the model."""

import io
import os

os.environ["PRELOAD_MODEL"] = "0"

import numpy as np
import soundfile as sf

from wim.noise_service import app as service


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


wav_io = io.BytesIO()
sf.write(wav_io, np.zeros(1600, dtype=np.float32), 16000, format="WAV", subtype="PCM_16")
wav = wav_io.getvalue()

check("sniffs WAV", service._suffix_for(wav, "") == ".wav")
check("announced M4A gets M4A suffix", service._suffix_for(b"x" * 12, "m4a") == ".m4a")

client = service.app.test_client()
health = client.get("/healthz")
check("health endpoint works before model load", health.status_code == 200)
check("ready stays closed before model load", client.get("/ready").status_code == 503)
check("empty audio is rejected", client.post("/v1/enhance", data=b"").status_code == 400)
check("unknown audio is rejected", client.post("/v1/enhance", data=b"x" * 100).status_code == 400)

print(f"PASSED: {passed}  FAILED: {failed}")
raise SystemExit(1 if failed else 0)

