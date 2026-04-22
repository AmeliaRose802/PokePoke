"""Helpers for decomposition output parsing and dependency graph wiring."""

import json
import re
from typing import Any


def extract_first_json_array(output: str) -> list[object] | None:
    """Extract the first valid JSON array from SDK output text."""
    decoder = json.JSONDecoder()

    fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", output, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        candidate = fenced_match.group(1).strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return parsed

    for start_index, char in enumerate(output):
        if char != "[":
            continue
        try:
            parsed, _ = decoder.raw_decode(output[start_index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed

    return None


def normalize_dependency_titles(raw_depends_on: object) -> list[str]:
    """Normalize subtask dependency titles from SDK output."""
    if isinstance(raw_depends_on, str):
        raw_depends_on = [raw_depends_on]
    if not isinstance(raw_depends_on, list):
        return []

    depends_on: list[str] = []
    seen: set[str] = set()
    for dependency in raw_depends_on:
        dependency_title = str(dependency).strip()[:80]
        if not dependency_title:
            continue
        key = dependency_title.lower()
        if key in seen:
            continue
        seen.add(key)
        depends_on.append(dependency_title)
    return depends_on


def filter_known_dependencies(subtasks: list[Any], item_id: str, logger: Any) -> None:
    """Drop unknown/self dependencies from subtask definitions in-place."""
    available_titles = {subtask.title.lower().strip() for subtask in subtasks}
    for subtask in subtasks:
        filtered_dependencies: list[str] = []
        for dependency in subtask.depends_on:
            dependency_key = dependency.lower().strip()
            if dependency_key == subtask.title.lower().strip():
                logger.warning(
                    "Skipping self-dependency for subtask '%s' in %s",
                    subtask.title, item_id,
                )
                continue
            if dependency_key not in available_titles:
                logger.warning(
                    "Skipping unknown dependency '%s' for subtask '%s' in %s",
                    dependency, subtask.title, item_id,
                )
                continue
            filtered_dependencies.append(dependency)
        subtask.depends_on = filtered_dependencies


def build_dependency_edges(created_subtasks: list[tuple[str, Any]], item_id: str, logger: Any) -> list[tuple[str, str]]:
    """Build (blocker_id, blocked_id) edges for created subtasks."""
    title_to_child_id = {
        subtask.title.lower().strip(): child_id
        for child_id, subtask in created_subtasks
    }

    edges: list[tuple[str, str]] = []
    for blocked_id, subtask in created_subtasks:
        for dependency in subtask.depends_on:
            blocker_id = title_to_child_id.get(dependency.lower().strip())
            if blocker_id is None:
                logger.warning(
                    "Dependency target '%s' was not created for subtask '%s' in %s",
                    dependency, subtask.title, item_id,
                )
                continue
            edges.append((blocker_id, blocked_id))
    return edges
