"""Launch dialog for selecting a repository and configuring agents when running as a frozen exe.

Uses tkinter (ships with Python/PyInstaller) to show a configuration window
before the main pywebview UI is created.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LaunchConfig:
    """Settings collected from the launch dialog."""
    repo_path: Path
    max_agents: int = 1


def _is_git_repo(path: Path) -> bool:
    """Quick check whether *path* is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            cwd=str(path),
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def pick_repo_directory() -> LaunchConfig | None:
    """Show a launch dialog with folder picker and agent count.

    Always shows the dialog so the user can choose which repository
    to work in and how many parallel agents to run.

    Returns a ``LaunchConfig`` or ``None`` when the user cancels.
    """

    # Try tkinter (bundled with CPython and PyInstaller)
    try:
        import tkinter as tk
        from tkinter import filedialog, ttk

        result: LaunchConfig | None = None

        root = tk.Tk()
        root.title("PokePoke — Launch")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        # Centre the window on screen
        win_w, win_h = 480, 220
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = (screen_w - win_w) // 2
        y = (screen_h - win_h) // 2
        root.geometry(f"{win_w}x{win_h}+{x}+{y}")

        # ── Repository path row ──
        path_frame = ttk.Frame(root, padding=10)
        path_frame.pack(fill="x")

        ttk.Label(path_frame, text="Repository folder:").pack(anchor="w")

        path_var = tk.StringVar(value=str(Path.cwd()))
        path_row = ttk.Frame(path_frame)
        path_row.pack(fill="x", pady=(4, 0))

        path_entry = ttk.Entry(path_row, textvariable=path_var)
        path_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def browse() -> None:
            selected = filedialog.askdirectory(
                title="Select a repository folder",
                mustexist=True,
                initialdir=path_var.get(),
            )
            if selected:
                path_var.set(selected)

        ttk.Button(path_row, text="Browse…", command=browse).pack(side="right")

        # ── Max agents row ──
        agents_frame = ttk.Frame(root, padding=(10, 4, 10, 4))
        agents_frame.pack(fill="x")

        ttk.Label(agents_frame, text="Max parallel agents:").pack(side="left")

        agents_var = tk.IntVar(value=1)
        agents_spin = ttk.Spinbox(
            agents_frame, from_=1, to=8, textvariable=agents_var, width=4
        )
        agents_spin.pack(side="left", padx=(8, 0))

        # ── Buttons ──
        btn_frame = ttk.Frame(root, padding=10)
        btn_frame.pack(fill="x")

        def on_launch() -> None:
            nonlocal result
            chosen = Path(path_var.get()).resolve()
            if chosen.is_dir():
                result = LaunchConfig(
                    repo_path=chosen,
                    max_agents=max(1, agents_var.get()),
                )
            root.destroy()

        def on_cancel() -> None:
            root.destroy()

        ttk.Button(btn_frame, text="Launch", command=on_launch).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="right")

        root.protocol("WM_DELETE_WINDOW", on_cancel)
        root.mainloop()

        return result

    except ImportError:
        # tkinter not available — fall back to a console prompt
        cwd = Path.cwd()
        print("📁 Current directory is not a git repository.")
        print(f"   cwd: {cwd}")
        while True:
            answer = input("Enter repository path (or 'q' to quit): ").strip()
            if answer.lower() == "q":
                return None
            p = Path(answer).resolve()
            if p.is_dir():
                return LaunchConfig(repo_path=p, max_agents=1)
            print(f"   ❌ Not a valid directory: {p}")
            print(f"   ❌ Not a valid directory: {p}")
