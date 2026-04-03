"""Tests for MCP memory client integration."""
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from pokepoke.models.mcp_memory_client import MCPMemoryClient, MemoryEntity


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.Popen for MCP server calls."""
    with patch('pokepoke.models.mcp_memory_client.subprocess.Popen') as mock:
        yield mock


@pytest.fixture
def temp_memory_file(tmp_path):
    """Create a temporary memory file path."""
    return tmp_path / ".pokepoke" / "memory.jsonl"


@pytest.fixture
def memory_client(tmp_path, temp_memory_file):
    """Create a memory client with temp file."""
    return MCPMemoryClient(memory_file_path=temp_memory_file, repo_root=tmp_path)


class TestMCPMemoryClientInitialization:
    """Tests for memory client initialization."""

    def test_init_with_custom_path(self, tmp_path):
        """Memory client initializes with custom file path."""
        custom_path = tmp_path / "custom_memory.jsonl"
        client = MCPMemoryClient(memory_file_path=custom_path, repo_root=tmp_path)

        assert client.memory_file == custom_path
        assert client.repo_root == tmp_path
        assert client.repo_slug == tmp_path.name

    def test_init_creates_pokepoke_directory(self, tmp_path):
        """Memory client creates .pokepoke directory if missing."""
        pokepoke_dir = tmp_path / ".pokepoke"
        assert not pokepoke_dir.exists()

        MCPMemoryClient(repo_root=tmp_path)

        assert pokepoke_dir.exists()
        assert pokepoke_dir.is_dir()

    def test_init_default_path(self, tmp_path):
        """Memory client uses default path when none specified."""
        client = MCPMemoryClient(repo_root=tmp_path)

        expected_path = tmp_path / ".pokepoke" / "memory.jsonl"
        assert client.memory_file == expected_path

    def test_repo_slug_generation(self, tmp_path):
        """Repo slug is correctly extracted from path."""
        repo_name = tmp_path.name
        client = MCPMemoryClient(repo_root=tmp_path)

        assert client.repo_slug == repo_name

    def test_discover_repo_root_with_git(self, tmp_path):
        """Discovers repo root by finding .git directory."""
        # Create a .git directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Create nested directory
        nested_dir = tmp_path / "src" / "models"
        nested_dir.mkdir(parents=True)

        # Create client from nested directory (mock cwd)
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(nested_dir)
            client = MCPMemoryClient(memory_file_path=tmp_path / "memory.jsonl")

            assert client.repo_root == tmp_path
        finally:
            os.chdir(old_cwd)


class TestEntityNameScoping:
    """Tests for repository-scoped entity names."""

    def test_scoped_entity_name(self, memory_client):
        """Entity names are prefixed with repo slug."""
        entity_name = "workflow.py"
        scoped = memory_client._scoped_entity_name(entity_name)

        assert scoped.startswith(memory_client.repo_slug + "::")
        assert entity_name in scoped

    def test_scoped_entity_name_idempotent(self, memory_client):
        """Scoping is idempotent - doesn't double-prefix."""
        entity_name = "workflow.py"
        scoped_once = memory_client._scoped_entity_name(entity_name)
        scoped_twice = memory_client._scoped_entity_name(scoped_once)

        assert scoped_once == scoped_twice

    def test_unscope_entity_name(self, memory_client):
        """Unscoping removes repo slug prefix."""
        entity_name = "workflow.py"
        scoped = memory_client._scoped_entity_name(entity_name)
        unscoped = memory_client._unscope_entity_name(scoped)

        assert unscoped == entity_name

    def test_unscope_unscoped_name(self, memory_client):
        """Unscoping unscoped name returns unchanged."""
        entity_name = "workflow.py"
        unscoped = memory_client._unscope_entity_name(entity_name)

        assert unscoped == entity_name


