"""CLI entry points."""

import argparse
import difflib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from . import __version__, ratchet, registry
from .crypto import get_key, sign_manifest_v2
from .manifest import (
    V1_ALG,
    V2_ALG,
    build_manifest,
    read_manifest,
    recorded_tree_id,
    verify_manifest,
    verify_signature,
)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / ".memory"


def _load_registry_or_none(registry_dir: Path):
    """Load the registry, printing a clean error instead of a traceback if it's corrupt."""
    try:
        return registry.load_registry(registry_dir)
    except ValueError as exc:
        print(f"Cannot read registry: {exc}", file=sys.stderr)
        return None


def _write_manifest_atomic(manifest_path: Path, manifest: dict) -> None:
    """Write manifest.json atomically via write-to-temp + os.replace.

    os.replace is atomic on both POSIX and Windows, so a crash mid-write or a
    concurrent read can never see a half-written (and therefore corrupt) file.
    """
    tmp_path = manifest_path.with_name(manifest_path.name + ".tmp")
    tmp_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp_path, manifest_path)


def init(args=None):
    parser = argparse.ArgumentParser(description="Initialize a .memory/ tree in a project.")
    parser.add_argument("target", help="Project directory to scaffold .memory/ into")
    parsed = parser.parse_args(args)

    target = Path(parsed.target).resolve()
    memory = target / ".memory"
    if memory.exists():
        print(f"Memory tree already exists: {memory}", file=sys.stderr)
        return 1

    # A real (non-editable) install can get its bundled templates/*.py
    # byte-compiled by pip; without this, copytree would pull any
    # __pycache__ into every new tree and build_manifest would hash it,
    # making verify fail later for reasons unrelated to actual content.
    shutil.copytree(TEMPLATE_DIR, memory, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # Generate initial manifest. tree_id is freshly minted here (build_manifest
    # mints one when none is given) -- this is the one place that's correct,
    # since it's genuinely a new tree; sign() below always reuses the existing one.
    manifest = build_manifest(memory)
    sig = sign_manifest_v2(manifest["revision"], manifest["tree_id"], manifest["files"])
    if sig:
        manifest["signature"] = {"alg": "HMAC-SHA256-v2", "value": sig}
    _write_manifest_atomic(memory / "manifests" / "manifest.json", manifest)
    print(f"Initialized memory tree at {memory}")
    if sig and not _record_revision(manifest, memory):
        return 1
    return 0


def _record_revision(manifest: dict, memory: Path) -> bool:
    """Record a signed manifest's revision in this machine's revision record.
    Returns False (after printing why) if the record can't be trusted."""
    try:
        warning = ratchet.record(get_key(), manifest["tree_id"], manifest["revision"], memory)
    except ratchet.RatchetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return False
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)
    return True


def _rollback_refusal(manifest: dict) -> Optional[str]:
    """Why this signed manifest's revision can't be accepted on this machine,
    or None. Only meaningful with the key set: without it neither the
    manifest's revision nor the record itself can be authenticated."""
    try:
        trees = ratchet.load(get_key())
    except ratchet.RatchetError as exc:
        return str(exc)
    return ratchet.rollback_error(trees, manifest.get("tree_id"), manifest.get("revision", 0))


def verify(args=None):
    parser = argparse.ArgumentParser(description="Verify integrity of a .memory/ tree.")
    parser.add_argument("memory", help="Path to .memory/ directory")
    parsed = parser.parse_args(args)

    try:
        result = verify_manifest(Path(parsed.memory))
    except (FileNotFoundError, ValueError) as exc:
        print(f"Cannot verify: {exc}", file=sys.stderr)
        return 1
    signature = result["signature"]

    if not result["ok"]:
        _report_verify_failures(result)
        return 1

    # A signature that passed with the key set is a v2 one, so its revision
    # is authentic; checking it against this machine's record is what
    # catches an older signed state restored over a newer one. The record is
    # only raised after the whole tree has passed.
    if signature["present"]:
        refusal = _rollback_refusal(result["manifest"])
        if refusal:
            print(f"Rollback check failed: {refusal}", file=sys.stderr)
            return 1
        if not _record_revision(result["manifest"], Path(parsed.memory)):
            return 1

    print("Manifest verification passed.")
    if not signature["present"]:
        print(f"Warning: {signature['reason']}", file=sys.stderr)
    return 0


def _report_verify_failures(result: dict) -> None:
    signature = result["signature"]
    if result["missing"]:
        print("Missing files:", ", ".join(result["missing"]), file=sys.stderr)
    if result["extra"]:
        print("Untracked files (present on disk, not in manifest):", ", ".join(result["extra"]), file=sys.stderr)
    if result["unsafe"]:
        print("Rejected manifest entries (unsafe path):", ", ".join(result["unsafe"]), file=sys.stderr)
    for failure in result["failures"]:
        print(
            f"Hash mismatch: {failure['path']}",
            file=sys.stderr,
        )
    if not signature["ok"]:
        print(f"Signature check failed: {signature['reason']}", file=sys.stderr)


