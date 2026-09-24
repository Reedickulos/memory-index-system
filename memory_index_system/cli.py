"""CLI entry points."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__, registry
from .crypto import sign_files_canonical
from .manifest import build_manifest, verify_manifest

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
    parsed = parser.parse_args(args)

    memory = Path(parsed.memory).resolve()
    manifest = build_manifest(memory)
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
    parsed = parser.parse_args(args)

    reg = registry.load_registry(Path(parsed.registry_dir))
    projects = reg.get("projects", [])
    if not projects:
        print("Registry is empty. Run memory-index-registry-scan first.", file=sys.stderr)
        return 1
    for p in projects:
        print(f"{p['id']}\t{p['name']}\t{p['path']}")
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


if __name__ == "__main__":
    sys.exit(init())
