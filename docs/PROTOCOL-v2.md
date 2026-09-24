# Memory Index Protocol — v2

This is a delta on [PROTOCOL.md (v1)](PROTOCOL.md), not a replacement.
Everything in v1 still applies — directory layout (§1), the manifest's
non-signature fields (§2), the registry (§5), and conformance (§6) — except
for the two things below. Per v1 §6 (Conformance) and the rule stated at the
top of that document, a breaking change to the signing format gets a new
document rather than a silent edit to v1, so implementations can tell which
rules a given tree was written against from the signature's `alg` value
alone.

## What changed, and why

v1's signature covered only the `files` array. Two things followed from
that, neither originally called out as a separate finding but both real:

1. **`revision` wasn't covered.** Anyone without the signing key could edit
   `revision` directly — roll it back, bump it, whatever — without
   invalidating the signature, since the signature never touched it. This
   matters because `revision` is the entire basis for `--expect-revision`'s
   optimistic-concurrency check (v1 §4): a signature that doesn't protect
   the value that check relies on doesn't actually back it with anything.
2. **Nothing identified the tree itself.** There was no way to tell "this
   manifest belongs to this tree" from data covered by the signature — only
   the filesystem path, which isn't signed and isn't stable across a
   legitimate move or rename.

## 1. `tree_id`

Every manifest now carries a `tree_id`: a UUID4 string, minted once when a
tree is first initialized, that never changes for that tree's lifetime.

- `memory-index-init` mints a fresh `tree_id`.
- `memory-index-sign` reads the existing `tree_id` from the current
  manifest and carries it forward unchanged. Identity survives every
  re-sign; a mismatch is a red flag, not routine drift.
- A manifest predating this field (no `tree_id` present) gets one minted
  the first time it's re-signed under v2 — printed, not silent, since it's
  a real one-time change, not routine behavior. See §3.

`tree_id` is a bare top-level string field in `manifest.json`, alongside
`revision`. It has no meaning on its own; what matters is that it's now
part of what the signature covers.

## 2. Signature format

```json
{
  "alg": "HMAC-SHA256-v2",
  "value": "<hex digest>"
}
```

The signed payload is no longer the bare `files` array. It's:

```json
{"v": 2, "revision": <int>, "tree_id": "<uuid>", "files": [...]}
```

Canonicalization is otherwise identical to v1 (PROTOCOL.md §3, steps 2–4):
object keys sorted ascending, no insignificant whitespace, UTF-8 encoded,
HMAC-SHA256 over the result, hex-encoded lowercase. In Python:

```python
payload = {"v": 2, "revision": revision, "tree_id": tree_id, "files": files}
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
signature = hmac.new(key, canonical, hashlib.sha256).hexdigest()
```

`generated` and `generator` remain outside the signed payload, same as v1 —
they're descriptive, not security-relevant, and including them would make
every signature fragile to a tool-version bump.

## 3. Verifying: v1 and v2 side by side

A v2-conformant verifier MUST dispatch on `signature.alg`:

| `alg` | how to verify | result if it matches |
|---|---|---|
| `HMAC-SHA256-v2` | recompute per §2 above | pass |
| `HMAC-SHA256` (v1) | recompute per v1 §3 (files only) | pass, but flagged as **legacy** — doesn't cover `revision` or `tree_id` |
| anything else | — | fail — unrecognized algorithm, not a legacy format |

A legacy v1 signature that verifies correctly is not a failure — v2 is
additive, and a v1-signed tree is exactly as trustworthy today as it was
before v2 existed. It's flagged so a caller (or a human) knows this
particular tree doesn't get the `revision`/`tree_id` protection, and should
be re-signed with the key to upgrade.

The rest of v1 §3's rules — the present/absent × key-available/unavailable
table, independent-untracked-file walk, path-containment check — are
unchanged and apply identically regardless of which signature format is in play.

## 4. Migration

There is no separate "upgrade" command. `memory-index-sign` on a tree
without a `tree_id` mints one and writes a v2 signature on that same call —
upgrading is just re-signing. A tree that's never re-signed keeps its v1
signature (if any) indefinitely; that's a legitimate, if not ideal, steady
state, not an error.

**Standalone `verify-manifest.py` needs upgrading too, and only the
installed CLI does that automatically.** `.memory/scripts/{sign,verify}-manifest.py`
are self-contained copies made once, at `init` time, from whatever version
of the template existed then (see PROTOCOL.md §1). A tree initialized before
v2 existed still carries a `verify-manifest.py` that only knows how to check
the v1 (files-only) format — it has no `alg` dispatch at all, so it treats a
v2 signature as simply not matching. Left alone, upgrading such a tree's
`manifest.json` to v2 would make that tree's own bundled verifier reject its
own manifest immediately.

The installed `memory-index-sign` closes this: the same call that mints a
missing `tree_id` also refreshes `scripts/*.py` from the package's current
template before re-hashing the tree, so the copy that travels with the tree
can check what was just written (and the refreshed files are themselves
covered by the new signature, like anything else under the tree). Running
`.memory/scripts/sign-manifest.py` directly — the fully standalone path, with
no package installed — does not: that script can write a valid v2
`manifest.json`, but it has no newer template to copy `verify-manifest.py`
from, so a legacy tree's bundled verifier stays on v1 logic until the
installed CLI is run against it at least once (or the tree's `scripts/`
directory is refreshed by hand). This is a real, open gap in the fully
standalone workflow, not an oversight being glossed over.

## 5. Still not covered: rollback

v2 closes "edit the revision (or tree_id) without the key" — it does not
close "replay a whole older, validly-signed (revision, tree_id, files)
tuple over a newer state." That's still the gap documented in v1 §7, and it
requires something outside the manifest — an external record of the
highest revision seen for a given `tree_id` — which v2 does not add. See v1
§7 for the full explanation; nothing here changes that analysis, except
that `tree_id` is now available as the natural key for such a record
(rather than a filesystem path, which doesn't survive a legitimate move).
