#!/usr/bin/env python3
"""Standalone entry point: regenerate and optionally sign a manifest.

Thin wrapper over memory_index_system.cli.sign so there is exactly one
implementation to fix. Requires the package to be installed (pip install -e .);
use `memory-index-sign` directly if it's on PATH.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory_index_system.cli import sign

if __name__ == "__main__":
    sys.exit(sign())
