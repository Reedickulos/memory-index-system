#!/usr/bin/env python3
"""Regenerate and optionally sign manifests/manifest.json for this .memory/ tree."""

import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_revision(root: Path) -> int:
    manifest_path = root / "manifests" / "manifest.json"
    if not manifest_path.exists():
        return 0
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    return int(data.get("revision", 0))


def main():
    root = Path(__file__).resolve().parent.parent
    revision = read_revision(root) + 1
    entries = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            path = Path(dirpath) / fn
            rel = path.relative_to(root).as_posix()
            if rel == "manifests/manifest.json":
                continue
            entries.append({"path": rel, "sha256": sha256_file(path)})
    entries.sort(key=lambda x: x["path"])

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

    (root / "manifests" / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
