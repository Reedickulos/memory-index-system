#!/usr/bin/env python3
"""Regenerate and optionally sign manifests/manifest.json for this .memory/ tree.

Self-contained on purpose: this script travels with the .memory/ tree when
it's handed to an agent or machine that doesn't have memory-index-system
installed, so it can't import the package — it duplicates just enough of
memory_index_system/manifest.py, crypto.py, and cli.py's sign() to stay
behaviorally identical to the installed package. If you change the package's
sign() or build_manifest(), mirror the change here too.
"""

import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

IGNORE_DIR_NAMES = {"__pycache__"}
IGNORE_FILE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
IGNORE_FILE_SUFFIXES = (".tmp", ".swp", ".swo", ".pyc", ".lock")


def is_ignored_file(name: str) -> bool:
    return name in IGNORE_FILE_NAMES or name.endswith(IGNORE_FILE_SUFFIXES)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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


def read_revision(root: Path) -> int:
    """Return the recorded revision, or 0 if there isn't one yet. Raises
    ValueError if manifest.json exists but isn't valid JSON -- that's
    corruption, not "no revision yet"."""
    manifest_path = root / "manifests" / "manifest.json"
    if not manifest_path.exists():
        return 0
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Manifest is not valid JSON: {manifest_path}") from exc
    return int(data.get("revision", 0))


def write_manifest_atomic(manifest_path: Path, manifest: dict) -> None:
    tmp_path = manifest_path.with_name(manifest_path.name + ".tmp")
    tmp_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp_path, manifest_path)


def main():
    root = Path(__file__).resolve().parent.parent
    lock_path = root / "manifests" / ".sign.lock"

    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(
            f"Another sign is already in progress on this tree ({lock_path} exists). "
            "If nothing is actually running, a previous sign may have crashed -- "
            "remove the lock file and retry.",
            file=sys.stderr,
        )
        return 1

    try:
        os.close(lock_fd)

        try:
            revision = read_revision(root) + 1
        except ValueError as exc:
            print(f"Refusing to sign: {exc}", file=sys.stderr)
            return 1

        entries = [{"path": rel, "sha256": sha256_file(root / rel)} for rel in sorted(walk_files(root))]

        manifest = {
            "project": "Memory Index System project",
            "generated": datetime.now(timezone.utc).isoformat(),
            "generator": "memory-index-system 0.1.0",
            "revision": revision,
            "file_count": len(entries),
            "files": entries,
        }

        key = os.environ.get("KIMI_MEMORY_KEY")
        if key:
            canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
            sig = hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
            manifest["signature"] = {"alg": "HMAC-SHA256", "value": sig}
            print("Manifest signed.")
        else:
            print("KIMI_MEMORY_KEY not set; manifest generated without signature.")

        write_manifest_atomic(root / "manifests" / "manifest.json", manifest)
        return 0
    finally:
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