class TestStoreFact:
    """Tests for storing facts in memory."""

    def test_store_fact_success(self, memory_client, mock_subprocess):
        """Successfully stores a fact with observations."""
        # Mock successful MCP server response
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        # Simulate init response
        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}

        # Simulate create_entities success
        create_response = {"jsonrpc": "2.0", "id": "test-id", "result": {"created": 1}}

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(create_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        result = memory_client.store_fact(
            entity_name="workflow.py",
            entity_type="file",
            observations=["Main orchestration loop", "Handles work item selection"]
        )

        assert result is True
        assert mock_subprocess.called

    def test_store_fact_adds_timestamp(self, memory_client, mock_subprocess):
        """Observations are timestamped when stored."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}
        create_response = {"jsonrpc": "2.0", "id": "test-id", "result": {"created": 1}}

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(create_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        observation = "Test observation"
        memory_client.store_fact(
            entity_name="test_entity",
            entity_type="test",
            observations=[observation]
        )

        # Check that stdin.write was called with timestamped observation
        write_calls = [call[0][0] for call in mock_process.stdin.write.call_args_list]
        # Second write call should contain the actual request (first is init)
        if len(write_calls) > 1:
            request_json = write_calls[1]
            request = json.loads(request_json)

            # Check the tool call structure
            assert request["method"] == "tools/call"
            # The observation should be timestamped somewhere in the request
            request_str = json.dumps(request)
            assert observation in request_str
            assert "[" in request_str  # Timestamp bracket present

    def test_store_fact_server_error(self, memory_client, mock_subprocess):
        """Handles server errors gracefully."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}
        error_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "error": {"code": -1, "message": "Server error"}
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(error_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        result = memory_client.store_fact(
            entity_name="test",
            entity_type="test",
            observations=["test"]
        )

        assert result is False

    def test_store_fact_updates_existing_entity(self, memory_client, mock_subprocess):
        """Successfully updates existing entity with add_observations."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}
        # First call to add_observations succeeds (entity exists)
        add_response = {"jsonrpc": "2.0", "id": "test-id", "result": {"added": 1}}

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(add_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        result = memory_client.store_fact(
            entity_name="existing_entity",
            entity_type="file",
            observations=["Additional observation"]
        )

        assert result is True

    def test_store_fact_creates_after_add_fails(self, memory_client, mock_subprocess):
        """Creates entity when add_observations fails with doesn't exist."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}
        # First call fails because entity doesn't exist
        error_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "error": {"code": -1, "message": "Entity doesn't exist"}
        }
        # Second call creates the entity
        create_response = {"jsonrpc": "2.0", "id": "test-id", "result": {"created": 1}}

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),  # First init
            json.dumps(error_response),  # add_observations fails
            json.dumps(init_response),  # Second init for create
            json.dumps(create_response)  # create_entities succeeds
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        result = memory_client.store_fact(
            entity_name="new_entity",
            entity_type="file",
            observations=["New observation"]
        )

        assert result is True


