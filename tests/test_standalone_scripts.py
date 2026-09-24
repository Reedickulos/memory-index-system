"""Tests for templates/.memory/scripts/*.py -- the self-contained scripts that
travel inside every .memory/ tree for use without the package installed.

Nothing else in the test suite runs these directly (everything else goes
through memory_index_system.cli), so this file exists specifically to catch
these scripts drifting from the package's behavior -- which is exactly how
they drifted before (see the "in-tree scripts have fallen behind" finding).
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from memory_index_system.cli import init, migrate, sign
from memory_index_system.crypto import sign_files_canonical, sign_manifest_v2
from memory_index_system.manifest import build_manifest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
LEGACY_V1_VERIFY_SCRIPT = (FIXTURES_DIR / "legacy_verify_manifest_v1.py").read_text(encoding="utf-8")


def downgrade_to_legacy_v1_tree(memory: Path) -> None:
    """Rewrite a freshly-init'd (current, v2) tree to look like one that was
    initialized before v2 existed: a files-only-signed manifest with no
    tree_id, and scripts/verify-manifest.py replaced by the actual pre-v2
    template content (from tests/fixtures/legacy_verify_manifest_v1.py,
    copied verbatim from the last commit before v2 signing landed)."""
    (memory / "scripts" / "verify-manifest.py").write_text(LEGACY_V1_VERIFY_SCRIPT, encoding="utf-8")
    manifest_path = memory / "manifests" / "manifest.json"
    revision = json.loads(manifest_path.read_text(encoding="utf-8"))["revision"]
    # Re-hash after swapping the script in, so the tree is internally
    # consistent -- a real pre-v2 tree would verify under its v1 signature.
    manifest = build_manifest(memory, revision=revision)
    del manifest["tree_id"]
    os.environ["KIMI_MEMORY_KEY"] = "test-secret"
    try:
        sig = sign_files_canonical(manifest["files"])
    finally:
        del os.environ["KIMI_MEMORY_KEY"]
    manifest["signature"] = {"alg": "HMAC-SHA256", "value": sig}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def init_signed(target: Path) -> Path:
    """init with the key set, so the tree is signed (v2) from the start."""
    os.environ["KIMI_MEMORY_KEY"] = "test-secret"
    try:
        init([str(target)])
    finally:
        del os.environ["KIMI_MEMORY_KEY"]
    return target / ".memory"


KEY_ENV = {"KIMI_MEMORY_KEY": "test-secret"}


def run_script(script_name: str, memory: Path, env=None, args=()):
    script = memory / "scripts" / script_name
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env=full_env,
    )


def test_standalone_verify_passes_on_fresh_init():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"

        result = run_script("verify-manifest.py", memory)
        assert result.returncode == 0, result.stderr


def test_standalone_sign_then_verify_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        memory = init_signed(target)

        sign_result = run_script("sign-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})
        assert sign_result.returncode == 0, sign_result.stderr

        manifest = json.loads((memory / "manifests" / "manifest.json").read_text(encoding="utf-8"))
        assert "signature" in manifest
        assert manifest["revision"] == 2  # init wrote 1, sign incremented it

        verify_result = run_script("verify-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})
        assert verify_result.returncode == 0, verify_result.stderr


def test_standalone_verify_fails_when_signature_stripped_but_key_available():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        memory = init_signed(target)

        assert run_script("sign-manifest.py", memory, env=KEY_ENV).returncode == 0
        manifest_path = memory / "manifests" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["signature"]
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        result = run_script("verify-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})
        assert result.returncode == 1
        assert "stripped" in result.stderr


def test_standalone_verify_fails_on_untracked_file():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        (memory / "semantic" / "injected.md").write_text("not tracked", encoding="utf-8")

        result = run_script("verify-manifest.py", memory)
        assert result.returncode == 1
        assert "Untracked files" in result.stderr


def test_standalone_verify_fails_on_untracked_dot_lock_file():
    """A real content file ending in .lock must not be confused with the
    transient manifests/.sign.lock -- only that exact path is ignored."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        (memory / "semantic" / "injected.lock").write_text("not tracked", encoding="utf-8")

        result = run_script("verify-manifest.py", memory)
        assert result.returncode == 1
        assert "Untracked files" in result.stderr


