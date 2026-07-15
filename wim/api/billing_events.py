"""Decode Google Play real-time developer notifications from Cloud Pub/Sub."""

import base64
import json


class BillingEventError(ValueError):
    pass


def decode_pubsub_cloud_event(cloud_event):
    """Return ``(message_id, DeveloperNotification)`` from a CloudEvent."""
    envelope = getattr(cloud_event, "data", cloud_event)
    if not isinstance(envelope, dict):
        raise BillingEventError("Pub/Sub event data is missing")
    message = envelope.get("message") or {}
    encoded = message.get("data")
    if not encoded:
        raise BillingEventError("Pub/Sub message data is missing")
    try:
        raw = base64.b64decode(encoded, validate=True)
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BillingEventError("Pub/Sub message data is invalid") from exc
    if not isinstance(payload, dict):
        raise BillingEventError("Developer notification is invalid")
    return str(message.get("messageId") or "unknown"), payload
