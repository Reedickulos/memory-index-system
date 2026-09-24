"""CLI entry points."""

import argparse
import difflib
import json
import shutil
import sys
from pathlib import Path

from . import __version__, registry
from .crypto import sign_files_canonical
from .manifest import build_manifest, read_revision, verify_manifest

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / ".memory"


def init(args=None):
    parser = argparse.ArgumentParser(description="Initialize a .memory/ tree in a project.")
    parser.add_argument("target", help="Project directory to scaffold .memory/ into")
    parsed = parser.parse_args(args)

    target = Path(parsed.target).resolve()
    memory = target / ".memory"
    if memory.exists():
        print(f"Memory tree already exists: {memory}", file=sys.stderr)
        return 1

    shutil.copytree(TEMPLATE_DIR, memory)
    # Generate initial manifest
    manifest = build_manifest(memory)
    sig = sign_files_canonical(manifest["files"])
    if sig:
        manifest["signature"] = {"alg": "HMAC-SHA256", "value": sig}
    (memory / "manifests" / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Initialized memory tree at {memory}")
    return 0


def verify(args=None):
    parser = argparse.ArgumentParser(description="Verify integrity of a .memory/ tree.")
    parser.add_argument("memory", help="Path to .memory/ directory")
    parsed = parser.parse_args(args)

    result = verify_manifest(Path(parsed.memory))
    signature = result["signature"]

    if result["ok"]:
        print("Manifest verification passed.")
        if not signature["present"]:
            print(f"Warning: {signature['reason']}", file=sys.stderr)
        return 0

    if result["missing"]:
        print("Missing files:", ", ".join(result["missing"]), file=sys.stderr)
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
    current_revision = read_revision(memory)

    if parsed.expect_revision is not None and current_revision != parsed.expect_revision:
        print(
            f"Refusing to sign: expected revision {parsed.expect_revision}, found "
            f"{current_revision}. Someone else already updated this tree since you "
            "last read it — reload it before re-signing instead of overwriting their change.",
            file=sys.stderr,
        )
        return 1

    manifest = build_manifest(memory, revision=current_revision + 1)
    sig = sign_files_canonical(manifest["files"])
    if sig:
        manifest["signature"] = {"alg": "HMAC-SHA256", "value": sig}
        print("Manifest signed with KIMI_MEMORY_KEY.")
    else:
        print("KIMI_MEMORY_KEY not set; manifest generated without signature.")
    (memory / "manifests" / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return 0


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

    reg = registry.load_registry(Path(parsed.registry_dir))
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

    reg = registry.load_registry(Path(parsed.registry_dir))
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
    reg = registry.load_registry(Path(parsed.registry_dir))
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
    sys.exit(init())
