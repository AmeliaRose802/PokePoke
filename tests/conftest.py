"""Test configuration for PokePoke tests."""
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# Fix Windows encoding issues with emojis in test output
# Set environment variable before any imports that might use stdout
if sys.platform == 'win32':
    # Set console code page to UTF-8 for Windows
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

