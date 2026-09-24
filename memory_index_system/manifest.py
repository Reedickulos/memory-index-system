"""Manifest generation and verification."""

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Dict, List

from . import __version__
from .crypto import get_key, sign_files_canonical


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
        "generator": f"memory-index-system {__version__}",
        "file_count": len(entries),
        "files": entries,
    }


def verify_signature(manifest: Dict) -> Dict:
    """Check manifest["signature"] against manifest["files"], if a signature is present.

    File hashes alone only catch accidental drift: anyone who can edit a
    tampered file can just as easily edit its hash entry in manifest.json to
    match. Reproducing the recorded HMAC (which requires the signing key) is
    what actually detects a manifest that was tampered with as a whole.
    """
    recorded = manifest.get("signature")
    if recorded is None:
        return {
            "present": False,
            "ok": True,
            "reason": "unsigned manifest — hash checks only, no protection against an edited manifest.json",
        }

    key = get_key()
    if key is None:
        return {
            "present": True,
            "ok": False,
            "reason": "manifest is signed but KIMI_MEMORY_KEY is not set; cannot verify",
        }

    expected = sign_files_canonical(manifest.get("files", []))
    actual = recorded.get("value") if isinstance(recorded, dict) else None
    if not actual or not expected or not hmac.compare_digest(actual, expected):
        return {
            "present": True,
            "ok": False,
            "reason": "signature does not match recorded files — manifest may have been tampered with",
        }

    return {"present": True, "ok": True, "reason": "signature verified"}


def verify_manifest(root: Path) -> Dict:
    """Verify every file in manifests/manifest.json against disk, and its signature if present."""
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

    signature = verify_signature(manifest)

    return {
        "ok": not failures and not missing and signature["ok"],
        "failures": failures,
        "missing": missing,
        "signature": signature,
    }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
