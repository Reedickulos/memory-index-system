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
  signature. See docs/PROTOCOL-v2.md.
- v1-signed manifests are rejected by verify rather than accepted with a
  warning: a v2 manifest could be relabelled with a v1 signature over the
  same files to edit `revision` or `tree_id` without the key. A genuine
  pre-v2 tree is upgraded once with the new `memory-index-migrate`, which
  verifies it fully under v1 first; running it needs a person's judgement
  (see docs/PROTOCOL-v2.md §4.2).
- `memory-index-sign` (and the in-tree `sign-manifest.py`) now authenticate
  the current manifest before carrying its `revision` and `tree_id` forward,
  so editing either without the key is refused instead of being signed as
  valid. An unsigned or missing manifest needs `--adopt-unsigned` once when
  a key is set; setting the key before `memory-index-init` avoids that.
  Without the key, signing a signed tree is refused instead of writing it
  back unsigned (which stripped its signature).
- `memory-index-sign` refreshes the tree's `scripts/*.py` from the current
  template on every run, so a tree's bundled verifier can always check the
  format just written. Running `.memory/scripts/sign-manifest.py` with no
  package installed can't do this — see docs/PROTOCOL-v2.md §4.3.
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
