from __future__ import annotations

from crawler.cache import SourceCache


def test_returns_none_for_missing_entry(tmp_path):
    cache = SourceCache(tmp_path)
    assert cache.get(1, "0xabc") is None


def test_roundtrips_stored_value(tmp_path):
    cache = SourceCache(tmp_path)
    cache.set(1, "0xAbC", {"hello": "world"})
    assert cache.get(1, "0xabc") == {"hello": "world"}  # lookup is case-insensitive


def test_separates_by_chain_id(tmp_path):
    cache = SourceCache(tmp_path)
    cache.set(1, "0xabc", {"chain": 1})
    cache.set(100, "0xabc", {"chain": 100})
    assert cache.get(1, "0xabc") == {"chain": 1}
    assert cache.get(100, "0xabc") == {"chain": 100}
