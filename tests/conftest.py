import os

import pytest


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path_factory, monkeypatch):
    """Rendered tiles and health probes write under STORAGE_ROOT; keep that out of the repository."""
    monkeypatch.setenv("NASA_POWER", "off")  # cases never call the network in tests
    if not os.environ.get("KEEP_STORAGE_ROOT"):
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path_factory.mktemp("storage")))
