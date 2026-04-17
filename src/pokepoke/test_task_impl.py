"""Core implementation for Test Task (PokePoke-yxd7e).

This module provides the core functionality for the test task,
which is used to validate the PokePoke orchestrator's ability
to handle parallel worker execution and validation.
"""


def perform_test_task() -> str:
    """Execute the test task core logic.

    This function serves as a minimal implementation to satisfy
    the "Implement core logic" requirement for the test task.
    It's designed to be simple and deterministic for testing purposes.

    Returns:
        str: Status message indicating task completion
    """
    return "test_task_complete"


def validate_test_task_completion(result: str) -> bool:
    """Validate that the test task completed successfully.

    Args:
        result: The result string from perform_test_task()

    Returns:
        bool: True if the result indicates successful completion
    """
    return result == "test_task_complete"
