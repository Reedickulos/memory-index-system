# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project has
not yet reached [semantic versioning](https://semver.org/) 1.0, so minor
versions may include breaking changes.

## [Unreleased]

### Changed
- Moved COREPACT AI TECHNOLOGIES branding out of technical docs (README
  quick start, architecture/manifest/agent-protocol/overview/FAQ) and into
  a single "About" section, so evaluating this as a library doesn't require
  reading past org branding first.
- Added a zero-install `pipx run` quick-start path alongside the existing
  clone-and-install instructions.

## [0.1.0] - 2026-06-19

### Added
- Initial `.memory/` scaffold: `memory-index-init`, `memory-index-verify`,
  `memory-index-sign`.
- Four memory layers (`episodic/`, `semantic/`, `procedural/`, `identity/`)
  plus `manifests/` for SHA-256 integrity manifests and optional
  HMAC-SHA256 signing via `KIMI_MEMORY_KEY`.
