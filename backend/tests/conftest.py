from pathlib import Path

import pytest

from core import service
from core.cache import TTLCache
from data import fetcher
from data.fetcher import UpstreamError

FIXTURE = Path(__file__).parent / "fixtures" / "germany_sample.xml"


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    """Every test starts with empty caches and no network access to the forecast file."""
    monkeypatch.setattr(service, "cache", TTLCache())
    monkeypatch.setattr(service, "forecast_cache", TTLCache())

    def no_pipeline(url):
        raise UpstreamError("forecast file not available in tests")

    monkeypatch.setattr(fetcher, "fetch_forecast_file", no_pipeline)


@pytest.fixture
def energy_xml() -> str:
    return FIXTURE.read_text(encoding="utf-8")
