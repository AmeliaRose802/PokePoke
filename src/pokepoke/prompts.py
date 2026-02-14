"""Prompt template loading and rendering service."""

from pathlib import Path
from typing import Dict, Any, List, Optional
import re


# Built-in prompts ship with the package
BUILTIN_PROMPTS_DIR = Path(__file__).parent / "builtin_prompts"

# Template variables used across prompts
TEMPLATE_VARIABLES: Dict[str, str] = {
    "id": "Work item ID (e.g. PokePoke-123)",
    "item_id": "Beads item ID",
    "title": "Work item title",
    "description": "Work item description",
    "priority": "Priority level (0-4)",
    "issue_type": "Type (bug, feature, task)",
    "labels": "Comma-separated labels",
    "retry_context": "Boolean to show retry section",
    "attempt": "Current retry attempt number",
    "max_retries": "Maximum retry attempts",
    "errors": "Formatted error list from previous attempt",
    "mcp_enabled": "Boolean to show MCP server section",
    "test_data_section": "Rendered test data for the prompt",
}


class PromptService:
    """Service for loading and rendering prompt templates.

    Loads prompts with a two-tier fallback:
      1. User overrides in ``prompts_dir`` (default ``.pokepoke/prompts/``)
      2. Built-in defaults bundled with the package
    """

    def __init__(
        self,
        prompts_dir: Optional[Path] = None,
        builtin_dir: Optional[Path] = None,
    ):
        """Initialize the prompt service.

        Args:
            prompts_dir: Path to user prompts directory.
                         Defaults to ``.pokepoke/prompts/`` in repo root.
            builtin_dir: Path to built-in prompts shipped with package.
                         Defaults to ``src/pokepoke/builtin_prompts/``.
        """
        if prompts_dir is None:
            current = Path(__file__).parent
            while current != current.parent:
                if (current / ".git").exists():
                    prompts_dir = current / ".pokepoke" / "prompts"
                    break
                current = current.parent
            if prompts_dir is None:
                prompts_dir = (
                    Path(__file__).parent.parent.parent / ".pokepoke" / "prompts"
                )

        self.prompts_dir = Path(prompts_dir)
        self.builtin_dir = Path(builtin_dir) if builtin_dir else BUILTIN_PROMPTS_DIR

        # At least one directory must exist
        if not self.prompts_dir.exists() and not self.builtin_dir.exists():
            raise FileNotFoundError(
                f"No prompts directory found: checked {self.prompts_dir} "
                f"and {self.builtin_dir}"
            )

    def load_prompt(self, template_name: str) -> str:
        """Load a prompt template by name.

        Checks user directory first, then falls back to built-in defaults.

        Args:
            template_name: Name of template (without .md extension)

        Returns:
            Raw template content

        Raises:
            FileNotFoundError: If template doesn't exist in either location
        """
        # User override takes priority
        user_path = self.prompts_dir / f"{template_name}.md"
        if user_path.exists():
            return user_path.read_text(encoding="utf-8")

        # Fall back to built-in
        builtin_path = self.builtin_dir / f"{template_name}.md"
        if builtin_path.exists():
            return builtin_path.read_text(encoding="utf-8")

        raise FileNotFoundError(
            f"Template not found: {template_name} "
            f"(checked {user_path} and {builtin_path})"
        )

    def list_prompts(self) -> List[Dict[str, Any]]:
        """List all available prompt templates with metadata.

        Returns:
            List of dicts with keys: name, is_override, has_builtin,
            source ('user' | 'builtin').
        """
        prompts: Dict[str, Dict[str, Any]] = {}

        # Collect built-in prompts
        if self.builtin_dir.exists():
            for f in sorted(self.builtin_dir.glob("*.md")):
                if f.name == "README.md":
                    continue
                name = f.stem
                prompts[name] = {
                    "name": name,
                    "is_override": False,
                    "has_builtin": True,
                    "source": "builtin",
                }

        # Overlay user prompts
        if self.prompts_dir.exists():
            for f in sorted(self.prompts_dir.glob("*.md")):
                if f.name == "README.md":
                    continue
                name = f.stem
                if name in prompts:
                    prompts[name]["is_override"] = True
                    prompts[name]["source"] = "user"
                else:
                    prompts[name] = {
                        "name": name,
                        "is_override": False,
                        "has_builtin": False,
                        "source": "user",
                    }

        return sorted(prompts.values(), key=lambda p: p["name"])

    def get_prompt_metadata(self, template_name: str) -> Dict[str, Any]:
        """Get metadata for a prompt template.

        Args:
            template_name: Name of template (without .md extension)

        Returns:
            Dict with name, content, is_override, has_builtin, source,
            and template_variables found in the content.
        """
        content = self.load_prompt(template_name)
        user_path = self.prompts_dir / f"{template_name}.md"
        builtin_path = self.builtin_dir / f"{template_name}.md"

        is_override = user_path.exists() and builtin_path.exists()
        has_builtin = builtin_path.exists()
        source = "user" if user_path.exists() else "builtin"

        # Extract template variables from content
        found_vars = sorted(set(re.findall(r'\{\{(\w+)\}\}', content)))

        return {
            "name": template_name,
            "content": content,
            "is_override": is_override,
            "has_builtin": has_builtin,
            "source": source,
            "template_variables": found_vars,
        }

    def save_prompt(self, template_name: str, content: str) -> Dict[str, Any]:
        """Save a prompt override to the user directory.

        Args:
            template_name: Name of template (without .md extension)
            content: Template content to save

        Returns:
            Dict with path and saved status.
        """
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        target = self.prompts_dir / f"{template_name}.md"
        target.write_text(content, encoding="utf-8")
        return {"path": str(target), "saved": True}

    def reset_prompt(self, template_name: str) -> Dict[str, Any]:
        """Remove a user override so the built-in default is used.

        Args:
            template_name: Name of template (without .md extension)

        Returns:
            Dict with reset status and whether a builtin fallback exists.

        Raises:
            FileNotFoundError: If no built-in default exists to fall back to.
        """
        builtin_path = self.builtin_dir / f"{template_name}.md"
        if not builtin_path.exists():
            raise FileNotFoundError(
                f"Cannot reset '{template_name}': no built-in default exists"
            )

        user_path = self.prompts_dir / f"{template_name}.md"
        if user_path.exists():
            user_path.unlink()
            return {"reset": True, "had_override": True}
        return {"reset": True, "had_override": False}
    
    def render_prompt(self, template: str, variables: Dict[str, Any]) -> str:
        """Render a prompt template with variables.
        
        Supports Mustache-like syntax:
        - {{variable}} - Simple substitution
        - {{#section}}...{{/section}} - Conditional sections (if variable is truthy)
        - {{#array}}...{{/array}} - Array iteration ({{.}} for current item)
        
        Args:
            template: Raw template content
            variables: Dictionary of variables to substitute
            
        Returns:
            Rendered prompt
        """
        result = template
        
        # Handle conditional sections and array iteration: {{#key}}...{{/key}}
        def replace_section(match: re.Match[str]) -> str:
            section_name = match.group(1)
            section_content = match.group(2)
            
            # Check if variable exists and is truthy
            if section_name in variables and variables[section_name]:
                value = variables[section_name]
                
                # If value is a list/tuple, iterate over it
                if isinstance(value, (list, tuple)):
                    rendered_parts = []
                    for item in value:
                        # For array iteration, {{.}} refers to current item
                        item_vars = variables.copy()
                        item_vars['.'] = item
                        rendered_parts.append(self._substitute_variables(section_content, item_vars))
                    return ''.join(rendered_parts)
                else:
                    # For conditional sections, just render once
                    return self._substitute_variables(section_content, variables)
            else:
                return ""
        
        # Process conditional sections and array iterations
        result = re.sub(
            r'\{\{#(\w+)\}\}(.*?)\{\{/\1\}\}',
            replace_section,
            result,
            flags=re.DOTALL
        )
        
        # Then handle simple variable substitutions
        result = self._substitute_variables(result, variables)
        
        return result
    
    def _substitute_variables(self, text: str, variables: Dict[str, Any]) -> str:
        """Substitute {{variable}} patterns with values.
        
        Args:
            text: Text containing {{variable}} patterns
            variables: Dictionary of variables
            
        Returns:
            Text with variables substituted
        """
        def replace_var(match: re.Match[str]) -> str:
            var_name = match.group(1)
            return str(variables.get(var_name, f"{{{{missing:{var_name}}}}}"))
        
        return re.sub(r'\{\{(\w+|\.)\}\}', replace_var, text)
    
    def load_and_render(self, template_name: str, variables: Dict[str, Any]) -> str:
        """Load and render a template in one call.
        
        Args:
            template_name: Name of template (without .md extension)
            variables: Dictionary of variables to substitute
            
        Returns:
            Rendered prompt
        """
        template = self.load_prompt(template_name)
        return self.render_prompt(template, variables)


# Singleton instance for easy access
_default_service: Optional[PromptService] = None


def get_prompt_service() -> PromptService:
    """Get the default prompt service instance.
    
    Returns:
        Default PromptService instance
    """
    global _default_service
    if _default_service is None:
        _default_service = PromptService()
    return _default_service
