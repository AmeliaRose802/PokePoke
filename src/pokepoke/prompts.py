"""Prompt template loading and rendering service."""

from pathlib import Path
from typing import Dict, Any, Optional
import re


class PromptService:
    """Service for loading and rendering prompt templates."""
    
    def __init__(self, prompts_dir: Optional[Path] = None):
        """Initialize the prompt service.
        
        Args:
            prompts_dir: Optional path to prompts directory. 
                        Defaults to .pokepoke/prompts/ in repo root.
        """
        if prompts_dir is None:
            # Find repo root by looking for .git directory
            current = Path(__file__).parent
            while current != current.parent:
                if (current / ".git").exists():
                    prompts_dir = current / ".pokepoke" / "prompts"
                    break
                current = current.parent
            
            if prompts_dir is None:
                # Fallback: relative to this file
                prompts_dir = Path(__file__).parent.parent.parent / ".pokepoke" / "prompts"
        
        self.prompts_dir = Path(prompts_dir)
        if not self.prompts_dir.exists():
            raise FileNotFoundError(
                f"Prompts directory not found: {self.prompts_dir}"
            )
    
    def load_prompt(self, template_name: str) -> str:
        """Load a prompt template by name.
        
        Args:
            template_name: Name of template (without .md extension)
            
        Returns:
            Raw template content
            
        Raises:
            FileNotFoundError: If template doesn't exist
        """
        template_path = self.prompts_dir / f"{template_name}.md"
        
        if not template_path.exists():
            raise FileNotFoundError(
                f"Template not found: {template_name} at {template_path}"
            )
        
        return template_path.read_text(encoding="utf-8")
    
    def render_prompt(self, template: str, variables: Dict[str, Any]) -> str:
        """Render a prompt template with variables.
        
        Supports Mustache-like syntax:
        - {{variable}} - Simple substitution
        - {{#section}}...{{/section}} - Conditional sections (if variable is truthy)
        
        Args:
            template: Raw template content
            variables: Dictionary of variables to substitute
            
        Returns:
            Rendered prompt
        """
        result = template
        
        # Handle conditional sections first: {{#key}}...{{/key}}
        def replace_section(match: re.Match[str]) -> str:
            section_name = match.group(1)
            section_content = match.group(2)
            
            # Check if variable exists and is truthy
            if section_name in variables and variables[section_name]:
                # Render the section content with variables
                return self._substitute_variables(section_content, variables)
            else:
                return ""
        
        # Process conditional sections
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
        
        return re.sub(r'\{\{(\w+)\}\}', replace_var, text)
    
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
