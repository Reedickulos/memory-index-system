# Registry Specification

> **A COREPACT AI TECHNOLOGIES Project**
> **ALIGNED BY DESIGN**

The registry indexes every initialized `.memory/` tree found under one or
more scanned directories, so an agent (or a person) can discover other
projects on the same machine before starting work. It lives outside any
single project, at `~/.memory-registry/` by default.

## `~/.memory-registry/registry.json`

```json
{
  "version": "1.0",
  "updated": "2026-09-24T01:23:56+00:00",
  "projects": [
    {
      "id": "ledger",
      "path": "C:\\Users\\johnd\\Desktop\\PROJECTS\\LEDGER\\.memory",
      "name": "Ledger Continuity",
      "summary": "# Project Charter\n\n## Name\n\nLedger Continuity\n\n## Purpose\n\n...",
      "tags": [],
      "status": "active",
      "last_synced": "2026-09-24T01:23:56+00:00",
      "manifest_hash": "sha256:...",
      "identity_summary": {
        "charter": "<full contents of identity/project-charter.md>",
        "claim_boundary": "<full contents of identity/claim-boundary.md>"
      }
    }
  ]
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `id` | string | The project directory's name (the parent of `.memory/`) |
| `path` | string | Absolute path to the project's `.memory/` directory |
| `name` | string | Parsed from the `## Name` section of `identity/project-charter.md`; falls back to a humanized `id` if the charter is missing or still has its placeholder text |
| `summary` | string | First 250 characters of the charter |
| `tags` | array | Parsed from a `## Tags` section in `identity/project-charter.md` (comma-separated); `[]` if the section is absent |
| `status` | string | Always `"active"` today; reserved for future archival states |
| `last_synced` | string | ISO 8601 timestamp of the scan that produced this entry |
| `manifest_hash` | string | `sha256:<hex>` of the project's own `manifests/manifest.json` file, as it stood at scan time |
| `identity_summary.charter` | string | Full contents of `identity/project-charter.md` |
| `identity_summary.claim_boundary` | string | Full contents of `identity/claim-boundary.md` |

Only `identity/` content is copied into the registry. `episodic/`,
`semantic/`, and `procedural/` files are never read by the scan — the
registry is meant to be safe to hand to another agent as an index, not a
copy of everything every project knows.

Staleness is not stored as part of an entry — it's computed at read time
from `last_synced` (see `is_stale()` and `memory-index-registry-list
--stale-days`), so it always reflects "now," not the state at scan time.

### What counts as a project

A directory counts as an indexed project only if it contains a `.memory/`
folder with a `manifests/manifest.json` inside it. A bare `.memory/`
directory without a manifest (e.g. created some other way, or mid-`init`)
is not indexed.

## `~/.memory-registry/scan-roots.json`

```json
{
  "roots": [
    "C:\\Users\\johnd\\Desktop\\PROJECTS"
  ]
}
```

Written by `memory-index-registry-scan --save-roots <dir>...`. A later
`memory-index-registry-scan` with no directory arguments scans the roots
saved here, in addition to any new ones passed on the command line.

## Not implemented (on purpose)

The registry does not compute a "god nodes" field naming the most central
or influential memory entries across projects. That idea traces back to a
per-agent "cognitive companion" concept that was reverted from this repo
pending a privacy review that has not happened. Adding it here, even as
inert data, would resurrect that design ahead of the review it's waiting on.
