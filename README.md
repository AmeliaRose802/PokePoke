# GitHub Copilot SDK Integration Test

## What is 2 + 2?

2 + 2 = 4

## What is the GitHub Copilot SDK?

The GitHub Copilot SDK is a set of libraries and tools that allow developers to integrate GitHub Copilot's AI-powered code completion and automation features into their own applications, editors, or workflows. It provides APIs for invoking Copilot's code suggestions, managing sessions, and interacting programmatically with Copilot's capabilities beyond the standard editor plugin experience.

---

*This file was created to fulfill beads item `poc-test-1` (Test SDK Integration).*

## AI backend configuration

PokePoke now supports pluggable AI backends. Configure `.pokepoke/config.yaml`:

```yaml
ai_backend:
  provider: copilot        # or claude-code
  copilot_cli_path: copilot.cmd
  claude_code_cli_path: claude
```

The Copilot adapter remains the default; setting `provider: claude-code` switches to the Claude Code CLI adapter. Worktrees and orchestrator workflows automatically honor the selected provider.
