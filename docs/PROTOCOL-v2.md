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

## 3. Verifying

A v2-conformant verifier MUST dispatch on `signature.alg`:

| `alg` | result |
|---|---|
| `HMAC-SHA256-v2` | recompute per §2 above; pass if it matches |
| `HMAC-SHA256` (v1) | **fail** — legacy format, not accepted (see below) |
| anything else | fail — unrecognized algorithm |

A `signature.value` that is missing or not a string fails the same way a
mismatched one does.

**Why v1 is rejected rather than accepted with a warning.** A v1 signature
covers only `files`. If verifiers accepted it, anyone without the key could
take a v2 manifest, relabel it with a v1 signature over the same file list
(one the key holder issued at some earlier point, e.g. before the tree was
upgraded), and then edit `revision` or `tree_id` freely — v2's protection
would be gone. Checking for a `tree_id` on v1 manifests doesn't help: the
attacker can delete it, and the result is indistinguishable from a genuine
pre-v2 tree. From the manifest alone the two cases can't be told apart, so
verification refuses both and leaves the decision to a person (§4.2).

The rest of v1 §3's rules — the present/absent × key-available/unavailable
table, independent-untracked-file walk, path-containment check — are
unchanged and apply identically.

## 4. Re-signing and migration

### 4.1 Re-signing authenticates the previous manifest

`memory-index-sign` carries `revision` (incremented) and `tree_id` forward
from the current manifest into the new signature. With the key set, it first
checks the current manifest's signature against the manifest's own recorded
fields, and refuses if that fails; otherwise anyone without the key could
edit either value and have the next legitimate sign bless it. Only the
recorded fields are checked, not the files on disk — those are expected to
have changed, since re-hashing them is what signing is for — so the normal
"edit files, then sign" workflow is unaffected.

| current manifest (key set) | `memory-index-sign` |
|---|---|
| valid v2 signature | signs; carries `revision`/`tree_id` forward |
| v2 signature that doesn't match | refuses |
| v1 signature | refuses — use `memory-index-migrate` (§4.2) |
| unsigned or missing | refuses unless `--adopt-unsigned` is passed |

`--adopt-unsigned` exists for a tree created before a key was set: its
revision and tree_id genuinely can't be authenticated (a stripped signature
looks the same), so they're taken as-is, once. Setting the key *before*
`memory-index-init` avoids this entirely — the tree is signed from the
start.

Without a key, signing an unsigned tree works as before and writes an
unsigned manifest; there's nothing to authenticate. Signing a **signed**
tree without the key is refused: writing it back unsigned would strip its
signature, silently dropping the tree's protection until someone with the
key noticed.

A `tree_id` that is missing, empty, or not a string is treated the same way
by every signer: a fresh one is minted, and a message says so.

### 4.2 Migrating a v1-signed tree

`memory-index-migrate` is a one-time, deliberate upgrade. It requires the
key, refuses unless the manifest has a v1 signature, and then verifies the
whole tree under v1 rules — hashes, untracked files, and the v1 signature —
refusing if anything fails. Only then does it write a v2 manifest (revision
incremented, a freshly minted `tree_id`). It's a no-op on a tree already on v2.

v1 never covered `revision`, so the revision migrate carries forward is
unauthenticated, and from the manifest alone it can't tell a genuine pre-v2
tree from a downgraded v2 one (§3). The revision record (§5) narrows this:
migrate refuses if this machine has already seen a v2-signed tree at the
same path, which is what a downgrade looks like — an attacker can strip
`tree_id` but not move the tree. On a machine with no history for that path
(a fresh machine, or a deleted record) that check has nothing to go on, so
**running migrate still needs a person's judgement there: don't run it
automatically in response to a verify failure** — doing that on a downgraded
tree is exactly what an attacker would want. Any `tree_id` on a v1 manifest
is discarded rather than carried forward, since no v1 tool ever wrote one.

### 4.3 The in-tree scripts

`.memory/scripts/{sign,verify}-manifest.py` are self-contained copies made
once, at `init` time, from whatever version of the template existed then
(see PROTOCOL.md §1). A tree initialized before v2 existed still carries a
`verify-manifest.py` that only knows the v1 format and treats a v2 signature
as not matching — so a tree upgraded to v2 would be rejected by its own
bundled verifier.

The installed `memory-index-sign` and `memory-index-migrate` refresh
`scripts/*.py` from the package's current template on every run, before
re-hashing the tree, so the copies that travel with the tree can check what
was just written (the refreshed files are covered by the new signature like
anything else). It's every run, not only when a `tree_id` is minted, because
a tree can already have a `tree_id` and a v2 signature while still carrying
an old verifier — for example after the standalone signer adopted it.

Running `.memory/scripts/sign-manifest.py` directly — no package installed —
refreshes nothing: it has no newer template to copy from. A tree it signs
keeps whatever verifier it had until the installed `memory-index-sign` runs
against it once (or `scripts/` is refreshed by hand). This is a real, open
gap in the fully standalone workflow, not an oversight being glossed over.
The standalone signer applies the same authentication rules as §4.1,
including `--adopt-unsigned`; it has no migrate, so a v1-signed tree needs
the installed package.

## 5. Rollback: the per-machine revision record

A valid signature proves a manifest was signed at some point, not that it's
the latest one: a whole older, validly-signed (revision, tree_id, files)
state can be restored over a newer one and still verify, because every hash
and the signature genuinely match. Nothing inside the manifest can catch
that (v1 §7); it needs an external reference to "the newest state already
seen." This implementation keeps one per machine.

**The record.** `~/.memory-registry/ratchet.json` (override the location
with the `MEMORY_INDEX_RATCHET` environment variable) maps each `tree_id` to
the highest revision seen for it and the path it was last seen at. It is
signed with the same key as the trees, so it can't be forged or wound back
without the key. It sits beside the registry but in its own file, because
a registry rescan drops entries for roots it wasn't given.

**How it's used** (only with the key set — without it, neither a manifest's
revision nor the record can be authenticated, and the record isn't read):

| command | checks | records |
|---|---|---|
| `memory-index-init` | — | the new tree at revision 1 |
| `memory-index-verify` | refuses a revision lower than the recorded one | the revision, only after the whole tree passed |
| `memory-index-sign` | refuses to sign on top of a revision lower than the recorded one | the new revision |
| `memory-index-migrate` | refuses if a v2 tree was already seen at this path (§4.2) | the migrated revision |

A record that fails authentication makes all of these fail closed. The
record only ever moves forward; if its lock is held by another process for
too long, the command still succeeds and warns that this one update wasn't
recorded.

**What it doesn't cover:**
- **No history, no protection.** On a machine that has never seen a tree,
  or after the record is deleted (deleting it is also the way to reset a
  record that no longer authenticates, e.g. after changing keys), the first
  state it sees is accepted as the baseline. Deletion needs only write
  access to the home directory, not the key.
- **Per machine only.** Two machines don't share history; a rollback made
  on one machine to a state newer than anything the other has seen isn't
  detectable there.
- **The key holder.** Anyone with the key can sign anything, including a
  "newer" revision of old content.
- **The standalone in-tree scripts** (`.memory/scripts/*.py`) don't read or
  write the record; they're built to run with no package installed and no
  shared state. Only the installed commands give rollback protection.
- **Same revision, different content.** Only the revision number is
  recorded, so two different states signed at the same revision (e.g. by
  two machines that each signed revision N) aren't told apart.
