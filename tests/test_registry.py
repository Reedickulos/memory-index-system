"""Tests for the cross-project registry."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory_index_system import registry
from memory_index_system.cli import init, registry_diff, registry_list, registry_scan, registry_search


def make_project(base: Path, name: str, charter_name: str | None = None) -> Path:
    target = base / name
    target.mkdir(parents=True)
    init([str(target)])
    if charter_name:
        charter_path = target / ".memory" / "identity" / "project-charter.md"
        text = charter_path.read_text(encoding="utf-8")
        text = text.replace(
            "## Name\n\nMy Project", f"## Name\n\n{charter_name}"
        )
        charter_path.write_text(text, encoding="utf-8")
    return target / ".memory"


def test_find_memory_trees_finds_initialized_tree():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_project(root, "proj-a")
        found = registry.find_memory_trees(root)
        assert len(found) == 1
        assert found[0].name == ".memory"


def test_find_memory_trees_ignores_uninitialized_dot_memory():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bare = root / "proj-b" / ".memory"
        bare.mkdir(parents=True)  # no manifests/manifest.json inside
        found = registry.find_memory_trees(root)
        assert found == []


def test_summarize_project_falls_back_to_humanized_name():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        memory = make_project(root, "my-cool-project")  # charter left as placeholder
        entry = registry.summarize_project(memory)
        assert entry["id"] == "my-cool-project"
        assert entry["name"] == "My Cool Project"
        assert entry["manifest_hash"].startswith("sha256:")
        assert "claim_boundary" in entry["identity_summary"]


def test_summarize_project_reads_charter_name_when_filled_in():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        memory = make_project(root, "proj-c", charter_name="Ledger Continuity")
        entry = registry.summarize_project(memory)
        assert entry["name"] == "Ledger Continuity"


def test_build_registry_aggregates_multiple_projects():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_project(root, "proj-one")
        make_project(root, "proj-two")
        built = registry.build_registry([root])
        assert built["version"] == "1.0"
        assert len(built["projects"]) == 2
        ids = {p["id"] for p in built["projects"]}
        assert ids == {"proj-one", "proj-two"}


def test_search_registry_by_query_and_tag():
    built = {
        "projects": [
            {"id": "a", "name": "Ledger", "summary": "continuity work", "tags": ["finance"], "identity_summary": {}},
            {"id": "b", "name": "Sema", "summary": "unrelated", "tags": ["research"], "identity_summary": {}},
        ]
    }
    by_query = registry.search_registry(built, query="ledger")
    assert [p["id"] for p in by_query] == ["a"]

    by_tag = registry.search_registry(built, tag="research")
    assert [p["id"] for p in by_tag] == ["b"]


def test_registry_scan_cli_writes_registry(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "projects"
        root.mkdir()
        make_project(root, "proj-x")
        registry_dir = Path(tmp) / "registry"

        rc = registry_scan([str(root), "--registry-dir", str(registry_dir)])
        assert rc == 0
        assert (registry_dir / "registry.json").exists()

        rc = registry_list(["--registry-dir", str(registry_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "proj-x" in out


def test_registry_scan_with_no_roots_fails(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        registry_dir = Path(tmp) / "registry"
        rc = registry_scan(["--registry-dir", str(registry_dir)])
        assert rc == 1


def test_registry_search_cli(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "projects"
        root.mkdir()
        make_project(root, "findable-project", charter_name="Findable Project")
        registry_dir = Path(tmp) / "registry"
        registry_scan([str(root), "--registry-dir", str(registry_dir)])

        rc = registry_search(["Findable", "--registry-dir", str(registry_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "findable-project" in out

        rc = registry_search(["no-such-thing", "--registry-dir", str(registry_dir)])
        assert rc == 1


def test_is_stale_fresh_entry_is_not_stale():
    entry = {"last_synced": datetime.now(timezone.utc).isoformat()}
    assert registry.is_stale(entry, stale_after_days=30) is False


def test_is_stale_old_entry_is_stale():
    old = datetime.now(timezone.utc) - timedelta(days=45)
    entry = {"last_synced": old.isoformat()}
    assert registry.is_stale(entry, stale_after_days=30) is True


def test_is_stale_missing_timestamp_is_stale():
    assert registry.is_stale({}) is True


def test_registry_list_marks_stale_entries(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        registry_dir = Path(tmp) / "registry"
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        fresh = datetime.now(timezone.utc).isoformat()
        reg = {
            "version": "1.0",
            "updated": fresh,
            "projects": [
                {"id": "old-proj", "name": "Old", "path": "/old", "last_synced": old},
                {"id": "fresh-proj", "name": "Fresh", "path": "/fresh", "last_synced": fresh},
            ],
        }
        registry.save_registry(reg, registry_dir)

        rc = registry_list(["--registry-dir", str(registry_dir), "--stale-days", "30"])
        assert rc == 0
        out = capsys.readouterr().out
        lines = {line.split("\t")[0]: line for line in out.strip().splitlines()}
        assert lines["[STALE] old-proj"].startswith("[STALE]")
        assert not lines["fresh-proj"].startswith("[STALE]")


def test_registry_diff_reports_no_changes_when_untouched(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "projects"
        root.mkdir()
        memory = make_project(root, "diff-proj")
        registry_dir = Path(tmp) / "registry"
        registry_scan([str(root), "--registry-dir", str(registry_dir)])

        rc = registry_diff([str(memory), "--registry-dir", str(registry_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No changes since last scan." in out


def test_registry_diff_shows_unified_diff_after_edit(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "projects"
        root.mkdir()
        memory = make_project(root, "diff-proj2")
        registry_dir = Path(tmp) / "registry"
        registry_scan([str(root), "--registry-dir", str(registry_dir)])

        charter_path = memory / "identity" / "project-charter.md"
        charter_path.write_text(
            charter_path.read_text(encoding="utf-8").replace("My Project", "Renamed Project"),
            encoding="utf-8",
        )

        rc = registry_diff([str(memory), "--registry-dir", str(registry_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "-My Project" in out
        assert "+Renamed Project" in out


def test_registry_diff_unknown_project_fails(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "projects"
        root.mkdir()
        memory = make_project(root, "unregistered-proj")
        registry_dir = Path(tmp) / "registry"  # never scanned

        rc = registry_diff([str(memory), "--registry-dir", str(registry_dir)])
        assert rc == 1
