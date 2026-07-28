"""Setuptools build backend that bundles the production web application."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from setuptools import build_meta as _setuptools


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"


def _build_frontend() -> None:
    """Install locked frontend dependencies and generate package assets."""
    if os.environ.get("AGENT_DASHBOARD_SKIP_WEB_BUILD") == "1":
        return
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(
            "npm is required to build agent-dashboard web assets; install Node.js "
            "or set AGENT_DASHBOARD_SKIP_WEB_BUILD=1 to package the fallback UI"
        )
    subprocess.run([npm, "ci"], cwd=FRONTEND, check=True)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    _build_frontend()
    return _setuptools.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    _build_frontend()
    return _setuptools.build_editable(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    _build_frontend()
    return _setuptools.build_sdist(sdist_directory, config_settings)


def __getattr__(name):
    return getattr(_setuptools, name)
