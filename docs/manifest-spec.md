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
  "file_count": 42,
  "files": [
    {
      "path": "INDEX.md",
      "sha256": "..."
    }
  ],
  "signature": {
    "alg": "HMAC-SHA256",
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
| `file_count` | integer | Number of files |
| `files` | array | `{path, sha256}` entries |
| `signature` | object | Optional HMAC-SHA256 signature |

### Signature

If `KIMI_MEMORY_KEY` is set, the manifest is signed over the canonical JSON of the `files` array. The signature object is appended after signing.

`memory-index-verify` checks the signature, not just file hashes — hashes alone only catch a file that drifted from what `manifest.json` records, not a `manifest.json` that was edited to match a tampered file. Rules:

- A `signature` field present requires `KIMI_MEMORY_KEY` to reproduce it; mismatch or a missing key both fail.
- A `signature` field absent while `KIMI_MEMORY_KEY` **is** set also fails — a verifier holding the key almost certainly expects signed manifests, so a missing one is treated as likely stripped, not as intentionally unsigned.
- A `signature` field absent while no key is set passes on hashes alone, with a warning that this gives no protection against a directly edited manifest.

`memory-index-verify` also walks the tree independently and fails if it finds a file that exists on disk but isn't recorded in `files` — recorded-entries-only checking can't catch an added file, which is the most likely form of tampering for a memory tree. Manifest entries whose `path` is absolute or contains a `..` segment are rejected rather than resolved, since only hash comparison happens against them (see [PROTOCOL.md §3](PROTOCOL.md#3-signing-and-verifying-the-part-that-must-be-byte-exact)).
