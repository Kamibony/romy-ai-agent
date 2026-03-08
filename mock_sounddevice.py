import sys
from unittest.mock import MagicMock
sys.modules['sounddevice'] = MagicMock()
