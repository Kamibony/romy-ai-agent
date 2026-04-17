import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Mock firebase_admin before importing db
mock_firestore = MagicMock()
mock_firebase_admin = MagicMock()
mock_firebase_admin.firestore = mock_firestore

sys.modules['firebase_admin'] = mock_firebase_admin
sys.modules['firebase_admin.firestore'] = mock_firestore

# Now import db
import db

class TestGetTaskSession(unittest.TestCase):
    def setUp(self):
        # Reset mocks before each test
        mock_firestore.reset_mock()
        mock_firestore.client.side_effect = None
        mock_firestore.client.return_value = MagicMock()

    def test_get_task_session_exists(self):
        # Setup mock
        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db

        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"id": "test_id", "status": "pending"}
        mock_doc_ref.get.return_value = mock_doc

        # Execute
        result = db.get_task_session("test_id")

        # Assert
        self.assertEqual(result, {"id": "test_id", "status": "pending"})
        mock_db.collection.assert_called_with("task_sessions")
        mock_db.collection.return_value.document.assert_called_with("test_id")

    def test_get_task_session_not_exists(self):
        # Setup mock
        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db

        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref

        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_doc_ref.get.return_value = mock_doc

        # Execute
        result = db.get_task_session("non_existent")

        # Assert
        self.assertIsNone(result)

    def test_get_task_session_exception(self):
        # Setup mock
        mock_firestore.client.side_effect = Exception("Firestore error")

        # Execute
        result = db.get_task_session("any_id")

        # Assert
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
