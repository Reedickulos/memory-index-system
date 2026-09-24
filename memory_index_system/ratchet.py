"""Per-machine record of the highest signed revision seen for each tree.

A valid signature only proves a manifest was signed at some point, not that
it's the latest one, so a whole older (manifest, files) pair can be restored
over a newer state and still verify. This record is the external reference
point that catches that on this machine: verify and sign refuse a revision
lower than the highest one recorded for the same tree_id.

The record is signed with the tree signing key, so without the key it can't
be forged or wound back. It can still be deleted, which resets this
machine's history; a machine with no history (fresh, or deleted) can't
detect a rollback. See docs/PROTOCOL-v2.md §5.

It lives beside the registry but in its own file: a registry rescan drops
entries for roots it wasn't given, and this history must not be lost that way.
"""

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

DEFAULT_RATCHET_PATH = Path.home() / ".memory-registry" / "ratchet.json"
RATCHET_PATH_ENV = "MEMORY_INDEX_RATCHET"
_LOCK_ATTEMPTS = 40
_LOCK_WAIT_SECONDS = 0.05


class RatchetError(Exception):
    """The record exists but can't be trusted (unreadable, malformed, or its
    signature doesn't match). Callers fail closed on this."""


def ratchet_path() -> Path:
    override = os.environ.get(RATCHET_PATH_ENV)
    return Path(override) if override else DEFAULT_RATCHET_PATH


def _sign(trees: Dict, key: bytes) -> str:
    canonical = json.dumps({"v": 1, "trees": trees}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def load(key: bytes) -> Dict:
    """Return {tree_id: {"revision", "path", "seen"}}, or {} if there's no record yet."""
    path = ratchet_path()
    if not path.exists():
        return {}
    reset_hint = f"Deleting {path} resets this machine's rollback history."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RatchetError(f"revision record {path} is unreadable ({exc}). {reset_hint}") from exc
    trees = data.get("trees") if isinstance(data, dict) else None
    recorded = data.get("signature") if isinstance(data, dict) else None
    if not isinstance(trees, dict) or not isinstance(recorded, str):
        raise RatchetError(f"revision record {path} is malformed. {reset_hint}")
    if not hmac.compare_digest(recorded, _sign(trees, key)):
        raise RatchetError(
            f"revision record {path} failed authentication — it may have been edited, or "
            f"signed with a different key. {reset_hint}"
        )
    return trees


def rollback_error(trees: Dict, tree_id, revision: int) -> Optional[str]:
    entry = trees.get(tree_id) if isinstance(tree_id, str) else None
    if entry and revision < entry["revision"]:
        return (
            f"revision {revision} is older than revision {entry['revision']} this machine "
            f"has already seen for tree {tree_id} — an older signed state may have been "
            "restored over a newer one"
        )
    return None


def seen_at_path(trees: Dict, memory: Path) -> Optional[Tuple[str, int]]:
    target = str(memory.resolve())
    for tree_id, entry in trees.items():
        if entry.get("path") == target:
            return tree_id, entry["revision"]
    return None


def record(key: bytes, tree_id: str, revision: int, memory: Path) -> Optional[str]:
    """Raise the recorded revision for tree_id to at least `revision`.

    Returns a warning (and records nothing) if another process holds the
    record's lock for too long; that weakens protection for this one update
    but mustn't fail the operation that triggered it. Raises RatchetError if
    the existing record can't be trusted.
    """
    path = ratchet_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    for _ in range(_LOCK_ATTEMPTS):
        try:
            os.close(os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            time.sleep(_LOCK_WAIT_SECONDS)
    else:
        return (
            f"revision record not updated: {lock_path} is held by another process (if nothing "
            "is running, a previous run crashed; remove the lock file)"
        )
    try:
        trees = load(key)
        entry = trees.get(tree_id)
        if entry is None or revision >= entry["revision"]:
            trees[tree_id] = {
                "revision": revision,
                "path": str(memory.resolve()),
                "seen": datetime.now(timezone.utc).isoformat(),
            }
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_text(
            json.dumps({"trees": trees, "signature": _sign(trees, key)}, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, path)
        return None
    finally:
        lock_path.unlink(missing_ok=True)
