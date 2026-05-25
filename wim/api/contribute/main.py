"""
WiM — L1 Contribution Cloud Function
Deploy to GCP Cloud Functions (gen2, HTTP trigger).

Accepts anonymized L1-transfer corrections and writes them to Firestore
for future training data. No Firebase auth required — caller is responsible
for anonymization (anonymous_id is a hash, not a uid).

Endpoint: POST /
Body: {
    "raw": "original disfluent transcript",
    "model_output": "what WiM reconstructed",
    "user_correction": "what the user actually meant",
    "profile_l1": "russian",
    "anonymous_id": "<sha256-of-uid>",
    "profile_l1_confidence": 0.92  (optional)
}
"""

import json
import uuid

import functions_framework
from google.cloud import firestore
from firebase_admin import initialize_app

# Initialize Firebase Admin (uses default GCP credentials)
try:
    initialize_app()
except ValueError:
    pass  # Already initialized

db = firestore.Client()

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "3600",
}

SUPPORTED_L1 = {
    "russian", "spanish", "mandarin", "hindi", "arabic",
    "farsi", "french", "german", "korean", "japanese",
}

MAX_TEXT_LEN = 2000
MAX_ID_LEN = 64


@functions_framework.http
def handle(request):
    """HTTP Cloud Function entry point."""
    # CORS preflight
    if request.method == "OPTIONS":
        return ("", 204, CORS_HEADERS)

    if request.method != "POST":
        return (json.dumps({"error": "POST required"}), 405, CORS_HEADERS)

    # Parse body
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        return (json.dumps({"error": "Invalid JSON"}), 400, CORS_HEADERS)

    # Required field presence check — user_correction may be empty string (implicit rejection signal)
    required = ("raw", "model_output", "profile_l1", "anonymous_id")
    for field in required:
        if not body.get(field):
            return (json.dumps({"error": f"Missing required field: {field}"}), 400, CORS_HEADERS)
    if "user_correction" not in body:
        return (json.dumps({"error": "Missing required field: user_correction"}), 400, CORS_HEADERS)

    raw = body["raw"].strip()
    model_output = body["model_output"].strip()
    user_correction = body["user_correction"].strip()
    profile_l1 = body["profile_l1"].strip().lower()
    anonymous_id = body["anonymous_id"].strip()
    confidence = body.get("profile_l1_confidence")

    # Validate profile_l1
    if profile_l1 not in SUPPORTED_L1:
        return (json.dumps({
            "error": f"Unsupported profile_l1: {profile_l1!r}",
            "supported": sorted(SUPPORTED_L1),
        }), 400, CORS_HEADERS)

    # Validate string lengths
    if len(raw) > MAX_TEXT_LEN:
        return (json.dumps({"error": f"'raw' exceeds {MAX_TEXT_LEN} characters"}), 400, CORS_HEADERS)
    if len(model_output) > MAX_TEXT_LEN:
        return (json.dumps({"error": f"'model_output' exceeds {MAX_TEXT_LEN} characters"}), 400, CORS_HEADERS)
    if len(user_correction) > MAX_TEXT_LEN:
        return (json.dumps({"error": f"'user_correction' exceeds {MAX_TEXT_LEN} characters"}), 400, CORS_HEADERS)
    if len(anonymous_id) > MAX_ID_LEN:
        return (json.dumps({"error": f"'anonymous_id' exceeds {MAX_ID_LEN} characters"}), 400, CORS_HEADERS)

    # Validate optional confidence if provided
    if confidence is not None:
        try:
            confidence = float(confidence)
            if not (0.0 <= confidence <= 1.0):
                raise ValueError()
        except (TypeError, ValueError):
            return (json.dumps({"error": "'profile_l1_confidence' must be a float between 0.0 and 1.0"}), 400, CORS_HEADERS)

    # Build Firestore doc
    auto_id = str(uuid.uuid4())
    doc_data = {
        "raw": raw,
        "model_output": model_output,
        "user_correction": user_correction,
        "profile_l1": profile_l1,
        "anonymous_id": anonymous_id,
        "timestamp": firestore.SERVER_TIMESTAMP,
    }
    if confidence is not None:
        doc_data["confidence"] = confidence

    # Write to l1_contributions/{profile_l1}/entries/{auto_id}
    try:
        db.collection("l1_contributions").document(profile_l1).collection("entries").document(auto_id).set(doc_data)
    except Exception:
        import logging
        logging.exception("Firestore write failed for l1_contributions")
        return (
            json.dumps({"error": "Storage unavailable"}),
            503,
            {**CORS_HEADERS, "Content-Type": "application/json"},
        )

    return (
        json.dumps({"ok": True, "contribution_id": auto_id}),
        200,
        {**CORS_HEADERS, "Content-Type": "application/json"},
    )
