"""Google Play subscription verification for the WiM Cloud plan."""

import hashlib
from datetime import datetime, timezone
from urllib.parse import quote

PACKAGE_NAME = "com.wimlabs.wim"
PRODUCT_ID = "wim_cloud_monthly"
PLUS_PRODUCT_ID = "wim_cloud_plus_monthly"
BASE_PLAN_ID = "monthly"
# Two plans since 2026-10-11 (George: Cloud $4.99 = layers 1-3, Cloud Plus
# $7.99 adds layer 4). Both live in Play Console as subscriptions with one
# base plan each, id "monthly".
PRODUCT_TIERS = {PRODUCT_ID: "basic", PLUS_PRODUCT_ID: "plus"}
SUBSCRIPTION_TIERS = frozenset(PRODUCT_TIERS.values())
ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
PUBLISHER_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"
ENTITLED_STATES = {
    "SUBSCRIPTION_STATE_ACTIVE",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
    # Cancellation stops renewal, not access already paid through expiryTime.
    "SUBSCRIPTION_STATE_CANCELED",
}


class BillingVerificationError(RuntimeError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def account_hash(uid):
    """Value also sent as BillingFlowParams.obfuscatedAccountId on Android."""
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_expiry(value):
    if not value:
        raise BillingVerificationError("Subscription has no expiry", 409)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        raise BillingVerificationError("Subscription expiry is invalid", 409)


def fetch_subscription_with_google(purchase_token, product_id=None, session=None):
    """Fetch and structurally validate a Google Play subscription resource.

    *product_id* pins the expected plan (in-app purchase path). ``None`` accepts
    any WiM plan (RTDN path, where only the token is known); the matched plan
    comes back as ``purchase["_wim_product_id"]`` either way.

    This deliberately allows inactive lifecycle states so RTDN processing can
    revoke stale entitlements after a refund, expiration, or account hold.
    ``verify_with_google`` adds the active-entitlement requirement used during
    an in-app purchase.
    """
    if not purchase_token or len(purchase_token) > 4096:
        raise BillingVerificationError("Missing or invalid purchase token")
    if product_id is not None and product_id not in PRODUCT_TIERS:
        raise BillingVerificationError("Unknown product ID")
    wanted = {product_id} if product_id else set(PRODUCT_TIERS)

    if session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        credentials, _ = google.auth.default(scopes=[ANDROID_PUBLISHER_SCOPE])
        session = AuthorizedSession(credentials)
    url = (
        f"{PUBLISHER_BASE}/applications/{quote(PACKAGE_NAME, safe='')}"
        f"/purchases/subscriptionsv2/tokens/{quote(purchase_token, safe='')}"
    )
    response = session.get(url, timeout=20)
    if response.status_code == 404:
        raise BillingVerificationError("Subscription was not found", 404)
    if response.status_code == 410:
        raise BillingVerificationError("Subscription token has expired", 410)
    if response.status_code != 200:
        raise BillingVerificationError(
            f"Google Play verification failed ({response.status_code})", 503)
    purchase = response.json()
    line_item = next(
        (item for item in purchase.get("lineItems", [])
         if item.get("productId") in wanted),
        None,
    )
    if not line_item:
        raise BillingVerificationError("Subscription product does not match", 409)
    base_plan_id = (line_item.get("offerDetails") or {}).get("basePlanId")
    if base_plan_id and base_plan_id != BASE_PLAN_ID:
        raise BillingVerificationError("Subscription base plan does not match", 409)
    expiry_ts = _parse_expiry(line_item.get("expiryTime"))
    purchase["_wim_line_item"] = line_item
    purchase["_wim_product_id"] = line_item.get("productId")
    purchase["_wim_expiry_ts"] = expiry_ts
    return purchase, session


def subscription_is_entitled(purchase, now=None):
    state = purchase.get("subscriptionState")
    now_ts = datetime.now(timezone.utc).timestamp() if now is None else float(now)
    return state in ENTITLED_STATES and float(purchase.get("_wim_expiry_ts", 0)) > now_ts


def verify_with_google(purchase_token, product_id=None, session=None, now=None):
    purchase, session = fetch_subscription_with_google(
        purchase_token, product_id, session)
    if not subscription_is_entitled(purchase, now=now):
        if purchase.get("subscriptionState") in ENTITLED_STATES:
            raise BillingVerificationError("Subscription has expired", 409)
        raise BillingVerificationError("Subscription is not entitled", 409)
    return purchase, session


def acknowledge_with_google(session, purchase_token, product_id=PRODUCT_ID):
    url = (
        f"{PUBLISHER_BASE}/applications/{quote(PACKAGE_NAME, safe='')}"
        f"/purchases/subscriptions/{quote(product_id, safe='')}"
        f"/tokens/{quote(purchase_token, safe='')}:acknowledge"
    )
    response = session.post(url, json={}, timeout=20)
    if response.status_code not in (200, 204):
        raise BillingVerificationError(
            f"Google Play acknowledgement failed ({response.status_code})", 503)
