"""Terminal UI utilities for PowerShell display enhancements and TUI."""

import os
import sys
import builtins
import time
import threading
from typing import Optional, List, Any, Dict, Iterator
from datetime import datetime
from contextlib import contextmanager

# Try msvcrt for Windows key handling
try:
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore

# Try logging imports, handled gracefully if rich not installed (though strictly required now)
try:
    from rich.console import Console, Group
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich.style import Style
    from rich.box import ROUNDED, HEAVY
    from rich.table import Table
    from rich import print as rprint
except ImportError:
    # Fallback or error
    pass

from pokepoke.types import SessionStats, AgentStats

def set_terminal_banner(text: str) -> None:
    """Set the PowerShell window title to display a banner.
    
    Args:
        text: Text to display in the terminal title bar
    """
    if sys.platform != 'win32':
        return
    
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(text)
    except Exception:
        pass


def clear_terminal_banner() -> None:
    """Clear the terminal banner."""
    set_terminal_banner("PokePoke")


def format_work_item_banner(item_id: str, title: str, status: str = "In Progress") -> str:
    """Format a work item as a banner string."""
    max_title_length = 60
    if len(title) > max_title_length:
        title = title[:max_title_length - 3] + "..."
    return f"🚀 PokePoke: {item_id} - {title} [{status}]"


