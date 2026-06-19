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
    key = get_key()
    if not key:
        return None
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()
