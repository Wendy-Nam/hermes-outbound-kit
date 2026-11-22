"""Internal package bootstrap for Hermes Outbound Kit."""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
LAYER_DIRS = (
    SRC_ROOT / "core",
    SRC_ROOT / "profile",
    SRC_ROOT / "pipelines",
    SRC_ROOT / "setup",
)


def ensure_paths() -> Path:
    """Register project root and src layers on sys.path once."""
    for directory in (PROJECT_ROOT, *LAYER_DIRS):
        text = str(directory)
        if text not in sys.path:
            sys.path.insert(0, text)
    return PROJECT_ROOT


ensure_paths()
