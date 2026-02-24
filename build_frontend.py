#!/usr/bin/env python3
"""Build script to pre-build React frontend and copy to Python package.

This script:
1. Runs 'npm run build' in the desktop/ directory
2. Copies the built assets to src/pokepoke/static/
3. Can be called during package building or manually
"""

import shutil
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], cwd: Path | None = None) -> None:
    """Run a command and check for success."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        print(f"❌ Command failed: {' '.join(cmd)}")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
        sys.exit(1)
    print("✅ Command succeeded")


def build_frontend() -> None:
    """Build the React frontend and copy to package static directory."""
    # Determine project root (where this script is located)
    script_dir = Path(__file__).parent
    project_root = script_dir

    desktop_dir = project_root / "desktop"
    dist_dir = desktop_dir / "dist"
    static_dir = project_root / "src" / "pokepoke" / "static"

    # Verify directories exist
    if not desktop_dir.exists():
        print(f"❌ Desktop directory not found: {desktop_dir}")
        sys.exit(1)

    if not static_dir.exists():
        print(f"❌ Static directory not found: {static_dir}")
        sys.exit(1)

    print(f"🔨 Building React frontend in {desktop_dir}")

    # Check if npm is available
    try:
        result = subprocess.run(["npm", "--version"], capture_output=True, check=True, shell=True)
        print(f"✅ npm version: {result.stdout.decode().strip()}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ npm not found. Please install Node.js")
        sys.exit(1)

    # Install dependencies if node_modules doesn't exist
    if not (desktop_dir / "node_modules").exists():
        print("📦 Installing npm dependencies...")
        run_command(["npm", "install"], cwd=desktop_dir)

    # Build the frontend
    print("🏗️  Building frontend...")
    run_command(["npm", "run", "build"], cwd=desktop_dir)

    # Verify build output exists
    if not dist_dir.exists() or not (dist_dir / "index.html").exists():
        print(f"❌ Build failed - no output found in {dist_dir}")
        sys.exit(1)

    # Clear existing static assets (except __init__.py)
    print("🧹 Clearing old static assets...")
    for item in static_dir.iterdir():
        if item.name != "__init__.py":
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    # Copy built assets to static directory
    print(f"📁 Copying built assets from {dist_dir} to {static_dir}")
    for item in dist_dir.iterdir():
        dest = static_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
            print(f"   📁 {item.name}/")
        else:
            shutil.copy2(item, dest)
            print(f"   📄 {item.name}")

    print("✅ Frontend build and copy completed successfully!")


if __name__ == "__main__":
    build_frontend()
