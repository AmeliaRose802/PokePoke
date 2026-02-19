"""Custom build backend that builds React frontend before packaging.

This module wraps the standard setuptools build backend and adds
a pre-build step that runs our frontend build script.
"""

import os
import subprocess
import sys
from pathlib import Path

# Import the standard setuptools backend
from setuptools.build_meta import *
from setuptools.build_meta import build_wheel as _build_wheel, build_sdist as _build_sdist


def _run_frontend_build():
    """Run the frontend build script before packaging."""
    # Find the build script in the project root
    project_root = Path.cwd()
    build_script = project_root / "build_frontend.py"
    
    if not build_script.exists():
        print("⚠️  Frontend build script not found, skipping frontend build")
        return
    
    print("🔨 Running pre-build step: building React frontend...")
    try:
        result = subprocess.run([sys.executable, str(build_script)], check=True, capture_output=True, text=True)
        print("✅ Frontend build completed successfully")
        if result.stdout:
            print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"❌ Frontend build failed: {e}")
        if e.stdout:
            print("stdout:", e.stdout)
        if e.stderr:
            print("stderr:", e.stderr)
        # Don't fail the entire build - just warn
        print("⚠️  Continuing with package build despite frontend build failure")
    except Exception as e:
        print(f"❌ Error running frontend build: {e}")
        print("⚠️  Continuing with package build despite frontend build failure")


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    """Build wheel with frontend pre-build step."""
    _run_frontend_build()
    return _build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    """Build source distribution with frontend pre-build step."""
    _run_frontend_build()
    return _build_sdist(sdist_directory, config_settings)