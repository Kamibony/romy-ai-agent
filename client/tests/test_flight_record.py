import sys
import os
from unittest.mock import MagicMock

# Mocking hardware/OS specific modules before importing agent
sys.modules['uiautomation'] = MagicMock()
sys.modules['ctypes'] = MagicMock()
sys.modules['sounddevice'] = MagicMock()
sys.modules['scipy'] = MagicMock()
sys.modules['scipy.io'] = MagicMock()
sys.modules['scipy.io.wavfile'] = MagicMock()
sys.modules['pyautogui'] = MagicMock()
sys.modules['plyer'] = MagicMock()
sys.modules['winsound'] = MagicMock()
sys.modules['requests'] = MagicMock()
sys.modules['urllib3'] = MagicMock()
sys.modules['urllib3.util.retry'] = MagicMock()
sys.modules['requests.adapters'] = MagicMock()
sys.modules['pydantic'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['PIL.Image'] = MagicMock()
sys.modules['PIL.ImageDraw'] = MagicMock()
sys.modules['PIL.ImageFont'] = MagicMock()
sys.modules['numpy'] = MagicMock()

import unittest
from unittest.mock import patch, mock_open, call
import json
import base64
from datetime import datetime

# Add client/ to path to import agent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import agent
from agent import save_flight_record

class TestSaveFlightRecord(unittest.TestCase):
    def setUp(self):
        self.doc_id = "test_doc"
        self.iteration = 1
        self.payload = {"command": "test"}
        self.response = {"actions": []}
        self.action_executed = {"action": "WAIT"}
        self.screenshot_b64 = base64.b64encode(b"fake_image_data").decode('utf-8')
        self.system_state = {"state": "idle"}

    @patch("os.environ.get")
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("agent.datetime")
    @patch("agent.logging")
    def test_save_flight_record_happy_path(self, mock_logging, mock_datetime, mock_open_file, mock_makedirs, mock_env_get):
        # Setup
        mock_env_get.side_effect = lambda key: "/mock/appdata" if key == "LOCALAPPDATA" else None

        fixed_now = datetime(2023, 10, 27, 10, 0, 0)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.now.strftime.return_value = "20231027_100000"
        mock_datetime.now.isoformat.return_value = fixed_now.isoformat()

        # Execute
        save_flight_record(self.doc_id, self.iteration, self.payload, self.response, self.action_executed, self.screenshot_b64, self.system_state)

        # Verify makedirs
        expected_base_dir = "/mock/appdata/RomyAgentBrowserData"
        expected_user_dir = os.path.join(expected_base_dir, "flight_records", self.doc_id)
        mock_makedirs.assert_called_once_with(expected_user_dir, exist_ok=True)

        # Verify JSON file write call
        expected_json_path = os.path.join(expected_user_dir, f"record_{self.iteration}_20231027_100000.json")
        mock_open_file.assert_any_call(expected_json_path, "w", encoding="utf-8")

        # Verify Screenshot file write call
        expected_img_path = os.path.join(expected_user_dir, f"screenshot_{self.iteration}_20231027_100000.png")
        mock_open_file.assert_any_call(expected_img_path, "wb")

    @patch("os.environ.get")
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("agent.logging")
    def test_save_flight_record_no_localappdata(self, mock_logging, mock_open_file, mock_makedirs, mock_env_get):
        mock_env_get.return_value = None # No LOCALAPPDATA

        save_flight_record(self.doc_id, self.iteration, self.payload, self.response, self.action_executed, self.screenshot_b64)

        # It should use fallback path
        called_path = mock_makedirs.call_args[0][0]
        self.assertTrue(called_path.endswith(os.path.join("RomyAgentBrowserData", "flight_records", self.doc_id)))

    @patch("os.environ.get")
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("agent.logging")
    def test_save_flight_record_none_arguments(self, mock_logging, mock_open_file, mock_makedirs, mock_env_get):
        mock_env_get.return_value = "/tmp"

        save_flight_record(self.doc_id, self.iteration, None, None, None, None, None)

        # Should not crash and should use {} fallbacks
        self.assertTrue(mock_open_file.called)

        # Get the record data written to the mock file
        # json.dump(record_data, f, indent=2, ensure_ascii=False)
        # We can check that the written data contains empty dicts for the missing params
        # But json.dump calls f.write multiple times.

    @patch("os.environ.get")
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("agent.logging")
    def test_save_flight_record_screenshot_error(self, mock_logging, mock_open_file, mock_makedirs, mock_env_get):
        mock_env_get.return_value = "/tmp"
        invalid_b64 = "!!!not_base64!!!"

        save_flight_record(self.doc_id, self.iteration, self.payload, self.response, self.action_executed, invalid_b64)

        # Screenshot write should fail and log error
        found = False
        for call_args in mock_logging.error.call_args_list:
            if "Failed to save screenshot" in str(call_args[0][0]):
                found = True
                break
        self.assertTrue(found)

    @patch("os.environ.get")
    @patch("os.makedirs")
    @patch("agent.logging")
    def test_save_flight_record_exception_handling(self, mock_logging, mock_makedirs, mock_env_get):
        mock_env_get.return_value = "/tmp"
        mock_makedirs.side_effect = Exception("Disk full")

        # Should not raise exception
        save_flight_record(self.doc_id, self.iteration, self.payload, self.response, self.action_executed, self.screenshot_b64)

        mock_logging.error.assert_called_with("Failed to save flight record: Disk full")

if __name__ == "__main__":
    unittest.main()
