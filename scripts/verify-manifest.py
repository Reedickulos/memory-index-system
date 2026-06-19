#!/usr/bin/env python3
"""Standalone helper: verify a .memory/ manifest."""

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Verify a .memory/ manifest.")
    parser.add_argument("memory", help="Path to .memory/ directory")
    args = parser.parse_args()

    root = Path(args.memory).resolve()
    manifest_path = root / "manifests" / "manifest.json"
    if not manifest_path.exists():
        print(f"Missing manifest: {manifest_path}", file=sys.stderr)
        return 1

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    ok = True
    for entry in manifest.get("files", []):
        path = root / entry["path"]
        if not path.exists():
            print(f"Missing: {entry['path']}", file=sys.stderr)
            ok = False
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            print(f"Mismatch: {entry['path']}", file=sys.stderr)
            ok = False

    if ok:
        print("Verification passed.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