def _acquire_sign_lock(memory: Path):
    """Take the tree's advisory sign lock; return its path, or None (after
    printing why) if another sign already holds it.

    It closes the gap between reading the current revision and writing the
    next one: without it, two concurrent signs could both read revision N and
    both believe they're clear to write N+1, even with matching
    --expect-revision. os.O_EXCL creation is atomic, so only one caller wins.
    """
    lock_path = memory / "manifests" / ".sign.lock"
    try:
        os.close(os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        print(
            f"Another sign is already in progress on this tree ({lock_path} exists). "
            "If nothing is actually running, a previous sign may have crashed — "
            "remove the lock file and retry.",
            file=sys.stderr,
        )
        return None
    return lock_path


def _write_signed_manifest(memory: Path, revision: int, tree_id) -> bool:
    """Write and (with the key set) sign the next manifest, then record it in
    this machine's revision record. Returns False if recording failed."""
    if tree_id is None:
        print("No tree_id found on this manifest; minting one now.")

    # Every run, not only when minting a tree_id: a tree can already carry a
    # tree_id and a v2 signature while its bundled verify-manifest.py still
    # predates v2 (e.g. it was adopted by the bundled sign-manifest.py, which
    # can't replace its sibling). The refreshed files are hashed below, so
    # they're covered by the signature like everything else in the tree.
    shutil.copytree(
        TEMPLATE_DIR / "scripts",
        memory / "scripts",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        dirs_exist_ok=True,
    )

    manifest = build_manifest(memory, revision=revision, tree_id=tree_id)
    sig = sign_manifest_v2(manifest["revision"], manifest["tree_id"], manifest["files"])
    if sig:
        manifest["signature"] = {"alg": V2_ALG, "value": sig}
        print("Manifest signed.")
    else:
        print("MEMORY_INDEX_KEY not set; manifest generated without signature.")
    _write_manifest_atomic(memory / "manifests" / "manifest.json", manifest)
    return not sig or _record_revision(manifest, memory)


def sign(args=None):
    parser = argparse.ArgumentParser(description="Regenerate and optionally sign the manifest.")
    parser.add_argument("memory", help="Path to .memory/ directory")
    parser.add_argument(
        "--expect-revision",
        type=int,
        help=(
            "Fail unless the on-disk manifest's current revision equals this. "
            "Optimistic-concurrency check: catches two agents re-signing the "
            "same tree without knowing about each other's change."
        ),
    )
    parser.add_argument(
        "--adopt-unsigned",
        action="store_true",
        help=(
            "With MEMORY_INDEX_KEY set, allow signing a tree whose current manifest is "
            "missing or unsigned (e.g. one created before a key existed). Its revision "
            "and tree_id can't be authenticated, so they're taken as-is. Needed once per tree."
        ),
    )
    parsed = parser.parse_args(args)

    memory = Path(parsed.memory).resolve()
    if not (memory / "manifests").is_dir():
        print(f"Not a memory-index tree (no manifests/ directory found): {memory}", file=sys.stderr)
        return 1

    lock_path = _acquire_sign_lock(memory)
    if lock_path is None:
        return 1

    try:
        try:
            previous = read_manifest(memory)
        except ValueError as exc:
            print(f"Refusing to sign: {exc}", file=sys.stderr)
            return 1

        # revision and tree_id are carried forward from the current manifest,
        # so they must be authentic before they're signed again: otherwise
        # anyone without the key could edit either and have the next
        # legitimate sign bless it. Only the manifest's own recorded contents
        # are checked here, not the files on disk -- those are expected to
        # have changed, since re-hashing them is what sign is for.
        if get_key() is not None:
            recorded = previous.get("signature") if previous else None
            if recorded is None:
                if not parsed.adopt_unsigned:
                    state = "missing" if previous is None else "unsigned"
                    print(
                        f"Refusing to sign: the current manifest is {state}, so its revision and "
                        "tree_id can't be authenticated (a stripped signature looks the same). "
                        "If this tree was created without a key, pass --adopt-unsigned once to "
                        "sign it as-is.",
                        file=sys.stderr,
                    )
                    return 1
            else:
                check = verify_signature(previous)
                if not check["ok"]:
                    print(
                        f"Refusing to sign: the current manifest failed authentication "
                        f"({check['reason']}). Signing now would carry forward a revision and "
                        "tree_id nobody verified.",
                        file=sys.stderr,
                    )
                    return 1
        elif previous is not None and previous.get("signature") is not None:
            print(
                "Refusing to sign: the current manifest is signed, but MEMORY_INDEX_KEY is not "
                "set. Writing it back unsigned would strip its signature. Set the key and retry.",
                file=sys.stderr,
            )
            return 1

        current_revision = previous.get("revision", 0) if previous else 0
        if parsed.expect_revision is not None and current_revision != parsed.expect_revision:
            print(
                f"Refusing to sign: expected revision {parsed.expect_revision}, found "
                f"{current_revision}. Someone else already updated this tree since you "
                "last read it — reload it before re-signing instead of overwriting their change.",
                file=sys.stderr,
            )
            return 1

        # Signing on top of a rolled-back state would bless it with a fresh,
        # valid signature, so refuse here rather than leave it to verify.
        if get_key() is not None and previous is not None:
            refusal = _rollback_refusal(previous)
            if refusal:
                print(f"Refusing to sign: {refusal}", file=sys.stderr)
                return 1

        if not _write_signed_manifest(memory, current_revision + 1, recorded_tree_id(previous)):
            return 1
        return 0
    finally:
        lock_path.unlink(missing_ok=True)


def migrate(args=None):
    parser = argparse.ArgumentParser(
        description=(
            "One-time upgrade of a tree signed with the legacy v1 format to v2. Verifies "
            "the tree fully under v1 first. v1 never covered revision, so the recorded "
            "revision is carried forward unauthenticated: only migrate a tree you trust "
            "hasn't been downgraded from v2."
        )
    )
    parser.add_argument("memory", help="Path to .memory/ directory")
    parsed = parser.parse_args(args)

    memory = Path(parsed.memory).resolve()
    if not (memory / "manifests").is_dir():
        print(f"Not a memory-index tree (no manifests/ directory found): {memory}", file=sys.stderr)
        return 1
    if get_key() is None:
        print("Cannot migrate: MEMORY_INDEX_KEY is not set.", file=sys.stderr)
        return 1

    lock_path = _acquire_sign_lock(memory)
    if lock_path is None:
        return 1

    try:
        try:
            previous = read_manifest(memory)
        except ValueError as exc:
            print(f"Refusing to migrate: {exc}", file=sys.stderr)
            return 1
        if previous is None:
            print("Refusing to migrate: no manifest found.", file=sys.stderr)
            return 1

        recorded = previous.get("signature")
        alg = recorded.get("alg") if isinstance(recorded, dict) else None
        if alg == V2_ALG:
            print("Already on signature format v2; nothing to migrate.")
            return 0
        if alg != V1_ALG:
            state = "unsigned" if recorded is None else f"signed with {alg!r}"
            print(
                "Refusing to migrate: only a manifest with a legacy v1 signature can be "
                f"migrated, and this one is {state}. "
                "For an unsigned tree, use memory-index-sign --adopt-unsigned.",
                file=sys.stderr,
            )
            return 1

        result = verify_manifest(memory, allow_legacy=True)
        if not result["ok"]:
            print("Refusing to migrate: the tree doesn't verify under its v1 signature.", file=sys.stderr)
            _report_verify_failures(result)
            return 1

        # A downgrade attacker can strip tree_id, but not move the tree: if
        # this machine has already seen a v2 manifest at this path, a v1 one
        # here now is what a downgrade looks like, not a pre-v2 tree.
        try:
            seen = ratchet.seen_at_path(ratchet.load(get_key()), memory)
        except ratchet.RatchetError as exc:
            print(f"Refusing to migrate: {exc}", file=sys.stderr)
            return 1
        if seen:
            print(
                f"Refusing to migrate: this machine has already seen a v2-signed tree at {memory} "
                f"(tree {seen[0]}, revision {seen[1]}), so a v1 manifest here now looks like a "
                "downgrade, not a tree that predates v2.",
                file=sys.stderr,
            )
            return 1

        revision = previous.get("revision", 0)
        print(
            f"Warning: v1 signatures never covered revision, so revision {revision} is being "
            "carried forward unauthenticated. This machine has no v2 history for this path, "
            "which is expected for a genuine pre-v2 tree but can't rule out a downgrade on "
            "a machine that never saw the tree before.",
            file=sys.stderr,
        )
        # No v1 tool ever wrote a tree_id, so one present on a v1 manifest
        # wasn't put there by a signer; don't carry it into a v2 signature.
        if not _write_signed_manifest(memory, revision + 1, None):
            return 1
        print("Migrated to signature format v2.")
        return 0
    finally:
        lock_path.unlink(missing_ok=True)


def registry_scan(args=None):
    parser = argparse.ArgumentParser(
        description="Scan filesystem roots for .memory/ trees and (re)build the registry."
    )
    parser.add_argument(
        "roots", nargs="*", help="Directories to scan, in addition to any saved scan roots"
    )
    parser.add_argument(
        "--save-roots",
        action="store_true",
        help="Remember the given roots for future scans (writes scan-roots.json)",
    )
    parser.add_argument(
        "--registry-dir",
        default=str(registry.DEFAULT_REGISTRY_DIR),
        help="Registry directory (default: %(default)s)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=registry.DEFAULT_MAX_DEPTH,
        help="Maximum directory depth to descend while scanning (default: %(default)s)",
    )
    parsed = parser.parse_args(args)

    registry_dir = Path(parsed.registry_dir)
    cli_roots = [Path(r) for r in parsed.roots]
    all_roots = registry.load_scan_roots(registry_dir) + cli_roots

    if not all_roots:
        print(
            "No roots to scan. Pass one or more directories, optionally with "
            "--save-roots to remember them for next time.",
            file=sys.stderr,
        )
        return 1

    if parsed.save_roots and cli_roots:
        registry.save_scan_roots(cli_roots, registry_dir)

    built = registry.build_registry(all_roots, max_depth=parsed.max_depth)
    path = registry.save_registry(built, registry_dir)
    print(f"Indexed {len(built['projects'])} project(s) into {path}")
    return 0


def registry_list(args=None):
    parser = argparse.ArgumentParser(description="List projects currently in the registry.")
    parser.add_argument("--registry-dir", default=str(registry.DEFAULT_REGISTRY_DIR))
    parser.add_argument(
        "--stale-days",
        type=int,
        default=registry.DEFAULT_STALE_DAYS,
        help="Flag entries not scanned in this many days as stale (default: %(default)s)",
    )
    parsed = parser.parse_args(args)

    reg = _load_registry_or_none(Path(parsed.registry_dir))
    if reg is None:
        return 1
    projects = reg.get("projects", [])
    if not projects:
        print("Registry is empty. Run memory-index-registry-scan first.", file=sys.stderr)
        return 1
    for p in projects:
        marker = "[STALE] " if registry.is_stale(p, stale_after_days=parsed.stale_days) else ""
        print(f"{marker}{p['id']}\t{p['name']}\t{p['path']}")
    return 0


def registry_search(args=None):
    parser = argparse.ArgumentParser(description="Search the registry by text and/or tag.")
    parser.add_argument("query", nargs="?", help="Text to search for in name/summary/identity files")
    parser.add_argument("--tag", help="Filter to projects with this tag")
    parser.add_argument("--registry-dir", default=str(registry.DEFAULT_REGISTRY_DIR))
    parsed = parser.parse_args(args)

    if not parsed.query and not parsed.tag:
        parser.error("provide a query, --tag, or both")

    reg = _load_registry_or_none(Path(parsed.registry_dir))
    if reg is None:
        return 1
    results = registry.search_registry(reg, query=parsed.query, tag=parsed.tag)
    if not results:
        print("No matches.")
        return 1
    for p in results:
        print(f"{p['id']}\t{p['name']}\t{p['path']}")
    return 0


def registry_diff(args=None):
    parser = argparse.ArgumentParser(
        description="Show what changed in a project's identity files since the last registry scan."
    )
    parser.add_argument("memory", help="Path to the project's .memory/ directory")
    parser.add_argument("--registry-dir", default=str(registry.DEFAULT_REGISTRY_DIR))
    parsed = parser.parse_args(args)

    memory_dir = Path(parsed.memory).resolve()
    reg = _load_registry_or_none(Path(parsed.registry_dir))
    if reg is None:
        return 1
    entry = next((p for p in reg.get("projects", []) if p.get("path") == str(memory_dir)), None)
    if entry is None:
        print(
            f"No registry entry for {memory_dir}. Run memory-index-registry-scan first.",
            file=sys.stderr,
        )
        return 1

    fields = [
        ("charter", memory_dir / "identity" / "project-charter.md"),
        ("claim_boundary", memory_dir / "identity" / "claim-boundary.md"),
    ]
    changed = False
    for field, path in fields:
        old_text = entry.get("identity_summary", {}).get(field, "")
        new_text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        if old_text == new_text:
            continue
        changed = True
        print(f"--- {field} (registry, as of {entry.get('last_synced')})")
        print(f"+++ {field} (on disk now)")
        for line in difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), lineterm=""):
            print(line)
        print()

    if not changed:
        print("No changes since last scan.")
    return 0


if __name__ == "__main__":
    print(
        "This module has no single entry point — run one of the installed "
        "commands instead: memory-index-init, memory-index-verify, "
        "memory-index-sign, memory-index-migrate, memory-index-registry-scan/-list/-search/-diff.",
        file=sys.stderr,
    )
    sys.exit(2)
