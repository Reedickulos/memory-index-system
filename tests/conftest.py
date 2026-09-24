import pytest

from memory_index_system.ratchet import RATCHET_PATH_ENV


@pytest.fixture(autouse=True)
def isolated_revision_record(tmp_path, monkeypatch):
    """Keep every test's revision record out of the real home directory, and
    independent of every other test's."""
    path = tmp_path / "ratchet.json"
    monkeypatch.setenv(RATCHET_PATH_ENV, str(path))
    return path
