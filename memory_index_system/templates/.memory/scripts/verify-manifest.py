#!/usr/bin/env python3
"""Verify integrity of this .memory/ tree.

Self-contained on purpose: this script travels with the .memory/ tree when
it's handed to an agent or machine that doesn't have memory-index-system
installed, so it can't import the package — it duplicates just enough of
memory_index_system/manifest.py and crypto.py to check hashes and signature.
"""

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sign_files_canonical(files):
    key = os.environ.get("KIMI_MEMORY_KEY")
    if not key:
        return None
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def main():
    root = Path(__file__).resolve().parent.parent
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
            print(f"Hash mismatch: {entry['path']}", file=sys.stderr)
            ok = False

    # Hashes alone only catch a file that drifted from manifest.json — not a
    # manifest.json edited to match a tampered file. The signature is what
    # actually protects against that, so check it when one is recorded.
    recorded = manifest.get("signature")
    if recorded is None:
        print("Warning: unsigned manifest — hash checks only, no protection against an edited manifest.json", file=sys.stderr)
    else:
        expected = sign_files_canonical(manifest.get("files", []))
        actual_sig = recorded.get("value") if isinstance(recorded, dict) else None
        if not expected:
            print("Signature check failed: manifest is signed but KIMI_MEMORY_KEY is not set; cannot verify", file=sys.stderr)
            ok = False
        elif not actual_sig or not hmac.compare_digest(actual_sig, expected):
            print("Signature check failed: signature does not match recorded files — manifest may have been tampered with", file=sys.stderr)
            ok = False

    if ok:
        print("Verification passed.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
