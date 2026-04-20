"""
Phase 4 — Ears shootout benchmark.

Runs multiple local ASR backends (Vosk, whisper.cpp, Qwen3-ASR) + OpenAI Whisper
cloud as baseline against a stratified corpus of audio clips.

Two separate metrics, labelled distinctly (do NOT conflate):

  1. WER vs ground truth
     Only computable on clips with human-annotated ground truth (FluencyBank
     Timestamped subset). Measures OBJECTIVE accuracy.

  2. Pipeline-agreement rate
     Measures how close each ear's output is to what Lavrentiy's current pipeline
     (OpenAI Whisper -> L2/L3/L4 -> Falcon) produced historically for the SAME
     clip. NOT a measure of accuracy — just familiarity to the existing system.
     Clearly labelled because circular-use (pipeline agreeing with itself) is
     a real failure mode to avoid.

Plus operationalized disfluency-preservation metrics (not subjective judge calls):
  - literal word-repetition count
  - partial-word / hyphenated-fragment count
  - interjection retention (um / uh / like / ah)
  - block handling classification (silence / hallucinated-filler / marker / speech)

Designed to be run when all three local ears are integrated. Gracefully skips
any backend that isn't installed yet — partial runs still produce useful data.

Usage:
  python _phase4_ears_benchmark.py \
      [--corpus AUDIO_ARCHIVE_DIR] \
      [--fluencybank FLUENCYBANK_TIMESTAMPED_DIR] \
      [--n-short 10 --n-medium 10 --n-long 10] \
      [--out phase4_results.json]

Output: JSON + CSV with per-clip, per-ear rows. Columns clearly label which
metric is which. No silent hallucination of "the winning ear" — ranking is
left to analysis / a follow-up aggregator script.
"""

import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import time
import traceback
import wave
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────
DEFAULT_ARCHIVE = os.path.expanduser("~/.lavrentiy/audio_archive")
DEFAULT_HISTORY_DB = os.path.expanduser("~/.lavrentiy/profiles/gugosf/history.db")
# Script lives in <repo>/bench/ — REPO_ROOT is the parent.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

# Known Whisper hallucination patterns to flag in block-handling classification
WHISPER_HALLUCINATION_MARKERS = [
    r"thank you[.!]?",
    r"transcribed by",
    r"subscribe",
    r"like and subscribe",
    r"thanks for watching",
    r"captions by",
    r"otter\.ai",
]

# Interjections to count retention of
INTERJECTIONS = {"um", "uh", "uhm", "umm", "er", "ah", "mm", "hmm", "like", "you know"}

# Block-marker patterns (if the ear explicitly marks blocks)
BLOCK_MARKER_PATTERNS = [
    r"\[block\]", r"\[pause\]", r"\[silence\]",
    r"\[b\]", r"\[p\]", r"<block>", r"<pause>",
]


# ── Backend registry — each must return {"text": str, "elapsed_ms": int} ──

