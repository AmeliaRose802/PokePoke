"""Re-export gate_rejection_tracker tests for coverage scoping.

The coverage pre-commit hook maps source files to test files by convention:
  src/pokepoke/foo.py → tests/test_foo.py

The actual tests live in tests/models/ but the scoping does not search
subdirectories.  This file re-exports them so coverage runs pick them up
automatically.
"""

from tests.models.test_gate_rejection_stats import *  # noqa: F401,F403
