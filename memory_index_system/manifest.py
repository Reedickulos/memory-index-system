"""Manifest generation and verification."""

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root: Path) -> Dict:
    """Build a manifest of every file under root except manifests/manifest.json."""
    root = root.resolve()
    entries: List[Dict[str, str]] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            path = Path(dirpath) / fn
            rel = path.relative_to(root).as_posix()
            if rel == "manifests/manifest.json":
                continue
            entries.append({"path": rel, "sha256": sha256_file(path)})
    entries.sort(key=lambda x: x["path"])
    return {
        "project": "Memory Index System project",
        "generated": _now_iso(),
        "generator": f"memory-index-system",
        "file_count": len(entries),
        "files": entries,
    }


def verify_manifest(root: Path) -> Dict:
    """Verify every file in manifests/manifest.json against disk."""
    root = root.resolve()
    manifest_path = root / "manifests" / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    failures = []
    missing = []
    for entry in manifest.get("files", []):
        path = root / entry["path"]
        if not path.exists():
            missing.append(entry["path"])
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            failures.append({"path": entry["path"], "expected": entry["sha256"], "actual": actual})

    return {"ok": not failures and not missing, "failures": failures, "missing": missing}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