def test_standalone_sign_ignores_os_and_editor_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        (memory / ".DS_Store").write_bytes(b"mac metadata")

        run_script("sign-manifest.py", memory)
        manifest = json.loads((memory / "manifests" / "manifest.json").read_text(encoding="utf-8"))
        assert not any(".DS_Store" in entry["path"] for entry in manifest["files"])


def test_standalone_verify_fails_cleanly_on_corrupt_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        (memory / "manifests" / "manifest.json").write_text("{not valid json", encoding="utf-8")

        result = run_script("verify-manifest.py", memory)
        assert result.returncode == 1
        assert "not valid JSON" in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="drive-letter/backslash escape is Windows-specific")
def test_standalone_verify_rejects_windows_drive_and_backslash_paths():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        manifest_path = memory / "manifests" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].append({"path": "C:/Windows/System32/drivers/etc/hosts", "sha256": "a" * 64})
        manifest["files"].append({"path": "..\\..\\outside.txt", "sha256": "b" * 64})
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        result = run_script("verify-manifest.py", memory)
        assert result.returncode == 1


def test_standalone_tree_id_minted_and_stable_across_signs():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        manifest_path = memory / "manifests" / "manifest.json"

        tree_id = json.loads(manifest_path.read_text(encoding="utf-8"))["tree_id"]
        assert tree_id

        run_script("sign-manifest.py", memory)
        after = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert after["tree_id"] == tree_id


