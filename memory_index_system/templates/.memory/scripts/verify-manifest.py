#!/usr/bin/env python3
"""Verify integrity of this .memory/ tree.

Self-contained on purpose: this script travels with the .memory/ tree when
it's handed to an agent or machine that doesn't have memory-index-system
installed, so it can't import the package — it duplicates just enough of
memory_index_system/manifest.py and crypto.py to stay behaviorally identical
to the installed package's verify(). If you change manifest.verify_manifest()
or verify_signature(), mirror the change here too.
"""

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path, PurePosixPath

IGNORE_DIR_NAMES = {"__pycache__"}
IGNORE_FILE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
IGNORE_FILE_SUFFIXES = (".tmp", ".swp", ".swo", ".pyc", ".lock")


def is_ignored_file(name: str) -> bool:
    return name in IGNORE_FILE_NAMES or name.endswith(IGNORE_FILE_SUFFIXES)


def is_safe_relative_path(path_str: str) -> bool:
    if not path_str:
        return False
    p = PurePosixPath(path_str)
    return not p.is_absolute() and ".." not in p.parts


def walk_files(root: Path):
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIR_NAMES]
        for fn in filenames:
            if is_ignored_file(fn):
                continue
            path = Path(dirpath) / fn
            rel = path.relative_to(root).as_posix()
            if rel == "manifests/manifest.json":
                continue
            entries.append(rel)
    return entries


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

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"Manifest is not valid JSON: {manifest_path}", file=sys.stderr)
        return 1

    ok = True
    recorded_paths = set()
    for entry in manifest.get("files", []):
        entry_path = entry.get("path", "")
        if not is_safe_relative_path(entry_path):
            print(f"Rejected manifest entry (unsafe path): {entry_path}", file=sys.stderr)
            ok = False
            continue
        recorded_paths.add(entry_path)
        path = root / entry_path
        if not path.exists():
            print(f"Missing: {entry_path}", file=sys.stderr)
            ok = False
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            print(f"Hash mismatch: {entry_path}", file=sys.stderr)
            ok = False

    # Files present on disk but never recorded in the manifest are the most
    # likely form of tampering -- an added file that was simply never signed.
    extra = sorted(set(walk_files(root)) - recorded_paths)
    if extra:
        print(f"Untracked files (present on disk, not in manifest): {', '.join(extra)}", file=sys.stderr)
        ok = False

    # Hashes alone only catch a file that drifted from manifest.json -- not a
    # manifest.json edited to match a tampered file. The signature is what
    # actually protects against that, so check it when one is recorded.
    recorded = manifest.get("signature")
    key = os.environ.get("KIMI_MEMORY_KEY")
    if recorded is None:
        if key:
            # A verifier holding the key almost certainly expects signed
            # manifests -- an absent signature here is more likely stripped
            # than intentional.
            print(
                "Signature check failed: no signature found, but a signing key is "
                "available -- it may have been stripped after tampering",
                file=sys.stderr,
            )
            ok = False
        else:
            print(
                "Warning: unsigned manifest — hash checks only, no protection against an edited manifest.json",
                file=sys.stderr,
            )
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
