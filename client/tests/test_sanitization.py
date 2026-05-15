import unittest
import os
import sys
from unittest.mock import MagicMock

# Mocking or setting env to avoid side effects during import
os.environ["ROMY_TEST_MODE"] = "1"

# Mock modules that are missing or cause issues during import
mocks = [
    "logger_setup",
    "requests",
    "requests.adapters",
    "urllib3.util.retry",
    "uiautomation",
    "ctypes",
    "sounddevice",
    "pyautogui",
    "plyer",
    "winsound",
    "config",
    "local_bridge",
    "pydantic",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "scipy",
    "scipy.io",
    "scipy.io.wavfile",
    "numpy",
    "pygetwindow"
]

for m in mocks:
    sys.modules[m] = MagicMock()

# Specifically handle some things that might be used at top level
sys.modules["config"].STEALTH_MODE = False
sys.modules["config"].GET_COMMAND_ENDPOINT = "http://mock"

from client.agent import sanitize_extracted_parameter

class TestSanitization(unittest.TestCase):
    def test_non_string_input(self):
        self.assertEqual(sanitize_extracted_parameter(123), 123)
        self.assertEqual(sanitize_extracted_parameter(None), None)
        self.assertEqual(sanitize_extracted_parameter(["a"]), ["a"])

    def test_url_sanitization(self):
        self.assertEqual(sanitize_extracted_parameter("https://example.com/.", "url"), "https://example.com/")
        self.assertEqual(sanitize_extracted_parameter("https://example.com/???", "url"), "https://example.com/")
        self.assertEqual(sanitize_extracted_parameter("www.test.com;;;", "url"), "www.test.com")
        self.assertEqual(sanitize_extracted_parameter("  http://google.com  ", "url"), "http://google.com")

    def test_text_email_sanitization(self):
        self.assertEqual(sanitize_extracted_parameter("user@example.com.", "text"), "user@example.com")
        self.assertEqual(sanitize_extracted_parameter("contact@domain.co.uk!", "text"), "contact@domain.co.uk")

    def test_text_url_like_sanitization(self):
        self.assertEqual(sanitize_extracted_parameter("www.example.com,", "text"), "www.example.com")
        self.assertEqual(sanitize_extracted_parameter("http://localhost:8080\"", "text"), "http://localhost:8080")

    def test_numeric_sanitization(self):
        self.assertEqual(sanitize_extracted_parameter("12345.", "text"), "12345")
        self.assertEqual(sanitize_extracted_parameter("1,000;", "text"), "1,000")
        self.assertEqual(sanitize_extracted_parameter("1 000 000!", "text"), "1 000 000")
        # Ensure it doesn't strip if not ending in punctuation (regex match check)
        self.assertEqual(sanitize_extracted_parameter("12345", "text"), "12345")

    def test_short_search_terms(self):
        self.assertEqual(sanitize_extracted_parameter("apple.", "text"), "apple")
        self.assertEqual(sanitize_extracted_parameter("red apple!", "text"), "red apple")
        self.assertEqual(sanitize_extracted_parameter("big red apple;", "text"), "big red apple")

    def test_abbreviation_exclusion(self):
        self.assertEqual(sanitize_extracted_parameter("Mr.", "text"), "Mr.")
        self.assertEqual(sanitize_extracted_parameter("Inc.", "text"), "Inc.")
        self.assertEqual(sanitize_extracted_parameter("Dr.", "text"), "Dr.")
        self.assertEqual(sanitize_extracted_parameter("ave.", "text"), "ave.")

    def test_long_text_no_strip(self):
        # More than 3 words should not be stripped unless it matches other rules
        self.assertEqual(sanitize_extracted_parameter("this is a long sentence.", "text"), "this is a long sentence.")
        self.assertEqual(sanitize_extracted_parameter("one two three four!", "text"), "one two three four!")

    def test_mixed_trailing_punctuation(self):
        self.assertEqual(sanitize_extracted_parameter("test.?!", "text"), "test")
        self.assertEqual(sanitize_extracted_parameter("https://example.com/path/.\"'", "url"), "https://example.com/path/")

if __name__ == '__main__':
    unittest.main()
