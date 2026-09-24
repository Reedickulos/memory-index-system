"""Tests for manifest generation and verification."""

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from memory_index_system.cli import init, migrate, sign, verify
from memory_index_system.crypto import sign_files_canonical
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
        os.environ["MEMORY_INDEX_KEY"] = "test-secret"
        try:
            assert sign([str(target / ".memory"), "--adopt-unsigned"]) == 0
            manifest = json.loads(
                (target / ".memory" / "manifests" / "manifest.json").read_text(encoding="utf-8")
            )
            assert "signature" in manifest
            assert manifest["signature"]["alg"] == "HMAC-SHA256-v2"
        finally:
            del os.environ["MEMORY_INDEX_KEY"]


def test_verify_passes_with_correct_signature():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        os.environ["MEMORY_INDEX_KEY"] = "test-secret"
        try:
            run_init(target)
            assert run_verify(target / ".memory") == 0
        finally:
            del os.environ["MEMORY_INDEX_KEY"]


def test_verify_fails_on_tampered_file_with_patched_hash():
    """A manifest edited to match a tampered file must still fail, via its signature."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        os.environ["MEMORY_INDEX_KEY"] = "test-secret"
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
            del os.environ["MEMORY_INDEX_KEY"]


def test_verify_fails_on_signed_manifest_without_key():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        os.environ["MEMORY_INDEX_KEY"] = "test-secret"
        try:
            run_init(target)
        finally:
            del os.environ["MEMORY_INDEX_KEY"]
        assert run_verify(target / ".memory") == 1


def test_verify_passes_unsigned_manifest_with_warning():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)  # no MEMORY_INDEX_KEY set
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
        os.environ["MEMORY_INDEX_KEY"] = "test-secret"
        try:
            run_init(target)
            memory = target / ".memory"
            manifest_path = memory / "manifests" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["signature"]
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            assert run_verify(memory) == 1
        finally:
            del os.environ["MEMORY_INDEX_KEY"]


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


@pytest.mark.parametrize("content", ["{not valid json", "[]", '{"revision": "3"}', '{"revision": -1}'])
def test_read_manifest_raises_on_corrupt_manifest(content):
    from memory_index_system.manifest import read_manifest

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        (memory / "manifests" / "manifest.json").write_text(content, encoding="utf-8")

        with pytest.raises(ValueError):
            read_manifest(memory)


@pytest.mark.parametrize("command", [lambda m: run_sign(m), lambda m: run_verify(m)])
def test_non_object_manifest_is_refused_cleanly(command, capsys):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        (memory / "manifests" / "manifest.json").write_text("[]", encoding="utf-8")

        assert command(memory) == 1
        assert "not a JSON object" in capsys.readouterr().err


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


def test_tree_id_minted_at_init_and_stable_across_signs():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        manifest_path = memory / "manifests" / "manifest.json"

        tree_id = json.loads(manifest_path.read_text(encoding="utf-8"))["tree_id"]
        assert tree_id  # non-empty

        run_sign(memory)
        run_sign(memory)
        after = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert after["tree_id"] == tree_id  # identity survives re-signing


def test_v2_signature_fails_if_revision_tampered_alone():
    """Tampering with only `revision` (files untouched) must break a v2
    signature -- v1 didn't cover revision at all, which was the point of v2."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        os.environ["MEMORY_INDEX_KEY"] = "test-secret"
        try:
            run_init(target)
            memory = target / ".memory"
            manifest_path = memory / "manifests" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["revision"] = 999  # only the revision changes; files/signature untouched
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            assert run_verify(memory) == 1
        finally:
            del os.environ["MEMORY_INDEX_KEY"]


def test_v2_signature_fails_if_tree_id_tampered_alone():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        os.environ["MEMORY_INDEX_KEY"] = "test-secret"
        try:
            run_init(target)
            memory = target / ".memory"
            manifest_path = memory / "manifests" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tree_id"] = "swapped-identity"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            assert run_verify(memory) == 1
        finally:
            del os.environ["MEMORY_INDEX_KEY"]


@pytest.fixture
def signing_key():
    os.environ["MEMORY_INDEX_KEY"] = "test-secret"
    yield
    del os.environ["MEMORY_INDEX_KEY"]


@pytest.fixture
def signed_tree(signing_key):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        yield target / ".memory"


def _manifest_path(memory: Path) -> Path:
    return memory / "manifests" / "manifest.json"


