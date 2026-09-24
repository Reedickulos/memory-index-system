# FAQ

## Why not just use a database?

Databases are great for structured data, but they are opaque to humans and hard to hand off across agents. This system optimizes for readability, portability, and git-friendly diffs.

## Can I use this without Python?

Yes. The memory tree is just Markdown and JSON. The Python CLI and scripts are helpers, not requirements.

## What if an agent ignores the boot sequence?

That is a known risk. The `INDEX.md` begins with an explicit agent-entry rule, and the `initiation-order.json` is standardized. Future versions may include stronger enforcement hooks.

## How is this different from RAG?

RAG retrieves snippets from a corpus. This system preserves structured, authored context with explicit provenance and claim boundaries.

## Do I have to sign the manifest?

No. SHA-256 hashes are enough to detect accidental drift. HMAC-SHA256 signing is optional and only protects against tampering if the key is kept secret.

## Can I embed this inside another repo?

Yes. The `.memory/` tree can live inside any project. Add `*.key` and `KIMI_MEMORY_KEY` to `.gitignore` if you use signing.