class TestRetrieveFacts:
    """Tests for retrieving facts from memory."""

    def test_retrieve_facts_success(self, memory_client, mock_subprocess):
        """Successfully retrieves matching facts."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}

        # MCP protocol response format: entities are nested in content[0].text as JSON
        entities_data = {
            "entities": [
                {
                    "name": f"{memory_client.repo_slug}::workflow.py",
                    "entityType": "file",
                    "observations": ["[2026-01-01T00:00:00] Main loop", "[2026-01-01T00:00:00] Handles items"]
                }
            ]
        }
        search_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(entities_data)
                    }
                ]
            }
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(search_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        results = memory_client.retrieve_facts("workflow")

        assert len(results) == 1
        assert results[0].name == "workflow.py"
        assert results[0].entity_type == "file"
        assert len(results[0].observations) == 2

    def test_retrieve_facts_filters_other_repos(self, memory_client, mock_subprocess):
        """Only returns facts from current repository."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}

        # MCP protocol response format: entities are nested in content[0].text as JSON
        entities_data = {
            "entities": [
                {
                    "name": f"{memory_client.repo_slug}::workflow.py",
                    "entityType": "file",
                    "observations": ["Our repo"]
                },
                {
                    "name": "other_repo::workflow.py",
                    "entityType": "file",
                    "observations": ["Other repo"]
                }
            ]
        }
        search_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(entities_data)
                    }
                ]
            }
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(search_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        results = memory_client.retrieve_facts("workflow")

        # Should only return the entity from our repo
        assert len(results) == 1
        assert results[0].name == "workflow.py"

    def test_retrieve_facts_empty_result(self, memory_client, mock_subprocess):
        """Returns empty list when no facts match."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}

        # MCP protocol response format: entities are nested in content[0].text as JSON
        entities_data = {"entities": []}
        search_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(entities_data)
                    }
                ]
            }
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(search_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        results = memory_client.retrieve_facts("nonexistent")

        assert results == []

    def test_retrieve_facts_no_content(self, memory_client, mock_subprocess):
        """Returns empty list when response has no content."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}
        search_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {"content": []}
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(search_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        results = memory_client.retrieve_facts("query")

        assert results == []

    def test_retrieve_facts_empty_text(self, memory_client, mock_subprocess):
        """Returns empty list when text content is empty."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}
        search_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {
                "content": [{"type": "text", "text": ""}]
            }
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(search_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        results = memory_client.retrieve_facts("query")

        assert results == []

    def test_retrieve_facts_server_error(self, memory_client, mock_subprocess):
        """Returns empty list on server error."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}
        error_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "error": {"code": -1, "message": "Server error"}
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(error_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        results = memory_client.retrieve_facts("query")

        assert results == []


class TestListAllFacts:
    """Tests for listing all facts."""

    def test_list_all_facts_success(self, memory_client, mock_subprocess):
        """Successfully lists all facts for repository."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}

        entities_data = {
            "entities": [
                {
                    "name": f"{memory_client.repo_slug}::entity1",
                    "entityType": "file",
                    "observations": ["obs1"]
                },
                {
                    "name": f"{memory_client.repo_slug}::entity2",
                    "entityType": "module",
                    "observations": ["obs2"]
                }
            ]
        }
        read_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(entities_data)
                    }
                ]
            }
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(read_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        results = memory_client.list_all_facts()

        assert len(results) == 2
        assert results[0].name == "entity1"
        assert results[1].name == "entity2"

    def test_list_all_facts_error(self, memory_client, mock_subprocess):
        """Returns empty list on error."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}
        error_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "error": {"code": -1, "message": "Error"}
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(error_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        results = memory_client.list_all_facts()

        assert results == []


class TestDeleteEntity:
    """Tests for deleting entities."""

    def test_delete_entity_success(self, memory_client, mock_subprocess):
        """Successfully deletes an entity."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}
        delete_response = {"jsonrpc": "2.0", "id": "test-id", "result": {"deleted": 1}}

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(delete_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        result = memory_client.delete_entity("test_entity")

        assert result is True

    def test_delete_entity_error(self, memory_client, mock_subprocess):
        """Returns False on error."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}
        error_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "error": {"code": -1, "message": "Error"}
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(error_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        result = memory_client.delete_entity("test_entity")

        assert result is False


class TestCleanStaleObservations:
    """Tests for TTL/decay cleanup."""

    def test_clean_stale_observations(self, memory_client, mock_subprocess):
        """Removes observations older than max_age_days."""
        # Create timestamps: one fresh, one stale
        fresh_date = datetime.now()
        stale_date = fresh_date - timedelta(days=40)

        fresh_obs = f"[{fresh_date.isoformat()}] Fresh observation"
        stale_obs = f"[{stale_date.isoformat()}] Stale observation"

        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        # Mock responses for: init, read_graph, init, delete_observations
        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}

        # MCP protocol response format: entities are nested in content[0].text as JSON
        entities_data = {
            "entities": [
                {
                    "name": f"{memory_client.repo_slug}::test_entity",
                    "entityType": "test",
                    "observations": [fresh_obs, stale_obs]
                }
            ]
        }
        read_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(entities_data)
                    }
                ]
            }
        }
        delete_response = {"jsonrpc": "2.0", "id": "test-id", "result": {"deleted": 1}}

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),  # First read_graph init
            json.dumps(read_response),  # read_graph result
            json.dumps(init_response),  # delete_observations init
            json.dumps(delete_response)  # delete_observations result
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        removed = memory_client.clean_stale_observations(max_age_days=30)

        assert removed == 1

    def test_clean_removes_entity_when_all_stale(self, memory_client, mock_subprocess):
        """Deletes entity when all observations are stale."""
        stale_date = datetime.now() - timedelta(days=40)
        stale_obs = f"[{stale_date.isoformat()}] Stale observation"

        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}

        # MCP protocol response format: entities are nested in content[0].text as JSON
        entities_data = {
            "entities": [
                {
                    "name": f"{memory_client.repo_slug}::test_entity",
                    "entityType": "test",
                    "observations": [stale_obs]
                }
            ]
        }
        read_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(entities_data)
                    }
                ]
            }
        }
        delete_obs_response = {"jsonrpc": "2.0", "id": "test-id", "result": {"deleted": 1}}
        delete_entity_response = {"jsonrpc": "2.0", "id": "test-id", "result": {"deleted": 1}}

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),  # read_graph init
            json.dumps(read_response),  # read_graph result
            json.dumps(init_response),  # delete_observations init
            json.dumps(delete_obs_response),  # delete_observations result
            json.dumps(init_response),  # delete_entities init
            json.dumps(delete_entity_response)  # delete_entities result
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        removed = memory_client.clean_stale_observations(max_age_days=30)

        assert removed == 1
        # Verify delete_entities was called (check write calls)
        assert mock_process.stdin.write.call_count >= 4  # init + read + init + delete

    def test_clean_handles_invalid_timestamp(self, memory_client, mock_subprocess):
        """Keeps observations with invalid timestamps."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}

        entities_data = {
            "entities": [
                {
                    "name": f"{memory_client.repo_slug}::test_entity",
                    "entityType": "test",
                    "observations": [
                        "[invalid-timestamp] Invalid timestamp",
                        "No timestamp at all"
                    ]
                }
            ]
        }
        read_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(entities_data)
                    }
                ]
            }
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(read_response)
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        removed = memory_client.clean_stale_observations(max_age_days=30)

        # No observations should be removed (all have invalid/missing timestamps)
        assert removed == 0

    def test_clean_handles_deletion_error(self, memory_client, mock_subprocess):
        """Continues cleaning even if one deletion fails."""
        stale_date = datetime.now() - timedelta(days=40)
        stale_obs = f"[{stale_date.isoformat()}] Stale observation"

        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}

        entities_data = {
            "entities": [
                {
                    "name": f"{memory_client.repo_slug}::test_entity",
                    "entityType": "test",
                    "observations": [stale_obs]
                }
            ]
        }
        read_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(entities_data)
                    }
                ]
            }
        }
        error_response = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "error": {"code": -1, "message": "Deletion failed"}
        }

        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),  # read_graph init
            json.dumps(read_response),  # read_graph result
            json.dumps(init_response),  # delete_observations init
            json.dumps(error_response)  # delete_observations fails
        ]
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        removed = memory_client.clean_stale_observations(max_age_days=30)

        # Should return 0 because deletion failed
        assert removed == 0


class TestSubprocessCleanup:
    """Tests that subprocess cleanup happens even on exceptions."""

    def test_process_cleaned_up_on_stdin_write_error(self, memory_client, mock_subprocess):
        """Subprocess is terminated when stdin write raises an exception."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        # Fail on the first stdin write (init request)
        mock_process.stdin.write.side_effect = OSError("Broken pipe")
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        with pytest.raises(RuntimeError, match="MCP memory server call failed"):
            memory_client._call_mcp_server("tools/call", {"name": "test"})

        # Subprocess must still be cleaned up
        mock_process.stdin.close.assert_called()
        mock_process.wait.assert_called()

    def test_process_cleaned_up_on_stdout_readline_error(self, memory_client, mock_subprocess):
        """Subprocess is terminated when stdout readline raises an exception."""
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        # readline fails during init response read
        mock_process.stdout.readline.side_effect = OSError("Read error")
        mock_process.wait.return_value = None
        mock_subprocess.return_value = mock_process

        with pytest.raises(RuntimeError, match="MCP memory server call failed"):
            memory_client._call_mcp_server("tools/call", {"name": "test"})

        mock_process.wait.assert_called()

    def test_process_killed_on_wait_timeout(self, memory_client, mock_subprocess):
        """Subprocess is killed when wait() times out during cleanup."""
        import subprocess as sp

        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.stderr = Mock()

        # Simulate successful communication
        init_response = {"jsonrpc": "2.0", "id": "test-id", "result": {}}
        call_response = {"jsonrpc": "2.0", "id": "test-id", "result": {"ok": True}}
        mock_process.stdout.readline.side_effect = [
            json.dumps(init_response),
            json.dumps(call_response)
        ]

        # wait() times out, forcing kill
        mock_process.wait.side_effect = [sp.TimeoutExpired("npx", 5), None]
        mock_subprocess.return_value = mock_process

        memory_client._call_mcp_server("tools/call", {"name": "test"})

        mock_process.kill.assert_called_once()


