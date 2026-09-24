"""Tests for manifest generation and verification."""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from memory_index_system.cli import init, sign, verify
from memory_index_system.manifest import _is_safe_relative_path


def run_init(target: Path) -> int:
    return init([str(target)])


def run_sign(memory: Path) -> int:
    return sign([str(memory)])


def run_verify(memory: Path) -> int:
    return verify([str(memory)])


def test_init_creates_memory_tree():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        assert run_init(target) == 0
        memory = target / ".memory"
        assert memory.exists()
        assert (memory / "INDEX.md").exists()
        assert (memory / "manifests" / "manifest.json").exists()


def test_verify_passes_on_fresh_init():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        assert run_verify(target / ".memory") == 0


def test_verify_fails_after_modification():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        (target / ".memory" / "INDEX.md").write_text("tampered", encoding="utf-8")
        assert run_verify(target / ".memory") == 1


def test_sign_regenerates_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        manifest_path = target / ".memory" / "manifests" / "manifest.json"
        before = json.loads(manifest_path.read_text(encoding="utf-8"))
        (target / ".memory" / "episodic" / "test.md").write_text("hello", encoding="utf-8")
        run_sign(target / ".memory")
        after = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert after["file_count"] == before["file_count"] + 1


def test_sign_with_key_adds_signature():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            run_sign(target / ".memory")
            manifest = json.loads(
                (target / ".memory" / "manifests" / "manifest.json").read_text(encoding="utf-8")
            )
            assert "signature" in manifest
            assert manifest["signature"]["alg"] == "HMAC-SHA256"
        finally:
            del os.environ["KIMI_MEMORY_KEY"]


def test_verify_passes_with_correct_signature():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            run_init(target)
            assert run_verify(target / ".memory") == 0
        finally:
            del os.environ["KIMI_MEMORY_KEY"]


def test_verify_fails_on_tampered_file_with_patched_hash():
    """A manifest edited to match a tampered file must still fail, via its signature."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            run_init(target)
            memory = target / ".memory"
            index_md = memory / "INDEX.md"
            index_md.write_text("tampered", encoding="utf-8")

            manifest_path = memory / "manifests" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            new_hash = hashlib.sha256(index_md.read_bytes()).hexdigest()
            for entry in manifest["files"]:
                if entry["path"] == "INDEX.md":
                    entry["sha256"] = new_hash
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            assert run_verify(memory) == 1
        finally:
            del os.environ["KIMI_MEMORY_KEY"]


def test_verify_fails_on_signed_manifest_without_key():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            run_init(target)
        finally:
            del os.environ["KIMI_MEMORY_KEY"]
        assert run_verify(target / ".memory") == 1


def test_verify_passes_unsigned_manifest_with_warning():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)  # no KIMI_MEMORY_KEY set
        assert run_verify(target / ".memory") == 0


def test_revision_starts_at_one_and_increments_on_sign():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        manifest_path = memory / "manifests" / "manifest.json"

        assert json.loads(manifest_path.read_text(encoding="utf-8"))["revision"] == 1

        run_sign(memory)
        assert json.loads(manifest_path.read_text(encoding="utf-8"))["revision"] == 2

        run_sign(memory)
        assert json.loads(manifest_path.read_text(encoding="utf-8"))["revision"] == 3


def test_sign_with_correct_expect_revision_succeeds():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"

        rc = sign([str(memory), "--expect-revision", "1"])
        assert rc == 0
        assert json.loads(
            (memory / "manifests" / "manifest.json").read_text(encoding="utf-8")
        )["revision"] == 2


def test_sign_with_stale_expect_revision_is_refused():
    """Simulates two agents: one signs first, the other's stale --expect-revision must be refused."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"

        run_sign(memory)  # agent A signs; revision goes 1 -> 2

        # agent B still thinks the revision is 1 (stale read) and tries to sign
        rc = sign([str(memory), "--expect-revision", "1"])
        assert rc == 1
        # the on-disk manifest must be untouched by the refused attempt
        assert json.loads(
            (memory / "manifests" / "manifest.json").read_text(encoding="utf-8")
        )["revision"] == 2


def test_init_excludes_pycache_from_bundled_templates(monkeypatch):
    """A real install can get templates/*.py byte-compiled by pip; init must
    not copy __pycache__/*.pyc into the new tree or hash it into the manifest."""
    import shutil as shutil_module

    from memory_index_system import cli as cli_module

    with tempfile.TemporaryDirectory() as tmp:
        fake_template = Path(tmp) / "fake-template" / ".memory"
        shutil_module.copytree(cli_module.TEMPLATE_DIR, fake_template)

        pycache = fake_template / "scripts" / "__pycache__"
        pycache.mkdir()
        (pycache / "init-memory.cpython-313.pyc").write_bytes(b"fake bytecode")

        monkeypatch.setattr(cli_module, "TEMPLATE_DIR", fake_template)

        target = Path(tmp) / "proj"
        target.mkdir()
        assert run_init(target) == 0

        memory = target / ".memory"
        assert not (memory / "scripts" / "__pycache__").exists()

        manifest = json.loads((memory / "manifests" / "manifest.json").read_text(encoding="utf-8"))
        assert not any("__pycache__" in entry["path"] or entry["path"].endswith(".pyc") for entry in manifest["files"])


def test_verify_on_nonexistent_path_fails_cleanly(capsys):
    rc = run_verify(Path("/definitely/does/not/exist/xyz") / ".memory")
    assert rc == 1
    err = capsys.readouterr().err
    assert "Cannot verify" in err


