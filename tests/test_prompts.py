"""Tests for prompt template loading and rendering."""

import pytest
from pokepoke.prompts import PromptService


def test_prompt_service_initialization():
    """Test that prompt service initializes with correct directory."""
    service = PromptService()
    assert service.prompts_dir.exists()
    assert service.prompts_dir.name == "prompts"


def test_load_prompt_exists():
    """Test loading an existing prompt template."""
    service = PromptService()
    template = service.load_prompt("work-item")
    
    assert template is not None
    assert "{{id}}" in template
    assert "{{title}}" in template
    assert "{{description}}" in template


def test_load_prompt_not_found():
    """Test that loading non-existent template raises error."""
    service = PromptService()
    
    with pytest.raises(FileNotFoundError, match="Template not found: nonexistent"):
        service.load_prompt("nonexistent")


def test_render_simple_variables():
    """Test rendering template with simple variable substitution."""
    service = PromptService()
    template = "Hello {{name}}, your ID is {{id}}."
    
    result = service.render_prompt(template, {
        "name": "Alice",
        "id": "123"
    })
    
    assert result == "Hello Alice, your ID is 123."


def test_render_conditional_section_shown():
    """Test that conditional sections render when variable is truthy."""
    service = PromptService()
    template = "Start{{#section}}\nMiddle content{{/section}}\nEnd"
    
    result = service.render_prompt(template, {"section": True})
    
    assert "Middle content" in result
    assert result == "Start\nMiddle content\nEnd"


def test_render_conditional_section_hidden():
    """Test that conditional sections hide when variable is falsy."""
    service = PromptService()
    template = "Start{{#section}}\nMiddle content{{/section}}\nEnd"
    
    result = service.render_prompt(template, {"section": False})
    
    assert "Middle content" not in result
    assert result == "Start\nEnd"


def test_render_conditional_with_variables():
    """Test that variables inside conditional sections are substituted."""
    service = PromptService()
    template = "{{#show}}Name: {{name}}{{/show}}"
    
    result = service.render_prompt(template, {
        "show": True,
        "name": "Bob"
    })
    
    assert result == "Name: Bob"


def test_render_missing_variable():
    """Test that missing variables are marked."""
    service = PromptService()
    template = "Hello {{name}}, your role is {{role}}."
    
    result = service.render_prompt(template, {"name": "Charlie"})
    
    assert "Charlie" in result
    assert "{{missing:role}}" in result


def test_load_and_render():
    """Test the combined load and render method."""
    service = PromptService()
    
    result = service.load_and_render("work-item", {
        "id": "PokePoke-123",
        "title": "Test Task",
        "description": "Do something",
        "priority": 1,
        "issue_type": "task",
        "labels": "test, example",
    })
    
    assert "PokePoke-123" in result
    assert "Test Task" in result
    assert "Do something" in result
    assert "**Priority:** 1" in result
    assert "**Type:** task" in result
    assert "**Labels:** test, example" in result


def test_render_work_item_with_labels():
    """Test rendering work item template with labels."""
    service = PromptService()
    
    result = service.load_and_render("work-item", {
        "id": "PokePoke-456",
        "title": "Fix bug",
        "description": "Fix the thing",
        "priority": 0,
        "issue_type": "bug",
        "labels": "urgent, backend",
    })
    
    assert "**Labels:** urgent, backend" in result


def test_render_work_item_without_labels():
    """Test rendering work item template without labels (conditional hidden)."""
    service = PromptService()
    
    result = service.load_and_render("work-item", {
        "id": "PokePoke-789",
        "title": "Add feature",
        "description": "Add new feature",
        "priority": 2,
        "issue_type": "feature",
        "labels": None,  # No labels
    })
    
    assert "PokePoke-789" in result
    assert "Add feature" in result
    # Labels section should not appear
    assert "Labels:" not in result


def test_render_retry_template():
    """Test rendering retry template with errors."""
    service = PromptService()
    
    result = service.load_and_render("work-item-retry", {
        "id": "PokePoke-999",
        "title": "Retry Task",
        "description": "Fix this",
        "priority": 1,
        "issue_type": "task",
        "labels": None,
        "retry_context": True,
        "attempt": 2,
        "max_retries": 3,
        "errors": "  - Test failed\n  - Coverage too low",
    })
    
    assert "RETRY ATTEMPT 2/3" in result
    assert "Test failed" in result
    assert "Coverage too low" in result


def test_render_retry_template_no_retry():
    """Test rendering retry template without retry context (first attempt)."""
    service = PromptService()
    
    result = service.load_and_render("work-item-retry", {
        "id": "PokePoke-888",
        "title": "First Try",
        "description": "Initial attempt",
        "priority": 1,
        "issue_type": "task",
        "labels": None,
        "retry_context": False,  # First attempt, no retry
    })
    
    assert "PokePoke-888" in result
    assert "First Try" in result
    # Retry section should not appear
    assert "RETRY ATTEMPT" not in result


def test_render_array_iteration():
    """Test rendering template with array iteration."""
    service = PromptService()
    template = "Allowed:\n{{#items}}- {{.}}\n{{/items}}"
    
    result = service.render_prompt(template, {
        "items": ["path1", "path2", "path3"]
    })
    
    assert "- path1" in result
    assert "- path2" in result
    assert "- path3" in result
    assert result == "Allowed:\n- path1\n- path2\n- path3\n"


