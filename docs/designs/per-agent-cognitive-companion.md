> **COREPACT AI TECHNOLOGIES — ALIGNED BY DESIGN**

# Design: Per-Agent Cognitive Companion

## Problem

AI agents in long-running councils or research loops are usually stateless between calls. Their context is owned by the orchestrator, and their individual reasoning traces are lost or merged into a single session log. This makes it easy for an agent to:

- Drift from its own prior reasoning.
- Repeat itself without adding new information.
- Lose sight of the constitutional or safety framework it agreed to.

## Proposal

Give every agent its own lightweight **Cognitive Companion**: a memory worker that sits beside the agent, not above it.

## Principles

1. **Sovereignty-first.** The companion can remember, mirror, and nudge. It cannot edit or override the agent’s output.
2. **Memory as identity.** The companion maintains a per-agent memory ledger so the agent has continuity across rounds.
3. **Constitutional mirroring.** The companion surfaces relevant constitutional clauses when drift is detected.
4. **Constructive evolution.** The companion uses an `evolve → evaluate → analyze` loop on the agent’s own trace to suggest better reasoning paths.

## Architecture

```textnAgent Seat (C1..Cn)
    │
    ├─► Cognitive Companion
    │       ├─ Per-agent memory ledger (episodic + semantic)
    │       ├─ Drift / repetition detector
    │       ├─ Constitutional relevance matcher
    │       └─ ASI-style self-evolution loop
    │
    └─► Final response (agent remains in control)
```

## Triggers

The companion activates when it detects:

- **Semantic repetition** — current output is too similar to prior outputs.
- **Drift** — current output contradicts the agent’s own ledger or the constitution.
- **Low information gain** — the response adds no new artifact, test, or claim.
- **Constitutional gap** — the response ignores a ratified rule or claim boundary.

## Companion actions

When a trigger fires, the companion may:

1. Append a short memory note to the agent’s ledger.
2. Include a **mirror prompt** in the agent’s next turn: "You previously argued X; your current response leans Y. Here is the relevant constitutional clause."
3. Suggest a **disturb question** for the agent to ask itself.

It never:

- Replaces the agent’s response.
- Votes on consensus.
- Enforces penalties.

## Relationship to Memory Index System

The companion reads and writes a per-agent `.memory/` tree using the same four-layer structure:

- `episodic/` — per-agent turn-by-turn trace.
- `semantic/` — durable beliefs and claims the agent has committed to.
- `procedural/` — how this agent should operate.
- `identity/` — this agent’s charter and boundaries.

## Open questions

- Should the companion be a separate worker process or a prompt-layer wrapper?
- What are the right thresholds for drift and repetition?
- How does the companion avoid becoming a second hidden controller?

## Status

Conceptual design. Implementation is tracked in the project backlog.
