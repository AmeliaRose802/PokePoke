"""Structured outcome model for work agents."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

WORK_AGENT_OUTCOME_STATUSES = frozenset({
    "completed", "blocked", "needs_clarification", "too_large",
})


@dataclass
class WorkAgentOutcome:
    """Structured outcome returned by a work agent at the end of its session.

    Work agents are instructed to emit a JSON block with this schema so the
    orchestrator can make intelligent decisions (fail-fast on blocked/too_large
    items, pass structured context to the gate agent, etc.).
    """
    status: str  # completed | blocked | needs_clarification | too_large
    reason: str = ""
    files_modified: list[str] = field(default_factory=list)
    tests_added: list[str] = field(default_factory=list)
    suggested_split: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in WORK_AGENT_OUTCOME_STATUSES:
            raise ValueError(
                f"Invalid work agent outcome status: {self.status!r}. "
                f"Must be one of {sorted(WORK_AGENT_OUTCOME_STATUSES)}"
            )


def parse_work_agent_outcome(output: str | None) -> WorkAgentOutcome | None:
    """Extract a structured WorkAgentOutcome from raw agent output.

    Looks for the *last* fenced JSON block whose ``status`` field matches a
    known work-agent outcome status.  Returns ``None`` when no valid outcome
    block is found (the agent may not have emitted one).
    """
    if not output:
        return None

    json_blocks = list(re.finditer(
        r'```[jJ][sS][oO][nN]\s*(\{.*?\})\s*```', output, re.DOTALL,
    ))
    for match in reversed(json_blocks):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        status = data.get("status")
        if status not in WORK_AGENT_OUTCOME_STATUSES:
            continue
        return WorkAgentOutcome(
            status=status,
            reason=str(data.get("reason", "")),
            files_modified=_str_list(data.get("files_modified")),
            tests_added=_str_list(data.get("tests_added")),
            suggested_split=_str_list(data.get("suggested_split")),
        )
    return None


def _str_list(value: Any) -> list[str]:
    """Coerce *value* to a ``list[str]``, returning [] for non-list inputs."""
    if isinstance(value, list):
        return [str(v) for v in value]
    return []
