import unittest
from unittest.mock import patch, MagicMock
from lavrentiy.firestore_publisher import publish_profile_to_firestore
import lavrentiy.firestore_publisher as fp

class TestFirestorePublisher(unittest.TestCase):
    def setUp(self):
        fp._last_payload_hash = None

    @patch('lavrentiy.firestore_publisher.firestore')
    def test_publish_success(self, mock_firestore):
        mock_client = MagicMock()
        mock_firestore.Client.return_value = mock_client
        mock_firestore.SERVER_TIMESTAMP = 'mock_timestamp'

        uid = "test-uid-12345"
        tw = ["apple", "banana"]
        ow = {"/a/": 0.5, "/b/": 0.8}
        cp = {"avoidance_pairs": {}}

        result = publish_profile_to_firestore(uid, tw, ow, cp)
        self.assertTrue(result)

        expected_payload = {
            "trigger_words": tw,
            "onset_weights": ow,
            "covert_profile": cp,
            "updated_at": 'mock_timestamp'
        }
        mock_client.collection.assert_called_with("wim_users")
        mock_client.collection().document.assert_called_with(uid)
        mock_client.collection().document().set.assert_called_with(expected_payload, merge=True)

    @patch('lavrentiy.firestore_publisher.firestore')
    def test_publish_idempotency(self, mock_firestore):
        mock_client = MagicMock()
        mock_firestore.Client.return_value = mock_client
        mock_firestore.SERVER_TIMESTAMP = 'mock_timestamp'

        uid = "test-uid-12345"
        tw = ["apple"]
        ow = {}
        cp = {}

        # First call should write
        res1 = publish_profile_to_firestore(uid, tw, ow, cp)
        self.assertTrue(res1)
        self.assertEqual(mock_client.collection().document().set.call_count, 1)

        # Second call with same data shouldn't write
        res2 = publish_profile_to_firestore(uid, tw, ow, cp)
        self.assertTrue(res2)
        self.assertEqual(mock_client.collection().document().set.call_count, 1)

if __name__ == '__main__':
    unittest.main()
