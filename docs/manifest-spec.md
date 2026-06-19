# Manifest Specification

> **CORE-LAB — A DIVISION OF COREPACT AI TECHNOLOGIES**  
> **ALIGNED BY DESIGN**

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
| `file_count` | integer | Number of files |
| `files` | array | `{path, sha256}` entries |
| `signature` | object | Optional HMAC-SHA256 signature |

### Signature

If `KIMI_MEMORY_KEY` is set, the manifest is signed over the canonical JSON of the `files` array. The signature object is appended after signing.
