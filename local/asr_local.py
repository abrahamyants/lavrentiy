# Local L1 ASR dispatcher for Lavrentiy.
# Single engine: faster-whisper (CTranslate2). Returns the verbose segment
# confidence data used by the reconstruction pipeline.

from local.fw_local import transcribe as _fw_transcribe


def transcribe(filepath, temperature, prompt_text, language="en", model_size="base"):
    """Run local faster-whisper and return text, segments, and engine name."""
    result = _fw_transcribe(filepath, temperature, prompt_text, language, model_size)
    if result is None:
        raise RuntimeError("faster-whisper returned None")
    result.setdefault("engine", "faster-whisper")
    return result
