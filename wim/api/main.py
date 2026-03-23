"""
What I Meant — Cloud Function Entry Point
Deploy to GCP Cloud Functions (Python 3.11+).

Endpoint: POST /reconstruct
Body: {
    "raw": "so um like the thing is we need to uh get the report",
    "tone": "professional",       // optional, default "casual"
    "layer": 2,                   // optional, default 2
    "situation": "default",       // optional
    "mode": "FAST",               // optional: RAW, FAST, SAFE
    "profile": {...},             // optional: user profile dict
    "whisper_low_conf": [...],    // optional
    "whisper_disagreements": [...] // optional
}

Response: {
    "clean": "We need to get the report.",
    "raw": "so um like the thing is...",
    "confidence": 0.92,
    "falcon_ok": true,
    "ms": 340,
    "mode": "FAST",
    "tone": "professional",
    "layer": 2
}
"""

import json
import functions_framework
from reconstruct import reconstruct_intent


@functions_framework.http
def handle(request):
    """HTTP Cloud Function entry point."""
    # CORS preflight
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    cors = {"Access-Control-Allow-Origin": "*"}

    if request.method != "POST":
        return (json.dumps({"error": "POST required"}), 405, cors)

    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        return (json.dumps({"error": "Invalid JSON"}), 400, cors)

    raw = body.get("raw", "").strip()
    if not raw:
        return (json.dumps({"error": "Missing 'raw' field"}), 400, cors)

    result = reconstruct_intent(
        raw_text=raw,
        tone=body.get("tone", "casual"),
        layer=body.get("layer", 2),
        profile=body.get("profile"),
        situation=body.get("situation", "default"),
        mode=body.get("mode", "FAST"),
        whisper_low_conf=body.get("whisper_low_conf"),
        whisper_disagreements=body.get("whisper_disagreements"),
        speech_severity_mod=body.get("speech_severity_mod", 0.0),
    )

    return (json.dumps(result), 200, {**cors, "Content-Type": "application/json"})
