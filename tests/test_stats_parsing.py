"""Tests for agent statistics parsing."""

from pokepoke.stats import parse_agent_stats


def test_parse_agent_stats_with_all_fields():
    """Test parsing stats when all fields are present."""
    output = """
    Some output here
    Total duration (wall): 45.2s
    Total duration (API): 30.1s
    Total code changes: 150 lines added, 45 lines removed
    Input: 25.5k input
    Output: 10.2k output
    Est. 3 Premium requests
    More output
    """
    
    stats = parse_agent_stats(output)
    
    assert stats is not None
    assert stats.wall_duration == 45.2
    assert stats.api_duration == 30.1
    assert stats.lines_added == 150
    assert stats.lines_removed == 45
    assert stats.input_tokens == 25500
    assert stats.output_tokens == 10200
    assert stats.premium_requests == 3


def test_parse_agent_stats_with_partial_fields():
    """Test parsing stats when only some fields are present."""
    output = """
    Total duration (wall): 12.5s
    Input: 5000 input
    Output: 2000 output
    """
    
    stats = parse_agent_stats(output)
    
    assert stats is not None
    assert stats.wall_duration == 12.5
    assert stats.api_duration == 0.0
    assert stats.lines_added == 0
    assert stats.lines_removed == 0
    assert stats.input_tokens == 5000
    assert stats.output_tokens == 2000
    assert stats.premium_requests == 0


def test_parse_agent_stats_with_no_stats():
    """Test that None is returned when no stats are found in output."""
    output = "Just some regular output with no statistics"
    
    stats = parse_agent_stats(output)
    
    assert stats is None


def test_parse_agent_stats_with_empty_output():
    """Test that None is returned for empty output."""
    stats = parse_agent_stats("")
    assert stats is None
    
    stats = parse_agent_stats(None)
    assert stats is None


def test_parse_agent_stats_with_alternative_premium_format():
    """Test parsing premium requests with alternative format."""
    output = """
    Total usage est: 5 Premium requests
    """
    
    stats = parse_agent_stats(output)
    
    assert stats is not None
    assert stats.premium_requests == 5


def test_parse_agent_stats_with_tokens_in_thousands():
    """Test parsing tokens when values are in thousands with 'k' suffix."""
    output = """
    15.5k input
    8.2k output
    """
    
    stats = parse_agent_stats(output)
    
    assert stats is not None
    assert stats.input_tokens == 15500
    assert stats.output_tokens == 8200


def test_parse_agent_stats_with_tokens_without_k():
    """Test parsing tokens when values are plain numbers."""
    output = """
    1500 input
    800 output
    """
    
    stats = parse_agent_stats(output)
    
    assert stats is not None
    assert stats.input_tokens == 1500
    assert stats.output_tokens == 800


def test_parse_agent_stats_with_zero_changes():
    """Test parsing when code changes are zero."""
    output = """
    Total duration (wall): 10.0s
    Total code changes: 0 lines added, 0 lines removed
    """
    
    stats = parse_agent_stats(output)
    
    assert stats is not None
    assert stats.wall_duration == 10.0
    assert stats.lines_added == 0
    assert stats.lines_removed == 0


def test_parse_agent_stats_with_invalid_format():
    """Test that parsing continues even with some invalid fields."""
    output = """
    Total duration (wall): 15.0s
    Total code changes: invalid format
    5k input
    """
    
    # Should still parse the valid fields
    stats = parse_agent_stats(output)
    
    assert stats is not None
    assert stats.wall_duration == 15.0
    assert stats.input_tokens == 5000
    assert stats.lines_added == 0  # Failed to parse, defaults to 0


def test_parse_agent_stats_with_exception_handling(capsys, monkeypatch):
    """Test that exceptions during parsing are caught and logged."""
    # Create output that will trigger an exception during parsing
    output = "Total duration (wall): 10.0s"
    
    # Mock float() to raise ValueError
    original_float = float
    call_count = [0]
    
    def mock_float(value):
        call_count[0] += 1
        if call_count[0] == 1:  # First call to float() in parse
            raise ValueError("Mock parsing error")
        return original_float(value)
    
    monkeypatch.setattr('builtins.float', mock_float)
    
    # Should return None and print warning
    stats = parse_agent_stats(output)
    
    assert stats is None
    captured = capsys.readouterr()
    assert "Warning: Failed to parse agent stats" in captured.out
    assert "Mock parsing error" in captured.out
