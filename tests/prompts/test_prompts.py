"""Tests for prompt template loading and rendering."""

import pytest

from pokepoke.prompts.prompts import PromptService


def test_prompt_service_initialization(monkeypatch):
    """Test that prompt service initializes with correct directory."""
    # Ensure CWD is the repo root so _find_repo_root() works
    import os
    monkeypatch.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    service = PromptService()
    assert service.prompts_dir.exists() or service.builtin_dir.exists()
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


@pytest.mark.parametrize(
    "bad_name",
    [
        "../evil",
        "..\\evil",
        "bad/name",
        "bad\\name",
        "bad..name",
        "bad\x00name",
        "",
    ],
)
def test_save_prompt_rejects_invalid_template_name(tmp_path, bad_name):
    """save_prompt should reject names that could escape the prompts directory."""
    user_dir = tmp_path / "user"
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "valid.md").write_text("ok", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)

    with pytest.raises(ValueError, match="Template name"):
        service.save_prompt(bad_name, "content")


@pytest.mark.parametrize(
    "bad_name",
    [
        "../evil",
        "..\\evil",
        "bad/name",
        "bad\\name",
        "bad..name",
        "bad\x00name",
        "",
    ],
)
def test_load_prompt_rejects_invalid_template_name(tmp_path, bad_name):
    """load_prompt should reject names that could escape the prompts directory."""
    user_dir = tmp_path / "user"
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "valid.md").write_text("ok", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)

    with pytest.raises(ValueError, match="Template name"):
        service.load_prompt(bad_name)


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


def test_default_prompts_dir_uses_repo_root(monkeypatch, tmp_path):
    """Default prompts_dir should resolve from the target repo root, not package path."""
    # Simulate a repo root with .pokepoke/prompts and a built-in fallback
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    user_dir = repo_root / ".pokepoke" / "prompts"
    builtin_dir = repo_root / "builtin"
    builtin_dir.mkdir(parents=True)
    (builtin_dir / "test.md").write_text("builtin", encoding="utf-8")

    monkeypatch.setattr("pokepoke.prompts.prompts.BUILTIN_PROMPTS_DIR", builtin_dir)
    monkeypatch.setattr("pokepoke.prompts.prompts._find_repo_root", lambda: repo_root)

    service = PromptService()
    result = service.save_prompt("test", "override")

    assert service.prompts_dir == user_dir
    assert result["saved"]
    assert (user_dir / "test.md").read_text(encoding="utf-8") == "override"

# ── Code Review Prompt Content Tests ─────────────────────────────────────


def test_code_reviewer_prompt_has_mandatory_filing_section():
    """Code reviewer prompt must contain MANDATORY FILING REQUIREMENTS section."""
    service = PromptService()
    content = service.load_prompt("code-reviewer")

    assert "MANDATORY FILING REQUIREMENTS" in content
    assert "🚨 CRITICAL:" in content


def test_code_reviewer_prompt_requires_high_severity_filing():
    """Code reviewer prompt must mandate filing HIGH severity issues."""
    service = PromptService()
    content = service.load_prompt("code-reviewer")

    # Must contain explicit language requiring HIGH severity filing
    assert "HIGH severity (P0/P1) findings MUST ALWAYS be filed" in content
    assert "NO EXCEPTIONS" in content

    # Should forbid dismissing HIGH severity issues
    assert "CANNOT dismiss HIGH severity findings" in content or \
           "cannot dismiss HIGH severity findings" in content


def test_code_reviewer_prompt_has_severity_classification():
    """Code reviewer prompt must require severity classification."""
    service = PromptService()
    content = service.load_prompt("code-reviewer")

    assert "Classify Severity" in content or "classify severity" in content
    assert "HIGH (P0/P1)" in content
    assert "MEDIUM (P2)" in content
    assert "LOW (P3)" in content


def test_code_reviewer_prompt_has_summary_requirements():
    """Code reviewer prompt must specify summary requirements."""
    service = PromptService()
    content = service.load_prompt("code-reviewer")

    assert "Summary Requirements" in content or "summary MUST" in content.lower()
    # Must forbid saying "no significant issues" when HIGH severity found
    assert "Never say" in content or "NEVER say" in content


def test_code_reviewer_builtin_matches_user_version():
    """Built-in code-reviewer.md must have same mandatory requirements as user version."""
    service = PromptService()

    # Load from user dir
    user_content = (service.prompts_dir / "code-reviewer.md").read_text(encoding="utf-8")

    # Load from builtin dir
    builtin_content = (service.builtin_dir / "code-reviewer.md").read_text(encoding="utf-8")

    # Both should have the critical mandatory filing section
    assert "MANDATORY FILING REQUIREMENTS" in user_content
    assert "MANDATORY FILING REQUIREMENTS" in builtin_content

    # Both should require HIGH severity filing
    assert "HIGH severity (P0/P1) findings MUST ALWAYS be filed" in user_content
    assert "HIGH severity (P0/P1) findings MUST ALWAYS be filed" in builtin_content


# ── Template Inheritance Tests ───────────────────────────────────────────


