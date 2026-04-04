"""
What I Meant — Cloud Function Backend Proxy
Deploy to GCP Cloud Functions (Python 3.11+).

Authenticates users via Firebase Auth, checks subscription tier,
rate-limits, then calls OpenAI with the server-side API key.

Endpoint: POST /
Headers: Authorization: Bearer <firebase_id_token>
Body: {
    "raw": "so um like the thing is we need to uh get the report",
    "tone": "professional",
    "layer": 2,
    "situation": "default",
    "mode": "FAST",
    "profile": {...}
}
"""

import json
import os
import time

import functions_framework
from google.cloud import firestore
from firebase_admin import auth, initialize_app

from reconstruct import reconstruct_intent

# Initialize Firebase Admin (uses default GCP credentials)
try:
    initialize_app()
except ValueError:
    pass  # Already initialized

db = firestore.Client()

# Tier definitions
TIERS = {
    "invite": {"max_layer": 2, "daily_limit": 30, "name": "Free"},
    "basic": {"max_layer": 2, "daily_limit": 200, "name": "Basic ($5.99)"},
    "pro": {"max_layer": 4, "daily_limit": 999999, "name": "Pro ($14.99)"},
}

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "3600",
}


def verify_token(request):
    """Extract and verify Firebase ID token from Authorization header.
    Returns (uid, error_response). If uid is None, return error_response."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, (json.dumps({"error": "Missing Authorization header"}), 401, CORS_HEADERS)

    token = auth_header.split("Bearer ")[1].strip()
    try:
        decoded = auth.verify_id_token(token)
        return decoded["uid"], None
    except Exception as e:
        return None, (json.dumps({"error": f"Invalid token: {str(e)[:100]}"}), 401, CORS_HEADERS)


def get_user_tier(uid):
    """Get user's subscription tier from Firestore. Default to 'invite'."""
    doc = db.collection("wim_users").document(uid).get()
    if doc.exists:
        return doc.to_dict().get("tier", "invite")
    # First-time user: create doc with invite tier
    db.collection("wim_users").document(uid).set({
        "tier": "invite",
        "created": firestore.SERVER_TIMESTAMP,
        "daily_count": 0,
        "daily_reset": time.time(),
    })
    return "invite"


def check_rate_limit(uid, tier_config):
    """Check and increment daily usage. Returns (ok, remaining, error_response)."""
    ref = db.collection("wim_users").document(uid)
    doc = ref.get()
    data = doc.to_dict() if doc.exists else {}

    daily_count = data.get("daily_count", 0)
    daily_reset = data.get("daily_reset", 0)

    # Reset counter if it's a new day (86400 seconds)
    if time.time() - daily_reset > 86400:
        daily_count = 0
        ref.update({"daily_count": 0, "daily_reset": time.time()})

    if daily_count >= tier_config["daily_limit"]:
        return False, 0, (json.dumps({
            "error": "Daily limit reached",
            "limit": tier_config["daily_limit"],
            "tier": tier_config["name"],
        }), 429, CORS_HEADERS)

    # Increment
    ref.update({"daily_count": firestore.Increment(1)})
    remaining = tier_config["daily_limit"] - daily_count - 1
    return True, remaining, None


@functions_framework.http
def handle(request):
    """HTTP Cloud Function entry point."""
    # CORS preflight
    if request.method == "OPTIONS":
        return ("", 204, CORS_HEADERS)

    if request.method != "POST":
        return (json.dumps({"error": "POST required"}), 405, CORS_HEADERS)

    # Authenticate
    uid, err = verify_token(request)
    if err:
        return err

    # Get tier
    tier_name = get_user_tier(uid)
    tier_config = TIERS.get(tier_name, TIERS["invite"])

    # Parse body
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        return (json.dumps({"error": "Invalid JSON"}), 400, CORS_HEADERS)

    # Profile sync: Lavrentiy desktop pushes learned profile to Firestore
    if body.get("action") == "sync_profile":
        profile_data = body.get("profile", {})
        profile_data["sync_ts"] = time.time()
        db.collection("wim_users").document(uid).set(profile_data, merge=True)
        return (json.dumps({"ok": True}), 200, {**CORS_HEADERS, "Content-Type": "application/json"})

    # GDPR: export user's stored data
    if body.get("action") == "export_data":
        doc = db.collection("wim_users").document(uid).get()
        data = doc.to_dict() if doc.exists else {}
        return (json.dumps({"ok": True, "data": data}), 200, {**CORS_HEADERS, "Content-Type": "application/json"})

    # GDPR: delete user's cloud data
    if body.get("action") == "delete_data":
        db.collection("wim_users").document(uid).delete()
        return (json.dumps({"ok": True, "deleted": True}), 200, {**CORS_HEADERS, "Content-Type": "application/json"})

    raw = body.get("raw", "").strip()
    if not raw:
        return (json.dumps({"error": "Missing 'raw' field"}), 400, CORS_HEADERS)

    # Check layer against tier
    requested_layer = body.get("layer", 2)
    if requested_layer > tier_config["max_layer"]:
        return (json.dumps({
            "error": f"Layer {requested_layer} requires Pro tier",
            "max_layer": tier_config["max_layer"],
            "tier": tier_config["name"],
        }), 403, CORS_HEADERS)

    # Rate limit
    ok, remaining, rate_err = check_rate_limit(uid, tier_config)
    if not ok:
        return rate_err

    # Process
    result = reconstruct_intent(
        raw_text=raw,
        tone=body.get("tone", "casual"),
        layer=requested_layer,
        profile=body.get("profile"),
        situation=body.get("situation", "default"),
        mode=body.get("mode", "SAFE"),
        whisper_low_conf=body.get("whisper_low_conf"),
        whisper_disagreements=body.get("whisper_disagreements"),
        speech_severity_mod=body.get("speech_severity_mod", 0.0),
    )

    result["tier"] = tier_config["name"]
    result["remaining"] = remaining

    return (json.dumps(result), 200, {**CORS_HEADERS, "Content-Type": "application/json"})
