# Overview

The Memory Index System is a lightweight, file-based knowledge architecture for projects that span multiple AI sessions, models, or human collaborators.

## The problem

When you work with AI assistants on complex research or engineering, most of the context lives in:

- A chat thread that will eventually be lost or summarized away.
- A human’s head.
- A hard-drive path that another agent cannot access.
- Scattered files with no enforced structure.

That makes continuity fragile. It also makes claims untraceable: you cannot tell whether an output came from a source, a hallucination, or a tuned prompt.

## The solution

The Memory Index System packages context into a self-contained `.memory/` directory with four layers:

- **Episodic** — what happened, when, and why.
- **Semantic** — durable facts, hypotheses, and contracts.
- **Procedural** — how any agent should continue the work.
- **Identity** — what the project is, what it values, and what it refuses to claim.

A manifest and boot sequence enforce integrity and orientation.

## Design principles

1. **Human-readable first.** Markdown and JSON are primary; embeddings are secondary indexes only.
2. **Portable.** Zip the tree and hand it off.
3. **Integrity-checked.** SHA-256 hashes detect drift; HMAC-SHA256 detects tampering.
4. **Alignment-first.** Safety, traceability, and claim boundaries are structural, not optional.

## When to use this

- Long-running research threads.
- Multi-agent workflows.
- Projects with falsifiable hypotheses.
- Any work where traceability matters more than speed.