def test_standalone_v2_signature_fails_if_revision_tampered_alone():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        memory = init_signed(target)
        assert run_script("sign-manifest.py", memory, env=KEY_ENV).returncode == 0

        manifest_path = memory / "manifests" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["revision"] = 999
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        result = run_script("verify-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})
        assert result.returncode == 1




def _load(memory: Path) -> dict:
    return json.loads((memory / "manifests" / "manifest.json").read_text(encoding="utf-8"))


def _save(memory: Path, manifest: dict) -> None:
    (memory / "manifests" / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def test_standalone_verify_rejects_legacy_v1_signature():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        manifest = _load(memory)
        del manifest["tree_id"]
        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            manifest["signature"] = {"alg": "HMAC-SHA256", "value": sign_files_canonical(manifest["files"])}
        finally:
            del os.environ["KIMI_MEMORY_KEY"]
        _save(memory, manifest)

        result = run_script("verify-manifest.py", memory, env=KEY_ENV)
        assert result.returncode == 1
        assert "memory-index-migrate" in result.stderr


def test_standalone_sign_refuses_legacy_v1_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        downgrade_to_legacy_v1_tree(memory)
        before = _load(memory)

        result = run_script("sign-manifest.py", memory, env=KEY_ENV)
        assert result.returncode == 1
        assert "memory-index-migrate" in result.stderr
        assert _load(memory) == before


@pytest.mark.parametrize("field,value", [("tree_id", "some-other-tree"), ("revision", 999)])
def test_standalone_sign_refuses_to_carry_forward_edited_header_field(field, value):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        memory = init_signed(target)
        manifest = _load(memory)
        manifest[field] = value
        _save(memory, manifest)

        result = run_script("sign-manifest.py", memory, env=KEY_ENV)
        assert result.returncode == 1
        assert "does not match" in result.stderr
        assert _load(memory)[field] == value


def test_standalone_sign_refuses_unsigned_manifest_with_key_unless_adopted():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"

        refused = run_script("sign-manifest.py", memory, env=KEY_ENV)
        assert refused.returncode == 1
        assert "--adopt-unsigned" in refused.stderr

        adopted = run_script("sign-manifest.py", memory, env=KEY_ENV, args=["--adopt-unsigned"])
        assert adopted.returncode == 0, adopted.stderr
        assert run_script("verify-manifest.py", memory, env=KEY_ENV).returncode == 0
        assert run_script("sign-manifest.py", memory, env=KEY_ENV).returncode == 0


def test_standalone_sign_rejects_unknown_arguments():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        result = run_script("sign-manifest.py", target / ".memory", args=["--adopt-unsgined"])
        assert result.returncode == 2
        assert "Unrecognized arguments" in result.stderr


@pytest.mark.parametrize("bad_tree_id", ["", 0, None])
def test_standalone_sign_mints_and_announces_tree_id_when_empty_or_invalid(bad_tree_id):
    """Must match the installed sign: both mint and announce for all three."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        manifest = _load(memory)
        manifest["tree_id"] = bad_tree_id
        _save(memory, manifest)

        result = run_script("sign-manifest.py", memory)
        assert result.returncode == 0, result.stderr
        assert "minting one now" in result.stdout
        tree_id = _load(memory)["tree_id"]
        assert isinstance(tree_id, str) and tree_id


def test_standalone_verify_fails_cleanly_on_non_string_signature_value():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        memory = init_signed(target)
        manifest = _load(memory)
        manifest["signature"]["value"] = 12345
        _save(memory, manifest)

        result = run_script("verify-manifest.py", memory, env=KEY_ENV)
        assert result.returncode == 1
        assert "not a string" in result.stderr
        assert "Traceback" not in result.stderr


@pytest.mark.parametrize("script", ["verify-manifest.py", "sign-manifest.py"])
def test_standalone_scripts_refuse_non_object_manifest_cleanly(script):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        (memory / "manifests" / "manifest.json").write_text("[]", encoding="utf-8")

        result = run_script(script, memory)
        assert result.returncode == 1
        assert "not a JSON object" in result.stderr
        assert "Traceback" not in result.stderr


def test_legacy_in_tree_verifier_rejects_a_valid_v2_manifest():
    """Why scripts/ must be refreshed: a pre-v2 verify-manifest.py (the real
    pre-v2 content) only knows the files-only check, so it rejects its own
    tree's valid v2 manifest -- not tampering, just a stale verifier."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        memory = init_signed(target)
        (memory / "scripts" / "verify-manifest.py").write_text(LEGACY_V1_VERIFY_SCRIPT, encoding="utf-8")
        previous = _load(memory)
        manifest = build_manifest(memory, revision=previous["revision"], tree_id=previous["tree_id"])
        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            sig = sign_manifest_v2(manifest["revision"], manifest["tree_id"], manifest["files"])
        finally:
            del os.environ["KIMI_MEMORY_KEY"]
        manifest["signature"] = {"alg": "HMAC-SHA256-v2", "value": sig}
        _save(memory, manifest)

        result = run_script("verify-manifest.py", memory, env=KEY_ENV)
        assert result.returncode == 1
        assert "signature does not match" in result.stderr.lower()


def test_migrate_refreshes_legacy_scripts_so_the_in_tree_verifier_accepts_v2():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        downgrade_to_legacy_v1_tree(memory)

        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            assert migrate([str(memory)]) == 0
        finally:
            del os.environ["KIMI_MEMORY_KEY"]

        refreshed = (memory / "scripts" / "verify-manifest.py").read_text(encoding="utf-8")
        assert refreshed != LEGACY_V1_VERIFY_SCRIPT
        result = run_script("verify-manifest.py", memory, env=KEY_ENV)
        assert result.returncode == 0, result.stderr


def test_installed_sign_repairs_verifier_after_bundled_sign_adopted_tree():
    """A tree created before a key existed, still carrying a pre-v2 verifier,
    is adopted by the bundled sign-manifest.py (tree_id minted, v2 written).
    That script can't replace its sibling, so the verifier rejects the tree
    until the installed sign runs -- which must repair it even though
    tree_id is already present."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        manifest = _load(memory)
        del manifest["tree_id"]
        _save(memory, manifest)
        (memory / "scripts" / "verify-manifest.py").write_text(LEGACY_V1_VERIFY_SCRIPT, encoding="utf-8")

        adopted = run_script("sign-manifest.py", memory, env=KEY_ENV, args=["--adopt-unsigned"])
        assert adopted.returncode == 0, adopted.stderr
        assert _load(memory)["tree_id"]
        assert run_script("verify-manifest.py", memory, env=KEY_ENV).returncode == 1

        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            assert sign([str(memory)]) == 0
        finally:
            del os.environ["KIMI_MEMORY_KEY"]

        result = run_script("verify-manifest.py", memory, env=KEY_ENV)
        assert result.returncode == 0, result.stderr


def test_standalone_sign_without_key_refuses_to_strip_a_signed_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        memory = init_signed(target)
        before = _load(memory)

        result = run_script("sign-manifest.py", memory)
        assert result.returncode == 1
        assert "would strip its signature" in result.stderr
        assert _load(memory) == before
