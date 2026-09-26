"""Manifest generation and verification."""

import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__
from .crypto import get_key, sign_files_canonical, sign_manifest_v2


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


V1_ALG = "HMAC-SHA256"
V2_ALG = "HMAC-SHA256-v2"


def read_manifest(root: Path) -> Optional[Dict]:
    """Return root's parsed manifest.json, or None if there isn't one yet.

    Raises ValueError if it exists but is unreadable, isn't a JSON object, or
    has a non-integer revision. That's corruption, not "no manifest yet":
    treating it as absent would mask it (e.g. let --expect-revision 0 through).
    """
    manifest_path = root / "manifests" / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Manifest is not valid JSON: {manifest_path}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read manifest: {manifest_path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Manifest is not a JSON object: {manifest_path}")
    revision = data.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError(f"Manifest has an invalid revision ({revision!r}): {manifest_path}")
    return data


def recorded_tree_id(manifest: Optional[Dict]) -> Optional[str]:
    """The manifest's tree_id, or None when it's absent, empty, or not a string.
    Both signers treat all three the same way: mint a fresh one, and say so."""
    tree_id = manifest.get("tree_id") if manifest else None
    return tree_id if isinstance(tree_id, str) and tree_id else None


IGNORE_DIR_NAMES = {"__pycache__"}
IGNORE_FILE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
IGNORE_FILE_SUFFIXES = (".tmp", ".swp", ".swo", ".pyc")
# The exact relative path of cli.sign()'s transient lock file -- NOT a ".lock"
# suffix rule. A suffix-based ignore would let any real content file that
# happens to end in .lock (e.g. semantic/injected.lock) bypass both manifest
# generation and the untracked-file check in verify_manifest below.
SIGN_LOCK_PATH = "manifests/.sign.lock"


def _is_ignored_file(name: str) -> bool:
    return name in IGNORE_FILE_NAMES or name.endswith(IGNORE_FILE_SUFFIXES)


def _is_safe_relative_path(root: Path, path_str: str) -> bool:
    """Reject a manifest entry path that could escape root, by actually
    joining and resolving it with the host's own Path class and checking
    containment — not by pattern-matching for '..' or a leading '/'.

    Pattern-matching against PurePosixPath rules alone is not enough: on
    Windows, "C:/Windows/x" and "..\\..\\x" are neither absolute nor
    contain a POSIX ".." component under PurePosixPath, but `root / path_str`
    a few lines later uses the *host's* Path class (WindowsPath here), which
    does treat a drive letter as absolute and a backslash as a separator —
    so a manifest crafted with either would pass a POSIX-only check and then
    genuinely escape root once joined and read. Resolving with the same Path
    class that will actually perform the join guarantees the safety check
    and the real access agree.

    Only used against paths read from a manifest.json (untrusted input from
    disk) — paths this module generates itself via _walk_files are always
    already-safe relative POSIX paths under root.
    """
    if not path_str:
        return False
    try:
        resolved = (root / path_str).resolve()
    except (OSError, ValueError):
        return False
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _walk_files(root: Path) -> List[str]:
    """List every relative POSIX path under root, except manifests/manifest.json,
    the transient sign lock file, and OS/editor artifacts (.DS_Store, Thumbs.db,
    __pycache__, *.tmp, *.swp, ...)."""
    entries: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIR_NAMES]
        for fn in filenames:
            if _is_ignored_file(fn):
                continue
            path = Path(dirpath) / fn
            rel = path.relative_to(root).as_posix()
            if rel in ("manifests/manifest.json", SIGN_LOCK_PATH):
                continue
            entries.append(rel)
    return entries


def build_manifest(root: Path, revision: int = 1, tree_id: Optional[str] = None) -> Dict:
    """Build a manifest of every file under root except manifests/manifest.json.

    `revision` is a caller-supplied monotonic counter, not something this
    function infers — see cli.sign()'s --expect-revision for how it's used
    as an optimistic-concurrency check between agents editing the same tree.

    `tree_id` is a stable identity for this tree, covered by the v2 signature
    (see crypto.sign_manifest_v2) so it can't be forged by anyone without the
    key. A fresh one is minted if not given — callers should pass the
    existing tree's tree_id (via recorded_tree_id) whenever re-signing, so the
    identity survives across revisions; only init() should let a new one be
    minted for what's genuinely a brand-new tree.
    """
    root = root.resolve()
    entries = [
        {"path": rel, "sha256": sha256_file(root / rel)} for rel in sorted(_walk_files(root))
    ]
    return {
        "project": "Memory Index System project",
        "generated": _now_iso(),
        "generator": f"memory-index-system {__version__}",
        "revision": revision,
        "tree_id": tree_id or str(uuid.uuid4()),
        "file_count": len(entries),
        "files": entries,
    }


