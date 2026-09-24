#!/usr/bin/env python3
"""Standalone entry point: verify a .memory/ manifest.

Thin wrapper over memory_index_system.cli.verify so there is exactly one
implementation to fix. Requires the package to be installed (pip install -e .);
use `memory-index-verify` directly if it's on PATH.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory_index_system.cli import verify

if __name__ == "__main__":
    sys.exit(verify())
