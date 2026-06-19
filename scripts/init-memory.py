#!/usr/bin/env python3
"""Standalone helper: scaffold a .memory/ tree."""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "templates" / ".memory"


def main():
    parser = argparse.ArgumentParser(description="Initialize a .memory/ tree.")
    parser.add_argument("target", help="Project directory")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    memory = target / ".memory"
    if memory.exists():
        print(f"Already exists: {memory}", file=sys.stderr)
        return 1

    shutil.copytree(ROOT, memory)
    print(f"Initialized {memory}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
