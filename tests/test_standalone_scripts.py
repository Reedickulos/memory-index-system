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

from memory_index_system.cli import init, sign
from memory_index_system.crypto import sign_files_canonical

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
LEGACY_V1_VERIFY_SCRIPT = (FIXTURES_DIR / "legacy_verify_manifest_v1.py").read_text(encoding="utf-8")


def downgrade_to_legacy_v1_tree(memory: Path) -> None:
    """Rewrite a freshly-init'd (current, v2) tree to look like one that was
    initialized before v2 existed: a files-only-signed manifest with no
    tree_id, and scripts/verify-manifest.py replaced by the actual pre-v2
    template content (from tests/fixtures/legacy_verify_manifest_v1.py,
    copied verbatim from the last commit before v2 signing landed)."""
    manifest_path = memory / "manifests" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("tree_id", None)
    os.environ["KIMI_MEMORY_KEY"] = "test-secret"
    try:
        sig = sign_files_canonical(manifest["files"])
    finally:
        del os.environ["KIMI_MEMORY_KEY"]
    manifest["signature"] = {"alg": "HMAC-SHA256", "value": sig}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (memory / "scripts" / "verify-manifest.py").write_text(LEGACY_V1_VERIFY_SCRIPT, encoding="utf-8")


def run_script(script_name: str, memory: Path, env=None):
    script = memory / "scripts" / script_name
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(script)],
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
        init([str(target)])
        memory = target / ".memory"

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
        init([str(target)])
        memory = target / ".memory"

        run_script("sign-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})
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
        init([str(target)])
        memory = target / ".memory"
        run_script("sign-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})

        manifest_path = memory / "manifests" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["revision"] = 999
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        result = run_script("verify-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})
        assert result.returncode == 1


def test_standalone_legacy_v1_signature_still_verifies_with_warning():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        manifest_path = memory / "manifests" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["tree_id"]
        # sign_files_canonical reads KIMI_MEMORY_KEY from THIS process's own
        # environment, not the subprocess env passed to run_script below.
        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            sig = sign_files_canonical(manifest["files"])
        finally:
            del os.environ["KIMI_MEMORY_KEY"]
        manifest["signature"] = {"alg": "HMAC-SHA256", "value": sig}
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        result = run_script("verify-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})
        assert result.returncode == 0
        assert "legacy" in result.stderr.lower()


def test_standalone_sign_upgrades_legacy_v1_tree_to_v2():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        manifest_path = memory / "manifests" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["tree_id"]
        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            sig = sign_files_canonical(manifest["files"])
        finally:
            del os.environ["KIMI_MEMORY_KEY"]
        manifest["signature"] = {"alg": "HMAC-SHA256", "value": sig}
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        run_script("sign-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})

        upgraded = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert upgraded["signature"]["alg"] == "HMAC-SHA256-v2"
        assert upgraded["tree_id"]

        result = run_script("verify-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})
        assert result.returncode == 0


def test_legacy_in_tree_verifier_rejects_a_freshly_upgraded_v2_manifest():
    """Root-cause reproduction: a tree whose scripts/ predates v2 (real
    pre-v2 verify-manifest.py content) has its manifest upgraded to v2 by
    something else -- here, writing a v2 signature directly, standing in for
    whatever upgraded it -- while scripts/ is left untouched. That legacy
    verifier only knows the files-only v1 check, so it rejects its own
    tree's now-valid v2 manifest. This is the bug: not a hash mismatch, not
    real tampering, just a stale in-tree verifier that predates the format
    it's being asked to check."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        downgrade_to_legacy_v1_tree(memory)

        from memory_index_system.crypto import sign_manifest_v2

        manifest_path = memory / "manifests" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["tree_id"] = "11111111-1111-1111-1111-111111111111"
        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            sig = sign_manifest_v2(manifest["revision"], manifest["tree_id"], manifest["files"])
        finally:
            del os.environ["KIMI_MEMORY_KEY"]
        manifest["signature"] = {"alg": "HMAC-SHA256-v2", "value": sig}
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        result = run_script("verify-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})
        assert result.returncode == 1
        assert "signature does not match" in result.stderr.lower()


def test_sign_refreshes_legacy_scripts_when_upgrading_tree_to_v2():
    """The fix: memory-index-sign (the installed CLI) upgrading a genuinely
    legacy (pre-v2) tree must refresh scripts/*.py from the current template
    in the same call that mints tree_id and writes the v2 signature -- so
    the tree's own bundled verifier can check what was just written, instead
    of rejecting it the way the previous test demonstrates."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        downgrade_to_legacy_v1_tree(memory)
        assert (memory / "scripts" / "verify-manifest.py").read_text(encoding="utf-8") == LEGACY_V1_VERIFY_SCRIPT

        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            assert sign([str(memory)]) == 0
        finally:
            del os.environ["KIMI_MEMORY_KEY"]

        refreshed = (memory / "scripts" / "verify-manifest.py").read_text(encoding="utf-8")
        assert refreshed != LEGACY_V1_VERIFY_SCRIPT
        assert "HMAC-SHA256-v2" in refreshed

        result = run_script("verify-manifest.py", memory, env={"KIMI_MEMORY_KEY": "test-secret"})
        assert result.returncode == 0, result.stderr


def test_installed_sign_repairs_verifier_after_bundled_sign_already_upgraded_tree():
    """Bundled sign-manifest.py upgrades first (minting tree_id, writing v2)
    but can't replace its legacy sibling verifier. The installed sign must
    still repair it even though tree_id is already present."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        init([str(target)])
        memory = target / ".memory"
        downgrade_to_legacy_v1_tree(memory)
        env = {"KIMI_MEMORY_KEY": "test-secret"}

        assert run_script("sign-manifest.py", memory, env=env).returncode == 0
        manifest = json.loads((memory / "manifests" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["tree_id"]
        assert manifest["signature"]["alg"] == "HMAC-SHA256-v2"
        assert run_script("verify-manifest.py", memory, env=env).returncode == 1

        os.environ["KIMI_MEMORY_KEY"] = "test-secret"
        try:
            assert sign([str(memory)]) == 0
        finally:
            del os.environ["KIMI_MEMORY_KEY"]

        result = run_script("verify-manifest.py", memory, env=env)
        assert result.returncode == 0, result.stderr