def ear_vosk(wav_path, config=None):
    """Vosk ASR backend."""
    try:
        import vosk
    except ImportError:
        return {"skip": "vosk not installed"}
    model_path = (config or {}).get("vosk_model", os.path.expanduser("~/vosk-model"))
    if not os.path.exists(model_path):
        # Try common alternate locations
        for alt in [
            os.path.join(REPO_ROOT, "models", "vosk"),
            os.path.expanduser("~/.lavrentiy/models/vosk"),
            "C:/vosk-model",
        ]:
            if os.path.exists(alt):
                model_path = alt
                break
        else:
            return {"skip": f"vosk model not found (checked {model_path} and common alternates)"}
    t0 = time.time()
    try:
        model = vosk.Model(model_path)
        wf = wave.open(wav_path, "rb")
        rec = vosk.KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(True)
        text_parts = []
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                text_parts.append(res.get("text", ""))
        final = json.loads(rec.FinalResult())
        text_parts.append(final.get("text", ""))
        text = " ".join(p for p in text_parts if p).strip()
        return {"text": text, "elapsed_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"error": f"vosk: {e}", "elapsed_ms": int((time.time() - t0) * 1000)}


def ear_whisper_cpp(wav_path, config=None):
    """whisper.cpp ASR backend — shells out to the ./main binary."""
    binary = (config or {}).get("whispercpp_binary")
    model = (config or {}).get("whispercpp_model")
    if not binary or not os.path.exists(binary):
        # Common locations
        for alt in [
            os.path.join(REPO_ROOT, "whisper.cpp", "main.exe"),
            os.path.join(REPO_ROOT, "whisper.cpp", "build", "main.exe"),
            os.path.expanduser("~/whisper.cpp/main.exe"),
            "C:/whisper.cpp/main.exe",
        ]:
            if os.path.exists(alt):
                binary = alt
                break
        else:
            return {"skip": "whisper.cpp binary not found"}
    if not model:
        for alt in [
            os.path.join(os.path.dirname(binary), "models", "ggml-base.en.bin"),
            os.path.join(os.path.dirname(binary), "models", "ggml-large-v3.bin"),
        ]:
            if os.path.exists(alt):
                model = alt
                break
        else:
            return {"skip": "whisper.cpp model file not found"}
    t0 = time.time()
    try:
        result = subprocess.run(
            [binary, "-m", model, "-f", wav_path, "-otxt", "-of", "/tmp/_wcpp_out"],
            capture_output=True, text=True, timeout=600,
        )
        txt_path = "/tmp/_wcpp_out.txt"
        text = ""
        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            os.unlink(txt_path)
        else:
            # Fall back to parsing stdout if no .txt produced
            text = result.stdout.strip()
        return {"text": text, "elapsed_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"error": f"whisper.cpp: {e}", "elapsed_ms": int((time.time() - t0) * 1000)}


def ear_qwen3(wav_path, config=None):
    """Qwen3-ASR backend with format auto-detection (ONNX vs PyTorch)."""
    # George's clarification: auto-dispatch based on what's actually in the model dir.
    # If .onnx files exist, use onnxruntime; otherwise use torch/transformers.
    model_dir = (config or {}).get("qwen3_dir")
    if not model_dir:
        for alt in [
            os.path.join(REPO_ROOT, "models", "qwen3-asr"),
            os.path.expanduser("~/qwen3-asr"),
            os.path.expanduser("~/.cache/huggingface/hub/models--Qwen--Qwen3-ASR-1.7B"),
            "C:/qwen3-asr",
        ]:
            if os.path.exists(alt):
                model_dir = alt
                break
        else:
            return {"skip": "qwen3-asr model dir not found"}
    # Format detection: ONNX takes priority if present
    onnx_files = glob.glob(os.path.join(model_dir, "**", "*.onnx"), recursive=True)
    if onnx_files:
        return _ear_qwen3_onnx(wav_path, model_dir, onnx_files)
    safetensors = glob.glob(os.path.join(model_dir, "**", "*.safetensors"), recursive=True)
    if safetensors:
        return _ear_qwen3_torch(wav_path, model_dir)
    return {"skip": f"qwen3-asr model dir exists ({model_dir}) but neither .onnx nor .safetensors found"}


def _ear_qwen3_onnx(wav_path, model_dir, onnx_files):
    try:
        import onnxruntime as ort
        import numpy as np
        import soundfile as sf
    except ImportError as e:
        return {"skip": f"qwen3-asr ONNX path: missing dep {e}"}
    t0 = time.time()
    try:
        # Pick the main encoder/decoder pair — heuristic: smallest file name or first
        main_onnx = sorted(onnx_files, key=len)[0]
        session = ort.InferenceSession(main_onnx, providers=["CPUExecutionProvider"])
        audio, sr = sf.read(wav_path, dtype="float32")
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)
        # This is intentionally a placeholder — actual Qwen3 ONNX inference needs
        # tokenizer + mel-spectrogram pre-processing per its reference pipeline.
        # When Gemini finishes the integration, replace this body with the exact
        # preprocessing from that integration.
        text = "[Qwen3-ASR ONNX integration placeholder — replace with Gemini's finished wiring]"
        return {"text": text, "elapsed_ms": int((time.time() - t0) * 1000),
                "placeholder": True, "onnx_file": main_onnx}
    except Exception as e:
        return {"error": f"qwen3-onnx: {e}", "elapsed_ms": int((time.time() - t0) * 1000)}


def _ear_qwen3_torch(wav_path, model_dir):
    try:
        import torch
        from transformers import AutoProcessor, AutoModelForCausalLM
        import soundfile as sf
    except ImportError as e:
        return {"skip": f"qwen3-asr PyTorch path: missing dep {e}"}
    t0 = time.time()
    try:
        processor = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(model_dir, trust_remote_code=True)
        model.eval()
        audio, sr = sf.read(wav_path, dtype="float32")
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)
        inputs = processor(audio=audio, sampling_rate=sr, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=512)
        text = processor.batch_decode(out, skip_special_tokens=True)[0].strip()
        return {"text": text, "elapsed_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"error": f"qwen3-torch: {e}", "elapsed_ms": int((time.time() - t0) * 1000),
                "traceback": traceback.format_exc()[:500]}


