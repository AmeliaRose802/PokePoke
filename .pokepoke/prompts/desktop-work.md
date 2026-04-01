{{>beads-item}}

## 🖥️ Desktop Frontend Context

This work item is related to the **PokePoke desktop application** - the TUI (Terminal UI) interface.

### Key Files

- `src/pokepoke/desktop/` - Desktop UI components
- `src/pokepoke/desktop/terminal_ui.py` - Main TUI controller
- `src/pokepoke/desktop/components/` - UI component library
- `desktop/` - Electron-based desktop app (if applicable)

### UI Patterns

**Terminal UI (TUI):**
- Built with Rich library for terminal rendering
- Agent cards display work item progress
- Real-time output streaming with context preservation
- Status indicators and progress bars

**State Management:**
- UI state is managed by terminal_ui.py
- Agent output routing through thread-local context
- Token usage and statistics tracked per agent

**Responsive Design:**
- Handle terminal resize gracefully
- Accommodate various terminal widths (min 80 chars)
- Use adaptive layouts and truncation

### Testing Desktop Changes

**Run desktop UI tests:**
```powershell
pytest tests/desktop/ --timeout={{command_timeout}}
```

**Manual testing:**
- Test with different terminal sizes
- Verify output formatting and colors
- Check real-time updates during agent execution
- Ensure proper cleanup on Ctrl+C

### Common Pitfalls

- ⚠️ Don't block the UI thread - use async patterns
- ⚠️ Don't forget terminal width constraints
- ⚠️ Test with both light and dark terminal themes
- ⚠️ Ensure proper ANSI escape sequence handling
