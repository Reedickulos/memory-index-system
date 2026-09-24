"""CLI entry points."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
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


if __name__ == "__main__":
    sys.exit(init())
