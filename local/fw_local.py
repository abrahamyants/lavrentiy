"""faster-whisper wrapper used by Lavrentiy's free local transcription path."""

import logging
import os
from pathlib import Path

_log = logging.getLogger("lavrentiy.fw_local")
_model = None

_SIZE_MAP = {
    "tiny": "tiny",
    "tiny.en": "tiny.en",
    "base": "base",
    "base.en": "base.en",
    "small": "small",
    "small.en": "small.en",
    "medium": "medium",
    "medium.en": "medium.en",
    "large-v2": "large-v2",
    "large-v3": "large-v3",
    "turbo": "large-v3-turbo",
    "large-v3-turbo": "large-v3-turbo",
}


def _resolve_size(model_size):
    """Use the installer-selected size, falling back to the bundled model."""
    selected = os.environ.get("LAV_FW_MODEL_SIZE", "small.en")
    return _SIZE_MAP.get(selected, selected)


def _resolve_model_dir(size_key):
    """Return the first installed model directory, or None to allow download."""
    repo = Path(__file__).resolve().parent.parent
    candidates = []
    env_dir = os.environ.get("LAV_FW_MODEL_DIR")
    if env_dir:
        candidates.extend((Path(env_dir), Path(env_dir) / size_key))
    candidates.extend(
        (
            repo / "models" / "faster-whisper" / size_key,
            repo / "eval-build" / "models" / "faster-whisper" / size_key,
            Path.home() / ".cache" / "faster-whisper" / size_key,
        )
    )
    for path in candidates:
        if (path / "model.bin").exists():
            return path
    return None


def _get_model(model_size):
    global _model
    if _model is not None:
        return _model

    from faster_whisper import WhisperModel

    size_key = _resolve_size(model_size)
    model_dir = _resolve_model_dir(size_key)
    compute_type = os.environ.get("LAV_FW_COMPUTE_TYPE", "int8")
    device = os.environ.get("LAV_FW_DEVICE", "cpu")
    if model_dir is not None:
        _log.info("Loading faster-whisper from %s", model_dir)
        _model = WhisperModel(str(model_dir), device=device, compute_type=compute_type)
    else:
        if os.environ.get("LAV_OFFLINE") == "1":
            raise FileNotFoundError(
                f"faster-whisper model '{size_key}' is missing and LAV_OFFLINE=1 "
                "prevents downloading it"
            )
        _log.info("Downloading faster-whisper '%s' from Hugging Face", size_key)
        _model = WhisperModel(size_key, device=device, compute_type=compute_type)
    return _model


def transcribe(filepath, temperature, prompt_text, language="en", model_size="base"):
    """Return local ASR output in the same shape as the cloud transcription path."""
    model = _get_model(model_size)
    temp = float(temperature) if temperature is not None else 0.0
    segments_iter, _info = model.transcribe(
        str(filepath),
        language=language or "en",
        task="transcribe",
        beam_size=5,
        temperature=temp,
        initial_prompt=prompt_text,
        vad_filter=False,
        word_timestamps=False,
        condition_on_previous_text=False,
    )

    segments = [
        {
            "text": segment.text,
            "start": float(segment.start),
            "end": float(segment.end),
            "avg_logprob": float(segment.avg_logprob),
            "no_speech_prob": float(segment.no_speech_prob),
        }
        for segment in segments_iter
    ]
    return {
        "text": "".join(segment["text"] for segment in segments).strip(),
        "segments": segments,
        "engine": "faster-whisper",
    }
