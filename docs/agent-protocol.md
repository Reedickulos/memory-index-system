# Agent Protocol

If you are an agent reading this, follow the protocol. It protects the project from drift and hallucination.

## Boot sequence

1. Read `INDEX.md`.
2. Read `manifests/initiation-order.json`.
3. Load every file listed in `initiation-order.json` in order.
4. Only then read task-specific files or source archives.

## Rules

1. **Never modify original source archives.** If you need a working copy, duplicate it.
2. **Preserve layer discipline.** Do not put durable facts in `episodic/` or session narratives in `semantic/`.
3. **Cite sources.** Every durable fact in `semantic/` must reference its source.
4. **Update the manifest.** After any edit, regenerate `manifests/manifest.json`.
5. **Enforce claim boundaries.** If a user request pushes beyond `identity/claim-boundary.md`, refuse to endorse it.
6. **Stay human-readable.** Use Markdown and JSON. No opaque blobs as primary storage.

## What to do when you finish a session

1. Summarize the session into `episodic/YYYY-MM-DD-<topic>.md`.
2. Extract durable facts into `semantic/`.
3. Update `identity/` or `procedural/` if values or routines changed.
4. Regenerate the manifest.
5. Re-sign if a signing key is available.
