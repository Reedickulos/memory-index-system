"""CLI entry points."""

import argparse
import difflib
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__, registry
from .crypto import sign_manifest_v2
from .manifest import build_manifest, read_revision, read_tree_id, verify_manifest

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
    return 0


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

    if result["ok"]:
        print("Manifest verification passed.")
        if not signature["present"] or signature.get("legacy"):
            print(f"Warning: {signature['reason']}", file=sys.stderr)
        return 0

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
    return 1


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
    parsed = parser.parse_args(args)

    memory = Path(parsed.memory).resolve()
    if not (memory / "manifests").is_dir():
        print(f"Not a memory-index tree (no manifests/ directory found): {memory}", file=sys.stderr)
        return 1

    # Advisory lock closing the gap between reading the current revision and
    # writing the next one: without it, two concurrent `sign` calls on the
    # same machine could both read revision N and both believe they're clear
    # to write N+1, even with matching --expect-revision. os.O_EXCL creation
    # is atomic at the OS level, so only one caller ever wins it.
    lock_path = memory / "manifests" / ".sign.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(
            f"Another sign is already in progress on this tree ({lock_path} exists). "
            "If nothing is actually running, a previous sign may have crashed — "
            "remove the lock file and retry.",
            file=sys.stderr,
        )
        return 1

    try:
        os.close(lock_fd)

        try:
            current_revision = read_revision(memory)
            existing_tree_id = read_tree_id(memory)
        except ValueError as exc:
            print(f"Refusing to sign: {exc}", file=sys.stderr)
            return 1

        if parsed.expect_revision is not None and current_revision != parsed.expect_revision:
            print(
                f"Refusing to sign: expected revision {parsed.expect_revision}, found "
                f"{current_revision}. Someone else already updated this tree since you "
                "last read it — reload it before re-signing instead of overwriting their change.",
                file=sys.stderr,
            )
            return 1

        if existing_tree_id is None:
            # A pre-v2 manifest (or one somehow missing tree_id): adopt a
            # fresh identity now rather than staying on the legacy signature
            # format forever. Not silent -- this is a real, one-time change.
            print("No tree_id found on this manifest; minting one now (upgrading to signature format v2).")

        manifest = build_manifest(memory, revision=current_revision + 1, tree_id=existing_tree_id)
        sig = sign_manifest_v2(manifest["revision"], manifest["tree_id"], manifest["files"])
        if sig:
            manifest["signature"] = {"alg": "HMAC-SHA256-v2", "value": sig}
            print("Manifest signed with KIMI_MEMORY_KEY.")
        else:
            print("KIMI_MEMORY_KEY not set; manifest generated without signature.")
        _write_manifest_atomic(memory / "manifests" / "manifest.json", manifest)
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
        "memory-index-sign, memory-index-registry-scan/-list/-search/-diff.",
        file=sys.stderr,
    )
    sys.exit(2)
