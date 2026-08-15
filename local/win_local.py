# Windows' built-in speech recognition, used when no model was bundled.
#
# The offline build carries faster-whisper small.en — 464 MB, and better than
# anything the OS provides. The online build leaves it out to be ~40 MB, and
# without this module every transcription on that build would have to go over
# the network: nothing offline, and a cost per take.
#
# Windows has shipped a recognizer since Vista. It is free, offline, already
# installed, and weighs nothing. It is also markedly less accurate than Whisper
# and hears only the system's installed languages, so it sits below
# faster-whisper in the dispatcher and is never chosen when the model exists.
#
# Reached through pythonnet, which the app already bundles for the WebView2
# window, so this adds no dependency.

import logging

_log = logging.getLogger(__name__)
_engine = None


def _load_engine():
    """Build a dictation recognizer, or raise so the caller can fall through."""
    global _engine
    if _engine is not None:
        return _engine

    import clr  # noqa: F401  (pythonnet; provides the CLR import hook)
    clr.AddReference("System.Speech")
    from System.Speech.Recognition import (  # type: ignore
        SpeechRecognitionEngine,
        DictationGrammar,
    )

    engine = SpeechRecognitionEngine()
    # Free dictation rather than a fixed command grammar: the speaker is
    # composing a message, not picking from a menu.
    engine.LoadGrammar(DictationGrammar())
    _engine = engine
    return _engine


def transcribe(filepath, temperature=0.0, prompt_text=None, language="en",
               model_size=None):
    """Transcribe a WAV with the OS recognizer.

    Returns the pipeline's shape: text, segments, engine. `segments` is always
    empty — Windows exposes no per-segment confidence, and the reconstruction
    layers treat that data as optional. Layer 4's clinical signals lean on it,
    which is one more reason this is the fallback and not the default.
    """
    engine = _load_engine()
    engine.SetInputToWaveFile(str(filepath))

    parts = []
    # Recognize() returns one utterance at a time and None at end of audio.
    # A bounded loop, because a recognizer that never returns None would
    # otherwise hang the dictation thread forever.
    for _ in range(400):
        try:
            result = engine.Recognize()
        except Exception as e:            # noqa: BLE001
            _log.warning("Windows recognizer stopped: %s", e)
            break
        if result is None:
            break
        text = (getattr(result, "Text", "") or "").strip()
        if text:
            parts.append(text)

    try:
        engine.SetInputToNull()           # release the file handle
    except Exception:                     # noqa: BLE001
        pass

    return {
        "text": " ".join(parts).strip(),
        "segments": [],
        "engine": "windows-speech",
    }
