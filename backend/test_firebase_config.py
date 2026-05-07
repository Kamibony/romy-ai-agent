import unittest
from unittest.mock import MagicMock, patch, ANY
import os
import sys
import importlib

# 1. Setup the mocks
mock_firebase_admin = MagicMock()
mock_firebase_admin._apps = {}

mock_credentials = MagicMock()
class Base:
    pass
mock_credentials.Base = Base
mock_firebase_admin.credentials = mock_credentials

# 2. Inject mocks into sys.modules
sys.modules['firebase_admin'] = mock_firebase_admin
sys.modules['firebase_admin.credentials'] = mock_credentials

# 3. Import the actual module under test
# We use importlib to ensure we get a fresh import if it was somehow loaded before
import firebase_config
importlib.reload(firebase_config)

class TestFirebaseConfig(unittest.TestCase):
    def setUp(self):
        # Reset mocks and _apps before each test
        mock_firebase_admin.reset_mock()
        mock_firebase_admin._apps = {}
        mock_firebase_admin.initialize_app.side_effect = None

        # Default mock app
        self.mock_app = MagicMock()
        mock_firebase_admin.initialize_app.return_value = self.mock_app
        mock_firebase_admin.get_app.return_value = self.mock_app

    def test_initialize_firebase_local_no_creds(self):
        """Test local initialization when GOOGLE_APPLICATION_CREDENTIALS is missing."""
        with patch.dict(os.environ, {"LOCAL_DEV": "True"}, clear=True):
            # Ensure GOOGLE_APPLICATION_CREDENTIALS is not in environ
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

            app = firebase_config.initialize_firebase()

            mock_firebase_admin.initialize_app.assert_called_once()
            args, kwargs = mock_firebase_admin.initialize_app.call_args
            # Verify it used MockCredential
            self.assertIsInstance(args[0], firebase_config.MockCredential)
            self.assertEqual(kwargs['options']['projectId'], 'demo-project')
            self.assertEqual(app, self.mock_app)

    def test_initialize_firebase_production_success(self):
        """Test successful ADC initialization in production mode."""
        with patch.dict(os.environ, {"LOCAL_DEV": "False"}, clear=True):
            app = firebase_config.initialize_firebase()

            mock_firebase_admin.initialize_app.assert_called_once_with()
            self.mock_app.credential.get_credential.assert_called_once()
            self.assertEqual(app, self.mock_app)

    def test_initialize_firebase_production_failure(self):
        """Test ADC failure in production mode (should return None after logging)."""
        with patch.dict(os.environ, {"LOCAL_DEV": "False"}, clear=True):
            mock_firebase_admin.initialize_app.side_effect = Exception("ADC failed")

            app = firebase_config.initialize_firebase()

            self.assertIsNone(app)

    def test_initialize_firebase_local_fallback(self):
        """Test fallback to mock credentials in local mode when ADC fails."""
        with patch.dict(os.environ, {"LOCAL_DEV": "True", "GOOGLE_APPLICATION_CREDENTIALS": "/some/path"}, clear=True):
            mock_app_mocked = MagicMock()

            # First call fails (ADC), second call succeeds (Mock)
            def side_effect(*args, **kwargs):
                if not args or not isinstance(args[0], firebase_config.MockCredential):
                    # Simulate that initialize_app might have registered the app before failing
                    mock_firebase_admin._apps["[DEFAULT]"] = MagicMock()
                    raise Exception("ADC failed")
                return mock_app_mocked

            mock_firebase_admin.initialize_app.side_effect = side_effect

            app = firebase_config.initialize_firebase()

            # Should have called initialize_app twice
            self.assertEqual(mock_firebase_admin.initialize_app.call_count, 2)
            # Check that [DEFAULT] was cleaned up from _apps after failure
            self.assertNotIn("[DEFAULT]", mock_firebase_admin._apps)
            self.assertEqual(app, mock_app_mocked)

    def test_initialize_firebase_already_initialized(self):
        """Test that it returns the existing app if already initialized."""
        mock_firebase_admin._apps = {"[DEFAULT]": self.mock_app}

        app = firebase_config.initialize_firebase()

        mock_firebase_admin.get_app.assert_called_once()
        self.assertEqual(app, self.mock_app)
        mock_firebase_admin.initialize_app.assert_not_called()

if __name__ == '__main__':
    unittest.main()
