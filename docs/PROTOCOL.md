# Memory Index Protocol — v1

This document defines what it means for a directory tree, or another tool,
to be **compatible** with Memory Index System — independent of this
package's Python implementation. Anything that reads and writes these exact
files in this exact shape can interoperate with `.memory/` trees this
package produces, and vice versa, regardless of what language it's written
in. That's the point of writing this down separately from the code: the
protocol is the contract; `memory_index_system` is one implementation of it.

This is v1. Breaking changes to any rule below require a v2 document, not a
silent edit to this one.

> **[PROTOCOL-v2.md](PROTOCOL-v2.md) exists and changes the signing format**
> (§3 below) to also cover `revision` and a new `tree_id` field, closing a
> gap where either could be edited without the signing key without breaking
> the signature. Everything else on this page — layout, manifest fields
> besides the signature, optimistic concurrency, the registry, conformance —
> is unchanged and still the current rule. A v1-signed manifest still
> verifies correctly today; it's just flagged as legacy.

## 1. Directory layout

A conformant `.memory/` tree contains, at minimum:

```text
.memory/
├── INDEX.md
├── manifests/
│   ├── manifest.json
│   └── initiation-order.json
├── identity/
│   ├── project-charter.md
│   └── claim-boundary.md
├── episodic/
├── semantic/
└── procedural/
```

`identity/project-charter.md` MUST contain a `## Name` Markdown heading
followed by the project's display name on the next non-blank line — this is
the only piece of the layout other tools are expected to parse structurally
(the [registry](registry-spec.md) depends on it). Everything else under
`episodic/`, `semantic/`, and `procedural/` is free-form Markdown; this
protocol imposes no schema on it.

## 2. The manifest (`manifests/manifest.json`)

See [Manifest Spec](manifest-spec.md) for the full field table. The rules
that matter for interoperability:

- **File hashing.** Every file's hash is `sha256` of its raw bytes (not of
  decoded text), lowercase hex, 64 characters.
- **Paths are POSIX-style.** Forward slashes always, even when the
  implementation runs on Windows. `manifests/manifest.json` itself is
  excluded from the `files` array.
- **`files` is sorted.** Entries are sorted ascending by `path`
  (codepoint/byte order) before the manifest is written. A conformant writer
  MUST produce this order; a conformant reader MUST NOT assume it and should
  sort defensively if order matters to it, since a non-conformant writer
  could omit this step.
- **`revision` is a monotonic integer**, starting at `1` when a tree is
  first initialized and incremented by exactly `1` each time the manifest is
  regenerated and written. It exists so two agents editing the same tree can
  detect a conflicting concurrent write (see §4) — it is not
  cryptographically protected and is not a security property.

## 3. Signing and verifying (the part that must be byte-exact)

Signing is optional per-tree (a manifest with no `signature` field is
valid — see manifest-spec.md's note on what that does and doesn't protect
against). When a manifest **is** signed, reproducing the signature requires
matching this exact procedure, because HMAC has no tolerance for
serialization drift — a single reordered key or extra space produces a
completely different digest:

1. Take the manifest's `files` array **exactly as it appears in
   `manifest.json`** — same entries, same order. Do not re-sort or
   re-derive it independently; you are reproducing what the signer signed,
   not recomputing your own view of the tree.
2. Serialize it as JSON with: object keys sorted ascending
   (`sort_keys=True`), no insignificant whitespace (Python's
   `separators=(",", ":")` — i.e. `,` and `:` with nothing else), UTF-8
   encoding. In Python this is exactly:
   ```python
   canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
   ```
3. Compute `HMAC-SHA256(key, canonical)` where `key` is the shared secret
   (this implementation reads it from the `KIMI_MEMORY_KEY` environment
   variable) encoded as UTF-8 bytes. Render the digest as lowercase hex.
4. Store it as `{"alg": "HMAC-SHA256", "value": "<hex digest>"}` under the
   manifest's `signature` key.

To verify: recompute steps 1–3 with the same key and compare the resulting
hex digest to `signature.value` using a constant-time comparison
(`hmac.compare_digest` or equivalent — a naive `==` on secrets leaks timing
information). Three states, not two:

| `signature` field | verifier has the key | result |
|---|---|---|
| present, matches | yes | pass |
| present, doesn't match | yes | **fail** |
| present | no | **fail** — can't check it, so don't assume it's fine |
| absent | yes | **fail** — a verifier holding the key almost certainly expects signed manifests; a missing signature here is more likely stripped than intentional |
| absent | no | pass, with a warning — hash checks only, no tamper protection |

Treating "absent signature + key available" as a pass (with only a warning)
was this protocol's original behavior and is a known-broken design: it lets
an attacker who edits a file and its manifest entry simply delete the
`signature` field to bypass detection entirely, indistinguishable from a
legitimately-never-signed tree.

