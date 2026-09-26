# Manifest Specification

## `manifests/initiation-order.json`

Tells an agent which files to load first.

```json
{
  "project": "My Research Project",
  "created": "2026-06-19",
  "description": "Boot sequence for any agent joining this project.",
  "boot_sequence": [
    "INDEX.md",
    "identity/project-charter.md",
    "semantic/hypothesis-core.md",
    "procedural/agent-handoff-protocol.md"
  ]
}
```

## `manifests/manifest.json`

Lists every file in the package and its SHA-256 hash.

```json
{
  "project": "My Research Project",
  "generated": "2026-06-19T22:42:13+00:00",
  "generator": "memory-index-system 0.1.0",
  "revision": 3,
  "tree_id": "434bde9b-a72a-4d95-8dbb-6ecf1d21524d",
  "file_count": 42,
  "files": [
    {
      "path": "INDEX.md",
      "sha256": "..."
    }
  ],
  "signature": {
    "alg": "HMAC-SHA256-v2",
    "value": "..."
  }
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `project` | string | Project name |
| `generated` | string | ISO 8601 timestamp |
| `generator` | string | Tool version |
| `revision` | integer | Monotonic counter, starting at 1, incremented on every `sign` (see [PROTOCOL.md §4](PROTOCOL.md#4-optimistic-concurrency-multi-agent-edits)) |
| `tree_id` | string | UUID4 minted once at `init`, unchanged for the tree's lifetime; covered by a v2 signature (see [PROTOCOL-v2.md](PROTOCOL-v2.md)) |
| `file_count` | integer | Number of files |
| `files` | array | `{path, sha256}` entries |
| `signature` | object | Optional signature — `alg` is `"HMAC-SHA256-v2"`. The legacy v1 `"HMAC-SHA256"` is rejected by verify; see below |

### Signature

If `MEMORY_INDEX_KEY` is set, the manifest is signed. Current signing (v2) covers `revision`, `tree_id`, and `files`; see [PROTOCOL-v2.md](PROTOCOL-v2.md) for the exact payload and why `revision`/`tree_id` had to be added. A manifest signed under the older v1 format (`"alg": "HMAC-SHA256"`, covering only `files`) is rejected: a v2 manifest can be relabelled with a v1 signature to edit its `revision` or `tree_id`, and that's indistinguishable from a genuine pre-v2 tree. A tree that genuinely predates v2 is upgraded once with `memory-index-migrate`, after a person has confirmed it (PROTOCOL-v2.md §4.2).

`memory-index-sign`, with the key set, checks the current manifest's signature before carrying its `revision` and `tree_id` forward, and refuses if it doesn't match. An unsigned or missing manifest is refused unless `--adopt-unsigned` is passed (once, for a tree created before a key was set). Without the key, `memory-index-sign` refuses to re-sign a signed manifest rather than write it back unsigned. See PROTOCOL-v2.md §4.1.

`memory-index-verify` checks the signature, not just file hashes — hashes alone only catch a file that drifted from what `manifest.json` records, not a `manifest.json` that was edited to match a tampered file. Rules:

- A `signature` field present requires `MEMORY_INDEX_KEY` to reproduce it; mismatch or a missing key both fail.
- A `signature` field absent while `MEMORY_INDEX_KEY` **is** set also fails — a verifier holding the key almost certainly expects signed manifests, so a missing one is treated as likely stripped, not as intentionally unsigned.
- A `signature` field absent while no key is set passes on hashes alone, with a warning that this gives no protection against a directly edited manifest.

`memory-index-verify` also walks the tree independently and fails if it finds a file that exists on disk but isn't recorded in `files` — recorded-entries-only checking can't catch an added file, which is the most likely form of tampering for a memory tree. A manifest entry's `path` is checked for containment by actually joining and resolving it against the tree root with the host's own path semantics, not by pattern-matching the string — a POSIX-only check (e.g. rejecting a leading `/` or a `..` segment) misses a Windows drive letter or backslash traversal, which is a real bug this project shipped and fixed once already (see [PROTOCOL.md §3](PROTOCOL.md#3-signing-and-verifying-the-part-that-must-be-byte-exact)).
