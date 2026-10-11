"""Validation and request preparation for WiM's authenticated audio route."""

import base64
import binascii
import io

MAX_AUDIO_BYTES = 12 * 1024 * 1024
# AAC from the phone's encoder runs 64-128 kbps; assuming the low end makes the
# estimate err long, so the minutes cap can only over-count, never under-count.
M4A_ASSUMED_BITS_PER_SECOND = 64_000
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


def estimate_audio_seconds(audio_bytes):
    """Seconds of audio in *audio_bytes*, read from the WAV header or
    estimated from size for M4A. Feeds the per-period minutes cap; the
    transcription provider bills by the minute, so this is the number that
    tracks cost. Returns 0.0 for anything unrecognised."""
    if not audio_bytes:
        return 0.0
    container = _sniff_container(audio_bytes)
    if container == "wav":
        pos = 12
        byte_rate = 0
        data_len = None
        while pos + 8 <= len(audio_bytes):
            cid = audio_bytes[pos:pos + 4]
            size = int.from_bytes(audio_bytes[pos + 4:pos + 8], "little")
            if cid == b"fmt " and pos + 16 <= len(audio_bytes):
                byte_rate = int.from_bytes(audio_bytes[pos + 16:pos + 20], "little")
            elif cid == b"data":
                data_len = min(size, len(audio_bytes) - pos - 8)
                break
            pos += 8 + size + (size & 1)
        if byte_rate <= 0:
            return 0.0
        if data_len is None:
            data_len = max(0, len(audio_bytes) - 44)
        return round(data_len / byte_rate, 1)
    if container == "m4a":
        return round(len(audio_bytes) * 8 / M4A_ASSUMED_BITS_PER_SECOND, 1)
    return 0.0


def _truthy(value, default=False):
    """Booleans arrive as JSON bools on the wrapped route and as strings
    ("true"/"false") on the multipart route. bool("false") is True — so
    parse, don't cast."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def prepare_audio_request(body, audio_bytes=None):
    """Two envelopes, one recording.

    - Wrapped (original): JSON body with `audio_base64`. Every build already
      in the wild sends this; it stays.
    - Raw (2026-09-06): multipart/form-data with the audio as the `file`
      part; `handle()` passes the bytes in as `audio_bytes`. A third fewer
      bytes over the phone's uplink and no decode step here.
    """
    if audio_bytes is None:
        encoded = body.get("audio_base64") or ""
        if not isinstance(encoded, str) or not encoded:
            raise AudioRequestError("Missing 'audio_base64' field or 'file' part")
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

    audio_file = io.BytesIO(audio_bytes)
    # OpenAI picks its demuxer off the filename, not the bytes — an .m4a body
    # announced as .wav is rejected as corrupt.
    audio_file.name = "wim-recording." + container
    verbose = _truthy(body.get("verbose_segments"), default=True) and model == "whisper-1"
    kwargs = {
        "model": model,
        "file": audio_file,
        "language": (str(body.get("language") or "en"))[:16],
        "temperature": temperature,
        "response_format": "verbose_json" if verbose else "json",
    }
    # Per-word times for the phone's clock-broom (timed filler stripping).
    # whisper-1 + verbose_json only; word granularity alone drops the
    # segments array, and the phone still reads segments — ask for both.
    if verbose and _truthy(body.get("word_timestamps")):
        kwargs["timestamp_granularities"] = ["word", "segment"]
    prompt = (body.get("prompt") or "").strip()
    if prompt:
        kwargs["prompt"] = prompt[:4000]
    return kwargs, len(audio_bytes), model