File-hash checks and signature checks are independent and both required:
hashes alone don't protect a manifest that's been edited to match a
tampered file; a signature alone (without also checking hashes) would still
let a tampered manifest go unnoticed if no one recomputed against disk.

Verification MUST also walk the tree independently (applying the same
ignore rules as §2) and fail if any file exists on disk that isn't recorded
in `files` — checking only recorded entries against disk can never detect
an *added* file, which is the more likely tampering vector for a memory
tree than modifying an existing one.

A manifest entry's `path` MUST be checked for containment before it's read,
and the check MUST use the host's own path-resolution semantics — join
`path` with the tree root, resolve it, and confirm the result still lives
under the resolved root — rather than pattern-matching the string for a
leading `/` or a POSIX `..` segment. Pattern-matching against POSIX rules
alone is not sufficient: on Windows, a value like `C:/Windows/x` or
`..\..\x` is neither absolute nor contains a `..` component under POSIX
path rules, but resolving it with the host's actual path class (which is
what happens when the entry is subsequently read) does escape the tree —
`root / "C:/Windows/x"` discards `root` entirely on Windows, since joining
onto an absolute path resets the accumulated path. Validate containment
with the same path implementation that will perform the real join, not a
POSIX-specific stand-in for it.

`memory-index-verify` runs all of these checks.

## 4. Optimistic concurrency (multi-agent edits)

There is no locking. Two agents can read the same tree, both make changes,
and both attempt to write a new manifest. To catch that instead of silently
losing one agent's work:

- Before regenerating a manifest, an agent reads the current `revision`.
- It writes its new manifest with `revision + 1`.
- If it can additionally assert "I still expect the on-disk revision to be
  what I last read" before writing (this implementation's
  `memory-index-sign --expect-revision N`), a second agent whose write
  lands first causes the first agent's later, stale-revision write to be
  refused rather than silently overwriting the second agent's change.

This is optimistic concurrency control, not a merge algorithm — it detects
a conflict and refuses to clobber it. Resolving the conflict (deciding whose
edits win, or combining them) is left to the agents or humans involved; this
protocol does not yet define an automatic merge.

Reading the revision and writing the next one are still two separate steps,
not one atomic operation — checking `--expect-revision` doesn't by itself
close the gap between two processes on the same machine both reading the
same revision before either writes. This implementation narrows that window
with a local advisory lock (an exclusively-created `manifests/.sign.lock`
file, held only for the duration of a `sign`) and writes the manifest itself
atomically (write to a temp file, then rename) so a crash mid-write can
never leave a corrupt `manifest.json` behind. Neither is a protocol
requirement — they're implementation-level mitigations for a single
machine, not a distributed lock — but any implementation should write
`manifest.json` atomically at minimum, since a half-written file breaks the
whole tree's verification, not just the writer's own change.

## 5. The registry

The registry (`~/.memory-registry/registry.json` by default) is a separate,
optional layer for discovering multiple `.memory/` trees on one machine. See
[Registry Spec](registry-spec.md) for its schema. It is built entirely from
data a `.memory/` tree already exposes (`identity/`, plus a manifest hash)
— nothing about the registry format is required for a single `.memory/`
tree to be protocol-conformant on its own.

## 6. Conformance

A tool is a **v1-conformant reader** if it can, given any `.memory/` tree
matching §1–§2, correctly determine whether it verifies (§3) using only the
files on disk and, if applicable, the shared signing key.

A tool is a **v1-conformant writer** if every manifest it produces satisfies
§2's rules exactly, such that a v1-conformant reader (in any language) can
verify it — including reproducing its signature per §3 with the same key.

Conformance is about the file formats and algorithms above, not about
implementing every CLI command this package ships (`registry-diff`,
staleness flags, etc. are conveniences built on top of a conformant tree,
not part of what makes a tree conformant).

## 7. Known limitation: no rollback/replay protection

*(Written for v1's files-only signature. [PROTOCOL-v2.md](PROTOCOL-v2.md)
now covers `revision` and adds `tree_id`, which closes the "edit revision
without the key" version of this problem described below — but not the
rollback problem itself. Read on; it still applies to both v1 and v2.)*

A v1 signature covers `files` only, so it does not cover `revision`, and
there is no mechanism binding a signature to "this is the most recent valid
state." Even under v2, where `revision` and `tree_id` are both covered, a
complete, validly-signed *older* manifest together with the files it
describes can still be restored wholesale over a newer state, and
verification will pass: every hash matches what's recorded, and the
signature matches what's signed, because both genuinely were valid together
at some earlier point — the signature has no way to know it's not the
current one. Detecting that kind of rollback requires an external reference
to "the last state I actually saw" (for instance, a caller comparing the
current manifest's `revision` against one it remembers from a previous
verify, keyed by `tree_id` under v2 rather than by filesystem path, which
doesn't survive a legitimate move) — nothing in the manifest format itself
carries that information yet. This is a real, open gap, not an oversight
being glossed over.
