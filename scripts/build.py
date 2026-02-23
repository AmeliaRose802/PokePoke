#!/usr/bin/env python3
"""Production build script for PokePoke with embedded React frontend.

This script handles the complete build process:
1. Builds the React frontend (npm run build)
2. Copies frontend assets to Python package
3. Builds the Python wheel with embedded assets

Usage:
    python scripts/build.py
"""

import subprocess
import sys
from pathlib import Path


def main():
    """Main build process."""
    project_root = Path(__file__).parent.parent

    print("🚀 Starting PokePoke production build...")

    # Step 1: Build the React frontend
    print("\n📦 Step 1: Building React frontend...")
    try:
        subprocess.run([sys.executable, "build_frontend.py"], cwd=project_root, check=True)
        print("✅ Frontend build completed")
    except subprocess.CalledProcessError as e:
        print(f"❌ Frontend build failed: {e}")
        sys.exit(1)

    # Step 2: Build the Python wheel
    print("\n🐍 Step 2: Building Python wheel...")
    try:
        subprocess.run([sys.executable, "-m", "build", "--wheel"], cwd=project_root, check=True)
        print("✅ Python wheel build completed")
    except subprocess.CalledProcessError as e:
        print(f"❌ Python wheel build failed: {e}")
        sys.exit(1)

    print("\n🎉 Build completed successfully!")
    print("📁 Output: dist/pokepoke-*.whl")
    print("\nNext steps for PyInstaller:")
    print("1. Install the wheel: pip install dist/pokepoke-*.whl")
    print("2. Run PyInstaller with the installed package")


if __name__ == "__main__":
    main()