def _load(memory: Path) -> dict:
    return json.loads(_manifest_path(memory).read_text(encoding="utf-8"))


def _save(memory: Path, manifest: dict) -> None:
    _manifest_path(memory).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _relabel_as_v1(memory: Path, drop_tree_id: bool = True) -> dict:
    """Rewrite the manifest as a v1 signer would have: files-only signature."""
    manifest = _load(memory)
    if drop_tree_id:
        manifest.pop("tree_id", None)
    manifest["signature"] = {"alg": "HMAC-SHA256", "value": sign_files_canonical(manifest["files"])}
    _save(memory, manifest)
    return manifest


def test_verify_rejects_legacy_v1_signature(signed_tree, capsys):
    _relabel_as_v1(signed_tree)
    assert run_verify(signed_tree) == 1
    assert "memory-index-migrate" in capsys.readouterr().err


def test_verify_rejects_downgrade_to_v1_that_edits_revision(signed_tree):
    """Relabelling a v2 manifest with a v1 signature over the same files used
    to verify (with a warning), letting revision be edited without the key."""
    manifest = _relabel_as_v1(signed_tree, drop_tree_id=False)
    manifest["revision"] = 999
    _save(signed_tree, manifest)
    assert run_verify(signed_tree) == 1


def test_verify_fails_cleanly_on_non_string_signature_value(signed_tree, capsys):
    manifest = _load(signed_tree)
    manifest["signature"]["value"] = 12345
    _save(signed_tree, manifest)
    assert run_verify(signed_tree) == 1
    assert "not a string" in capsys.readouterr().err


def test_sign_refuses_legacy_v1_manifest(signed_tree, capsys):
    before = _relabel_as_v1(signed_tree)
    assert run_sign(signed_tree) == 1
    assert "memory-index-migrate" in capsys.readouterr().err
    assert _load(signed_tree) == before


@pytest.mark.parametrize("field,value", [("tree_id", "some-other-tree"), ("revision", 999)])
def test_sign_refuses_to_carry_forward_edited_header_field(signed_tree, field, value, capsys):
    """Editing tree_id or revision without the key used to be blessed by the
    next legitimate sign."""
    manifest = _load(signed_tree)
    manifest[field] = value
    _save(signed_tree, manifest)

    assert run_sign(signed_tree) == 1
    assert "failed authentication" in capsys.readouterr().err
    assert _load(signed_tree)[field] == value  # nothing rewritten


def test_sign_carries_forward_authenticated_header(signed_tree):
    before = _load(signed_tree)
    (signed_tree / "episodic" / "note.md").write_text("new content", encoding="utf-8")

    assert sign([str(signed_tree), "--expect-revision", "1"]) == 0
    after = _load(signed_tree)
    assert after["tree_id"] == before["tree_id"]
    assert after["revision"] == 2
    assert run_verify(signed_tree) == 0


def test_sign_refuses_unsigned_manifest_with_key_unless_adopted(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)  # no key: unsigned
        memory = target / ".memory"
        os.environ["MEMORY_INDEX_KEY"] = "test-secret"
        try:
            assert run_sign(memory) == 1
            assert "--adopt-unsigned" in capsys.readouterr().err
            assert "signature" not in _load(memory)

            assert sign([str(memory), "--adopt-unsigned"]) == 0
            assert _load(memory)["signature"]["alg"] == "HMAC-SHA256-v2"
            assert run_verify(memory) == 0
            assert run_sign(memory) == 0  # authenticated from now on, no flag needed
        finally:
            del os.environ["MEMORY_INDEX_KEY"]


def test_sign_refuses_missing_manifest_with_key(signed_tree, capsys):
    _manifest_path(signed_tree).unlink()
    assert run_sign(signed_tree) == 1
    assert "missing" in capsys.readouterr().err


@pytest.mark.parametrize("bad_tree_id", ["", 0, None])
def test_sign_mints_and_announces_tree_id_when_empty_or_invalid(bad_tree_id, capsys):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        manifest = _load(memory)
        manifest["tree_id"] = bad_tree_id
        _save(memory, manifest)

        assert run_sign(memory) == 0
        assert "minting one now" in capsys.readouterr().out
        tree_id = _load(memory)["tree_id"]
        assert isinstance(tree_id, str) and tree_id


