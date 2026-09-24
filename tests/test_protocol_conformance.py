"""Proves docs/PROTOCOL.md's signing algorithm matches the real implementation.

This reimplements the canonicalization + HMAC steps from PROTOCOL.md section 3
independently of memory_index_system.crypto, using only stdlib. If someone
changes the signing algorithm in code without updating the spec (or vice
versa), this test is what catches it.
"""

import hashlib
import hmac
import json

from memory_index_system.crypto import sign_files_canonical


def spec_signature(files: list, key: str) -> str:
    """A literal implementation of docs/PROTOCOL.md section 3, steps 1-3."""
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def test_spec_algorithm_matches_implementation():
    files = [
        {"path": "identity/claim-boundary.md", "sha256": "a" * 64},
        {"path": "identity/project-charter.md", "sha256": "b" * 64},
    ]
    key = "shared-secret-123"

    import os

    os.environ["KIMI_MEMORY_KEY"] = key
    try:
        actual = sign_files_canonical(files)
    finally:
        del os.environ["KIMI_MEMORY_KEY"]

    expected = spec_signature(files, key)
    assert actual == expected


def test_spec_algorithm_is_order_sensitive():
    """The spec says order is part of what's signed -- reordering must change the digest."""
    key = "k"
    a = [{"path": "a.md", "sha256": "1" * 64}, {"path": "b.md", "sha256": "2" * 64}]
    b = [{"path": "b.md", "sha256": "2" * 64}, {"path": "a.md", "sha256": "1" * 64}]
    assert spec_signature(a, key) != spec_signature(b, key)


def test_spec_algorithm_key_matters():
    files = [{"path": "a.md", "sha256": "1" * 64}]
    assert spec_signature(files, "key-one") != spec_signature(files, "key-two")
