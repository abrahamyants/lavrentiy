"""Deletion helpers for WiM cloud accounts and all nested user data."""


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
