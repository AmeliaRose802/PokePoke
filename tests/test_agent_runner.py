"""Re-export agent_runner tests for coverage scoping.

The coverage pre-commit hook maps source files to test files by convention:
  src/pokepoke/foo.py → tests/test_foo.py

The actual tests live in tests/agents/test_agent_runner.py but the scoping
does not search subdirectories.  This file re-exports them so coverage runs
pick them up automatically.
"""

from tests.agents.test_agent_runner import *  # noqa: F401,F403
