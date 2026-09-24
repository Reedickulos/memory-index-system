"""Optional HMAC-SHA256 signing for manifests."""

import hashlib
import hmac
import json
import os
from typing import Optional


def get_key() -> Optional[bytes]:
    raw = os.environ.get("KIMI_MEMORY_KEY")
    if not raw:
        return None
    return raw.encode("utf-8")


def sign_files_canonical(files: list) -> Optional[str]:
    """Legacy v1 signing: covers only `files`. Kept so existing v1-signed
    manifests can still be verified — see sign_manifest_v2 for current signing.
    """
    key = get_key()
    if not key:
        return None
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def sign_manifest_v2(revision: int, tree_id: str, files: list) -> Optional[str]:
    """Current signing: covers revision and tree_id in addition to files.

    v1 only signed `files`, so revision (and, before it existed, nothing at
    all identifying the tree) could be edited freely by anyone without the
    key without invalidating the signature. See docs/PROTOCOL-v2.md.
    """
    key = get_key()
    if not key:
        return None
    payload = {"v": 2, "revision": revision, "tree_id": tree_id, "files": files}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()