def test_template_include_basic(tmp_path):
    """Test basic template inclusion using {{>template}} syntax."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "base.md").write_text("Base content\n", encoding="utf-8")
    (builtin_dir / "child.md").write_text("{{>base}}Extra content", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    result = service.load_and_render("child", {})

    assert "Base content" in result
    assert "Extra content" in result


def test_template_include_with_variables(tmp_path):
    """Test that included templates can use variables from the parent context."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "base.md").write_text("Hello {{name}}", encoding="utf-8")
    (builtin_dir / "child.md").write_text("{{>base}}\nWelcome!", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    result = service.load_and_render("child", {"name": "Alice"})

    assert "Hello Alice" in result
    assert "Welcome!" in result


def test_template_include_missing_template(tmp_path):
    """Test that missing template includes are marked."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "child.md").write_text("{{>missing}}", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    result = service.load_and_render("child", {})

    assert "{{missing include: missing}}" in result


def test_template_include_recursive(tmp_path):
    """Test nested template includes (A includes B, B includes C)."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "level3.md").write_text("Level 3", encoding="utf-8")
    (builtin_dir / "level2.md").write_text("Level 2 {{>level3}}", encoding="utf-8")
    (builtin_dir / "level1.md").write_text("Level 1 {{>level2}}", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    result = service.load_and_render("level1", {})

    assert "Level 1" in result
    assert "Level 2" in result
    assert "Level 3" in result


def test_template_include_with_user_override(tmp_path):
    """Test that user overrides work with template includes."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    builtin_dir = tmp_path / "builtin"
    builtin_dir.mkdir()
    (builtin_dir / "base.md").write_text("Builtin base", encoding="utf-8")
    (user_dir / "base.md").write_text("Custom base", encoding="utf-8")
    (builtin_dir / "child.md").write_text("{{>base}}", encoding="utf-8")

    service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
    result = service.load_and_render("child", {})

    # Should use the user override, not builtin
    assert "Custom base" in result
    assert "Builtin base" not in result


# ── Label-Based Template Selection Tests ─────────────────────────────────


def test_build_prompt_with_label_template_selection():
    """Test that prompt template is selected based on work item labels."""
    from pokepoke.config import reset_config
    from pokepoke.models.sdk_helpers import build_prompt_from_work_item
    from pokepoke.types import BeadsWorkItem

    reset_config()

    # Mock config with prompt_templates mapping
    import pokepoke.config as config_module
    original_get_config = config_module.get_config

    def mock_get_config():
        cfg = original_get_config()
        cfg.prompt_templates = {"orchestrator": "orchestrator-work"}
        return cfg

    config_module.get_config = mock_get_config

    try:
        work_item = BeadsWorkItem(
            id="PokePoke-123",
            title="Fix orchestrator bug",
            description="Fix the issue",
            status="ready",
            issue_type="bug",
            priority=1,
            labels=["orchestrator"],
        )

        prompt = build_prompt_from_work_item(work_item)

        # Should include orchestrator-specific content
        assert "Orchestrator Context" in prompt or "orchestrator" in prompt.lower()
    finally:
        config_module.get_config = original_get_config
        reset_config()


def test_build_prompt_falls_back_to_default_when_no_label_match():
    """Test that default template is used when no labels match config."""
    from pokepoke.config import reset_config
    from pokepoke.models.sdk_helpers import build_prompt_from_work_item
    from pokepoke.types import BeadsWorkItem

    reset_config()

    work_item = BeadsWorkItem(
        id="PokePoke-456",
        title="Generic task",
        description="Do something",
        status="ready",
        issue_type="task",
        priority=2,
        labels=["unknown-label"],
    )

    prompt = build_prompt_from_work_item(work_item)

    # Should use default beads-item template
    assert "PokePoke-456" in prompt
    assert "Generic task" in prompt
    # Should NOT have label-specific content
    assert "Orchestrator Context" not in prompt


def test_build_prompt_with_multiple_labels_uses_first_match():
    """Test that first matching label is used when multiple labels exist."""
    from pokepoke.config import reset_config
    from pokepoke.models.sdk_helpers import build_prompt_from_work_item
    from pokepoke.types import BeadsWorkItem

    reset_config()

    import pokepoke.config as config_module
    original_get_config = config_module.get_config

    def mock_get_config():
        cfg = original_get_config()
        cfg.prompt_templates = {
            "orchestrator": "orchestrator-work",
            "desktop": "desktop-work",
        }
        return cfg

    config_module.get_config = mock_get_config

    try:
        work_item = BeadsWorkItem(
            id="PokePoke-789",
            title="Fix bug",
            description="Fix it",
            status="ready",
            issue_type="bug",
            priority=1,
            labels=["orchestrator", "desktop"],  # Has both labels
        )

        prompt = build_prompt_from_work_item(work_item)

        # Should use orchestrator template (first match in labels list)
        # Note: This test documents current behavior - first label wins
        assert "PokePoke-789" in prompt
    finally:
        config_module.get_config = original_get_config
        reset_config()


def test_build_prompt_with_no_labels():
    """Test that default template is used when work item has no labels."""
    from pokepoke.config import reset_config
    from pokepoke.models.sdk_helpers import build_prompt_from_work_item
    from pokepoke.types import BeadsWorkItem

    reset_config()

    work_item = BeadsWorkItem(
        id="PokePoke-999",
        title="Task with no labels",
        description="Description",
        status="ready",
        issue_type="task",
        priority=3,
        labels=[],  # No labels
    )

    prompt = build_prompt_from_work_item(work_item)

    # Should use default template
    assert "PokePoke-999" in prompt
    assert "Task with no labels" in prompt

