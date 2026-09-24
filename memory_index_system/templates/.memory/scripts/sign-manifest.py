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
import uuid
from datetime import datetime, timezone
from pathlib import Path

IGNORE_DIR_NAMES = {"__pycache__"}
IGNORE_FILE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
IGNORE_FILE_SUFFIXES = (".tmp", ".swp", ".swo", ".pyc")
# Exact relative path of the transient sign lock file -- not a ".lock" suffix
# rule, which would let a real content file named e.g. injected.lock bypass
# manifest generation and the untracked-file check entirely.
SIGN_LOCK_PATH = "manifests/.sign.lock"


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
            if rel in ("manifests/manifest.json", SIGN_LOCK_PATH):
                continue
            entries.append(rel)
    return entries


def read_manifest(root: Path):
    """Return the parsed manifest.json, or None if there isn't one yet. Raises
    ValueError if it exists but is unreadable, isn't a JSON object, or has a
    non-integer revision -- that's corruption, not "no manifest yet"."""
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


def sign_manifest_v2(key: str, revision, tree_id, files) -> str:
    payload = {"v": 2, "revision": revision, "tree_id": tree_id, "files": files}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def authentication_error(previous, key: str, adopt_unsigned: bool):
    """Why the current manifest's revision/tree_id can't be trusted enough to
    carry forward into a new signature, or None if they can. Mirrors the
    installed package's sign()."""
    recorded = previous.get("signature") if previous else None
    if recorded is None:
        if adopt_unsigned:
            return None
        state = "missing" if previous is None else "unsigned"
        return (
            f"the current manifest is {state}, so its revision and tree_id can't be "
            "authenticated (a stripped signature looks the same). If this tree was created "
            "without a key, pass --adopt-unsigned once to sign it as-is."
        )
    alg = recorded.get("alg") if isinstance(recorded, dict) else None
    value = recorded.get("value") if isinstance(recorded, dict) else None
    if alg == "HMAC-SHA256":
        return (
            "the current manifest has a legacy v1 signature, which doesn't cover revision or "
            "tree_id. Once a person has confirmed this tree genuinely predates v2 (don't do "
            "this automatically), run the installed memory-index-migrate on it."
        )
    if alg != "HMAC-SHA256-v2":
        return f"unrecognized signature algorithm: {alg!r}"
    if not isinstance(value, str) or not value:
        return "signature value is missing or not a string"
    expected = sign_manifest_v2(
        key, previous.get("revision", 0), previous.get("tree_id", ""), previous.get("files", [])
    )
    if not hmac.compare_digest(value, expected):
        return "signature does not match -- manifest may have been tampered with"
    return None


def write_manifest_atomic(manifest_path: Path, manifest: dict) -> None:
    tmp_path = manifest_path.with_name(manifest_path.name + ".tmp")
    tmp_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp_path, manifest_path)


def main():
    args = sys.argv[1:]
    unknown = [a for a in args if a != "--adopt-unsigned"]
    if unknown:
        print(f"Unrecognized arguments: {' '.join(unknown)} (only --adopt-unsigned is supported)", file=sys.stderr)
        return 2
    adopt_unsigned = "--adopt-unsigned" in args

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
            previous = read_manifest(root)
        except ValueError as exc:
            print(f"Refusing to sign: {exc}", file=sys.stderr)
            return 1

        key = os.environ.get("KIMI_MEMORY_KEY")
        if key:
            error = authentication_error(previous, key, adopt_unsigned)
            if error:
                print(f"Refusing to sign: {error}", file=sys.stderr)
                return 1
        elif previous is not None and previous.get("signature") is not None:
            print(
                "Refusing to sign: the current manifest is signed, but KIMI_MEMORY_KEY is not "
                "set. Writing it back unsigned would strip its signature. Set the key and retry.",
                file=sys.stderr,
            )
            return 1

        revision = (previous.get("revision", 0) if previous else 0) + 1
        tree_id = previous.get("tree_id") if previous else None
        if not isinstance(tree_id, str) or not tree_id:
            tree_id = str(uuid.uuid4())
            print("No tree_id found on this manifest; minting one now.")
            # NOTE: unlike memory_index_system.cli.sign(), this standalone script
            # can't refresh its sibling verify-manifest.py -- it has no newer
            # template to copy from. If that verifier predates v2, it will
            # reject the v2 manifest written below; run the installed
            # `memory-index-sign` once (it syncs scripts/ on every run), or
            # replace scripts/verify-manifest.py by hand.

        entries = [{"path": rel, "sha256": sha256_file(root / rel)} for rel in sorted(walk_files(root))]

        manifest = {
            "project": "Memory Index System project",
            "generated": datetime.now(timezone.utc).isoformat(),
            "generator": "memory-index-system 0.1.0",
            "revision": revision,
            "tree_id": tree_id,
            "file_count": len(entries),
            "files": entries,
        }

        if key:
            sig = sign_manifest_v2(key, revision, tree_id, entries)
            manifest["signature"] = {"alg": "HMAC-SHA256-v2", "value": sig}
            print("Manifest signed.")
        else:
            print("KIMI_MEMORY_KEY not set; manifest generated without signature.")

        write_manifest_atomic(root / "manifests" / "manifest.json", manifest)
        return 0
    finally:
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
