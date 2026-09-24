"""Cross-project registry: index every .memory/ tree found under configured roots.

Lets an agent discover other projects' memory trees before starting work —
the "step 0 of the boot sequence" this system is meant to support — without
granting broad filesystem access. The registry only stores what identity/
already publishes about each project (charter, claim boundary) plus a
manifest hash; it never copies in episodic/semantic/procedural content.

Deliberately not implemented here: a "god nodes" field naming the most
central/influential memory entries. That concept traces back to a per-agent
"cognitive companion" design that was reverted from this repo pending a
privacy review that has not happened — reintroducing it here, even as a
data field, would resurrect that design without the review it's waiting on.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .manifest import sha256_file

DEFAULT_REGISTRY_DIR = Path.home() / ".memory-registry"
REGISTRY_FILENAME = "registry.json"
SCAN_ROOTS_FILENAME = "scan-roots.json"
DEFAULT_MAX_DEPTH = 6
DEFAULT_STALE_DAYS = 30
SKIP_DIR_NAMES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".memory-registry"}
SUMMARY_CHARS = 250
CHARTER_NAME_PLACEHOLDER = "My Project"

_NAME_RE = re.compile(r"^##\s*Name\s*\n+([^\n#]+)", re.MULTILINE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _humanize(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title()


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _project_name(charter_text: str, project_id: str) -> str:
    match = _NAME_RE.search(charter_text)
    if match:
        name = match.group(1).strip()
        if name and name != CHARTER_NAME_PLACEHOLDER:
            return name
    return _humanize(project_id)


def find_memory_trees(root: Path, max_depth: int = DEFAULT_MAX_DEPTH) -> List[Path]:
    """Find every .memory/ directory under root that has a manifest.

    A bare `.memory/` folder without a manifest (e.g. scaffolded some other
    way, or mid-init) is not considered an indexed tree.
    """
    root = root.resolve()
    found: List[Path] = []
    root_depth = len(root.parts)

    for dirpath, dirnames, _filenames in os.walk(root):
        current = Path(dirpath)
        depth = len(current.parts) - root_depth
        if depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]

        if current.name == ".memory" and (current / "manifests" / "manifest.json").exists():
            found.append(current)
            dirnames[:] = []  # don't look for memory trees nested inside one

    return found


def summarize_project(memory_dir: Path) -> Dict:
    """Build one registry entry from a .memory/ tree's published identity files."""
    memory_dir = memory_dir.resolve()
    project_id = memory_dir.parent.name

    manifest_path = memory_dir / "manifests" / "manifest.json"
    manifest_hash = f"sha256:{sha256_file(manifest_path)}" if manifest_path.exists() else None

    charter = _read_text(memory_dir / "identity" / "project-charter.md")
    claim_boundary = _read_text(memory_dir / "identity" / "claim-boundary.md")

    return {
        "id": project_id,
        "path": str(memory_dir),
        "name": _project_name(charter, project_id),
        "summary": charter[:SUMMARY_CHARS],
        "tags": [],
        "status": "active",
        "last_synced": _now_iso(),
        "manifest_hash": manifest_hash,
        "identity_summary": {
            "charter": charter,
            "claim_boundary": claim_boundary,
        },
    }


def build_registry(roots: List[Path], max_depth: int = DEFAULT_MAX_DEPTH) -> Dict:
    trees: List[Path] = []
    for root in roots:
        trees.extend(find_memory_trees(Path(root), max_depth=max_depth))

    unique_trees = sorted(set(trees))
    projects = [summarize_project(tree) for tree in unique_trees]
    return {
        "version": "1.0",
        "updated": _now_iso(),
        "projects": projects,
    }


def load_registry(registry_dir: Path = DEFAULT_REGISTRY_DIR) -> Dict:
    path = Path(registry_dir) / REGISTRY_FILENAME
    if not path.exists():
        return {"version": "1.0", "updated": None, "projects": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(registry: Dict, registry_dir: Path = DEFAULT_REGISTRY_DIR) -> Path:
    registry_dir = Path(registry_dir)
    registry_dir.mkdir(parents=True, exist_ok=True)
    path = registry_dir / REGISTRY_FILENAME
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return path


def load_scan_roots(registry_dir: Path = DEFAULT_REGISTRY_DIR) -> List[Path]:
    path = Path(registry_dir) / SCAN_ROOTS_FILENAME
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    data = json.loads(raw)
    return [Path(p) for p in data.get("roots", [])]


def save_scan_roots(roots: List[Path], registry_dir: Path = DEFAULT_REGISTRY_DIR) -> Path:
    registry_dir = Path(registry_dir)
    registry_dir.mkdir(parents=True, exist_ok=True)
    path = registry_dir / SCAN_ROOTS_FILENAME
    existing = load_scan_roots(registry_dir)
    combined = sorted({str(Path(p).resolve()) for p in [*existing, *roots]})
    path.write_text(json.dumps({"roots": combined}, indent=2), encoding="utf-8")
    return path


def is_stale(entry: Dict, stale_after_days: int = DEFAULT_STALE_DAYS, now: Optional[datetime] = None) -> bool:
    """A stale entry hasn't been rescanned recently enough to trust its identity_summary as current."""
    last_synced = entry.get("last_synced")
    if not last_synced:
        return True
    try:
        synced_at = datetime.fromisoformat(last_synced)
    except ValueError:
        return True
    if now is None:
        now = datetime.now(timezone.utc)
    return (now - synced_at).total_seconds() > stale_after_days * 86400


def search_registry(registry: Dict, query: Optional[str] = None, tag: Optional[str] = None) -> List[Dict]:
    projects = registry.get("projects", [])

    if tag:
        projects = [p for p in projects if tag in p.get("tags", [])]

    if query:
        needle = query.lower()

        def matches(p: Dict) -> bool:
            haystack = " ".join(
                [
                    p.get("name", ""),
                    p.get("summary", ""),
                    p.get("identity_summary", {}).get("charter", ""),
                    p.get("identity_summary", {}).get("claim_boundary", ""),
                ]
            ).lower()
            return needle in haystack

        projects = [p for p in projects if matches(p)]

    return projects
