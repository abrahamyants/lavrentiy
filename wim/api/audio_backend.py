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


def _sniff_container(audio_bytes):
    """Return "wav" or "m4a" for a recognised container, else None.

    WiM compresses the recorder's 16 kHz mono PCM to AAC before upload — raw
    WAV is 32 KB per second of speech and the phone uplink, not inference, is
    what users feel. WAV is still accepted: builds already in Play review send
    it, and the transcoder falls back to WAV whenever an OEM encoder misbehaves.
    """
    if len(audio_bytes) < 12:
        return None
    if audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
        return "wav"
    # ISO base media: a size-prefixed 'ftyp' box opens the file.
    if audio_bytes[4:8] == b"ftyp":
        return "m4a"
    return None


def named_audio_file(audio_bytes, container):
    audio_file = io.BytesIO(audio_bytes)
    # OpenAI picks its demuxer off the filename, not the bytes.
    audio_file.name = "wim-recording." + container
    return audio_file


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
    container = _sniff_container(audio_bytes)
    if container is None:
        raise AudioRequestError("Audio must be a valid WAV or M4A file")

    model = body.get("model", "gpt-4o-transcribe")
    if model not in AUDIO_MODELS:
        raise AudioRequestError("Unsupported transcription model")
    try:
        temperature = max(0.0, min(float(body.get("temperature", 0.0)), 1.0))
    except (TypeError, ValueError):
        raise AudioRequestError("Invalid temperature")

    audio_file = named_audio_file(audio_bytes, container)
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
    if verbose and bool(body.get("word_timestamps", False)):
        kwargs["timestamp_granularities"] = ["word", "segment"]
    return kwargs, len(audio_bytes), model, audio_bytes, container
