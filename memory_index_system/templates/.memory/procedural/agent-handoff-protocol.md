# Agent Handoff Protocol

> **MUST READ BEFORE ANY WORK.**

## Boot sequence

1. Read `INDEX.md`.
2. Read `manifests/initiation-order.json`.
3. Load the files in `boot_sequence` in order.

## Rules

1. Never modify original source archives.
2. Preserve layer discipline.
3. Cite sources for every durable fact.
4. Update `manifests/manifest.json` after edits.
5. Enforce `identity/claim-boundary.md`.
6. Keep all artifacts human-readable (Markdown/JSON).
