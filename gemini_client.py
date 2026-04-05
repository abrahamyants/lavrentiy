"""gemini_client.py — Minimal HTTP client for Google Gemini 2.5 Pro

Used for L2/L3 reconstruction in Lavrentiy. L4 + Falcon stay on GPT-4o.
Why: Gemini 2.5 Pro is ~50% cheaper on input tokens than GPT-4o, with
competitive quality for instruction-following (which is what L2/L3 needs).

Contract matches OpenAI's client.chat.completions.create() shape enough
to swap in easily — returns a text string from the model.
"""

import json
import urllib.request
import urllib.error

GEMINI_MODEL = "gemini-2.5-pro"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


def generate(system_prompt: str, user_prompt: str, api_key: str,
             temperature: float = 0.3, max_tokens: int = 1000) -> str:
    """Call Gemini 2.5 Pro with a system + user prompt. Returns the generated text.
    Raises Exception on API error — caller should catch and fall back to OpenAI."""
    if not api_key:
        raise ValueError("No Gemini API key configured")

    # Gemini treats system_prompt as a systemInstruction, user_prompt as a user content.
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": user_prompt}]}
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{GEMINI_ENDPOINT}?key={api_key}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:300]
        raise Exception(f"Gemini {e.code}: {err_body}")
    except urllib.error.URLError as e:
        raise Exception(f"Gemini network error: {e.reason}")

    # Parse response: candidates[0].content.parts[0].text
    candidates = data.get("candidates", [])
    if not candidates:
        raise Exception(f"Gemini returned no candidates: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        # Check finish reason — might have been blocked by safety filters
        finish = candidates[0].get("finishReason", "unknown")
        raise Exception(f"Gemini returned empty content (finish: {finish})")
    return parts[0].get("text", "").strip()
