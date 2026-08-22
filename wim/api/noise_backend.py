"""Private service-to-service client for WiM's BSRNN-Flow cleaner."""

from __future__ import annotations

import os

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token
import requests


MAX_CLEAN_AUDIO_BYTES = 16 * 1024 * 1024


class NoiseEnhancementError(RuntimeError):
    pass


def _service_token(service_url):
    return id_token.fetch_id_token(GoogleAuthRequest(), service_url)


def enhance_audio(
    audio_bytes,
    container,
    service_url=None,
    post=None,
    token_provider=None,
):
    """Return `(clean_wav_bytes, metadata)` from the private Flow service."""
    service_url = (service_url or os.environ.get("WIM_NOISE_URL", "")).rstrip("/")
    if not service_url:
        raise NoiseEnhancementError("WIM_NOISE_URL is not configured")
    if not audio_bytes:
        raise NoiseEnhancementError("Audio is empty")

    post = post or requests.post
    token_provider = token_provider or _service_token
    try:
        token = token_provider(service_url)
        response = post(
            service_url + "/v1/enhance",
            data=audio_bytes,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "X-WiM-Audio-Format": container,
            },
            timeout=(10, 100),
        )
    except Exception as exc:
        raise NoiseEnhancementError(f"Noise service request failed: {type(exc).__name__}") from exc

    if response.status_code != 200:
        raise NoiseEnhancementError(
            f"Noise service returned {response.status_code}: {response.text[:160]}"
        )
    cleaned = response.content
    if not cleaned or len(cleaned) > MAX_CLEAN_AUDIO_BYTES:
        raise NoiseEnhancementError("Noise service returned an empty or oversized file")
    if len(cleaned) < 44 or cleaned[:4] != b"RIFF" or cleaned[8:12] != b"WAVE":
        raise NoiseEnhancementError("Noise service did not return a valid WAV")

    return cleaned, {
        "model": response.headers.get("X-WiM-Noise-Model", "bsrnn-flow"),
        "cache": response.headers.get("X-WiM-Noise-Cache", "unknown"),
        "latency_ms": response.headers.get("X-WiM-Noise-Ms", "0"),
    }

