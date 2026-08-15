# Local L1 ASR dispatcher for Lavrentiy.
#
# Two engines, tried in order:
#
#   1. faster-whisper (CTranslate2), when the model was bundled. Returns the
#      verbose segment confidence data the reconstruction layers use, and is
#      what Layer 4 reads its clinical signals out of.
#   2. Windows' built-in recognizer, when it was not. Free, offline, already
#      installed, no download — and noticeably less accurate, with no segment
#      confidences at all. It exists so the ~40 MB online build still hears
#      you when the network is gone.
#
# The order never inverts: a build carrying the model never touches the OS
# recognizer.

import logging

_log = logging.getLogger(__name__)

try:
    from local.fw_local import transcribe as _fw_transcribe
except Exception:                          # noqa: BLE001
    _fw_transcribe = None


def _try_windows(filepath, temperature, prompt_text, language):
    from local.win_local import transcribe as _win_transcribe
    return _win_transcribe(filepath, temperature, prompt_text, language)


def transcribe(filepath, temperature, prompt_text, language="en", model_size="base"):
    """Run local ASR and return text, segments, and engine name."""
    if _fw_transcribe is not None:
        try:
            result = _fw_transcribe(filepath, temperature, prompt_text, language, model_size)
            if result is not None:
                result.setdefault("engine", "faster-whisper")
                return result
            _log.warning("faster-whisper returned None; trying the OS recognizer")
        except Exception as e:             # noqa: BLE001
            # A missing model directory lands here on the online build, and so
            # does a genuine decode failure on the offline one. Either way the
            # OS recognizer is a better answer than no transcription.
            _log.warning("faster-whisper unavailable (%s); trying the OS recognizer", e)

    return _try_windows(filepath, temperature, prompt_text, language)
