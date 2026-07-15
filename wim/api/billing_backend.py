"""Google Play one-time purchase verification for WiM Cloud Unlock."""

import hashlib
from urllib.parse import quote

PACKAGE_NAME = "com.wim.app"
PRODUCT_ID = "wim_cloud_unlock"
ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
PUBLISHER_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"


class BillingVerificationError(RuntimeError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def account_hash(uid):
    """Value also sent as BillingFlowParams.obfuscatedAccountId on Android."""
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_with_google(purchase_token, product_id=PRODUCT_ID, session=None):
    if not purchase_token or len(purchase_token) > 4096:
        raise BillingVerificationError("Missing or invalid purchase token")
    if product_id != PRODUCT_ID:
        raise BillingVerificationError("Unknown product ID")

    if session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        credentials, _ = google.auth.default(scopes=[ANDROID_PUBLISHER_SCOPE])
        session = AuthorizedSession(credentials)
    url = (
        f"{PUBLISHER_BASE}/applications/{quote(PACKAGE_NAME, safe='')}"
        f"/purchases/products/{quote(product_id, safe='')}"
        f"/tokens/{quote(purchase_token, safe='')}"
    )
    response = session.get(url, timeout=20)
    if response.status_code == 404:
        raise BillingVerificationError("Purchase was not found", 404)
    if response.status_code != 200:
        raise BillingVerificationError(
            f"Google Play verification failed ({response.status_code})", 503)
    purchase = response.json()
    if purchase.get("purchaseState") != 0:
        raise BillingVerificationError("Purchase is not completed", 409)
    if int(purchase.get("quantity", 1)) < 1:
        raise BillingVerificationError("Purchase has no entitlement quantity", 409)
    return purchase, session


def acknowledge_with_google(session, purchase_token, product_id=PRODUCT_ID):
    url = (
        f"{PUBLISHER_BASE}/applications/{quote(PACKAGE_NAME, safe='')}"
        f"/purchases/products/{quote(product_id, safe='')}"
        f"/tokens/{quote(purchase_token, safe='')}:acknowledge"
    )
    response = session.post(url, json={}, timeout=20)
    if response.status_code not in (200, 204):
        raise BillingVerificationError(
            f"Google Play acknowledgement failed ({response.status_code})", 503)