def test_render_array_empty():
    """Test rendering template with empty array."""
    service = PromptService()
    template = "Start{{#items}}\n- {{.}}{{/items}}\nEnd"
    
    result = service.render_prompt(template, {
        "items": []
    })
    
    assert result == "Start\nEnd"


def test_render_beads_item_with_labels():
    """Test rendering beads-item template with labels."""
    service = PromptService()
    
    result = service.load_and_render("beads-item", {
        "item_id": "PokePoke-123",
        "title": "Fix bug",
        "description": "Fix the authentication bug",
        "issue_type": "bug",
        "priority": 1,
        "labels": "security, backend"
    })
    
    assert "PokePoke-123" in result
    assert "Fix bug" in result
    assert "Fix the authentication bug" in result
    assert "security, backend" in result
    assert "All pre-commit validation passes successfully" in result


# ── Fallback & override tests ────────────────────────────────────────────


def test_fallback_loads_from_builtin(tmp_path):
    """When user dir has no template, fall back to builtin."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "hello.md").write_text("built-in hello", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    assert service.load_prompt("hello") == "built-in hello"


def test_user_override_takes_priority(tmp_path):
    """User override should take priority over built-in."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "hello.md").write_text("built-in hello", encoding="utf-8")
    (user_dir / "hello.md").write_text("custom hello", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    assert service.load_prompt("hello") == "custom hello"


def test_load_prompt_not_found_in_either(tmp_path):
    """Raise FileNotFoundError when template is in neither directory."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    with pytest.raises(FileNotFoundError, match="Template not found"):
        service.load_prompt("missing")


def test_list_prompts_merges_sources(tmp_path):
    """list_prompts should merge builtin and user prompts."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "alpha.md").write_text("a", encoding="utf-8")
    (builtin_dir / "beta.md").write_text("b", encoding="utf-8")
    (user_dir / "beta.md").write_text("b-custom", encoding="utf-8")
    (user_dir / "gamma.md").write_text("g", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    result = service.list_prompts()

    names = [p["name"] for p in result]
    assert names == ["alpha", "beta", "gamma"]

    by_name = {p["name"]: p for p in result}
    assert by_name["alpha"]["source"] == "builtin"
    assert not by_name["alpha"]["is_override"]
    assert by_name["beta"]["source"] == "user"
    assert by_name["beta"]["is_override"]
    assert by_name["gamma"]["source"] == "user"
    assert not by_name["gamma"]["has_builtin"]


def test_list_prompts_excludes_readme(tmp_path):
    """README.md should not be listed as a prompt template."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "README.md").write_text("docs", encoding="utf-8")
    (builtin_dir / "hello.md").write_text("hi", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    names = [p["name"] for p in service.list_prompts()]
    assert "README" not in names
    assert "hello" in names


def test_get_prompt_metadata(tmp_path):
    """get_prompt_metadata should return content and template variables."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "test.md").write_text(
        "Hello {{name}}, id={{id}}", encoding="utf-8"
    )

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    meta = service.get_prompt_metadata("test")

    assert meta["name"] == "test"
    assert meta["source"] == "builtin"
    assert not meta["is_override"]
    assert meta["has_builtin"]
    assert "name" in meta["template_variables"]
    assert "id" in meta["template_variables"]
    assert "Hello {{name}}" in meta["content"]


def test_save_prompt_creates_override(tmp_path):
    """save_prompt should write to user directory."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "test.md").write_text("original", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    result = service.save_prompt("test", "custom content")

    assert result["saved"]
    assert (user_dir / "test.md").read_text(encoding="utf-8") == "custom content"
    # Now loading should return the override
    assert service.load_prompt("test") == "custom content"


def test_reset_prompt_removes_override(tmp_path):
    """reset_prompt should delete user override so builtin is used."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "test.md").write_text("original", encoding="utf-8")
    (user_dir / "test.md").write_text("custom", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    assert service.load_prompt("test") == "custom"

    result = service.reset_prompt("test")
    assert result["reset"]
    assert result["had_override"]
    assert service.load_prompt("test") == "original"


def test_reset_prompt_no_builtin_raises(tmp_path):
    """reset_prompt should raise if there is no builtin to fall back to."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (user_dir / "custom.md").write_text("my prompt", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    with pytest.raises(FileNotFoundError, match="no built-in default exists"):
        service.reset_prompt("custom")


def test_reset_prompt_no_override_exists(tmp_path):
    """reset_prompt when no override exists should return had_override=False."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "test.md").write_text("original", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    result = service.reset_prompt("test")
    assert result["reset"]
    assert not result["had_override"]


def test_init_fails_when_no_directories_exist(tmp_path):
    """PromptService should raise if both directories are missing."""
    with pytest.raises(FileNotFoundError, match="No prompts directory found"):
        PromptService(
            prompts_dir=tmp_path / "missing_user",
            builtin_dir=tmp_path / "missing_builtin",
        )


def test_save_prompt_creates_user_dir(tmp_path):
    """save_prompt should create user prompts directory if it doesn't exist."""
    user_dir = tmp_path / "new_user_dir"
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "test.md").write_text("original", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    service.save_prompt("test", "new content")
    assert user_dir.exists()
    assert (user_dir / "test.md").read_text(encoding="utf-8") == "new content"
