#!/usr/bin/env python3
"""Standalone entry point: scaffold a .memory/ tree.

Thin wrapper over memory_index_system.cli.init so there is exactly one
implementation to fix. Requires the package to be installed (pip install -e .);
use `memory-index-init` directly if it's on PATH.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory_index_system.cli import init

if __name__ == "__main__":
    sys.exit(init())
