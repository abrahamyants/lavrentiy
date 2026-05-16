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
import logging
import os
import time

import functions_framework
from google.cloud import firestore
from firebase_admin import auth, initialize_app

from reconstruct import reconstruct_intent

# Structured logging — Cloud Run / Functions parses JSON lines on stdout into
# Cloud Logging fields. INFO level for normal flow, ERROR for failures.
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _emit(level, **fields):
    """Emit a single JSON-shaped log line for Cloud Logging structured search."""
    try:
        logging.log(level, json.dumps(fields, default=str))
    except Exception:
        # Never let logging itself break a request.
        pass

# Initialize Firebase Admin (uses default GCP credentials)
try:
    initialize_app()
except ValueError:
    pass  # Already initialized

db = firestore.Client()

# Tier definitions
TIERS = {
    "invite": {"max_layer": 4, "daily_limit": 30, "name": "Invite"},
    "basic": {"max_layer": 4, "daily_limit": 200, "name": "Basic ($5.99)"},
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
    """Check and increment daily usage atomically. Returns (ok, remaining, error_response)."""
    ref = db.collection("wim_users").document(uid)
    daily_limit = tier_config["daily_limit"]

    @firestore.transactional
    def _txn(transaction):
        snapshot = ref.get(transaction=transaction)
        data = snapshot.to_dict() if snapshot.exists else {}
        count = data.get("daily_count", 0)
        reset_ts = data.get("daily_reset", 0)
        now = time.time()
        is_reset = now - reset_ts > 86400
        if is_reset:
            count = 0
        if count >= daily_limit:
            return False, 0
        # Single update() per ref — two update() calls in one transaction
        # merge such that the later call's field mutations replace the
        # earlier's (Firestore Python SDK semantics), which silently
        # clobbers a daily_count reset followed by an Increment(1).
        update_data = {"daily_count": count + 1}
        if is_reset:
            update_data["daily_reset"] = now
        transaction.update(ref, update_data)
        return True, daily_limit - count - 1

    ok, remaining = _txn(db.transaction())
    if not ok:
        return False, 0, (json.dumps({
            "error": "Daily limit reached",
            "limit": daily_limit,
            "tier": tier_config["name"],
        }), 429, CORS_HEADERS)
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
        _ALLOWED_PROFILE_KEYS = {
            "trigger_words", "onset_weights", "covert_profile",
            "filler_words", "vocabulary", "corrections"
        }
        raw = body.get("profile", {})
        profile_data = {k: v for k, v in raw.items() if k in _ALLOWED_PROFILE_KEYS}
        profile_data["sync_ts"] = time.time()
        db.collection("wim_users").document(uid).set(profile_data, merge=True)
        return (json.dumps({"ok": True}), 200, {**CORS_HEADERS, "Content-Type": "application/json"})

    # GDPR: export user's stored data (user-visible fields only — strip internal billing/quota state)
    if body.get("action") == "export_data":
        doc = db.collection("wim_users").document(uid).get()
        full = doc.to_dict() if doc.exists else {}
        # Expose learned-profile metadata but hide rate-limiting / tier internals
        user_visible = {
            k: v for k, v in full.items()
            if k in {"trigger_words", "onset_weights", "covert_profile",
                     "filler_words", "vocabulary", "corrections", "sync_ts", "created"}
        }
        return (json.dumps({"ok": True, "data": user_visible}), 200, {**CORS_HEADERS, "Content-Type": "application/json"})

    # GDPR: delete user's cloud data
    if body.get("action") == "delete_data":
        db.collection("wim_users").document(uid).delete()
        return (json.dumps({"ok": True, "deleted": True}), 200, {**CORS_HEADERS, "Content-Type": "application/json"})

    # Command Mode: highlight + voice command → transformed text.
    # Re-uses the rate-limit + tier infrastructure but skips the heavy
    # reconstruction prompt — this is a free-form text-transform, not a
    # disfluency reconstruction.
    if body.get("action") == "command":
        source = (body.get("source") or "").strip()
        command = (body.get("command") or "").strip()
        if not source or not command:
            return (json.dumps({"error": "Missing 'source' or 'command' field"}), 400, CORS_HEADERS)

        ok, remaining, rate_err = check_rate_limit(uid, tier_config)
        if not ok:
            return rate_err

        from reconstruct import client as openai_client
        if openai_client is None:
            return (json.dumps({"error": "Backend OpenAI client not configured"}), 500, CORS_HEADERS)

        try:
            system_prompt = (
                "You are a text transformation assistant. The user highlighted some text "
                "and spoke a command to modify it. Apply the command and return ONLY the "
                "transformed text, nothing else. Preserve the meaning. Do not add "
                "explanations, quotes, or prefixes."
            )
            user_content = f"TEXT:\n{source}\n\nCOMMAND: {command}"
            resp = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=1024,
            )
            transformed = resp.choices[0].message.content.strip()
            return (json.dumps({
                "transformed": transformed,
                "tier": tier_config["name"],
                "remaining": remaining,
            }), 200, {**CORS_HEADERS, "Content-Type": "application/json"})
        except Exception as e:
            return (json.dumps({"error": f"Transform failed: {str(e)[:200]}"}), 500, CORS_HEADERS)

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

    # Process — wrap so the client sees a structured retriable/terminal
    # signal instead of an opaque body-less 500. retriable=True covers
    # OpenAI timeouts, rate-limit 429s, and transient 5xx. Anything else
    # is reported as a terminal app-level error.
    t_call = time.time()
    try:
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
            paralinguistic_events=body.get("paralinguistic_events"),
            prosodic_context=body.get("prosodic_context"),
            language_code=body.get("language_code", "en"),
        )
    except Exception as e:
        latency_ms = round((time.time() - t_call) * 1000)
        # OpenAI SDK exceptions are subclassed by retryability — APITimeoutError
        # and RateLimitError are retriable; APIStatusError ≥500 is retriable;
        # 4xx (excluding 429) is terminal. We don't import openai exception
        # types directly to keep this file robust to SDK reshuffles, so we
        # introspect by name + status_code attribute when available.
        retriable = False
        status_code = getattr(e, "status_code", None)
        exc_name = type(e).__name__
        if exc_name in ("APITimeoutError", "APIConnectionError", "RateLimitError"):
            retriable = True
        elif status_code is not None and status_code >= 500:
            retriable = True
        _emit(
            logging.ERROR,
            event="reconstruct_failed",
            uid=uid,
            layer=requested_layer,
            latency_ms=latency_ms,
            exception=exc_name,
            error=str(e)[:300],
            retriable=retriable,
        )
        body_out = {
            "error": f"Reconstruction failed: {exc_name}",
            "retriable": retriable,
            "tier": tier_config["name"],
        }
        http_code = 503 if retriable else 500
        return (json.dumps(body_out), http_code, CORS_HEADERS)

    latency_ms = round((time.time() - t_call) * 1000)
    _emit(
        logging.INFO,
        event="reconstruct_ok",
        uid=uid,
        layer=requested_layer,
        latency_ms=latency_ms,
        model="gpt-4o-2024-11-20" if requested_layer < 4 else "gpt-4o-2024-11-20",
        mode=result.get("mode"),
    )

    result["tier"] = tier_config["name"]
    result["remaining"] = remaining

    return (json.dumps(result), 200, {**CORS_HEADERS, "Content-Type": "application/json"})