class TestMemoryHelpers:
    """Tests for memory_helpers module."""

    def test_get_memory_client_disabled(self):
        """Returns None when memory is disabled."""
        from pokepoke.models.memory_helpers import get_memory_client

        with patch('pokepoke.models.memory_helpers.get_config') as mock_config:
            config = Mock()
            config.mcp_server.memory_enabled = False
            mock_config.return_value = config

            client = get_memory_client()

            assert client is None

    def test_get_memory_client_enabled(self, tmp_path):
        """Returns client when memory is enabled."""
        from pokepoke.models.memory_helpers import get_memory_client

        with patch('pokepoke.models.memory_helpers.get_config') as mock_config:
            config = Mock()
            config.mcp_server.memory_enabled = True
            config.mcp_server.memory_file_path = None
            mock_config.return_value = config

            client = get_memory_client(repo_root=tmp_path)

            assert client is not None
            assert isinstance(client, MCPMemoryClient)

    def test_retrieve_relevant_memories_with_labels(self, tmp_path):
        """Retrieves memories based on work item labels."""
        from pokepoke.models.memory_helpers import retrieve_relevant_memories
        from pokepoke.types import BeadsWorkItem

        work_item = BeadsWorkItem(
            id="TEST-123",
            title="Fix workflow bug",
            description="Fix the bug",
            issue_type="bug",
            priority=1,
            labels=["orchestrator", "workflow"],
            status="pending"  # Required field
        )

        with patch('pokepoke.models.memory_helpers.get_memory_client') as mock_get_client:
            mock_client = Mock()
            mock_entity = MemoryEntity(
                name="workflow.py",
                entity_type="file",
                observations=["[2026-01-01T00:00:00] Main loop"]
            )
            mock_client.retrieve_facts.return_value = [mock_entity]
            mock_get_client.return_value = mock_client

            result = retrieve_relevant_memories(work_item, repo_root=tmp_path)

            assert result is not None
            assert "workflow.py" in result
            assert "Main loop" in result
            assert "file" in result
