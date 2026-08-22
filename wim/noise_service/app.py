"""Private BSRNN-Flow speech-enhancement service for WiM cloud audio."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from flask import Flask, Response, jsonify, request
import numpy as np
import soundfile as sf
import soxr


MODEL_NAME = "urgent2026-bsrnn-flow"
MODEL_CONFIG = os.environ.get("FLOW_MODEL_CONFIG", "/models/flow_bsrnn.config.json")
MODEL_WEIGHTS = os.environ.get("FLOW_MODEL_WEIGHTS", "/models/flow_bsrnn.safetensors")
MODEL_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 16_000
MAX_INPUT_BYTES = int(os.environ.get("MAX_INPUT_BYTES", str(12 * 1024 * 1024)))
MAX_AUDIO_SECONDS = float(os.environ.get("MAX_AUDIO_SECONDS", "30"))
FLOW_STEPS = int(os.environ.get("FLOW_STEPS", "15"))
CACHE_ENTRIES = int(os.environ.get("CACHE_ENTRIES", "8"))
FLOW_CHUNK_SAMPLES = int(os.environ.get("FLOW_CHUNK_SAMPLES", "96000"))
FLOW_OVERLAP_SAMPLES = int(os.environ.get("FLOW_OVERLAP_SAMPLES", "8000"))

app = Flask(__name__)

_model = None
_model_load_ms = None
_inference_lock = threading.Lock()
_cache_lock = threading.Lock()
_cache: OrderedDict[str, bytes] = OrderedDict()


class AudioInputError(ValueError):
    pass


def _suffix_for(data: bytes, announced: str) -> str:
    announced = (announced or "").strip().lower()
    if announced in {"wav", "wave"} or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"):
        return ".wav"
    if announced in {"m4a", "mp4", "aac"} or (len(data) >= 12 and data[4:8] == b"ftyp"):
        return ".m4a"
    if announced == "flac" or data[:4] == b"fLaC":
        return ".flac"
    if announced == "mp3" or data[:3] == b"ID3" or data[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return ".mp3"
    raise AudioInputError("Audio must be WAV, M4A, FLAC, or MP3")


def _decode_audio(data: bytes, announced: str) -> np.ndarray:
    suffix = _suffix_for(data, announced)
    with tempfile.TemporaryDirectory(prefix="wim-noise-") as tmp:
        source = Path(tmp) / f"input{suffix}"
        decoded = Path(tmp) / "decoded.wav"
        source.write_bytes(data)
        try:
            subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(source), "-ac", "1", "-ar", str(MODEL_SAMPLE_RATE),
                    "-c:a", "pcm_f32le", str(decoded),
                ],
                check=True,
                timeout=45,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", b"") or b""
            raise AudioInputError(f"Audio decode failed: {detail.decode(errors='replace')[:160]}") from exc

        samples, sample_rate = sf.read(decoded, dtype="float32", always_2d=True)

    if sample_rate != MODEL_SAMPLE_RATE:
        raise AudioInputError("Decoded audio has the wrong sample rate")
    mono = samples.mean(axis=1, dtype=np.float32)
    if mono.size == 0 or not np.isfinite(mono).all():
        raise AudioInputError("Decoded audio is empty or invalid")
    if mono.size / MODEL_SAMPLE_RATE > MAX_AUDIO_SECONDS:
        raise AudioInputError(f"Audio exceeds {MAX_AUDIO_SECONDS:g} seconds")
    return np.ascontiguousarray(mono, dtype=np.float32)


def _load_model():
    global _model, _model_load_ms
    if _model is not None:
        return _model

    started = time.monotonic()
    import torch
    from safetensors.torch import load_file
    from baseline_code.config import Config
    from baseline_code.flow_model import FlowSEModel

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required")
    config = json.loads(Path(MODEL_CONFIG).read_text(encoding="utf-8"))
    config.pop("source_commit", None)
    config.pop("checkpoint_sha256", None)
    model = FlowSEModel(Config(**config))
    model.load_state_dict(load_file(MODEL_WEIGHTS, device="cpu"), strict=True)
    model.to("cuda")
    # The build converter already selected the checkpoint's EMA weights.
    model.eval(no_ema=True)
    _model = model
    _model_load_ms = round((time.monotonic() - started) * 1000)
    return model


def _encode_wav(samples: np.ndarray) -> bytes:
    if samples.size == 0:
        raise RuntimeError("Enhancer returned empty audio")
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(samples)))
    if peak > 1e-8:
        samples = samples / peak * 0.9
    if OUTPUT_SAMPLE_RATE != MODEL_SAMPLE_RATE:
        samples = soxr.resample(samples, MODEL_SAMPLE_RATE, OUTPUT_SAMPLE_RATE, quality="HQ")
    samples = np.clip(samples, -1.0, 1.0).astype(np.float32, copy=False)
    out = io.BytesIO()
    sf.write(out, samples, OUTPUT_SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return out.getvalue()


def _enhance_chunked(model, samples: np.ndarray) -> np.ndarray:
    """Run the published short-clip model over long WiM takes with crossfades."""
    import torch

    if FLOW_CHUNK_SAMPLES <= FLOW_OVERLAP_SAMPLES:
        raise RuntimeError("FLOW_CHUNK_SAMPLES must exceed FLOW_OVERLAP_SAMPLES")
    stride = FLOW_CHUNK_SAMPLES - FLOW_OVERLAP_SAMPLES
    mixed = np.zeros(samples.size, dtype=np.float32)
    weights = np.zeros(samples.size, dtype=np.float32)

    for start in range(0, samples.size, stride):
        end = min(start + FLOW_CHUNK_SAMPLES, samples.size)
        chunk = samples[start:end]
        waveform = torch.from_numpy(chunk).unsqueeze(0).to("cuda")
        length = torch.tensor([chunk.size], dtype=torch.long, device="cuda")
        with torch.inference_mode():
            enhanced = model.enhance(waveform, MODEL_SAMPLE_RATE, length, N=FLOW_STEPS)
        part = enhanced.detach().float().cpu().numpy().reshape(-1)
        if part.size < chunk.size:
            part = np.pad(part, (0, chunk.size - part.size))
        elif part.size > chunk.size:
            part = part[:chunk.size]

        window = np.ones(chunk.size, dtype=np.float32)
        fade = min(FLOW_OVERLAP_SAMPLES, chunk.size)
        if start > 0 and fade > 0:
            window[:fade] = np.linspace(0.0, 1.0, fade, endpoint=True, dtype=np.float32)
        if end < samples.size and fade > 0:
            window[-fade:] = np.minimum(
                window[-fade:],
                np.linspace(1.0, 0.0, fade, endpoint=True, dtype=np.float32),
            )
        mixed[start:end] += part * window
        weights[start:end] += window
        if end == samples.size:
            break

    return mixed / np.maximum(weights, 1e-6)


def _enhance(samples: np.ndarray) -> tuple[bytes, bool, int]:
    key = hashlib.sha256(samples.astype("<f4", copy=False).tobytes()).hexdigest()
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached, True, 0

    started = time.monotonic()
    with _inference_lock:
        # A request may have waited behind another identical request.
        with _cache_lock:
            cached = _cache.get(key)
            if cached is not None:
                _cache.move_to_end(key)
                return cached, True, round((time.monotonic() - started) * 1000)

        model = _load_model()
        cleaned = _encode_wav(_enhance_chunked(model, samples))

        with _cache_lock:
            _cache[key] = cleaned
            _cache.move_to_end(key)
            while len(_cache) > CACHE_ENTRIES:
                _cache.popitem(last=False)

    return cleaned, False, round((time.monotonic() - started) * 1000)


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "model": MODEL_NAME})


@app.get("/ready")
def ready():
    if _model is None:
        return jsonify({"ready": False, "model": MODEL_NAME}), 503
    return jsonify({"ready": True, "model": MODEL_NAME, "load_ms": _model_load_ms})


@app.post("/v1/enhance")
def enhance_route():
    data = request.get_data(cache=False)
    if not data:
        return jsonify({"error": "Audio body is required"}), 400
    if len(data) > MAX_INPUT_BYTES:
        return jsonify({"error": "Audio exceeds the byte limit"}), 413
    try:
        samples = _decode_audio(data, request.headers.get("X-WiM-Audio-Format", ""))
        cleaned, cache_hit, elapsed_ms = _enhance(samples)
    except AudioInputError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("Flow enhancement failed")
        return jsonify({"error": f"Enhancement failed: {type(exc).__name__}"}), 500

    response = Response(cleaned, status=200, mimetype="audio/wav")
    response.headers["X-WiM-Noise-Model"] = MODEL_NAME
    response.headers["X-WiM-Noise-Cache"] = "hit" if cache_hit else "miss"
    response.headers["X-WiM-Noise-Ms"] = str(elapsed_ms)
    return response


if os.environ.get("PRELOAD_MODEL", "1") == "1":
    _load_model()
