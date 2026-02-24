# PokePoke

Autonomous workflow orchestrator that integrates the Beads issue tracker with GitHub Copilot CLI for automated development.

## Installation

### Desktop installer (recommended)

The desktop installer is the easiest way to get PokePoke running on Windows.

**Prerequisites:**

- Windows 10 or later
- [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) (the installer will attempt to install this automatically if missing)

**Steps:**

1. Download the latest `PokePokeInstaller-<version>.exe` from the [Releases](https://github.com/AmeliaRose802/PokePoke/releases) page.
2. Run the installer. If prompted by SmartScreen, click **More info** → **Run anyway**.
3. Choose an install location (defaults to `C:\Program Files\PokePoke`).
4. The installer creates Start Menu and Desktop shortcuts automatically.

**What the installer sets up:**

- The PokePoke desktop application (`PokePoke.exe`)
- Start Menu shortcuts (app + uninstall)
- Desktop shortcut
- WebView2 Runtime (if not already present)
- Add/Remove Programs entry for easy uninstallation

To uninstall, use **Add/Remove Programs** in Windows Settings or run the uninstaller from the Start Menu.

### Install from source (for development)

```bash
pip install -e .
```

Requires Python 3.12 or later.

## Usage

```bash
# Interactive mode (manual work item selection)
python -m pokepoke.orchestrator --interactive

# Autonomous mode (automatic selection, no prompts)
python -m pokepoke.orchestrator --autonomous

# Continuous mode (process multiple items in a loop)
python -m pokepoke.orchestrator --interactive --continuous
python -m pokepoke.orchestrator --autonomous --continuous
```

## AI backend configuration

PokePoke supports pluggable AI backends. Configure `.pokepoke/config.yaml`:

```yaml
ai_backend:
  provider: copilot        # or claude-code
  copilot_cli_path: copilot.cmd
  claude_code_cli_path: claude
```

The Copilot adapter remains the default; setting `provider: claude-code` switches to the Claude Code CLI adapter. Worktrees and orchestrator workflows automatically honor the selected provider.
