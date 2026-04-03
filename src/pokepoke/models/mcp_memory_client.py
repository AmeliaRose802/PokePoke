"""MCP Memory Server client wrapper for persistent agent knowledge."""
import contextlib
import json
import logging
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntity:
    """Represents an entity in the knowledge graph."""
    name: str
    entity_type: str
    observations: list[str]


@dataclass
class MemoryRelation:
    """Represents a relation between entities."""
    from_entity: str
    to_entity: str
    relation_type: str


class MCPMemoryClient:
    """Client for interacting with MCP memory server via JSON-RPC over stdio."""

    def __init__(self, memory_file_path: str | Path | None = None, repo_root: Path | None = None) -> None:
        """Initialize memory client.

        Args:
            memory_file_path: Custom path to memory.jsonl file. If None, uses repo default.
            repo_root: Repository root path for scoping. If None, discovers from cwd.
        """
        self.repo_root = repo_root or self._discover_repo_root()

        if memory_file_path:
            self.memory_file = Path(memory_file_path)
        else:
            # Default: {repo_root}/.pokepoke/memory.jsonl
            self.memory_file = self.repo_root / ".pokepoke" / "memory.jsonl"

        # Ensure .pokepoke directory exists
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)

        # Repository slug for scoping entities
        self.repo_slug = self.repo_root.name

        logger.debug(f"Initialized MCP memory client: memory_file={self.memory_file}, repo={self.repo_slug}")

    def _discover_repo_root(self) -> Path:
        """Find repository root by walking up from cwd."""
        current = Path.cwd().resolve()
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        return Path.cwd()

    def _scoped_entity_name(self, entity_name: str) -> str:
        """Prefix entity name with repo slug for scoping."""
        if entity_name.startswith(f"{self.repo_slug}::"):
            return entity_name
        return f"{self.repo_slug}::{entity_name}"

    def _unscope_entity_name(self, scoped_name: str) -> str:
        """Remove repo slug prefix from entity name."""
        prefix = f"{self.repo_slug}::"
        if scoped_name.startswith(prefix):
            return scoped_name[len(prefix):]
        return scoped_name

    def _call_mcp_server(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call MCP memory server via JSON-RPC over stdio.

        Args:
            method: JSON-RPC method name (e.g., "tools/call")
            params: Method parameters

        Returns:
            Response result dict

        Raises:
            RuntimeError: If server call fails
        """
        request_id = str(uuid.uuid4())

        # Build JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }

        try:
            # Start MCP memory server process
            env = {"MEMORY_FILE_PATH": str(self.memory_file)}

            import os
            process = subprocess.Popen(
                ["npx", "-y", "@modelcontextprotocol/server-memory"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                env={**os.environ, **env}
            )

            try:
                # Send initialize request first (MCP protocol requirement)
                init_request = {
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "clientInfo": {"name": "pokepoke-memory-client", "version": "1.0.0"}
                    }
                }

                if process.stdin:
                    process.stdin.write(json.dumps(init_request) + "\n")
                    process.stdin.flush()

                # Read and discard initialize response
                if process.stdout:
                    init_response_line = process.stdout.readline()
                    logger.debug(f"Init response: {init_response_line[:100]}")

                # Send actual request
                if process.stdin:
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()

                # Read response - filter out non-JSON lines (server logs)
                response_data = None
                max_attempts = 50

                if process.stdout:
                    for _ in range(max_attempts):
                        line = process.stdout.readline()
                        if not line:
                            break

                        # Try to parse as JSON
                        try:
                            parsed = json.loads(line)
                            if parsed.get("jsonrpc") == "2.0":
                                response_data = parsed
                                break
                        except json.JSONDecodeError:
                            # Not JSON, skip
                            continue
            finally:
                # Always clean up the subprocess to prevent resource leaks
                if process.stdin:
                    with contextlib.suppress(OSError):
                        process.stdin.close()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

            if response_data is None:
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"No valid JSON-RPC response from MCP server. stderr: {stderr}")

            # Check for errors
            if "error" in response_data:
                error = response_data["error"]
                raise RuntimeError(f"MCP Error: {error.get('message', 'Unknown error')} (Code: {error.get('code', 'N/A')})")

            result: dict[str, Any] = response_data.get("result", {})
            return result

        except Exception as e:
            logger.error(f"Failed to call MCP memory server: {e}")
            raise RuntimeError(f"MCP memory server call failed: {e}") from e

    def store_fact(
        self,
        entity_name: str,
        entity_type: str,
        observations: list[str],
        timestamp: datetime | None = None
    ) -> bool:
        """Store a fact in the knowledge graph.

        Args:
            entity_name: Name of the entity (will be scoped to repository)
            entity_type: Type of entity (e.g., "file", "module", "pattern")
            observations: List of observation strings about the entity
            timestamp: Optional timestamp for decay tracking (default: now)

        Returns:
            True if successful, False otherwise
        """
        scoped_name = self._scoped_entity_name(entity_name)
        timestamp_iso = (timestamp or datetime.now()).isoformat()

        # Add timestamp to each observation for TTL tracking
        timestamped_observations = [f"[{timestamp_iso}] {obs}" for obs in observations]

        try:
            # Try to add observations to existing entity
            try:
                self._call_mcp_server(
                    "tools/call",
                    {
                        "name": "add_observations",
                        "arguments": {
                            "observations": [
                                {
                                    "entityName": scoped_name,
                                    "contents": timestamped_observations
                                }
                            ]
                        }
                    }
                )
                logger.info(f"Added observations to existing entity: {entity_name}")
                return True
            except RuntimeError as e:
                # Entity doesn't exist, create it
                if "doesn't exist" in str(e) or "does not exist" in str(e):
                    self._call_mcp_server(
                        "tools/call",
                        {
                            "name": "create_entities",
                            "arguments": {
                                "entities": [
                                    {
                                        "name": scoped_name,
                                        "entityType": entity_type,
                                        "observations": timestamped_observations
                                    }
                                ]
                            }
                        }
                    )
                    logger.info(f"Created new entity with observations: {entity_name}")
                    return True
                raise
        except Exception as e:
            logger.error(f"Failed to store fact for {entity_name}: {e}")
            return False

    def retrieve_facts(self, query: str) -> list[MemoryEntity]:
        """Retrieve facts matching a search query.

        Args:
            query: Search query string

        Returns:
            List of matching entities with observations
        """
        try:
            result = self._call_mcp_server(
                "tools/call",
                {
                    "name": "search_nodes",
                    "arguments": {"query": query}
                }
            )

            # Parse MCP protocol response: result = {"content": [{"type": "text", "text": "..."}]}
            # The actual data is nested inside content[0].text as a JSON string
            content = result.get("content", [])
            if not content or len(content) == 0:
                logger.debug("No content in MCP response")
                return []

            text_content = content[0].get("text", "")
            if not text_content:
                logger.debug("Empty text content in MCP response")
                return []

            # Parse the JSON string to get the actual entity data
            data = json.loads(text_content)

            entities = []
            for entity_data in data.get("entities", []):
                name = entity_data.get("name", "")
                # Only return entities from this repo
                if name.startswith(f"{self.repo_slug}::"):
                    entities.append(MemoryEntity(
                        name=self._unscope_entity_name(name),
                        entity_type=entity_data.get("entityType", "unknown"),
                        observations=entity_data.get("observations", [])
                    ))

            logger.debug(f"Retrieved {len(entities)} facts for query: {query}")
            return entities

        except Exception as e:
            logger.error(f"Failed to retrieve facts for query '{query}': {e}")
            return []

    def list_all_facts(self) -> list[MemoryEntity]:
        """List all facts in the knowledge graph for this repository.

        Returns:
            List of all entities with observations
        """
        try:
            result = self._call_mcp_server(
                "tools/call",
                {
                    "name": "read_graph",
                    "arguments": {}
                }
            )

            # Parse MCP protocol response: result = {"content": [{"type": "text", "text": "..."}]}
            # The actual data is nested inside content[0].text as a JSON string
            content = result.get("content", [])
            if not content or len(content) == 0:
                logger.debug("No content in MCP response")
                return []

            text_content = content[0].get("text", "")
            if not text_content:
                logger.debug("Empty text content in MCP response")
                return []

            # Parse the JSON string to get the actual entity data
            data = json.loads(text_content)

            entities = []
            for entity_data in data.get("entities", []):
                name = entity_data.get("name", "")
                # Only return entities from this repo
                if name.startswith(f"{self.repo_slug}::"):
                    entities.append(MemoryEntity(
                        name=self._unscope_entity_name(name),
                        entity_type=entity_data.get("entityType", "unknown"),
                        observations=entity_data.get("observations", [])
                    ))

            logger.debug(f"Listed {len(entities)} total facts for repo {self.repo_slug}")
            return entities

        except Exception as e:
            logger.error(f"Failed to list all facts: {e}")
            return []

    def delete_entity(self, entity_name: str) -> bool:
        """Delete an entity and its observations.

        Args:
            entity_name: Name of entity to delete

        Returns:
            True if successful, False otherwise
        """
        scoped_name = self._scoped_entity_name(entity_name)

        try:
            self._call_mcp_server(
                "tools/call",
                {
                    "name": "delete_entities",
                    "arguments": {"entityNames": [scoped_name]}
                }
            )
            logger.info(f"Deleted entity: {entity_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete entity {entity_name}: {e}")
            return False

    def clean_stale_observations(self, max_age_days: int) -> int:
        """Remove observations older than max_age_days.

        Args:
            max_age_days: Maximum age in days for observations

        Returns:
            Number of observations removed
        """
        cutoff_date = datetime.now().timestamp() - (max_age_days * 24 * 60 * 60)
        removed_count = 0

        try:
            # Get all entities for this repo
            entities = self.list_all_facts()

            for entity in entities:
                stale_observations = []
                fresh_observations = []

                for obs in entity.observations:
                    # Extract timestamp from observation
                    if obs.startswith("[") and "]" in obs:
                        timestamp_str = obs[1:obs.index("]")]
                        try:
                            obs_timestamp = datetime.fromisoformat(timestamp_str).timestamp()
                            if obs_timestamp < cutoff_date:
                                stale_observations.append(obs)
                            else:
                                fresh_observations.append(obs)
                        except ValueError:
                            # Can't parse timestamp, keep the observation
                            fresh_observations.append(obs)
                    else:
                        # No timestamp, keep the observation
                        fresh_observations.append(obs)

                # Delete stale observations
                if stale_observations:
                    scoped_name = self._scoped_entity_name(entity.name)
                    try:
                        self._call_mcp_server(
                            "tools/call",
                            {
                                "name": "delete_observations",
                                "arguments": {
                                    "deletions": [
                                        {
                                            "entityName": scoped_name,
                                            "observations": stale_observations
                                        }
                                    ]
                                }
                            }
                        )
                        removed_count += len(stale_observations)
                        logger.debug(f"Removed {len(stale_observations)} stale observations from {entity.name}")
                    except Exception as e:
                        logger.error(f"Failed to delete stale observations from {entity.name}: {e}")

                # If all observations were stale, delete the entity
                if not fresh_observations:
                    self.delete_entity(entity.name)

            logger.info(f"Cleaned {removed_count} stale observations (older than {max_age_days} days)")
            return removed_count

        except Exception as e:
            logger.error(f"Failed to clean stale observations: {e}")
            return 0
