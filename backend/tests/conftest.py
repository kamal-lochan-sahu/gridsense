from pathlib import Path

import pytest

from core import service
from core.cache import TTLCache

FIXTURE = Path(__file__).parent / "fixtures" / "germany_sample.xml"


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    """Every test starts with an empty cache."""
    monkeypatch.setattr(service, "cache", TTLCache())


@pytest.fixture
def energy_xml() -> str:
    return FIXTURE.read_text(encoding="utf-8")
