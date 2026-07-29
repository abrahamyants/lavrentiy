"""Export and deletion helpers for WiM cloud accounts."""

from datetime import date, datetime


def make_json_safe(value):
    """Convert Firestore timestamp values into JSON-safe ISO strings."""
    if isinstance(value, dict):
        return {key: make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _delete_query_documents(db, query, batch_size=400):
    """Delete every document returned by a Firestore query in bounded batches."""
    deleted = 0
    while True:
        documents = list(query.limit(batch_size).stream())
        if not documents:
            return deleted
        batch = db.batch()
        for document in documents:
            batch.delete(document.reference)
        batch.commit()
        deleted += len(documents)


def delete_cloud_account(db, auth_client, uid):
    """Delete a user's tokens, nested sessions, profile, and Firebase account.

    Firestore does not cascade-delete subcollections when a parent document is
    removed. Synced sessions therefore must be deleted before ``wim_users/uid``.
    Firebase Authentication is deleted last so a transient Firestore failure
    never strands data behind an account the user can no longer authenticate.
    """
    deleted = {"tokens": 0, "sessions": 0}
    for collection_name in ("wim_subscription_tokens", "wim_purchase_tokens"):
        query = db.collection(collection_name).where("uid", "==", uid)
        deleted["tokens"] += _delete_query_documents(db, query)

    user_ref = db.collection("wim_users").document(uid)
    deleted["sessions"] = _delete_query_documents(
        db, user_ref.collection("sessions"))
    user_ref.delete()
    auth_client.delete_user(uid)
    return deleted