def ear_openai_whisper(wav_path, config=None):
    """OpenAI Whisper API — baseline reference (cloud)."""
    api_key = (config or {}).get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        api_key_file = os.path.join(REPO_ROOT, "api_key.txt")
        if os.path.exists(api_key_file):
            with open(api_key_file) as f:
                api_key = f.read().strip()
    if not api_key:
        return {"skip": "no OpenAI API key found"}
    try:
        import openai
    except ImportError:
        return {"skip": "openai package not installed"}
    t0 = time.time()
    try:
        client = openai.OpenAI(api_key=api_key)
        with open(wav_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-1", file=f, response_format="text"
            )
        text = resp if isinstance(resp, str) else resp.text
        return {"text": text.strip(), "elapsed_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"error": f"openai-whisper: {e}", "elapsed_ms": int((time.time() - t0) * 1000)}


BACKENDS = {
    "vosk": ear_vosk,
    "whisper_cpp": ear_whisper_cpp,
    "qwen3_asr": ear_qwen3,
    "openai_whisper_api": ear_openai_whisper,
}


# ── Disfluency-preservation metrics (operationalized per George's spec) ──

def count_word_repetitions(text):
    """Count adjacent literal word repetitions ('go go', 'I I', 'the the')."""
    if not text:
        return 0
    return len(re.findall(r"\b(\w+)\s+\1\b", text, flags=re.IGNORECASE))


def count_partial_word_markers(text):
    """Count hyphenated fragments indicating false starts ('w- want', 'p-p-pop')."""
    if not text:
        return 0
    return len(re.findall(r"\b\w+-", text))


def count_interjections(text):
    """Count retained interjection tokens (um / uh / like / ah etc.)."""
    if not text:
        return 0
    tokens = re.findall(r"\b[\w']+\b", text.lower())
    return sum(1 for t in tokens if t in INTERJECTIONS)


def classify_block_handling(text, audio_has_blocks=None):
    """Classify how the ear handled blocks in the audio.

    Returns one of: 'empty' / 'hallucinated_filler' / 'marker' / 'speech' / 'unknown'.
    audio_has_blocks: optional boolean from VAD preprocessing.
    """
    if not text or not text.strip():
        return "empty"
    low = text.lower()
    for pat in WHISPER_HALLUCINATION_MARKERS:
        if re.search(pat, low):
            return "hallucinated_filler"
    for pat in BLOCK_MARKER_PATTERNS:
        if re.search(pat, low, flags=re.IGNORECASE):
            return "marker"
    return "speech"


def count_prolongations(text):
    """Count words with 3+ consecutive same letter — prolongation markers.

    Catches 'sssso', 'mmmeeting', 'iiiii', 'noooo'. Ignores 2-in-a-row (which is
    common in real English: 'cool', 'need', 'tree', 'committee'). 3+ in a row is
    almost always a prolongation artifact, not a real English spelling.
    """
    if not text:
        return 0
    return len(re.findall(r"\b\w*([a-zA-Zа-яА-Я])\1\1+\w*\b", text))


def count_false_starts(text):
    """Count likely false-start / self-repair discourse markers.

    False starts are hard to detect semantically without parsing — this counts
    the discourse markers that typically accompany them: 'I mean', 'wait',
    'sorry', 'actually' at clause boundaries, ellipses, em-dashes mid-sentence.
    Imperfect proxy but operationalizable and reproducible.
    """
    if not text:
        return 0
    markers = [
        r"\bI mean\b",
        r"\bwait[,.]",
        r"\bsorry[,.]",
        r"\byou know\b",
        r"\bactually[,.]",
        r"\.{3,}",          # ellipsis
        r"\s—\s",           # em-dash with spaces (mid-sentence break)
        r"\s-{2,}\s",       # double-hyphen break
    ]
    count = 0
    for m in markers:
        count += len(re.findall(m, text, flags=re.IGNORECASE))
    return count


# ── Phase 2 per-layer stutter metrics ────────────────────────────────────
# These measure how well L2/L3/L4 reconstructions STRIP disfluencies from raw
# transcripts. Higher strip/collapse rate = layer did more work.
# Computed as (raw_count - clean_count) / max(raw_count, 1) — i.e., fraction removed.

def _strip_rate(raw_count, clean_count):
    """Fraction of raw-side disfluency markers that were removed by a layer."""
    if raw_count == 0:
        return None  # no disfluencies to strip — metric undefined
    return max(0.0, (raw_count - clean_count) / raw_count)


def compute_layer_strip_rates(raw, cleaned):
    """Given a raw transcript and a layer's cleaned output, compute four strip rates."""
    return {
        "word_repeat_collapse_rate": _strip_rate(
            count_word_repetitions(raw), count_word_repetitions(cleaned)
        ),
        "fragment_strip_rate": _strip_rate(
            count_partial_word_markers(raw), count_partial_word_markers(cleaned)
        ),
        "prolongation_collapse_rate": _strip_rate(
            count_prolongations(raw), count_prolongations(cleaned)
        ),
        "false_start_strip_rate": _strip_rate(
            count_false_starts(raw), count_false_starts(cleaned)
        ),
    }


def compute_phonetic_onset_honored(raw, cleaned, profile):
    """L4-only: for each word in raw that starts with a hard onset (weight > 0.5
    in profile.onset_weights), did it survive in the cleaned output?

    Measures whether L4 avoided the trap of swapping a user's hard-onset word
    for a different-onset synonym. High rate = L4 respected the phonetic intent.
    Returns None when the profile has no hard onsets or raw has no hard-onset words.
    """
    if not profile:
        return None
    weights = (profile.get("onset_weights") or {})
    hard_onsets = [o for o, w in weights.items() if w and w > 0.5]
    if not hard_onsets:
        return None
    raw_words = re.findall(r"\b\w+\b", (raw or "").lower())
    clean_set = set(re.findall(r"\b\w+\b", (cleaned or "").lower()))
    # A raw-side word "starts with hard onset" if its first 1-3 chars match any onset
    hard_words = []
    for w in raw_words:
        wl = w.lower()
        for o in hard_onsets:
            if wl.startswith(o.lower()):
                hard_words.append(wl)
                break
    if not hard_words:
        return None
    preserved = sum(1 for w in hard_words if w in clean_set)
    return preserved / len(hard_words)


def compute_covert_recovery(raw, cleaned, profile):
    """L4-only: for each known avoidance pair in profile.covert_profile.avoidance_pairs,
    count 'recoveries' — where the raw contains a known SUBSTITUTE and the cleaned
    output contains the AVOIDED WORD (i.e., L4 reversed a tracked avoidance).

    Measures how often L4 correctly recovers the intended word from a known
    avoidance pattern. Returns None when profile has no avoidance pairs.
    """
    if not profile:
        return None
    covert = (profile.get("covert_profile") or {}).get("avoidance_pairs") or {}
    if not covert:
        return None
    raw_low = (raw or "").lower()
    clean_low = (cleaned or "").lower()
    recoveries = 0
    opportunities = 0
    for situation_bucket, words in covert.items():
        for avoided, data in (words or {}).items():
            subs = (data or {}).get("common_substitutes") or []
            for sub in subs:
                if re.search(rf"\b{re.escape(sub)}\b", raw_low):
                    opportunities += 1
                    if re.search(rf"\b{re.escape(avoided)}\b", clean_low):
                        recoveries += 1
    if opportunities == 0:
        return None
    return recoveries / opportunities


# ── WER (objective, vs human-annotated ground truth) ─────────────────────

def compute_wer(reference, hypothesis):
    """Classic Levenshtein-based WER on whitespace-tokenized text.
    reference is the human-annotated ground-truth string; hypothesis is the ear output.
    Returns float in [0, 1] (lower is better). Returns None if reference is empty.
    """
    if not reference or not reference.strip():
        return None
    r = reference.lower().split()
    h = (hypothesis or "").lower().split()
    if not r:
        return None
    # Levenshtein word-level
    dp = [list(range(len(h) + 1))]
    for i in range(1, len(r) + 1):
        row = [i] + [0] * len(h)
        for j in range(1, len(h) + 1):
            cost = 0 if r[i-1] == h[j-1] else 1
            row[j] = min(row[j-1] + 1, dp[i-1][j] + 1, dp[i-1][j-1] + cost)
        dp.append(row)
    return dp[len(r)][len(h)] / len(r)


def compute_pipeline_agreement(pipeline_output, ear_output):
    """Agreement rate between current-pipeline clean output and this ear's raw output.
    This is NOT WER. The pipeline output is the AI-cleaned text — so this measures
    'how close is this raw transcript to the cleaned pipeline version'. Which is
    biased by ear choice (the current pipeline already uses OpenAI Whisper ears).
    Labelled separately and never conflated with WER per George's fix.
    """
    if not pipeline_output:
        return None
    return 1.0 - compute_wer(pipeline_output, ear_output or "") \
        if compute_wer(pipeline_output, ear_output or "") is not None else None


# ── Corpus building ──────────────────────────────────────────────────────

def wav_duration(wav_path):
    try:
        with wave.open(wav_path, "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return None


def classify_duration(seconds):
    if seconds is None:
        return "unknown"
    if seconds < 10:
        return "short"
    if seconds < 60:
        return "medium"
    return "long"


def build_corpus_from_archive(archive_dir, n_short=10, n_medium=10, n_long=10, history_db=None):
    """Walk audio_archive, stratify clips by duration, optionally pair with
    historical pipeline output from history.db for pipeline-agreement metric.
    Returns list of {path, duration_s, duration_bucket, pipeline_output, clip_id}.
    """
    wavs = []
    for root, _, files in os.walk(archive_dir):
        for f in files:
            if f.lower().endswith(".wav"):
                wavs.append(os.path.join(root, f))
    # Map to duration buckets
    buckets = {"short": [], "medium": [], "long": []}
    for w in wavs:
        d = wav_duration(w)
        buckets[classify_duration(d)].append({"path": w, "duration_s": d})
    # Pipeline-output pairing via history.db (best-effort)
    pipeline_lookup = {}
    if history_db and os.path.exists(history_db):
        try:
            import sqlite3
            conn = sqlite3.connect(history_db)
            cur = conn.cursor()
            cur.execute("SELECT id, raw, out FROM sessions WHERE raw IS NOT NULL")
            for sid, raw, out in cur.fetchall():
                pipeline_lookup[str(sid)] = {"raw": raw, "out": out}
            conn.close()
        except Exception as e:
            print(f"[warn] couldn't load history.db: {e}")
    # Sample and tag
    import random
    random.seed(42)
    result = []
    for bucket, n in [("short", n_short), ("medium", n_medium), ("long", n_long)]:
        items = buckets[bucket]
        random.shuffle(items)
        for it in items[:n]:
            clip_id = Path(it["path"]).stem
            sid_match = re.search(r"(\d+)", clip_id)
            pipeline = pipeline_lookup.get(sid_match.group(1)) if sid_match else None
            it.update({
                "clip_id": clip_id,
                "duration_bucket": bucket,
                "pipeline_raw": (pipeline or {}).get("raw"),
                "pipeline_out": (pipeline or {}).get("out"),
                "source": "archive",
            })
            result.append(it)
    return result


def build_corpus_from_fluencybank(fluencybank_dir):
    """Walk a FluencyBank Timestamped directory, pair each WAV with its
    CHAT/CTM/TextGrid ground-truth file. Returns list with
    {path, duration_s, duration_bucket, ground_truth, clip_id, source='fluencybank'}.
    """
    if not fluencybank_dir or not os.path.exists(fluencybank_dir):
        return []
    result = []
    for root, _, files in os.walk(fluencybank_dir):
        for f in files:
            if not f.lower().endswith(".wav"):
                continue
            wav = os.path.join(root, f)
            stem = os.path.splitext(wav)[0]
            gt = None
            for ext in (".txt", ".cha", ".ctm", ".TextGrid", ".trn"):
                cand = stem + ext
                if os.path.exists(cand):
                    with open(cand, "r", encoding="utf-8", errors="ignore") as fh:
                        gt = fh.read()
                    break
            if gt:
                d = wav_duration(wav)
                result.append({
                    "path": wav, "duration_s": d,
                    "duration_bucket": classify_duration(d),
                    "clip_id": Path(wav).stem,
                    "ground_truth": gt.strip(),
                    "source": "fluencybank",
                })
    return result


# ── Main benchmark loop ──────────────────────────────────────────────────

def run_benchmark(corpus, backend_names, backend_config=None):
    rows = []
    backend_config = backend_config or {}
    for i, clip in enumerate(corpus, 1):
        for backend_name in backend_names:
            if backend_name not in BACKENDS:
                continue
            print(f"[{i}/{len(corpus)}] {clip['clip_id']} ({clip.get('duration_bucket','?')}) -> {backend_name}")
            result = BACKENDS[backend_name](clip["path"], backend_config)
            row = {
                "clip_id": clip["clip_id"],
                "source": clip.get("source"),
                "duration_s": clip.get("duration_s"),
                "duration_bucket": clip.get("duration_bucket"),
                "ear": backend_name,
                "skip_reason": result.get("skip"),
                "error": result.get("error"),
                "placeholder": result.get("placeholder", False),
                "transcript": result.get("text", ""),
                "transcribe_ms": result.get("elapsed_ms"),
            }
            txt = result.get("text", "") or ""
            # Disfluency-preservation metrics (always computable from transcript).
            # These are the four buckets George specified: word repeats, partial
            # words, prolongations, blocks. Plus interjections and false-starts
            # as supplementary signals.
            row["word_repetitions"] = count_word_repetitions(txt)
            row["partial_word_markers"] = count_partial_word_markers(txt)
            row["prolongations"] = count_prolongations(txt)
            row["interjections_retained"] = count_interjections(txt)
            row["false_starts"] = count_false_starts(txt)
            row["block_handling"] = classify_block_handling(txt)
            # WER — only if ground truth exists (FluencyBank)
            gt = clip.get("ground_truth")
            row["wer_vs_ground_truth"] = compute_wer(gt, txt) if gt else None
            row["has_ground_truth"] = bool(gt)
            # Pipeline-agreement — only if history.db pairing exists
            po = clip.get("pipeline_out")
            row["pipeline_agreement"] = compute_pipeline_agreement(po, txt) if po else None
            row["has_pipeline_pairing"] = bool(po)
            rows.append(row)
            msg = result.get("skip") or result.get("error") or f"{len(txt)} chars"
            print(f"    -> {msg}")
    return rows


# ── Phase 2: reconstruction-layer shootout ───────────────────────────────
# Takes raw transcripts and runs them through /api/reconstruct_test at L1/L2/L3/L4
# × tones × modes. Measures per-layer stutter metrics: word-repeat collapse,
# fragment strip, prolongation collapse, false-start strip. L4 adds phonetic-onset
# honored and covert recovery.
#
# Requires the Lavrentiy engine running on localhost:7878. Can be hit against
# either Current or Eval — whichever is up — and the results will reflect that
# engine's reconstruction behavior.

PHASE2_LAYERS = [1, 2, 3, 4]
PHASE2_TONES = ["casual", "professional", "formal", "friend"]
PHASE2_MODES = ["SAFE"]  # endpoint is SAFE-only for now; FAST/RAW derivable from code-path analysis


def call_reconstruct_test(raw_text, tone, layer, situation="default",
                          engine_url="http://127.0.0.1:7878"):
    """POST to /api/reconstruct_test and return the full response dict."""
    import urllib.request
    req = urllib.request.Request(
        f"{engine_url}/api/reconstruct_test",
        json.dumps({
            "raw": raw_text, "tone": tone, "layer": layer, "situation": situation,
        }).encode(),
        {"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def load_profile(profile_path):
    """Load profile.json for the active user (for L4 phonetic / covert metrics)."""
    if not profile_path or not os.path.exists(profile_path):
        return None
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def run_phase2_layers(raw_inputs, profile=None, engine_url="http://127.0.0.1:7878",
                      tones=None, layers=None, situations=None):
    """Run raw inputs through L1/L2/L3/L4 × tones × situations, capture
    per-layer stutter-collapse metrics + L4-specific phonetic metrics.

    raw_inputs: list of {"clip_id": str, "raw": str, "duration_bucket": str, ...}
                (typically from the same corpus used in Phase 1, with raw text
                sourced from historical history.db entries or Phase 1 output)
    profile:    loaded profile dict for hard-onset + covert-avoidance metrics
    """
    tones = tones or PHASE2_TONES
    layers = layers or PHASE2_LAYERS
    situations = situations or ["default"]
    rows = []
    total = len(raw_inputs) * len(tones) * len(layers) * len(situations)
    n = 0
    for item in raw_inputs:
        raw = item.get("raw") or item.get("pipeline_raw") or ""
        if not raw.strip():
            continue
        for tone in tones:
            for situ in situations:
                for layer in layers:
                    n += 1
                    print(f"[phase2 {n}/{total}] {item.get('clip_id','?')} "
                          f"L{layer}/{tone}/{situ}")
                    resp = call_reconstruct_test(raw, tone, layer, situ, engine_url)
                    cleaned = resp.get("clean", "")
                    filtered = resp.get("filtered", "")
                    row = {
                        "clip_id": item.get("clip_id"),
                        "duration_bucket": item.get("duration_bucket"),
                        "tone": tone,
                        "layer": layer,
                        "situation": situ,
                        "raw": raw,
                        "filtered_l1": filtered,
                        "cleaned": cleaned,
                        "falcon_ok": resp.get("falcon_ok"),
                        "recon_ms": resp.get("recon_ms"),
                        "error": resp.get("error"),
                    }
                    # Per-layer strip rates — the four buckets George specified
                    strip_rates = compute_layer_strip_rates(raw, cleaned)
                    row.update(strip_rates)
                    # Also record raw-side counts for reference
                    row["raw_word_repetitions"] = count_word_repetitions(raw)
                    row["raw_partial_word_markers"] = count_partial_word_markers(raw)
                    row["raw_prolongations"] = count_prolongations(raw)
                    row["raw_false_starts"] = count_false_starts(raw)
                    # L4-only metrics
                    if layer == 4:
                        row["phonetic_onset_honored"] = compute_phonetic_onset_honored(
                            raw, cleaned, profile
                        )
                        row["covert_recovery"] = compute_covert_recovery(
                            raw, cleaned, profile
                        )
                    else:
                        row["phonetic_onset_honored"] = None
                        row["covert_recovery"] = None
                    rows.append(row)
                    elapsed = row["recon_ms"]
                    err = row["error"]
                    preview = (cleaned or err or "(empty)")[:80]
                    print(f"    ms={elapsed} falcon={row['falcon_ok']} -> {preview}")
    return rows


# ── Markdown summary generation ──────────────────────────────────────────
# Per George's spec: output is CSV per phase + a markdown summary with
# aggregates. Not just print-to-terminal.

def _mean(values):
    vs = [v for v in values if v is not None]
    return sum(vs) / len(vs) if vs else None


def _mean_or_na(values, fmt="{:.3f}"):
    m = _mean(values)
    return fmt.format(m) if m is not None else "n/a"


def _count_values(values):
    """Count how many non-None values exist."""
    return sum(1 for v in values if v is not None)


def write_markdown_summary(phase1_rows, phase2_rows, out_path):
    """Produce a markdown summary aggregating Phase 1 and Phase 2 results."""
    lines = []
    lines.append(f"# Phase-4 Benchmark Summary")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # ── Phase 1 ──────────────────────────────────────────────────────────
    if phase1_rows:
        ears = sorted({r["ear"] for r in phase1_rows if r.get("ear")})
        lines.append("## Phase 1 — Ears Shootout")
        lines.append("")
        lines.append(f"Total runs: **{len(phase1_rows)}** across **{len(ears)}** ear backends.")
        lines.append("")

        # Per-ear aggregate table with the two clearly-separated accuracy metrics
        lines.append("### Accuracy metrics (separated per George's ground-truth fix)")
        lines.append("")
        lines.append("| Ear | Clips | Avg WER (vs FluencyBank GT) | Avg Pipeline-Agreement | Avg Transcribe ms |")
        lines.append("|---|---:|---:|---:|---:|")
        for ear in ears:
            ear_rows = [r for r in phase1_rows if r.get("ear") == ear and not r.get("skip_reason")]
            lines.append("| {ear} | {n} | {wer} | {pa} | {ms} |".format(
                ear=ear, n=len(ear_rows),
                wer=_mean_or_na([r.get("wer_vs_ground_truth") for r in ear_rows]),
                pa=_mean_or_na([r.get("pipeline_agreement") for r in ear_rows]),
                ms=_mean_or_na([r.get("transcribe_ms") for r in ear_rows], "{:.0f}"),
            ))
        n_gt = _count_values([r.get("wer_vs_ground_truth") for r in phase1_rows])
        n_pa = _count_values([r.get("pipeline_agreement") for r in phase1_rows])
        lines.append("")
        lines.append(f"**WER column** is computed only on clips with human-annotated ground truth — {n_gt} of {len(phase1_rows)} rows have it. This is the ONLY objective accuracy metric.")
        lines.append("")
        lines.append(f"**Pipeline-agreement** is computed on {n_pa} of {len(phase1_rows)} rows. This is NOT WER — it measures how close each ear's raw text is to the current pipeline's cleaned output, which is biased by the ear the pipeline already uses. Labelled separately for that reason.")
        lines.append("")

        # Per-ear disfluency-preservation table (the four buckets)
        lines.append("### Disfluency preservation — four bucketed metrics")
        lines.append("")
        lines.append("How well each ear retained disfluency markers in its output (higher = better preservation for clinical use; lower = more aggressive hallucination/cleaning).")
        lines.append("")
        lines.append("| Ear | Avg Word Reps | Avg Partial Words | Avg Prolongations | Block Handling Mix |")
        lines.append("|---|---:|---:|---:|---|")
        for ear in ears:
            ear_rows = [r for r in phase1_rows if r.get("ear") == ear and not r.get("skip_reason")]
            block_counts = {}
            for r in ear_rows:
                bh = r.get("block_handling")
                block_counts[bh] = block_counts.get(bh, 0) + 1
            bh_str = ", ".join(f"{k}:{v}" for k, v in sorted(block_counts.items())) or "n/a"
            lines.append("| {ear} | {wr} | {pw} | {pr} | {bh} |".format(
                ear=ear,
                wr=_mean_or_na([r.get("word_repetitions") for r in ear_rows], "{:.1f}"),
                pw=_mean_or_na([r.get("partial_word_markers") for r in ear_rows], "{:.1f}"),
                pr=_mean_or_na([r.get("prolongations") for r in ear_rows], "{:.1f}"),
                bh=bh_str,
            ))
        lines.append("")

        # Note any skips
        skips = [(r["ear"], r["skip_reason"]) for r in phase1_rows if r.get("skip_reason")]
        if skips:
            skip_summary = {}
            for ear, reason in skips:
                skip_summary.setdefault(ear, set()).add(reason)
            lines.append("### Skipped backends")
            lines.append("")
            for ear, reasons in sorted(skip_summary.items()):
                lines.append(f"- **{ear}**: {' | '.join(reasons)}")
            lines.append("")

    # ── Phase 2 ──────────────────────────────────────────────────────────
    if phase2_rows:
        layers = sorted({r["layer"] for r in phase2_rows if r.get("layer") is not None})
        lines.append("## Phase 2 — Reconstruction-Layer Shootout")
        lines.append("")
        lines.append(f"Total runs: **{len(phase2_rows)}** across layers **{layers}**.")
        lines.append("")

        # Per-layer stutter-metric aggregate table
        lines.append("### Per-layer stutter-collapse rates")
        lines.append("")
        lines.append("| Layer | Word-Repeat Collapse | Fragment Strip | Prolongation Collapse | False-Start Strip | Avg ms | Falcon Pass% |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|")
        for layer in layers:
            layer_rows = [r for r in phase2_rows if r.get("layer") == layer and not r.get("error")]
            if not layer_rows:
                continue
            falcon_pass = [1 if r.get("falcon_ok") else 0 for r in layer_rows if r.get("falcon_ok") is not None]
            lines.append("| L{layer} | {wr} | {fs} | {pc} | {fss} | {ms} | {fp} |".format(
                layer=layer,
                wr=_mean_or_na([r.get("word_repeat_collapse_rate") for r in layer_rows]),
                fs=_mean_or_na([r.get("fragment_strip_rate") for r in layer_rows]),
                pc=_mean_or_na([r.get("prolongation_collapse_rate") for r in layer_rows]),
                fss=_mean_or_na([r.get("false_start_strip_rate") for r in layer_rows]),
                ms=_mean_or_na([r.get("recon_ms") for r in layer_rows], "{:.0f}"),
                fp=f"{100 * _mean(falcon_pass):.0f}%" if falcon_pass else "n/a",
            ))
        lines.append("")

        # L4-only metrics
        l4_rows = [r for r in phase2_rows if r.get("layer") == 4 and not r.get("error")]
        if l4_rows:
            lines.append("### L4-only phonetic metrics")
            lines.append("")
            onset_vals = [r.get("phonetic_onset_honored") for r in l4_rows]
            covert_vals = [r.get("covert_recovery") for r in l4_rows]
            n_onset = _count_values(onset_vals)
            n_covert = _count_values(covert_vals)
            lines.append(f"- **phonetic_onset_honored** avg: {_mean_or_na(onset_vals)} (computed on {n_onset} of {len(l4_rows)} L4 rows — null when profile has no hard onsets or raw has no hard-onset words)")
            lines.append(f"- **covert_recovery** avg: {_mean_or_na(covert_vals)} (computed on {n_covert} of {len(l4_rows)} L4 rows — null when profile has no avoidance pairs or no opportunities found in raw)")
            lines.append("")

        # Per-tone breakdown
        tones = sorted({r["tone"] for r in phase2_rows if r.get("tone")})
        if len(tones) > 1:
            lines.append("### Per-tone strip rates (averaged across all layers)")
            lines.append("")
            lines.append("| Tone | Word-Repeat Collapse | Fragment Strip | Prolongation Collapse | False-Start Strip |")
            lines.append("|---|---:|---:|---:|---:|")
            for tone in tones:
                tr = [r for r in phase2_rows if r.get("tone") == tone and not r.get("error")]
                lines.append("| {tone} | {wr} | {fs} | {pc} | {fss} |".format(
                    tone=tone,
                    wr=_mean_or_na([r.get("word_repeat_collapse_rate") for r in tr]),
                    fs=_mean_or_na([r.get("fragment_strip_rate") for r in tr]),
                    pc=_mean_or_na([r.get("prolongation_collapse_rate") for r in tr]),
                    fss=_mean_or_na([r.get("false_start_strip_rate") for r in tr]),
                ))
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("Raw data: see the matching `.phase1.csv` and `.phase2.csv` files in this directory.")
    lines.append("")
    lines.append("No \"winning ear\" or \"best layer\" claim is made automatically. Winner selection is a decision, not a computation — review the tables and pick based on the priorities that matter for this ship (accuracy vs speed vs disfluency preservation vs license).")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", default=DEFAULT_ARCHIVE,
                   help="audio_archive dir (default: ~/.lavrentiy/audio_archive)")
    p.add_argument("--fluencybank", default=None,
                   help="FluencyBank Timestamped dir (optional — enables WER metric)")
    p.add_argument("--history-db", default=DEFAULT_HISTORY_DB,
                   help="history.db for pipeline-agreement pairing (default: gugosf profile)")
    p.add_argument("--n-short", type=int, default=10)
    p.add_argument("--n-medium", type=int, default=10)
    p.add_argument("--n-long", type=int, default=10)
    p.add_argument("--backends", default="vosk,whisper_cpp,qwen3_asr,openai_whisper_api",
                   help="comma-separated backend names to run")
    p.add_argument("--vosk-model", default=None)
    p.add_argument("--whispercpp-binary", default=None)
    p.add_argument("--whispercpp-model", default=None)
    p.add_argument("--qwen3-dir", default=None)
    # Default output lives alongside this script in bench/
    p.add_argument("--out", default=os.path.join(SCRIPT_DIR, "_phase4_results"))
    p.add_argument("--phase", default="1", choices=["1", "2", "both"],
                   help="1 = ears shootout; 2 = layers/reconstruction shootout; both = run 1 then 2")
    p.add_argument("--profile-path",
                   default=os.path.expanduser("~/.lavrentiy/profiles/gugosf/profile.json"),
                   help="profile.json for L4 phonetic-onset + covert-recovery metrics (Phase 2 only)")
    p.add_argument("--engine-url", default="http://127.0.0.1:7878",
                   help="Lavrentiy engine HTTP URL for Phase 2 /api/reconstruct_test calls")
    p.add_argument("--phase2-layers", default="1,2,3,4",
                   help="comma-separated layer numbers to test in Phase 2")
    p.add_argument("--phase2-tones", default="casual,professional,formal,friend",
                   help="comma-separated tones to test in Phase 2")
    p.add_argument("--phase2-situations", default="default",
                   help="comma-separated situations to test in Phase 2")
    args = p.parse_args()

    backend_names = [b.strip() for b in args.backends.split(",") if b.strip()]
    cfg = {
        "vosk_model": args.vosk_model,
        "whispercpp_binary": args.whispercpp_binary,
        "whispercpp_model": args.whispercpp_model,
        "qwen3_dir": args.qwen3_dir,
    }

    corpus = []
    if args.corpus and os.path.exists(args.corpus):
        print(f"[corpus] building from audio_archive: {args.corpus}")
        corpus.extend(build_corpus_from_archive(
            args.corpus, args.n_short, args.n_medium, args.n_long, args.history_db,
        ))
    if args.fluencybank:
        print(f"[corpus] adding FluencyBank Timestamped: {args.fluencybank}")
        corpus.extend(build_corpus_from_fluencybank(args.fluencybank))
    print(f"[corpus] total clips: {len(corpus)}")
    counts = {}
    for c in corpus:
        k = (c.get("source"), c.get("duration_bucket"))
        counts[k] = counts.get(k, 0) + 1
    for k, v in sorted(counts.items()):
        print(f"    {k}: {v}")

    # ── Phase 1 ──
    rows = []
    if args.phase in ("1", "both"):
        print(f"\n=== PHASE 1: ears shootout ===")
        rows = run_benchmark(corpus, backend_names, cfg)

    # ── Phase 2 ──
    phase2_rows = []
    if args.phase in ("2", "both"):
        print(f"\n=== PHASE 2: reconstruction-layer shootout ===")
        profile = load_profile(args.profile_path)
        if not profile:
            print(f"[warn] couldn't load profile at {args.profile_path} — L4 phonetic/covert metrics will be None")
        phase2_layers = [int(x) for x in args.phase2_layers.split(",") if x.strip()]
        phase2_tones = [x.strip() for x in args.phase2_tones.split(",") if x.strip()]
        phase2_situations = [x.strip() for x in args.phase2_situations.split(",") if x.strip()]
        # Source raw inputs: prefer history.db pipeline raw when available; otherwise
        # fall back to the corpus item's pipeline_raw or a sane default.
        raw_inputs = []
        for c in corpus:
            raw = c.get("pipeline_raw")
            if raw:
                raw_inputs.append({
                    "clip_id": c.get("clip_id"),
                    "duration_bucket": c.get("duration_bucket"),
                    "raw": raw,
                })
        if not raw_inputs:
            print("[warn] no raw transcripts found from history.db pairing; Phase 2 has nothing to work with")
        else:
            print(f"[phase2] running {len(raw_inputs)} raw inputs × "
                  f"{len(phase2_layers)} layers × {len(phase2_tones)} tones × "
                  f"{len(phase2_situations)} situations")
            phase2_rows = run_phase2_layers(
                raw_inputs, profile=profile, engine_url=args.engine_url,
                tones=phase2_tones, layers=phase2_layers, situations=phase2_situations,
            )

    # Persist Phase 1
    if rows:
        json_path = args.out + ".phase1.json"
        csv_path = args.out + ".phase1.csv"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        fieldnames = sorted({k for r in rows for k in r.keys()})
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n[phase1 done] {len(rows)} rows")
        print(f"              JSON: {json_path}")
        print(f"              CSV : {csv_path}")

    # Persist Phase 2
    if phase2_rows:
        json_path = args.out + ".phase2.json"
        csv_path = args.out + ".phase2.csv"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(phase2_rows, f, indent=2, ensure_ascii=False)
        fieldnames = sorted({k for r in phase2_rows for k in r.keys()})
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(phase2_rows)
        print(f"\n[phase2 done] {len(phase2_rows)} rows")
        print(f"              JSON: {json_path}")
        print(f"              CSV : {csv_path}")

    # Markdown summary — combines both phases into a single human-readable report
    if rows or phase2_rows:
        md_path = args.out + ".md"
        write_markdown_summary(rows, phase2_rows, md_path)
        print(f"\n[summary]     Markdown: {md_path}")

    print()
    print("Next step: open the .md summary, or load the CSVs in a spreadsheet.")
    print("           No 'winning ear' claim is made automatically. Winner")
    print("           selection is a decision, not a computation.")


if __name__ == "__main__":
    main()