class PokePokeUI:
    """Rich-based Terminal UI with sticky header/footer and separate orchestrator/agent panels.
    
    Provides a full-screen TUI with:
    - Sticky Header: Current Work Item info
    - Body: Split into Orchestrator logs and Copilot Agent logs
    - Sticky Footer: Session Statistics
    """
    
    def __init__(self) -> None:
        try:
            self.console = Console()
        except NameError:
            self.console = None # type: ignore
        self.layout = Layout()
        self.live: Optional[Live] = None
        
        # Log buffers
        self.orchestrator_buffer: List[str] = []
        self.agent_buffer: List[str] = []
        self.target_buffer = "orchestrator"  # "orchestrator" or "agent"
        
        self.max_log_lines = 1000
        self.is_running = False
        self.original_print = builtins.print
        
        # Scroll tracking
        self.active_panel = "agent"  # "orchestrator" or "agent"
        self.scroll_offsets = {
            "orchestrator": 0,
            "agent": 0
        }
        
        self.input_thread: Optional[threading.Thread] = None
        
        # Output buffering and styling
        self.current_line_buffer: str = ""
        self.current_style: Optional[str] = None
        
        # Initial UI Setup
        if self.console:
            self._setup_layout()
            
    def set_style(self, style: Optional[str]) -> None:
        """Set the current text style for logs."""
        # Flush any pending buffer with old style before switching
        if self.current_line_buffer:
            self.log_message(self.current_line_buffer)
            self.current_line_buffer = ""
        self.current_style = style
        
    def _setup_layout(self) -> None:
        self.layout.split(
            Layout(name="top_spacer", size=1),
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=5)
        )
        
        # Split body into two vertical panels
        self.layout["body"].split_row(
            Layout(name="orchestrator", ratio=1),
            Layout(name="agent", ratio=1)
        )
        
        self.layout["header"].update(Panel("Initialize...", style="bold white on blue", box=ROUNDED))
        self.layout["footer"].update(Panel("Waiting for stats...", style="dim", box=ROUNDED))
        
        self.layout["orchestrator"].update(Panel("", title="Orchestrator Logs", box=ROUNDED))
        self.layout["agent"].update(Panel("", title="Agent Logs (Active)", box=ROUNDED, style="blue"))

    @contextmanager
    def agent_output(self) -> Iterator[None]:
        """Context manager to route output to agent panel."""
        prev = self.target_buffer
        self.target_buffer = "agent"
        try:
            yield
        finally:
            self.target_buffer = prev

    def start(self) -> None:
        """Start the live UI and capture print output."""
        if not self.console:
            return
            
        if not self.is_running:
            self.live = Live(
                self.layout, 
                console=self.console, 
                screen=True, 
                refresh_per_second=4,
                auto_refresh=True
            )
            self.live.start()
            self.is_running = True
            
            # Start input thread for scrolling on Windows
            if sys.platform == 'win32' and msvcrt:
                self.input_thread = threading.Thread(target=self._input_loop, daemon=True)
                self.input_thread.start()
            
            # Monkeypatch print to capture output
            builtins.print = self.print_redirect

    def stop(self) -> None:
        """Stop the live UI and restore print."""
        if self.is_running and self.live:
            self.live.stop()
            self.is_running = False
            builtins.print = self.original_print
            
    def _input_loop(self) -> None:
        """Monitor keyboard input for scrolling."""
        if not msvcrt:
            return

        while self.is_running:
            if msvcrt.kbhit():
                try:
                    key = msvcrt.getch()
                    
                    # Tab to switch focus
                    if key == b'\t':
                        self.active_panel = "agent" if self.active_panel == "orchestrator" else "orchestrator"
                        self._update_panels()
                        continue
                        
                    if key == b'\xe0':  # Arrow prefix
                        code = msvcrt.getch()
                        moved = False
                        
                        curr_offset = self.scroll_offsets[self.active_panel]
                        buffer_len = len(self.orchestrator_buffer) if self.active_panel == "orchestrator" else len(self.agent_buffer)
                        
                        if code == b'H':  # Up
                            curr_offset += 1
                            moved = True
                        elif code == b'P':  # Down
                            curr_offset = max(0, curr_offset - 1)
                            moved = True
                        elif code == b'I':  # Page Up
                            curr_offset += 10
                            moved = True
                        elif code == b'Q':  # Page Down
                            curr_offset = max(0, curr_offset - 10)
                            moved = True
                            
                        # Clamp offset
                        max_offset = max(0, buffer_len - 5)
                        curr_offset = min(curr_offset, max_offset)
                        
                        if moved:
                            self.scroll_offsets[self.active_panel] = curr_offset
                            self._update_panels()
                except Exception:
                    pass
            time.sleep(0.05)
            
    def print_redirect(self, *args: Any, **kwargs: Any) -> None:
        """Redirect print calls to the UI log buffer with buffering."""
        file = kwargs.get('file', sys.stdout)
        # Capture stdout and None (default)
        if file in (sys.stdout, None):
            sep = kwargs.get('sep', ' ')
            end = kwargs.get('end', '\n')
            msg = sep.join(str(arg) for arg in args) + end
            
            # Append to buffer
            self.current_line_buffer += msg
            
            # Process complete lines
            while '\n' in self.current_line_buffer:
                line, remaining = self.current_line_buffer.split('\n', 1)
                self.log_message(line)
                self.current_line_buffer = remaining
                
            # Update UI to show partial progress if desired
            if self.current_line_buffer:
                self._update_panels()
        else:
            # Pass through stderr or other file handles
            self.original_print(*args, **kwargs)

    def log_message(self, message: str) -> None:
        """Add a message to the appropriate log buffer and update view."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Apply current style if needed
        prefix = ""
        suffix = ""
        if self.current_style:
            prefix = f"[{self.current_style}]"
            suffix = f"[/{self.current_style}]"
            
        target_list = self.agent_buffer if self.target_buffer == "agent" else self.orchestrator_buffer
        
        # Handle multiline messages
        for line in message.split('\n'):
            fmt_line = f"[{timestamp}] {prefix}{line}{suffix}"
            target_list.append(fmt_line)
        
        # Trim buffer
        if len(target_list) > self.max_log_lines:
            target_list[:] = target_list[-self.max_log_lines:]
            
        self._update_panels()

    def _get_panel_content(self, logs: List[str], offset: int, height: int) -> List[str]:
        """Get visible logs for a panel."""
        logs_to_show = list(logs)
        total = len(logs_to_show)
        
        if offset == 0:
            return logs_to_show[-height:]
        else:
            end_idx = total - offset
            start_idx = max(0, end_idx - height)
            return logs_to_show[start_idx:end_idx]

    def _update_panels(self) -> None:
        """Update both panels with current content."""
        if not self.console:
            return
            
        # Calculate visible lines roughly
        # Header (3) + Footer (5) + Borders (2) = ~10 lines overhead
        term_height = self.console.height
        body_lines = max(5, term_height - 10)
        
        # --- Orchestrator Panel ---
        orch_logs = self._get_panel_content(
            self.orchestrator_buffer, 
            self.scroll_offsets["orchestrator"],
            body_lines
        )
        orch_title = f"Orchestrator ({self.scroll_offsets['orchestrator']} scrolled)" if self.scroll_offsets["orchestrator"] > 0 else "Orchestrator"
        orch_style = "yellow" if self.scroll_offsets["orchestrator"] > 0 else "white"
        if self.active_panel == "orchestrator":
            orch_title += " [ACTIVE]"
            orch_style = "blue"
            
        self.layout["orchestrator"].update(
            Panel("\n".join(orch_logs), title=orch_title, box=ROUNDED, style=orch_style)
        )

        # --- Agent Panel ---
        # Add current line buffer to agent logs if that's the target
        agent_logs_source = list(self.agent_buffer)
        if self.target_buffer == "agent" and self.current_line_buffer:
             timestamp = datetime.now().strftime("%H:%M:%S")
             agent_logs_source.append(f"[{timestamp}] >> {self.current_line_buffer}")

        agent_logs = self._get_panel_content(
            agent_logs_source,
            self.scroll_offsets["agent"],
            body_lines
        )
        
        agent_title = f"Agent ({self.scroll_offsets['agent']} scrolled)" if self.scroll_offsets["agent"] > 0 else "Agent"
        agent_style = "yellow" if self.scroll_offsets["agent"] > 0 else "white"
        if self.active_panel == "agent":
            agent_title += " [ACTIVE] (Tab to switch)"
            agent_style = "blue"
            
        self.layout["agent"].update(
            Panel("\n".join(agent_logs), title=agent_title, box=ROUNDED, style=agent_style)
        )

    def update_header(self, item_id: str, title: str, status: str = "In Progress") -> None:
        """Update the sticky header."""
        if not self.console:
            return
            
        # Truncate title
        if len(title) > 60:
            title = title[:57] + "..."
            
        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="right")
        grid.add_row(
            f"[bold]{item_id}[/bold] - {title}", 
            f"[{status}]"
        )
        
        self.layout["header"].update(Panel(grid, style="bold white on blue", box=ROUNDED))

    def update_stats(self, session_stats: Optional[SessionStats], elapsed_time: float = 0.0) -> None:
        """Update the sticky footer with stats."""
        if not self.console:
            return

        if not session_stats:
            from pokepoke.types import SessionStats, AgentStats
            session_stats = SessionStats(agent_stats=AgentStats())

        agent_stats = session_stats.agent_stats
        
        # Format stats into a grid
        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="center", ratio=1)
        
        grid.add_row(
            f"⏱️ Runtime: {elapsed_time/60:.1f}m",
            f"⚡ API: {agent_stats.api_duration/60:.1f}m",
            f"📥 In: {agent_stats.input_tokens:,}",
            f"📤 Out: {agent_stats.output_tokens:,}"
        )
        grid.add_row(
            f"✅ Done: {session_stats.items_completed}",
            f"🔄 Retries: {agent_stats.retries}",
            f"💲 Est: ${agent_stats.estimated_cost:.3f}",
            f"🛠️ Tools: {agent_stats.tool_calls}"
        )
        
        self.layout["footer"].update(Panel(grid, title="Session Stats", style="cyan", box=ROUNDED))

# Global UI instance
ui = PokePokeUI()

