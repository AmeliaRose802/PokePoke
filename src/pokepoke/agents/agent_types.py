"""Centralized agent type registry for PokePoke orchestrator."""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentTypeDefinition:
    """Registry metadata for a known agent type."""

    key: str
    display_name: str
    emoji: str
    run_attr: str = ""
    aliases: tuple[str, ...] = ()
    always_show: bool = False

    def __post_init__(self) -> None:
        if not self.run_attr:
            object.__setattr__(self, "run_attr", f"{self.key}_agent_runs")


def _normalize_agent_key(value: str) -> str:
    """Normalize various agent identifiers to their slug form."""
    return value.strip().lower().replace(" ", "_")


AGENT_TYPES: dict[str, AgentTypeDefinition] = {
    "work": AgentTypeDefinition(
        key="work",
        display_name="Work",
        emoji="📋",
        always_show=True,
    ),
    "gate": AgentTypeDefinition(
        key="gate",
        display_name="Gate",
        emoji="🚪",
    ),
    "cleanup": AgentTypeDefinition(
        key="cleanup",
        display_name="Cleanup",
        emoji="🧹",
    ),
    "tech_debt": AgentTypeDefinition(
        key="tech_debt",
        display_name="Tech Debt",
        emoji="📊",
    ),
    "janitor": AgentTypeDefinition(
        key="janitor",
        display_name="Janitor",
        emoji="🧽",
    ),
    "backlog_cleanup": AgentTypeDefinition(
        key="backlog_cleanup",
        display_name="Backlog Cleanup",
        emoji="🗑️",
    ),
    "beta_tester": AgentTypeDefinition(
        key="beta_tester",
        display_name="Beta Tester",
        emoji="🧪",
    ),
    "code_review": AgentTypeDefinition(
        key="code_review",
        display_name="Code Review",
        emoji="🧐",
    ),
    "worktree_cleanup": AgentTypeDefinition(
        key="worktree_cleanup",
        display_name="Worktree Cleanup",
        emoji="🌲",
    ),
    "decomposition": AgentTypeDefinition(
        key="decomposition",
        display_name="Decomposition",
        emoji="🔀",
    ),
}


def _build_agent_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for key, agent in AGENT_TYPES.items():
        alias_values = {agent.key, _normalize_agent_key(agent.display_name)}
        alias_values.update(_normalize_agent_key(alias) for alias in agent.aliases)
        for alias in alias_values:
            aliases[alias] = key
    return aliases


_AGENT_TYPE_ALIASES = _build_agent_aliases()


def resolve_agent_type(agent_name: str) -> AgentTypeDefinition:
    """Resolve a human-friendly agent identifier to its registry entry."""
    normalized = _normalize_agent_key(agent_name)
    try:
        key = _AGENT_TYPE_ALIASES[normalized]
    except KeyError:
        raise ValueError(f"Unknown agent type: {agent_name}") from None
    return AGENT_TYPES[key]


def iter_agent_types() -> Iterable[AgentTypeDefinition]:
    """Yield agent definitions in registry order."""
    return AGENT_TYPES.values()


def _empty_agent_run_counts() -> dict[str, int]:
    """Create a zeroed-out agent run counts dict with all known agent keys."""
    return {key: 0 for key in AGENT_TYPES}
