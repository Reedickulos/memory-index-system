# Architecture

## Directory layout

```text
.memory/
├── INDEX.md                 # Agent entry rule and map
├── manifests/
│   ├── initiation-order.json # Boot sequence
│   └── manifest.json         # SHA-256 (+ optional HMAC)
├── episodic/                # Dated session narratives
├── semantic/                # Durable facts and contracts
├── procedural/              # Operating instructions
├── identity/                # Charter, values, claim boundaries
└── scripts/                 # Local automation helpers
```

## Layers in detail

### `episodic/`

One file per day or per significant session. Contains:

- Date and participants.
- What was discussed or decided.
- Open questions and next steps.
- Source citations.

### `semantic/`

The knowledge graph of the project. Files are topic-based, not date-based. Examples:

- Hypothesis statements.
- Architecture contracts.
- Parameter tables.
- Known gaps and risks.

### `procedural/`

How to operate on the project. Examples:

- Agent handoff protocol.
- Naming conventions.
- Manifest regeneration steps.
- Resume-session prompts.

### `identity/`

The project’s self-model. This is where alignment lives:

- Project charter.
- Claim boundaries.
- Values and non-goals.

## Integrity

- `manifests/manifest.json` lists every file and its SHA-256 hash.
- `manifests/initiation-order.json` tells an agent which files to read first.
- `scripts/verify-manifest.py` re-computes hashes and reports mismatches.
- `scripts/sign-manifest.py` rewrites the manifest and appends an HMAC-SHA256 signature if `MEMORY_INDEX_KEY` is set.
