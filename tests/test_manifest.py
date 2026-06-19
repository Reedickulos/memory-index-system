"""Tests for manifest generation and verification."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from memory_index_system.cli import init, sign, verify


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
