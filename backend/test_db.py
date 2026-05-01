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

class TestUpdateTaskSession(unittest.TestCase):
    def setUp(self):
        mock_firestore.reset_mock()
        mock_firestore.client.side_effect = None
        mock_firestore.client.return_value = MagicMock()

    def test_update_task_session_success(self):
        # Setup mock
        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref

        updates = {"status": "completed"}

        # Execute
        db.update_task_session("test_id", updates)

        # Assert
        mock_doc_ref.set.assert_called_with(updates, merge=True)

    def test_update_task_session_exception(self):
        # Setup mock
        mock_firestore.client.side_effect = Exception("Firestore error")

        # Execute & Assert (should not raise exception)
        db.update_task_session("any_id", {})

class TestCreateTaskSession(unittest.TestCase):
    def setUp(self):
        mock_firestore.reset_mock()
        mock_firestore.client.side_effect = None
        mock_firestore.client.return_value = MagicMock()

    def test_create_task_session_new(self):
        # Setup mock
        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref

        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_doc_ref.get.return_value = mock_doc

        # Execute
        db.create_task_session("new_session", "Hello")

        # Assert
        mock_doc_ref.set.assert_called_once()
        args, kwargs = mock_doc_ref.set.call_args
        self.assertEqual(args[0]["thread_history"], "Hello")
        self.assertEqual(args[0]["status"], "pending")
        self.assertEqual(args[0]["current_step"], 0)

    def test_create_task_session_exists(self):
        # Setup mock
        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc_ref.get.return_value = mock_doc

        # Execute
        db.create_task_session("existing_session")

        # Assert
        mock_doc_ref.set.assert_not_called()

    def test_create_task_session_exception(self):
        # Setup mock
        mock_firestore.client.side_effect = Exception("Firestore error")

        # Execute & Assert (should not raise exception)
        db.create_task_session("any_id")

class TestCheckUserLicense(unittest.TestCase):
    def setUp(self):
        mock_firestore.reset_mock()
        mock_firestore.client.side_effect = None
        mock_firestore.client.return_value = MagicMock()

    def test_check_user_license_local_dev(self):
        with patch.dict(os.environ, {"LOCAL_DEV": "True"}):
            self.assertTrue(db.check_user_license("local-dev-uid"))

        with patch.dict(os.environ, {"ROMY_TEST_MODE": "1"}):
            self.assertTrue(db.check_user_license("local-dev-uid"))

    def test_check_user_license_admin_role(self):
        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"role": "ADMIN"}
        mock_doc_ref.get.return_value = mock_doc

        self.assertTrue(db.check_user_license("user123"))

    def test_check_user_license_partner_role(self):
        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"role": "partner"}
        mock_doc_ref.get.return_value = mock_doc

        self.assertTrue(db.check_user_license("user123"))

    def test_check_user_license_active_true(self):
        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"is_active": True, "role": "user"}
        mock_doc_ref.get.return_value = mock_doc

        self.assertTrue(db.check_user_license("user123"))

    def test_check_user_license_inactive(self):
        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref

        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"is_active": False, "role": "user"}
        mock_doc_ref.get.return_value = mock_doc

        self.assertFalse(db.check_user_license("user123"))

    def test_check_user_license_not_exists(self):
        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref

        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_doc_ref.get.return_value = mock_doc

        self.assertFalse(db.check_user_license("user123"))

    def test_check_user_license_exception(self):
        mock_firestore.client.side_effect = Exception("Firestore error")
        self.assertFalse(db.check_user_license("user123"))

if __name__ == '__main__':
    unittest.main()