def test_migrate_upgrades_a_verified_v1_tree(signed_tree, isolated_revision_record, capsys):
    v1 = _relabel_as_v1(signed_tree)
    isolated_revision_record.unlink()  # a genuine pre-v2 tree: no v2 history on this machine

    assert migrate([str(signed_tree)]) == 0
    assert "unauthenticated" in capsys.readouterr().err
    after = _load(signed_tree)
    assert after["signature"]["alg"] == "HMAC-SHA256-v2"
    assert after["tree_id"]
    assert after["revision"] == v1["revision"] + 1
    assert run_verify(signed_tree) == 0


def test_migrate_discards_a_tree_id_found_on_a_v1_manifest(signed_tree, isolated_revision_record):
    """No v1 tool ever wrote a tree_id, so one on a v1 manifest wasn't put
    there by a signer and mustn't end up covered by a v2 signature."""
    manifest = _relabel_as_v1(signed_tree)
    manifest["tree_id"] = "planted-by-someone"
    _save(signed_tree, manifest)
    isolated_revision_record.unlink()

    assert migrate([str(signed_tree)]) == 0
    assert _load(signed_tree)["tree_id"] != "planted-by-someone"


def test_migrate_refuses_a_v1_tree_that_does_not_verify(signed_tree, capsys):
    before = _relabel_as_v1(signed_tree)
    (signed_tree / "identity" / "project-charter.md").write_text("tampered", encoding="utf-8")

    assert migrate([str(signed_tree)]) == 1
    err = capsys.readouterr().err
    assert "doesn't verify" in err
    assert "Hash mismatch" in err
    assert _load(signed_tree) == before


def test_migrate_is_a_no_op_on_a_v2_tree(signed_tree, capsys):
    before = _load(signed_tree)
    assert migrate([str(signed_tree)]) == 0
    assert "nothing to migrate" in capsys.readouterr().out
    assert _load(signed_tree) == before


def test_migrate_refuses_an_unsigned_tree(signing_key, capsys):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        memory = target / ".memory"
        manifest = _load(memory)
        del manifest["signature"]
        _save(memory, manifest)

        assert migrate([str(memory)]) == 1
        assert "--adopt-unsigned" in capsys.readouterr().err


