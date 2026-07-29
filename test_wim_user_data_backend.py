"""Contract checks for complete WiM cloud-account deletion."""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "wim", "api"))

from user_data_backend import delete_cloud_account, make_json_safe


class DatetimeWithNanoseconds(datetime):
    """Matches Firestore's datetime subclass closely enough for this contract."""


cloud_timestamp = DatetimeWithNanoseconds(
    2026, 7, 29, 12, 24, 34, 447000, tzinfo=timezone.utc
)
safe_export = make_json_safe({
    "created": cloud_timestamp,
    "nested": {"sync_ts": cloud_timestamp},
    "events": [cloud_timestamp],
})
assert safe_export == {
    "created": "2026-07-29T12:24:34.447000+00:00",
    "nested": {"sync_ts": "2026-07-29T12:24:34.447000+00:00"},
    "events": ["2026-07-29T12:24:34.447000+00:00"],
}
assert json.loads(json.dumps(safe_export)) == safe_export


class FakeDocument:
    def __init__(self, owner, doc_id):
        self.owner = owner
        self.id = doc_id
        self.reference = self

    def delete(self):
        self.owner.remove(self)


class FakeQuery:
    def __init__(self, ids=()):
        self.documents = [FakeDocument(self, doc_id) for doc_id in ids]
        self.batch_size = 400

    def where(self, *args):
        assert args == ("uid", "==", "user-123")
        return self

    def limit(self, count):
        self.batch_size = count
        return self

    def stream(self):
        return list(self.documents[:self.batch_size])

    def remove(self, document):
        self.documents.remove(document)


class FakeUserReference(FakeDocument):
    def __init__(self, owner, doc_id, sessions):
        super().__init__(owner, doc_id)
        self.sessions = sessions

    def collection(self, name):
        assert name == "sessions"
        return self.sessions


class FakeUsersCollection:
    def __init__(self, sessions):
        self.documents = []
        self.user = FakeUserReference(self, "user-123", sessions)
        self.documents.append(self.user)

    def document(self, uid):
        assert uid == "user-123"
        return self.user

    def remove(self, document):
        self.documents.remove(document)


class FakeBatch:
    def __init__(self):
        self.documents = []

    def delete(self, reference):
        self.documents.append(reference)

    def commit(self):
        for document in self.documents:
            document.delete()


class FakeDb:
    def __init__(self):
        self.subscription_tokens = FakeQuery(("sub-1", "sub-2"))
        self.purchase_tokens = FakeQuery(("purchase-1",))
        self.sessions = FakeQuery(str(index) for index in range(805))
        self.users = FakeUsersCollection(self.sessions)

    def collection(self, name):
        return {
            "wim_subscription_tokens": self.subscription_tokens,
            "wim_purchase_tokens": self.purchase_tokens,
            "wim_users": self.users,
        }[name]

    def batch(self):
        return FakeBatch()


class FakeAuth:
    def __init__(self):
        self.deleted = []

    def delete_user(self, uid):
        self.deleted.append(uid)


db = FakeDb()
auth = FakeAuth()
deleted = delete_cloud_account(db, auth, "user-123")

assert deleted == {"tokens": 3, "sessions": 805}
assert not db.subscription_tokens.documents
assert not db.purchase_tokens.documents
assert not db.sessions.documents
assert not db.users.documents
assert auth.deleted == ["user-123"]

print("PASSED: WiM cloud export and account-deletion contracts")
