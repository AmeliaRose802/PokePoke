"""Terminal UI utilities for PowerShell display enhancements and TUI."""

import os, sys, builtins, time, threading
from typing import Optional, List, Any, Dict, Iterator
from datetime import datetime
from contextlib import contextmanager

try: import msvcrt
except ImportError: msvcrt = None  # type: ignore

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
except ImportError: pass

from pokepoke.types import SessionStats, AgentStats

def set_terminal_banner(text: str) -> None:
    """Set the PowerShell window title to display a banner."""
    if sys.platform != 'win32': return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(text)
    except Exception: pass

def clear_terminal_banner() -> None: set_terminal_banner("PokePoke")

def format_work_item_banner(item_id: str, title: str, status: str = "In Progress") -> str:
    """Format a work item as a banner string."""
    max_title_length = 60
    if len(title) > max_title_length: title = title[:max_title_length - 3] + "..."
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

        # State for footer rendering
        self.current_work_item: Optional[Dict[str, str]] = None
        self.current_stats: Optional[SessionStats] = None
        self.current_elapsed_time: float = 0.0
        self.session_start_time: Optional[float] = None  # For real-time clock updates
        
        # Current agent tracking
        self.current_agent_name: Optional[str] = None
            
    def set_style(self, style: Optional[str]) -> None:
        """Set the current text style for logs."""
        # Flush any pending buffer with old style before switching
        if self.current_line_buffer:
            self.log_message(self.current_line_buffer)
            self.current_line_buffer = ""
        self.current_style = style
    
    def set_current_agent(self, agent_name: Optional[str]) -> None:
        """Set the currently running agent name for display."""
        self.current_agent_name = agent_name
        
    def _setup_layout(self) -> None:
        self.layout.split(
            Layout(name="body", ratio=1),
            Layout(name="footer", size=10)
        )
        
        # Split body into two vertical panels
        self.layout["body"].split_row(
            Layout(name="orchestrator", ratio=1),
            Layout(name="agent", ratio=1)
        )
        
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
                refresh_per_second=10,
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
        if not msvcrt: return

        while self.is_running:
            if msvcrt.kbhit():
                try:
                    key = msvcrt.getch()
                    if key == b'\t':
                        self.active_panel = "agent" if self.active_panel == "orchestrator" else "orchestrator"
                        self._update_panels()
                        continue
                        
                    if key == b'\xe0':
                        code = msvcrt.getch()
                        moved, curr_offset = False, self.scroll_offsets[self.active_panel]
                        buffer_len = len(self.orchestrator_buffer) if self.active_panel == "orchestrator" else len(self.agent_buffer)
                        
                        if code == b'H': curr_offset += 1; moved = True
                        elif code == b'P': curr_offset = max(0, curr_offset - 1); moved = True
                        elif code == b'I': curr_offset += 10; moved = True
                        elif code == b'Q': curr_offset = max(0, curr_offset - 10); moved = True
                            
                        self.scroll_offsets[self.active_panel] = min(curr_offset, max(0, buffer_len - 5))
                        if moved: self._update_panels()
                except Exception: pass
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
            # if self.current_line_buffer:
            #    self._update_panels()
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

    def _get_panel_content(self, logs: List[str], offset: int, height: int) -> tuple[List[str], bool, bool]:
        """Get visible logs for a panel.
        
        Returns:
            Tuple of (visible_logs, can_scroll_up, can_scroll_down)
        """
        logs_to_show = list(logs)
        total = len(logs_to_show)
        
        if offset == 0:
            visible = logs_to_show[-height:]
            can_scroll_up = total > height
            can_scroll_down = False
        else:
            end_idx = total - offset
            start_idx = max(0, end_idx - height)
            visible = logs_to_show[start_idx:end_idx]
            can_scroll_up = start_idx > 0
            can_scroll_down = offset > 0
            
        return visible, can_scroll_up, can_scroll_down

    def _update_panels(self) -> None:
        """Update both panels with current content."""
        if not self.console:
            return
            
        # Calculate visible lines roughly
        # Footer (7) + Borders (2) = 9 lines overhead
        term_height = self.console.height
        # Use -12 to be strictly safe and avoid ANY overflow/scrolling that causes flashing
        body_lines = max(5, term_height - 12)
        
        # --- Orchestrator Panel ---
        orch_logs, orch_can_up, orch_can_down = self._get_panel_content(
            self.orchestrator_buffer, 
            self.scroll_offsets["orchestrator"],
            body_lines
        )
        
        # Build orchestrator title with scroll indicators
        orch_title = "Orchestrator"
        scroll_indicators = []
        if orch_can_up:
            scroll_indicators.append("↑")
        if orch_can_down:
            scroll_indicators.append("↓")
        if scroll_indicators:
            orch_title += f" [{'/'.join(scroll_indicators)}]"
        if self.scroll_offsets["orchestrator"] > 0:
            orch_title += f" (+{self.scroll_offsets['orchestrator']})"
            
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

        agent_logs, agent_can_up, agent_can_down = self._get_panel_content(
            agent_logs_source,
            self.scroll_offsets["agent"],
            body_lines
        )
        
        # Build agent panel title with current agent name and scroll indicators
        if self.current_agent_name:
            agent_title = f"🤖 {self.current_agent_name}"
        else:
            agent_title = "Agent"
            
        scroll_indicators = []
        if agent_can_up:
            scroll_indicators.append("↑")
        if agent_can_down:
            scroll_indicators.append("↓")
        if scroll_indicators:
            agent_title += f" [{'/'.join(scroll_indicators)}]"
        if self.scroll_offsets["agent"] > 0:
            agent_title += f" (+{self.scroll_offsets['agent']})"
            
        agent_style = "yellow" if self.scroll_offsets["agent"] > 0 else "white"
        if self.active_panel == "agent":
            agent_title += " [ACTIVE]"
            agent_style = "blue"
            
        self.layout["agent"].update(
            Panel("\n".join(agent_logs), title=agent_title, box=ROUNDED, style=agent_style)
        )

    def _render_footer(self) -> None:
        """Render the footer panel containing work item info and stats."""
        if not self.console:
            return

        outer_grid = Table.grid(expand=True)
        outer_grid.add_column()
        
        # 1. Work Item Info (if active)
        if self.current_work_item:
            item_id = self.current_work_item["id"]
            title = self.current_work_item["title"]
            status = self.current_work_item["status"]
            
            # Truncate title - use more available space (reduce reserved space from 40 to 25)
            available_width = max(20, self.console.width - 25)
            if len(title) > available_width:
                title = title[:available_width-3] + "..."
                
            header_grid = Table.grid(expand=True)
            header_grid.add_column(justify="left", ratio=1, no_wrap=True, overflow="ellipsis")
            header_grid.add_column(justify="right", no_wrap=True)
            # Use dim style for more compact appearance
            header_grid.add_row(
                f"[bold]{item_id}[/bold] - [dim]{title}[/dim]", 
                f"[{status}]"
            )
            # Add a separator line or style
            outer_grid.add_row(Panel(header_grid, style="bold white on blue", box=ROUNDED))
        else:
            outer_grid.add_row(Panel("No active work item", style="dim", box=ROUNDED))

        # 2. Stats
        if not self.current_stats:
             from pokepoke.types import SessionStats, AgentStats
             self.current_stats = SessionStats(agent_stats=AgentStats())

        session_stats = self.current_stats
        agent_stats = session_stats.agent_stats
        
        # Compute elapsed time dynamically for real-time updates
        if self.session_start_time is not None:
            elapsed_time = time.time() - self.session_start_time
        else:
            elapsed_time = self.current_elapsed_time

        # Stats grid
        stats_grid = Table.grid(expand=True)
        stats_grid.add_column()
        
        # Metrics row
        metrics_grid = Table.grid(expand=True)
        metrics_grid.add_column(justify="center", ratio=1)
        metrics_grid.add_column(justify="center", ratio=1)
        metrics_grid.add_column(justify="center", ratio=1)
        metrics_grid.add_column(justify="center", ratio=1)
        
        metrics_grid.add_row(
            f"⏱️ {elapsed_time/60:.1f}m",
            f"⚡ API: {agent_stats.api_duration/60:.1f}m",
            f"📥 {agent_stats.input_tokens:,}",
            f"📤 {agent_stats.output_tokens:,}"
        )
        
        # 2nd row metrics
        metrics_grid.add_row(
            f"✅ Done: {session_stats.items_completed}",
            f"🔄 Retries: {agent_stats.retries}",
            f"�️ Tools: {agent_stats.tool_calls}",
            ""
        )
        stats_grid.add_row(metrics_grid)

        # Agent stats row
        agents_grid = Table.grid(expand=True)
        for _ in range(7):
            agents_grid.add_column(justify="center", ratio=1)
            
        agents_grid.add_row(
            f"👷 Work:{session_stats.work_agent_runs}",
            f"💸 Debt:{session_stats.tech_debt_agent_runs}",
            f"🧹 Jan:{session_stats.janitor_agent_runs}",
            f"🗄️ Blog:{session_stats.backlog_cleanup_agent_runs}",
            f"🧼 Cln:{session_stats.cleanup_agent_runs}",
            f"🧪 Beta:{session_stats.beta_tester_agent_runs}",
            f"🔍 Rev:{session_stats.code_review_agent_runs}"
        )
        stats_grid.add_row(agents_grid)
        
        outer_grid.add_row(stats_grid)
        
        self.layout["footer"].update(Panel(outer_grid, title="Status", style="cyan", box=ROUNDED))

    def update_header(self, item_id: str, title: str, status: str = "In Progress") -> None:
        """Update the current work item info (now part of footer)."""
        self.current_work_item = {
            "id": item_id,
            "title": title,
            "status": status
        }
        self._render_footer()

    def update_stats(self, session_stats: Optional[SessionStats], elapsed_time: float = 0.0) -> None:
        """Update the stats info (part of footer)."""
        self.current_stats = session_stats
        self.current_elapsed_time = elapsed_time
        self._render_footer()
    
    def set_session_start_time(self, start_time: float) -> None:
        """Set the session start time for real-time clock updates."""
        self.session_start_time = start_time

# Global UI instance
ui = PokePokeUI()

