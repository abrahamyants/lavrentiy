"""Offline purchase verification contract tests (no Play credentials needed)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "wim", "api"))
from billing_backend import (
    BillingVerificationError, PACKAGE_NAME, PRODUCT_ID,
    account_hash, token_hash, verify_with_google,
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

session = FakeSession(FakeResponse(200, {
    "purchaseState": 0,
    "acknowledgementState": 0,
    "quantity": 1,
    "orderId": "GPA.test",
}))
purchase, returned_session = verify_with_google("token/with/slash", PRODUCT_ID, session)
assert purchase["purchaseState"] == 0
assert returned_session is session
assert PACKAGE_NAME in session.url and "token%2Fwith%2Fslash" in session.url
print("PASS: completed purchase verifies and URL-encodes token")

must_fail("unknown product rejected",
          lambda: verify_with_google("token", "wrong_product", session), 400)
must_fail("missing purchase rejected",
          lambda: verify_with_google("token", PRODUCT_ID, FakeSession(FakeResponse(404))), 404)
must_fail("pending purchase rejected",
          lambda: verify_with_google("token", PRODUCT_ID,
              FakeSession(FakeResponse(200, {"purchaseState": 2}))), 409)
must_fail("canceled purchase rejected",
          lambda: verify_with_google("token", PRODUCT_ID,
              FakeSession(FakeResponse(200, {"purchaseState": 1}))), 409)

print("PASSED: billing backend contract")
