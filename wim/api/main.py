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
import time

import functions_framework
from google.cloud import firestore
from firebase_admin import auth, initialize_app

from reconstruct import reconstruct_intent
from audio_backend import AudioRequestError, prepare_audio_request
from billing_backend import (
    BillingVerificationError,
    PRODUCT_ID as BILLING_PRODUCT_ID,
    account_hash,
    acknowledge_with_google,
    token_hash,
    verify_with_google,
)

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
    "invite": {"max_layer": 1, "daily_limit": 0, "name": "Local / Free"},
    "basic": {"max_layer": 4, "daily_limit": 200, "name": "Cloud Unlock"},
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


def check_audio_rate_limit(uid, tier_config):
    """Separate audio quota so one dictation does not consume two user credits.

    Transcription and reconstruction are two HTTP calls for one user action.
    Charging both against `daily_count` would silently cut every advertised
    allowance in half; this parallel counter bounds audio cost without doing so.
    """
    ref = db.collection("wim_users").document(uid)
    daily_limit = tier_config["daily_limit"]

    @firestore.transactional
    def _txn(transaction):
        snapshot = ref.get(transaction=transaction)
        data = snapshot.to_dict() if snapshot.exists else {}
        count = data.get("audio_daily_count", 0)
        reset_ts = data.get("audio_daily_reset", 0)
        now = time.time()
        is_reset = now - reset_ts > 86400
        if is_reset:
            count = 0
        if count >= daily_limit:
            return False, 0
        update_data = {"audio_daily_count": count + 1}
        if is_reset:
            update_data["audio_daily_reset"] = now
        transaction.update(ref, update_data)
        return True, daily_limit - count - 1

    ok, remaining = _txn(db.transaction())
    if not ok:
        return False, 0, (json.dumps({
            "error": "Daily audio limit reached",
            "limit": daily_limit,
            "tier": tier_config["name"],
        }), 429, CORS_HEADERS)
    return True, remaining, None


_JSON_CORS = {**CORS_HEADERS, "Content-Type": "application/json"}
_ALLOWED_PROFILE_KEYS = {
    "trigger_words", "onset_weights", "covert_profile",
    "filler_words", "vocabulary", "corrections",
}
_EXPORT_VISIBLE_KEYS = {
    "trigger_words", "onset_weights", "covert_profile",
    "filler_words", "vocabulary", "corrections", "sync_ts", "created",
    "tier", "billing_product_id", "billing_order_id", "billing_verified_at",
}
_RETRIABLE_EXC_NAMES = {"APITimeoutError", "APIConnectionError", "RateLimitError"}


def _action_sync_profile(uid, tier_config, body):
    """Lavrentiy desktop pushes learned profile to Firestore."""
    raw = body.get("profile", {})
    profile_data = {k: v for k, v in raw.items() if k in _ALLOWED_PROFILE_KEYS}
    profile_data["sync_ts"] = time.time()
    db.collection("wim_users").document(uid).set(profile_data, merge=True)
    return (json.dumps({"ok": True}), 200, _JSON_CORS)


def _action_export_data(uid, tier_config, body):
    """GDPR: export user's stored data, stripping internal billing/quota state."""
    doc = db.collection("wim_users").document(uid).get()
    full = doc.to_dict() if doc.exists else {}
    user_visible = {k: v for k, v in full.items() if k in _EXPORT_VISIBLE_KEYS}
    return (json.dumps({"ok": True, "data": user_visible}), 200, _JSON_CORS)


def _action_delete_data(uid, tier_config, body):
    """GDPR: delete user's cloud data."""
    purchase_docs = db.collection("wim_purchase_tokens").where("uid", "==", uid).stream()
    for purchase_doc in purchase_docs:
        purchase_doc.reference.delete()
    db.collection("wim_users").document(uid).delete()
    return (json.dumps({"ok": True, "deleted": True}), 200, _JSON_CORS)


def _action_billing_status(uid, tier_config, body):
    doc = db.collection("wim_users").document(uid).get()
    data = doc.to_dict() if doc.exists else {}
    tier = data.get("tier", "invite")
    return (json.dumps({
        "ok": True,
        "unlocked": tier in ("basic", "pro"),
        "tier": tier,
        "product_id": data.get("billing_product_id"),
    }), 200, _JSON_CORS)


