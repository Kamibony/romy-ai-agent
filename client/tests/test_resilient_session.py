import unittest
from unittest.mock import MagicMock
import sys

# The test class
class TestResilientSession(unittest.TestCase):

    def setUp(self):
        # Save original sys.modules to restore later
        self.original_modules = sys.modules.copy()

        # Mock ALL problematic imports in client.agent before importing it
        # This is necessary because client.agent has top-level code that starts threads,
        # checks Windows-specific DPI settings, and imports many heavy libraries.
        for mod in [
            'uiautomation', 'sounddevice', 'pyautogui', 'plyer',
            'winsound', 'config', 'cv2', 'numpy', 'pyperclip', 'PIL',
            'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont', 'scipy', 'scipy.io.wavfile',
            'pydantic', 'local_bridge', 'requests', 'requests.adapters',
            'urllib3', 'urllib3.util', 'urllib3.util.retry'
        ]:
            sys.modules[mod] = MagicMock()

        # Special handling for pydantic and others to allow import of agent.py
        sys.modules['pydantic'].BaseModel = MagicMock
        sys.modules['pydantic'].ValidationError = type('ValidationError', (Exception,), {})

    def tearDown(self):
        # Restore sys.modules to avoid side effects on other tests
        sys.modules.clear()
        sys.modules.update(self.original_modules)

    def test_get_resilient_session(self):
        """Test that get_resilient_session correctly configures the session."""
        # Now import agent - it will use our sys.modules mocks
        from client import agent

        # Reset global session to ensure we test initialization
        agent._GLOBAL_SESSION = None

        # Call the function
        session = agent.get_resilient_session()

        # Access the mocks through sys.modules to verify interactions
        mock_session_cls = sys.modules['requests'].Session
        mock_retry_cls = sys.modules['urllib3.util.retry'].Retry
        mock_adapter_cls = sys.modules['requests.adapters'].HTTPAdapter

        # 1. Verify Session creation
        mock_session_cls.assert_called_once()
        self.assertEqual(session, mock_session_cls.return_value)

        # 2. Verify Retry configuration matches the implementation in agent.py
        mock_retry_cls.assert_called_once_with(
            total=5,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PATCH", "PUT", "DELETE"]
        )

        # 3. Verify Adapter configuration (uses the retry strategy)
        mock_adapter_cls.assert_called_once_with(max_retries=mock_retry_cls.return_value)

        # 4. Verify Mounting for both HTTP and HTTPS
        session.mount.assert_any_call("https://", mock_adapter_cls.return_value)
        session.mount.assert_any_call("http://", mock_adapter_cls.return_value)
        self.assertEqual(session.mount.call_count, 2)

        # 5. Verify Singleton behavior (subsequent calls return the same object)
        session2 = agent.get_resilient_session()
        self.assertIs(session, session2)
        self.assertEqual(mock_session_cls.call_count, 1)

if __name__ == '__main__':
    unittest.main()
