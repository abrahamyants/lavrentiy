"""Offline purchase verification contract tests (no Play credentials needed)."""

import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "wim", "api"))
from billing_backend import (
    BASE_PLAN_ID, BillingVerificationError, PACKAGE_NAME, PRODUCT_ID,
    account_hash, fetch_subscription_with_google, subscription_is_entitled,
    token_hash, verify_with_google,
)


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.url = None
    def get(self, url, timeout):
        self.url = url
        return self.response


def must_fail(label, body, status):
    try:
        body()
    except BillingVerificationError as e:
        assert e.status == status, (label, e.status)
        print("PASS:", label)
        return
    raise AssertionError(label)


assert len(account_hash("firebase-user")) == 64
assert account_hash("firebase-user") == account_hash("firebase-user")
assert token_hash("purchase-token") != token_hash("other-token")
print("PASS: stable privacy-preserving identifiers")

future = "2030-01-01T00:00:00Z"
session = FakeSession(FakeResponse(200, {
    "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
    "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
    "externalAccountIdentifiers": {"obfuscatedExternalAccountId": "abc"},
    "lineItems": [{
        "productId": PRODUCT_ID,
        "expiryTime": future,
        "latestSuccessfulOrderId": "GPA.test",
        "offerDetails": {"basePlanId": BASE_PLAN_ID},
    }],
}))
purchase, returned_session = verify_with_google(
    "token/with/slash", PRODUCT_ID, session,
    now=datetime.datetime(2029, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
assert purchase["subscriptionState"] == "SUBSCRIPTION_STATE_ACTIVE"
assert purchase["_wim_line_item"]["productId"] == PRODUCT_ID
assert returned_session is session
assert PACKAGE_NAME in session.url and "token%2Fwith%2Fslash" in session.url
assert PACKAGE_NAME == "com.wimlabs.wim"
assert "/purchases/subscriptionsv2/tokens/" in session.url
print("PASS: active subscription verifies and URL-encodes token")

must_fail("unknown product rejected",
          lambda: verify_with_google("token", "wrong_product", session), 400)
must_fail("missing purchase rejected",
          lambda: verify_with_google("token", PRODUCT_ID, FakeSession(FakeResponse(404))), 404)
must_fail("pending subscription rejected",
          lambda: verify_with_google("token", PRODUCT_ID, FakeSession(FakeResponse(200, {
              "subscriptionState": "SUBSCRIPTION_STATE_PENDING",
          }))), 409)

inactive, _ = fetch_subscription_with_google("token", PRODUCT_ID, FakeSession(FakeResponse(200, {
    "subscriptionState": "SUBSCRIPTION_STATE_ON_HOLD",
    "lineItems": [{"productId": PRODUCT_ID, "expiryTime": future}],
})))
assert not subscription_is_entitled(inactive, now=0)
print("PASS: inactive lifecycle state remains readable for RTDN revocation")
must_fail("wrong product rejected",
          lambda: verify_with_google("token", PRODUCT_ID, FakeSession(FakeResponse(200, {
              "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
              "lineItems": [{"productId": "wrong", "expiryTime": future}],
          })), now=0), 409)
must_fail("expired subscription rejected",
          lambda: verify_with_google("token", PRODUCT_ID, FakeSession(FakeResponse(200, {
              "subscriptionState": "SUBSCRIPTION_STATE_CANCELED",
              "lineItems": [{"productId": PRODUCT_ID, "expiryTime": "2020-01-01T00:00:00Z"}],
          })), now=1_700_000_000), 409)

canceled = FakeSession(FakeResponse(200, {
    "subscriptionState": "SUBSCRIPTION_STATE_CANCELED",
    "lineItems": [{"productId": PRODUCT_ID, "expiryTime": future}],
}))
purchase, _ = verify_with_google("token", PRODUCT_ID, canceled, now=0)
assert purchase["subscriptionState"] == "SUBSCRIPTION_STATE_CANCELED"
print("PASS: canceled subscription remains entitled through paid expiry")

print("PASSED: billing backend contract")
