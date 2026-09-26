"""Optional HMAC-SHA256 signing for manifests."""

import hashlib
import hmac
import json
import os
import sys
from typing import Optional

KEY_ENV = "MEMORY_INDEX_KEY"
LEGACY_KEY_ENV = "KIMI_MEMORY_KEY"
_legacy_warning_shown = False


def get_key() -> Optional[bytes]:
    """The signing key from MEMORY_INDEX_KEY, falling back to the deprecated
    KIMI_MEMORY_KEY so existing setups keep working. Warns once per process
    when the old name is used or is being ignored."""
    global _legacy_warning_shown
    raw = os.environ.get(KEY_ENV)
    legacy = os.environ.get(LEGACY_KEY_ENV)
    warning = None
    if raw:
        if legacy and legacy != raw:
            warning = f"{LEGACY_KEY_ENV} is set to a different value and is ignored; {KEY_ENV} takes precedence."
    elif legacy:
        warning = f"{LEGACY_KEY_ENV} is deprecated; set {KEY_ENV} instead (the old name still works for now)."
        raw = legacy
    if warning and not _legacy_warning_shown:
        print(f"Warning: {warning}", file=sys.stderr)
        _legacy_warning_shown = True
    return raw.encode("utf-8") if raw else None


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
