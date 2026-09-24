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
information). A mismatch, or a `signature` field present with no key
available to check it, MUST be treated as verification failure, not as an
unsigned tree — those are different states (see manifest-spec.md).

File-hash checks and signature checks are independent and both required:
hashes alone don't protect a manifest that's been edited to match a
tampered file; a signature alone (without also checking hashes) would still
let a tampered manifest go unnoticed if no one recomputed against disk.
`memory-index-verify` runs both.

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