def _action_verify_purchase(uid, tier_config, body):
    """Verify, bind, grant, and acknowledge the permanent cloud entitlement."""
    purchase_token = (body.get("purchase_token") or "").strip()
    product_id = (body.get("product_id") or "").strip()
    try:
        purchase, google_session = verify_with_google(purchase_token, product_id)
        external_id = purchase.get("obfuscatedExternalAccountId")
        if external_id != account_hash(uid):
            raise BillingVerificationError("Purchase belongs to a different account", 403)

        # A grant must never outlive an unacknowledged purchase: Play refunds
        # unacknowledged purchases after its acknowledgement window. Ack first;
        # a retry can safely finish the idempotent Firestore grant afterward.
        if purchase.get("acknowledgementState", 0) == 0:
            acknowledge_with_google(google_session, purchase_token, product_id)

        purchase_ref = db.collection("wim_purchase_tokens").document(token_hash(purchase_token))
        user_ref = db.collection("wim_users").document(uid)

        @firestore.transactional
        def _grant(transaction):
            existing = purchase_ref.get(transaction=transaction)
            if existing.exists and existing.to_dict().get("uid") != uid:
                return False
            transaction.set(purchase_ref, {
                "uid": uid,
                "product_id": BILLING_PRODUCT_ID,
                "order_id": purchase.get("orderId"),
                "purchase_time_ms": purchase.get("purchaseTimeMillis"),
                "verified_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)
            transaction.set(user_ref, {
                "tier": "basic",
                "billing_product_id": BILLING_PRODUCT_ID,
                "billing_order_id": purchase.get("orderId"),
                "billing_verified_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)
            return True

        if not _grant(db.transaction()):
            raise BillingVerificationError("Purchase token was already claimed", 409)

    except BillingVerificationError as e:
        _emit(logging.WARNING, event="billing_verify_rejected", uid=uid,
              status=e.status, error=str(e)[:200])
        return (json.dumps({"error": str(e)}), e.status, CORS_HEADERS)
    except Exception as e:
        _emit(logging.ERROR, event="billing_verify_failed", uid=uid,
              exception=type(e).__name__, error=str(e)[:300])
        return (json.dumps({"error": "Purchase verification temporarily unavailable"}),
                503, CORS_HEADERS)

    _emit(logging.INFO, event="billing_entitlement_granted", uid=uid,
          product_id=product_id)
    return (json.dumps({
        "ok": True,
        "unlocked": True,
        "tier": "basic",
        "product_id": BILLING_PRODUCT_ID,
    }), 200, _JSON_CORS)


def _action_command(uid, tier_config, body):
    """Command Mode: highlight + voice command → transformed text.
    Re-uses rate-limit + tier infrastructure but skips the heavy reconstruction
    prompt — this is a free-form text transform, not disfluency reconstruction.
    """
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
            model="gpt-4o-2024-11-20",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        transformed = (resp.choices[0].message.content or "").strip()
        return (json.dumps({
            "transformed": transformed,
            "tier": tier_config["name"],
            "remaining": remaining,
        }), 200, _JSON_CORS)
    except Exception as e:
        return (json.dumps({"error": f"Transform failed: {str(e)[:200]}"}), 500, CORS_HEADERS)


def _action_complete_partial(uid, tier_config, body):
    """Mid-block bridging: a partial utterance (speaker froze mid-sentence) ->
    up to 3 completion candidates the bubble shows as a tap row. Shared by
    Lavrentiy desktop and WiM Android signed-in users."""
    partial = (body.get("partial_text") or body.get("raw") or "").strip()
    if not partial:
        return (json.dumps({"error": "Missing 'partial_text' field"}), 400, CORS_HEADERS)

    ok, remaining, rate_err = check_rate_limit(uid, tier_config)
    if not ok:
        return rate_err

    from reconstruct import complete_partial
    t_call = time.time()
    try:
        candidates = complete_partial(
            partial,
            tone=body.get("tone", "casual"),
            language_code=body.get("language_code", "en"),
        )
    except Exception as e:
        latency_ms = round((time.time() - t_call) * 1000)
        _emit(logging.ERROR, event="complete_partial_failed", uid=uid,
              latency_ms=latency_ms, exception=type(e).__name__, error=str(e)[:300])
        return (json.dumps({
            "error": f"Completion failed: {type(e).__name__}",
            "tier": tier_config["name"],
        }), 500, CORS_HEADERS)

    _emit(logging.INFO, event="complete_partial_ok", uid=uid,
          latency_ms=round((time.time() - t_call) * 1000), n=len(candidates))
    return (json.dumps({
        "candidates": candidates,
        "tier": tier_config["name"],
        "remaining": remaining,
    }), 200, _JSON_CORS)


def _action_transcribe_audio(uid, tier_config, body):
    """Authenticated mobile audio transcription.

    WiM sends a base64-encoded WAV here so release builds never need an
    OpenAI secret on the phone.  `whisper-1` keeps verbose segment confidence
    for L4; `gpt-4o-transcribe` is the faster normal cloud path.
    """
    try:
        kwargs, audio_bytes_len, model = prepare_audio_request(body)
    except AudioRequestError as e:
        return (json.dumps({"error": str(e)}), e.status, CORS_HEADERS)

    ok, remaining, rate_err = check_audio_rate_limit(uid, tier_config)
    if not ok:
        return rate_err

    from reconstruct import client as openai_client
    if openai_client is None:
        return (json.dumps({"error": "Backend OpenAI client not configured"}), 500, CORS_HEADERS)

    t_call = time.time()
    try:
        response = openai_client.audio.transcriptions.create(**kwargs)
        payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    except Exception as e:
        latency_ms = round((time.time() - t_call) * 1000)
        retriable = _classify_exception(e)
        _emit(logging.ERROR, event="transcribe_audio_failed", uid=uid,
              latency_ms=latency_ms, exception=type(e).__name__,
              error=str(e)[:300], retriable=retriable)
        return (json.dumps({
            "error": f"Transcription failed: {type(e).__name__}",
            "retriable": retriable,
        }), 503 if retriable else 500, CORS_HEADERS)

    text = (payload.get("text") or "").strip()
    segments = payload.get("segments") or []
    _emit(logging.INFO, event="transcribe_audio_ok", uid=uid, model=model,
          latency_ms=round((time.time() - t_call) * 1000),
          audio_bytes=audio_bytes_len, segments=len(segments))
    return (json.dumps({
        "text": text,
        "segments": segments,
        "model": model,
        "remaining": remaining,
    }), 200, _JSON_CORS)


def _classify_exception(e):
    """Return True if the exception is retriable per OpenAI SDK conventions.
    Introspects by name + status_code to stay robust to SDK reshuffles instead
    of importing concrete openai exception classes.
    """
    exc_name = type(e).__name__
    if exc_name in _RETRIABLE_EXC_NAMES:
        return True
    status_code = getattr(e, "status_code", None)
    return status_code is not None and status_code >= 500


def _action_reconstruct(uid, tier_config, body):
    """Default action: disfluency reconstruction (the original endpoint)."""
    raw = body.get("raw", "").strip()
    if not raw:
        return (json.dumps({"error": "Missing 'raw' field"}), 400, CORS_HEADERS)

    requested_layer = body.get("layer", 2)
    if requested_layer > tier_config["max_layer"]:
        return (json.dumps({
            "error": f"Layer {requested_layer} requires Pro tier",
            "max_layer": tier_config["max_layer"],
            "tier": tier_config["name"],
        }), 403, CORS_HEADERS)

    ok, remaining, rate_err = check_rate_limit(uid, tier_config)
    if not ok:
        return rate_err

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
            preceding_context=body.get("preceding_context"),
            script_prep_context=body.get("script_prep"),
            compression_ratio_note=body.get("compression_ratio_note"),
            previous_outputs=body.get("previous_outputs"),
            prior_rejections=body.get("rejection_history"),
            style_examples=body.get("style_examples"),
            window_title=body.get("audience_package"),
        )
    except Exception as e:
        latency_ms = round((time.time() - t_call) * 1000)
        retriable = _classify_exception(e)
        exc_name = type(e).__name__
        _emit(
            logging.ERROR,
            event="reconstruct_failed",
            uid=uid, layer=requested_layer, latency_ms=latency_ms,
            exception=exc_name, error=str(e)[:300], retriable=retriable,
        )
        return (json.dumps({
            "error": f"Reconstruction failed: {exc_name}",
            "retriable": retriable,
            "tier": tier_config["name"],
        }), 503 if retriable else 500, CORS_HEADERS)

    latency_ms = round((time.time() - t_call) * 1000)
    _emit(
        logging.INFO,
        event="reconstruct_ok",
        uid=uid, layer=requested_layer, latency_ms=latency_ms,
        model=result.get("model", "n/a"),
        mode=result.get("mode"),
    )
    result["tier"] = tier_config["name"]
    result["remaining"] = remaining
    return (json.dumps(result), 200, _JSON_CORS)


_ACTION_HANDLERS = {
    "sync_profile":     _action_sync_profile,
    "export_data":      _action_export_data,
    "delete_data":      _action_delete_data,
    "command":          _action_command,
    "complete_partial": _action_complete_partial,
    "transcribe_audio": _action_transcribe_audio,
    "billing_status":   _action_billing_status,
    "verify_purchase":  _action_verify_purchase,
}

_ENTITLEMENT_FREE_ACTIONS = {
    "billing_status", "verify_purchase", "export_data", "delete_data", "sync_profile",
}


@functions_framework.http
def handle(request):
    """HTTP Cloud Function entry point — preflight + auth + dispatch."""
    if request.method == "OPTIONS":
        return ("", 204, CORS_HEADERS)
    if request.method != "POST":
        return (json.dumps({"error": "POST required"}), 405, CORS_HEADERS)

    uid, err = verify_token(request)
    if err:
        return err

    tier_name = get_user_tier(uid)
    tier_config = TIERS.get(tier_name, TIERS["invite"])

    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        return (json.dumps({"error": "Invalid JSON"}), 400, CORS_HEADERS)

    action = body.get("action")
    if tier_name not in ("basic", "pro") and action not in _ENTITLEMENT_FREE_ACTIONS:
        return (json.dumps({
            "error": "WiM Cloud Unlock is required",
            "error_code": "billing_required",
            "product_id": BILLING_PRODUCT_ID,
        }), 403, _JSON_CORS)

    action_handler = _ACTION_HANDLERS.get(action, _action_reconstruct)
    return action_handler(uid, tier_config, body)
