"""Offline Google Play RTDN decoding contract tests."""

import base64
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "wim", "api"))
from billing_events import BillingEventError, decode_pubsub_cloud_event


payload = {
    "version": "1.0",
    "packageName": "com.wimlabs.wim",
    "subscriptionNotification": {
        "version": "1.0",
        "notificationType": 2,
        "purchaseToken": "token-value",
    },
}
event = {"message": {
    "messageId": "message-1",
    "data": base64.b64encode(json.dumps(payload).encode()).decode(),
}}
message_id, decoded = decode_pubsub_cloud_event(event)
assert message_id == "message-1"
assert decoded == payload

# ``gcloud functions deploy --trigger-topic`` uses this unwrapped legacy
# background-event shape and calls the entry point as ``function(data, context)``.
legacy_event = event["message"]
message_id, decoded = decode_pubsub_cloud_event(legacy_event)
assert message_id == "message-1"
assert decoded == payload

for bad in ({}, {"message": {}}, {"message": {"data": "not base64"}}):
    try:
        decode_pubsub_cloud_event(bad)
    except BillingEventError:
        pass
    else:
        raise AssertionError(f"Invalid event accepted: {bad!r}")

print("PASSED: Google Play RTDN decoding contract")
