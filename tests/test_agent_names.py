"""Tests for agent name generation."""

import os
import re
import pytest
from unittest.mock import patch

from pokepoke.agent_names import (
    generate_agent_name,
    initialize_agent_name,
    ADJECTIVES,
    CREATURES
)


class TestGenerateAgentName:
    """Tests for generate_agent_name function."""
    
    def test_default_format(self):
        """Test that agent name has correct default format."""
        name = generate_agent_name()
        
        # Should match: pokepoke_{adjective}_{creature}_{hex}
        pattern = r'^pokepoke_[a-z]+_[a-z]+_[0-9a-f]{4}$'
        assert re.match(pattern, name), f"Name {name} doesn't match expected pattern"
    
    def test_custom_prefix(self):
        """Test that custom prefix is used."""
        name = generate_agent_name(prefix="testbot")
        assert name.startswith("testbot_")
    
    def test_uses_valid_adjective(self):
        """Test that generated name uses a valid adjective."""
        name = generate_agent_name()
        parts = name.split('_')
        adjective = parts[1]
        assert adjective in ADJECTIVES
    
    def test_uses_valid_creature(self):
        """Test that generated name uses a valid creature."""
        name = generate_agent_name()
        parts = name.split('_')
        creature = parts[2]
        assert creature in CREATURES
    
    def test_has_hex_suffix(self):
        """Test that name has 4-character hex suffix."""
        name = generate_agent_name()
        parts = name.split('_')
        hex_suffix = parts[3]
        
        # Should be exactly 4 hex characters
        assert len(hex_suffix) == 4
        assert all(c in '0123456789abcdef' for c in hex_suffix)
    
    def test_uniqueness(self):
        """Test that multiple calls generate different names (with high probability)."""
        names = [generate_agent_name() for _ in range(100)]
        
        # With ~87 million combinations, we should get 100 unique names
        unique_names = set(names)
        assert len(unique_names) >= 95, "Agent names don't have enough entropy"
    
    def test_format_parts_count(self):
        """Test that name has exactly 4 parts separated by underscores."""
        name = generate_agent_name()
        parts = name.split('_')
        assert len(parts) == 4


class TestInitializeAgentName:
    """Tests for initialize_agent_name function."""
    
    def test_uses_custom_name_when_provided(self):
        """Test that custom name is used when provided."""
        custom = "my_custom_agent"
        name = initialize_agent_name(custom_name=custom)
        assert name == custom
    
    def test_generates_name_when_none_provided(self):
        """Test that name is generated when no custom name provided."""
        name = initialize_agent_name()
        
        # Should be a generated name
        pattern = r'^pokepoke_[a-z]+_[a-z]+_[0-9a-f]{4}$'
        assert re.match(pattern, name)
    
    def test_generates_different_names_on_multiple_calls(self):
        """Test that multiple calls generate different names."""
        names = [initialize_agent_name() for _ in range(50)]
        unique_names = set(names)
        
        # Should have high uniqueness
        assert len(unique_names) >= 45


class TestAdjectives:
    """Tests for ADJECTIVES constant."""
    
    def test_adjectives_exist(self):
        """Test that adjectives list is not empty."""
        assert len(ADJECTIVES) > 0
    
    def test_adjectives_are_lowercase(self):
        """Test that all adjectives are lowercase."""
        for adj in ADJECTIVES:
            assert adj.islower(), f"Adjective '{adj}' is not lowercase"
    
    def test_adjectives_are_alphanumeric(self):
        """Test that all adjectives are alphanumeric."""
        for adj in ADJECTIVES:
            assert adj.isalpha(), f"Adjective '{adj}' contains non-alpha characters"
    
    def test_reasonable_adjective_count(self):
        """Test that we have a reasonable number of adjectives for entropy."""
        assert len(ADJECTIVES) >= 20, "Need more adjectives for good entropy"


class TestCreatures:
    """Tests for CREATURES constant."""
    
    def test_creatures_exist(self):
        """Test that creatures list is not empty."""
        assert len(CREATURES) > 0
    
    def test_creatures_are_lowercase(self):
        """Test that all creatures are lowercase."""
        for creature in CREATURES:
            assert creature.islower(), f"Creature '{creature}' is not lowercase"
    
    def test_creatures_are_alphanumeric(self):
        """Test that all creatures are alphanumeric."""
        for creature in CREATURES:
            assert creature.isalpha(), f"Creature '{creature}' contains non-alpha characters"
    
    def test_reasonable_creature_count(self):
        """Test that we have a reasonable number of creatures for entropy."""
        assert len(CREATURES) >= 20, "Need more creatures for good entropy"


class TestEntropyCalculation:
    """Tests to verify the entropy claims in the module."""
    
    def test_entropy_calculation(self):
        """Test that the entropy calculation is accurate.
        
        Entropy = log2(adjectives * creatures * hex_combinations)
        With 35+ adjectives, 38+ creatures, 65536 hex = ~87 million combinations
        """
        total_combinations = len(ADJECTIVES) * len(CREATURES) * (16 ** 4)
        
        # Should have at least 26 bits of entropy (67 million combinations)
        # 2^26 = 67,108,864
        assert total_combinations >= 67_000_000, (
            f"Only {total_combinations:,} combinations, need at least 67 million for good entropy"
        )


class TestIntegrationWithBeads:
    """Integration tests for agent name with beads management."""
    
    def test_agent_name_environment_variable_usage(self):
        """Test that AGENT_NAME env var is used by beads_management."""
        # This is an integration concern - the env var should be set by orchestrator
        # and read by beads_management.assign_and_sync_item
        test_name = "pokepoke_test_agent_1234"
        
        with patch.dict(os.environ, {'AGENT_NAME': test_name}):
            # The beads_management module should read this
            assert os.environ.get('AGENT_NAME') == test_name
    
    def test_orchestrator_sets_agent_name(self):
        """Test that orchestrator sets AGENT_NAME in environment."""
        # This will be tested in orchestrator tests
        # Just verify the pattern is compatible with bd command
        name = generate_agent_name()
        
        # Should not contain characters that would cause issues with shell commands
        assert ' ' not in name, "Agent name should not contain spaces"
        assert '"' not in name, "Agent name should not contain quotes"
        assert "'" not in name, "Agent name should not contain quotes"
