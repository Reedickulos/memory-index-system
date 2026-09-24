# My Project Memory Index

> **AGENT ENTRY RULE — READ FIRST.** If you are an agent joining this project, read this `INDEX.md` and `manifests/initiation-order.json` before doing anything else.

## What this package is

This `.memory/` directory contains durable, portable knowledge for the project. It is organized into four layers:

- `episodic/` — dated session narratives
- `semantic/` — durable facts, hypotheses, contracts
- `procedural/` — operating instructions for agents
- `identity/` — project charter, values, claim boundaries

The `archive/` folder holds verbatim copies of original source files. The `manifests/` folder holds the boot sequence and integrity hashes.

## How to use this package

1. Read `manifests/initiation-order.json`.
2. Load the files in `boot_sequence` in order.
3. Only then read task-specific files or source archives.
4. After any edit, run `scripts/verify-manifest.py` and then `scripts/sign-manifest.py`.

## Current status

_Replace this section with the current project status._