def test_migrate_requires_the_key(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        assert migrate([str(target / ".memory")]) == 1
        assert "MEMORY_INDEX_KEY is not set" in capsys.readouterr().err


def test_sign_without_key_refuses_to_strip_a_signed_manifest(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        os.environ["MEMORY_INDEX_KEY"] = "test-secret"
        try:
            run_init(target)
        finally:
            del os.environ["MEMORY_INDEX_KEY"]
        memory = target / ".memory"
        before = _load(memory)

        assert run_sign(memory) == 1
        assert "would strip its signature" in capsys.readouterr().err
        assert _load(memory) == before


def _snapshot(memory: Path, dest: Path) -> Path:
    shutil.copytree(memory, dest)
    return dest


def _restore(snapshot: Path, memory: Path) -> None:
    shutil.rmtree(memory)
    shutil.copytree(snapshot, memory)


def _recorded_revision(memory: Path):
    from memory_index_system import ratchet

    tree_id = _load(memory)["tree_id"]
    entry = ratchet.load(b"test-secret").get(tree_id)
    return entry["revision"] if entry else None


def test_verify_refuses_an_older_signed_state_restored_over_a_newer_one(signed_tree, tmp_path, capsys):
    """Rollback: every hash and the signature of the restored state are
    genuine, so only the revision record can catch it."""
    old = _snapshot(signed_tree, tmp_path / "rev1")
    (signed_tree / "episodic" / "note.md").write_text("newer", encoding="utf-8")
    assert run_sign(signed_tree) == 0
    assert run_verify(signed_tree) == 0

    _restore(old, signed_tree)
    capsys.readouterr()
    assert run_verify(signed_tree) == 1
    assert "Rollback check failed" in capsys.readouterr().err


def test_sign_refuses_to_build_on_a_rolled_back_state(signed_tree, tmp_path, capsys):
    old = _snapshot(signed_tree, tmp_path / "rev1")
    assert run_sign(signed_tree) == 0

    _restore(old, signed_tree)
    before = _load(signed_tree)
    assert run_sign(signed_tree) == 1
    assert "older than revision 2" in capsys.readouterr().err
    assert _load(signed_tree) == before


def test_verify_only_raises_the_record_after_a_full_pass(signed_tree):
    assert _recorded_revision(signed_tree) == 1  # init records its revision
    assert run_sign(signed_tree) == 0
    assert _recorded_revision(signed_tree) == 2

    from memory_index_system import ratchet

    manifest = _load(signed_tree)
    ratchet_path = ratchet.ratchet_path()
    trees = json.loads(ratchet_path.read_text(encoding="utf-8"))
    ratchet_path.unlink()  # forget, then fail a verify: nothing may be recorded
    (signed_tree / "episodic" / "note.md").write_text("untracked", encoding="utf-8")
    assert run_verify(signed_tree) == 1
    assert not ratchet_path.exists()
    assert manifest["tree_id"] in trees["trees"]


def test_migrate_refuses_when_this_machine_saw_a_v2_tree_at_the_path(signed_tree, capsys):
    """The downgrade: v2 relabelled as v1 with tree_id stripped. The
    manifest alone can't tell, but this machine has seen v2 here."""
    before = _relabel_as_v1(signed_tree)
    assert migrate([str(signed_tree)]) == 1
    assert "looks like a downgrade" in capsys.readouterr().err
    assert _load(signed_tree) == before


def test_a_tampered_revision_record_fails_closed(signed_tree, isolated_revision_record, capsys):
    data = json.loads(isolated_revision_record.read_text(encoding="utf-8"))
    for entry in data["trees"].values():
        entry["revision"] = 0  # try to wind history back without the key
    isolated_revision_record.write_text(json.dumps(data), encoding="utf-8")

    assert run_verify(signed_tree) == 1
    assert "failed authentication" in capsys.readouterr().err
    assert run_sign(signed_tree) == 1

    isolated_revision_record.unlink()  # the documented reset
    assert run_verify(signed_tree) == 0


def test_the_record_only_moves_forward(signed_tree):
    from memory_index_system import ratchet

    tree_id = _load(signed_tree)["tree_id"]
    assert ratchet.record(b"test-secret", tree_id, 7, signed_tree) is None
    assert ratchet.record(b"test-secret", tree_id, 3, signed_tree) is None
    assert ratchet.load(b"test-secret")[tree_id]["revision"] == 7


def test_unsigned_trees_never_touch_the_record(isolated_revision_record):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        assert run_sign(target / ".memory") == 0
        assert run_verify(target / ".memory") == 0
    assert not isolated_revision_record.exists()


def test_a_held_record_lock_warns_instead_of_failing(signed_tree, isolated_revision_record, capsys):
    lock = isolated_revision_record.with_name(isolated_revision_record.name + ".lock")
    lock.write_text("", encoding="utf-8")
    try:
        assert run_verify(signed_tree) == 0
        assert "revision record not updated" in capsys.readouterr().err
    finally:
        lock.unlink()


@pytest.fixture
def fresh_key_warning(monkeypatch):
    from memory_index_system import crypto

    monkeypatch.setattr(crypto, "_legacy_warning_shown", False)
    monkeypatch.delenv("MEMORY_INDEX_KEY", raising=False)
    monkeypatch.delenv("KIMI_MEMORY_KEY", raising=False)
    return monkeypatch


def test_legacy_key_name_still_works_with_a_deprecation_warning(fresh_key_warning, capsys):
    fresh_key_warning.setenv("KIMI_MEMORY_KEY", "old-name-secret")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        run_init(target)
        assert _load(target / ".memory")["signature"]["alg"] == "HMAC-SHA256-v2"
        assert run_verify(target / ".memory") == 0

        fresh_key_warning.delenv("KIMI_MEMORY_KEY")
        fresh_key_warning.setenv("MEMORY_INDEX_KEY", "old-name-secret")
        assert run_verify(target / ".memory") == 0  # same key under the new name
    err = capsys.readouterr().err
    assert err.count("KIMI_MEMORY_KEY is deprecated") == 1  # once per process, not per call


def test_new_key_name_takes_precedence_over_a_different_legacy_value(fresh_key_warning, capsys):
    from memory_index_system.crypto import get_key

    fresh_key_warning.setenv("MEMORY_INDEX_KEY", "new")
    fresh_key_warning.setenv("KIMI_MEMORY_KEY", "old")
    assert get_key() == b"new"
    assert "is ignored" in capsys.readouterr().err


def test_same_value_under_both_names_is_silent(fresh_key_warning, capsys):
    from memory_index_system.crypto import get_key

    fresh_key_warning.setenv("MEMORY_INDEX_KEY", "same")
    fresh_key_warning.setenv("KIMI_MEMORY_KEY", "same")
    assert get_key() == b"same"
    assert capsys.readouterr().err == ""
