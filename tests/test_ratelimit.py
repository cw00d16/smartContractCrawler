from __future__ import annotations

from crawler import ratelimit as ratelimit_module
from crawler.ratelimit import RateLimiter


def test_enforces_minimum_interval_between_calls(monkeypatch):
    fake_clock = [1000.0]  # start away from 0.0 to mimic a real monotonic clock
    sleeps: list[float] = []

    def fake_monotonic():
        return fake_clock[0]

    def fake_sleep(seconds):
        sleeps.append(seconds)
        fake_clock[0] += seconds

    monkeypatch.setattr(ratelimit_module.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(ratelimit_module.time, "sleep", fake_sleep)

    limiter = RateLimiter(calls_per_second=5)  # min_interval = 0.2s

    limiter.wait()  # first call: no prior call recorded yet, should not sleep
    limiter.wait()  # immediate second call: must wait out the full interval
    limiter.wait()  # immediate third call: same

    assert sleeps == [0.2, 0.2]


def test_no_sleep_when_enough_time_has_already_passed(monkeypatch):
    fake_clock = [1000.0]
    sleeps: list[float] = []

    monkeypatch.setattr(ratelimit_module.time, "monotonic", lambda: fake_clock[0])
    monkeypatch.setattr(ratelimit_module.time, "sleep", lambda s: sleeps.append(s))

    limiter = RateLimiter(calls_per_second=5)  # min_interval = 0.2s
    limiter.wait()
    fake_clock[0] += 1.0  # plenty of time passes between calls
    limiter.wait()

    assert sleeps == []
