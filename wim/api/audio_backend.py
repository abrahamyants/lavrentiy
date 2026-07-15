"""Validation and request preparation for WiM's authenticated audio route."""

import base64
import binascii
import io

MAX_AUDIO_BYTES = 12 * 1024 * 1024
AUDIO_MODELS = {"whisper-1", "gpt-4o-transcribe"}


class AudioRequestError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def prepare_audio_request(body):
    encoded = body.get("audio_base64") or ""
    if not isinstance(encoded, str) or not encoded:
        raise AudioRequestError("Missing 'audio_base64' field")
    if len(encoded) > ((MAX_AUDIO_BYTES + 2) // 3) * 4:
        raise AudioRequestError("Audio exceeds 12 MB limit", 413)
    try:
        audio_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise AudioRequestError("Invalid base64 audio")
    if not audio_bytes or len(audio_bytes) > MAX_AUDIO_BYTES:
        raise AudioRequestError("Audio is empty or exceeds 12 MB limit", 413)
    if (len(audio_bytes) < 44 or audio_bytes[:4] != b"RIFF" or
            audio_bytes[8:12] != b"WAVE"):
        raise AudioRequestError("Audio must be a valid WAV file")

    model = body.get("model", "gpt-4o-transcribe")
    if model not in AUDIO_MODELS:
        raise AudioRequestError("Unsupported transcription model")
    try:
        temperature = max(0.0, min(float(body.get("temperature", 0.0)), 1.0))
    except (TypeError, ValueError):
        raise AudioRequestError("Invalid temperature")

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "wim-recording.wav"
    verbose = bool(body.get("verbose_segments", True)) and model == "whisper-1"
    kwargs = {
        "model": model,
        "file": audio_file,
        "language": (body.get("language") or "en")[:16],
        "temperature": temperature,
        "response_format": "verbose_json" if verbose else "json",
    }
    prompt = (body.get("prompt") or "").strip()
    if prompt:
        kwargs["prompt"] = prompt[:4000]
    return kwargs, len(audio_bytes), model
