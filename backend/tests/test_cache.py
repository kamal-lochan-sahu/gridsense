import threading
import time

import pytest

from core.cache import TTLCache


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_returns_cached_value_within_ttl():
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    calls = []

    def loader():
        calls.append(1)
        return "value"

    assert cache.get_or_load("k", 60, loader) == ("value", False)
    clock.now = 59
    assert cache.get_or_load("k", 60, loader) == ("value", False)
    assert len(calls) == 1


def test_reloads_after_ttl():
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    values = iter(["first", "second"])

    assert cache.get_or_load("k", 60, lambda: next(values)) == ("first", False)
    clock.now = 61
    assert cache.get_or_load("k", 60, lambda: next(values)) == ("second", False)


def failing_loader():
    raise RuntimeError("upstream down")


def test_serves_stale_value_when_reload_fails():
    clock = FakeClock()
    cache = TTLCache(max_stale_seconds=1000, clock=clock)
    cache.get_or_load("k", 60, lambda: "old")
    clock.now = 100
    assert cache.get_or_load("k", 60, failing_loader) == ("old", True)


def test_stale_value_is_dropped_after_max_stale():
    clock = FakeClock()
    cache = TTLCache(max_stale_seconds=500, clock=clock)
    cache.get_or_load("k", 60, lambda: "old")
    clock.now = 600
    with pytest.raises(RuntimeError):
        cache.get_or_load("k", 60, failing_loader)


def test_error_without_cached_value_is_raised():
    with pytest.raises(RuntimeError):
        TTLCache().get_or_load("k", 60, failing_loader)


def test_ages_reports_seconds_since_load():
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    cache.get_or_load("k", 60, lambda: "v")
    clock.now = 12.34
    assert cache.ages() == {"k": 12.3}


def test_concurrent_callers_share_a_single_load():
    cache = TTLCache()
    calls = []
    results = []

    def loader():
        calls.append(1)
        time.sleep(0.2)
        return "value"

    def worker():
        results.append(cache.get_or_load("k", 60, loader))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1
    assert results == [("value", False)] * 5
