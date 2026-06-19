# Contributing to Memory Index System

> **A COREPACT AI TECHNOLOGIES Project**  
> **ALIGNED BY DESIGN**

Thank you for helping make agent memory safer, more portable, and more honest.

## How to contribute

1. **Open an issue first** for significant changes.
2. **Fork the repo** and create a feature branch.
3. **Write tests** for new behavior.
4. **Run the test suite** with `pytest`.
5. **Submit a pull request** with a clear description and references.

## What we value

- **Human-readable first.** Markdown and JSON are the primary storage formats.
- **Integrity.** Every change to memory artifacts should be manifest-tracked.
- **Alignment.** Safety, traceability, and claim boundaries are not optional.
- **Portability.** A memory package should boot anywhere without hard-drive access.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Development setup

```bash
git clone https://github.com/reedickulos/memory-index-system.git
cd memory-index-system
pip install -e ".[dev]"
pytest
```