def verify_signature(manifest: Dict, allow_legacy: bool = False) -> Dict:
    """Check manifest["signature"] against the manifest's own recorded fields.

    File hashes alone only catch accidental drift: anyone who can edit a
    tampered file can just as easily edit its hash entry in manifest.json to
    match. Reproducing the recorded HMAC (which requires the signing key) is
    what actually detects a manifest that was tampered with as a whole.

    Legacy v1 signatures are rejected unless allow_legacy is set (only
    `memory-index-migrate` sets it). From the manifest alone, a genuine
    pre-v2 tree is indistinguishable from a v2 tree an attacker downgraded to
    v1 in order to edit its revision or tree_id, so accepting v1 by default
    would let anyone strip v2's protection. See docs/PROTOCOL-v2.md §3.
    """
    recorded = manifest.get("signature")
    key = get_key()

    if recorded is None:
        if key is not None:
            # A verifier holding the key almost certainly expects signed
            # manifests. An absent signature in that context is much more
            # likely to mean "stripped after tampering" than "intentionally
            # unsigned" — someone who genuinely wanted unsigned mode wouldn't
            # have the key set when verifying.
            return {
                "present": False,
                "ok": False,
                "reason": (
                    "no signature found, but a signing key is available — "
                    "it may have been stripped after tampering"
                ),
            }
        return {
            "present": False,
            "ok": True,
            "reason": "unsigned manifest — hash checks only, no protection against an edited manifest.json",
        }

    if key is None:
        return {
            "present": True,
            "ok": False,
            "reason": "manifest is signed but MEMORY_INDEX_KEY is not set; cannot verify",
        }

    alg = recorded.get("alg") if isinstance(recorded, dict) else None
    actual = recorded.get("value") if isinstance(recorded, dict) else None

    if not isinstance(actual, str) or not actual:
        return {
            "present": True,
            "ok": False,
            "reason": "signature value is missing or not a string — manifest may have been tampered with",
        }

    if alg == V2_ALG:
        expected = sign_manifest_v2(
            manifest.get("revision", 0), manifest.get("tree_id", ""), manifest.get("files", [])
        )
        if not expected or not hmac.compare_digest(actual, expected):
            return {
                "present": True,
                "ok": False,
                "reason": (
                    "signature does not match — manifest may have been tampered with, "
                    "including its revision or tree_id (both are covered by this signature format)"
                ),
            }
        return {"present": True, "ok": True, "reason": "signature verified"}

    if alg == V1_ALG:
        if not allow_legacy:
            return {
                "present": True,
                "ok": False,
                "legacy": True,
                "reason": (
                    "legacy v1 signature (HMAC-SHA256) is not accepted: it doesn't cover revision "
                    "or tree_id, so a v2 manifest can be downgraded to it to edit either. Once a "
                    "person has confirmed this tree genuinely predates v2 (don't do this "
                    "automatically), run memory-index-migrate on it (see docs/PROTOCOL-v2.md §4)"
                ),
            }
        expected = sign_files_canonical(manifest.get("files", []))
        if not expected or not hmac.compare_digest(actual, expected):
            return {
                "present": True,
                "ok": False,
                "legacy": True,
                "reason": "signature does not match recorded files — manifest may have been tampered with",
            }
        return {
            "present": True,
            "ok": True,
            "legacy": True,
            "reason": "legacy v1 signature verified (covers files only, not revision or tree_id)",
        }

    return {
        "present": True,
        "ok": False,
        "reason": f"unrecognized signature algorithm: {alg!r}",
    }


def verify_manifest(root: Path, allow_legacy: bool = False) -> Dict:
    """Verify every file in manifests/manifest.json against disk, plus files present
    on disk but not recorded in the manifest, and the signature if present."""
    root = root.resolve()
    manifest = read_manifest(root)
    if manifest is None:
        raise FileNotFoundError(f"Manifest not found: {root / 'manifests' / 'manifest.json'}")

    failures = []
    missing = []
    unsafe = []
    recorded_paths = set()
    for entry in manifest.get("files", []):
        entry_path = entry.get("path", "")
        if not _is_safe_relative_path(root, entry_path):
            unsafe.append(entry_path)
            continue
        recorded_paths.add(entry_path)
        path = root / entry_path
        if not path.exists():
            missing.append(entry_path)
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            failures.append({"path": entry_path, "expected": entry["sha256"], "actual": actual})

    # Files present on disk but never recorded in the manifest are the most
    # likely form of tampering for a memory tree — an added file that was
    # simply never signed. Checking recorded entries against disk alone
    # can't catch this; it requires walking the tree independently too.
    extra = sorted(set(_walk_files(root)) - recorded_paths)

    signature = verify_signature(manifest, allow_legacy=allow_legacy)

    return {
        "ok": not failures and not missing and not extra and not unsafe and signature["ok"],
        "failures": failures,
        "missing": missing,
        "extra": extra,
        "unsafe": unsafe,
        "signature": signature,
        "manifest": manifest,
    }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
