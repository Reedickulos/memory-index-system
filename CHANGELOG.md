# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project has
not yet reached [semantic versioning](https://semver.org/) 1.0, so minor
versions may include breaking changes.

## [Unreleased]

### Security
- Signature verification now fails if a signature is absent while a signing
  key is available (previously passed with a warning, letting a tamper +
  signature-strip attack through undetected).
- `memory-index-verify` now detects files present on disk but not recorded
  in the manifest, and rejects manifest entries whose path could escape the
  tree root (validated using the host's own path semantics, not a
  POSIX-only pattern check — the original path-safety fix had a Windows
  drive-letter/backslash bypass, since fixed).
- Manifest signing (v2, `"alg": "HMAC-SHA256-v2"`) now covers `revision` and
  a new `tree_id` field, not just `files` — previously either could be
  edited by anyone without the signing key without invalidating the
  signature. See docs/PROTOCOL-v2.md. Manifests signed under the old format
  still verify, flagged as legacy; `memory-index-sign` upgrades a tree to
  v2 automatically on its next run.
- Fixed: that same v1→v2 upgrade used to leave a tree's own bundled
  `scripts/verify-manifest.py` on the old files-only format, so it rejected
  the tree's own manifest immediately after `memory-index-sign` upgraded it
  (reproduced against a v1 template tree with `KIMI_MEMORY_KEY` set).
  `memory-index-sign` now refreshes `scripts/*.py` from the current template
  as part of that same upgrade, so the in-tree verifier can check what was
  just written. Doesn't cover the fully standalone workflow (running
  `.memory/scripts/sign-manifest.py` with no package installed) — see
  docs/PROTOCOL-v2.md §4 for that remaining gap.
- `memory-index-sign` now holds an advisory lock for its read-check-write
  sequence and writes `manifest.json` atomically, closing most of a race
  where two concurrent signs could both pass `--expect-revision`.

### Changed
- Moved COREPACT AI TECHNOLOGIES branding out of technical docs (README
  quick start, architecture/manifest/agent-protocol/overview/FAQ) and into
  a single "About" section, so evaluating this as a library doesn't require
  reading past org branding first.
- Added a zero-install `pipx run` quick-start path alongside the existing
  clone-and-install instructions.
- Added the cross-project registry (`memory-index-registry-scan/-list/
  -search/-diff`), staleness flagging, and `docs/PROTOCOL.md` (v1).

## [0.1.0] - 2026-06-19

### Added
- Initial `.memory/` scaffold: `memory-index-init`, `memory-index-verify`,
  `memory-index-sign`.
- Four memory layers (`episodic/`, `semantic/`, `procedural/`, `identity/`)
  plus `manifests/` for SHA-256 integrity manifests and optional
  HMAC-SHA256 signing via `KIMI_MEMORY_KEY`.