def test_sign_on_nonexistent_path_fails_cleanly(capsys):
    rc = sign([str(Path("/definitely/does/not/exist/xyz") / ".memory")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Not a memory-index tree" in err


def test_build_manifest_ignores_os_and_editor_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"

        (memory / ".DS_Store").write_bytes(b"mac metadata")
        (memory / "Thumbs.db").write_bytes(b"windows metadata")
        (memory / "identity" / "draft.md.tmp").write_text("scratch", encoding="utf-8")
        pycache = memory / "scripts" / "__pycache__"
        pycache.mkdir()
        (pycache / "verify-manifest.cpython-313.pyc").write_bytes(b"bytecode")

        run_sign(memory)

        manifest = json.loads((memory / "manifests" / "manifest.json").read_text(encoding="utf-8"))
        paths = {entry["path"] for entry in manifest["files"]}
        assert not any(
            name in path or path.endswith((".tmp", ".pyc")) or "__pycache__" in path
            for path in paths
            for name in (".DS_Store", "Thumbs.db")
        )
        # a real, legitimate edit is still tracked
        assert "identity/draft.md.tmp" not in paths


def test_verify_fails_when_signature_stripped_but_key_available():
    """A verifier holding the key almost certainly expects signed manifests --
    an absent signature in that context should fail, not pass with a warning."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            run_init(target)
            memory = target / ".memory"
            manifest_path = memory / "manifests" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["signature"]
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            assert run_verify(memory) == 1
        finally:
            del os.environ["KIMI_MEMORY_KEY"]


def test_verify_fails_on_untracked_file():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        (memory / "semantic" / "injected.md").write_text("not tracked", encoding="utf-8")

        assert run_verify(memory) == 1


def test_verify_rejects_unsafe_manifest_paths():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        manifest_path = memory / "manifests" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].append({"path": "../../../etc/passwd", "sha256": "a" * 64})
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        assert run_verify(memory) == 1


def test_verify_fails_cleanly_on_corrupt_manifest_json(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        (memory / "manifests" / "manifest.json").write_text("{not valid json", encoding="utf-8")

        assert run_verify(memory) == 1
        assert "not valid JSON" in capsys.readouterr().err


def test_sign_fails_cleanly_on_corrupt_manifest_json(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        (memory / "manifests" / "manifest.json").write_text("{not valid json", encoding="utf-8")

        assert run_sign(memory) == 1
        assert "not valid JSON" in capsys.readouterr().err


def test_read_revision_raises_on_corrupt_manifest():
    from memory_index_system.manifest import read_revision

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        (memory / "manifests" / "manifest.json").write_text("{not valid json", encoding="utf-8")

        with pytest.raises(ValueError):
            read_revision(memory)


def test_sign_refuses_when_lock_file_present(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        lock_path = memory / "manifests" / ".sign.lock"
        lock_path.write_bytes(b"")

        rc = run_sign(memory)
        assert rc == 1
        assert "already in progress" in capsys.readouterr().err
        # the refused attempt must not have touched the manifest's revision
        manifest = json.loads((memory / "manifests" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["revision"] == 1


def test_sign_cleans_up_its_lock_file():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        run_sign(memory)
        assert not (memory / "manifests" / ".sign.lock").exists()


def test_sign_does_not_hash_its_own_lock_file():
    """The .sign.lock file exists on disk while build_manifest walks the tree
    during sign() -- it must never end up recorded in the manifest itself."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        run_sign(memory)
        manifest = json.loads((memory / "manifests" / "manifest.json").read_text(encoding="utf-8"))
        assert not any("sign.lock" in entry["path"] for entry in manifest["files"])


def test_verify_fails_on_untracked_file_named_dot_lock():
    """A real content file that happens to end in .lock must NOT be treated
    like the transient manifests/.sign.lock -- only that exact path is ignored."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        (memory / "semantic" / "injected.lock").write_text("not tracked", encoding="utf-8")

        assert run_verify(memory) == 1


def test_is_safe_relative_path_never_escapes_root_by_construction():
    """The check must reflect what root / path_str actually resolves to on
    this host, not POSIX-only assumptions -- so probe it with real
    resolution rather than asserting specific rejected strings, which would
    only be meaningful on the platform whose Path class the test runs under.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "proj" / ".memory"
        root.mkdir(parents=True)
        outside = Path(tmp) / "outside.txt"
        outside.write_text("secret", encoding="utf-8")

        candidates = [
            "identity/project-charter.md",  # genuinely safe
            "../../outside.txt",
            "../outside.txt",
            "/etc/passwd",
            "C:/Windows/System32/evil.txt",
            "C:\\Windows\\evil.txt",
            "..\\..\\outside.txt",
        ]
        for candidate in candidates:
            safe = _is_safe_relative_path(root, candidate)
            if safe:
                # If it was accepted as safe, it MUST actually resolve inside root --
                # this is the invariant the fix exists to guarantee, checked directly
                # rather than trusting the function's own answer.
                resolved = (root / candidate).resolve()
                resolved.relative_to(root.resolve())  # raises if this assertion is false


@pytest.mark.skipif(sys.platform != "win32", reason="drive-letter/backslash escape is Windows-specific")
def test_verify_rejects_windows_drive_and_backslash_paths():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        manifest_path = memory / "manifests" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].append({"path": "C:/Windows/System32/drivers/etc/hosts", "sha256": "a" * 64})
        manifest["files"].append({"path": "..\\..\\outside.txt", "sha256": "b" * 64})
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        assert run_verify(memory) == 1
