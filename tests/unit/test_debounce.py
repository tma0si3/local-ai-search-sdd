"""Unit tests for the debounce (T051).

The debounce is what stops one keystroke-triggered save from rebuilding a 500-document
index repeatedly, so it is tested directly rather than through the observer.
"""

from __future__ import annotations

import time

from localsearch.watcher import QUIET_PERIOD_SECONDS, Debouncer


def test_a_burst_of_events_produces_one_action():
    calls = []
    debouncer = Debouncer(0.1, lambda: calls.append(time.monotonic()))

    for _ in range(20):
        debouncer.trigger()
        time.sleep(0.005)

    time.sleep(0.3)
    assert len(calls) == 1


def test_events_spaced_beyond_the_quiet_period_produce_separate_actions():
    calls = []
    debouncer = Debouncer(0.1, lambda: calls.append(time.monotonic()))

    debouncer.trigger()
    time.sleep(0.25)
    debouncer.trigger()
    time.sleep(0.25)

    assert len(calls) == 2


def test_nothing_fires_before_the_quiet_period_elapses():
    calls = []
    debouncer = Debouncer(0.3, lambda: calls.append(1))
    debouncer.trigger()
    time.sleep(0.1)
    assert calls == []
    debouncer.cancel()


def test_cancel_prevents_a_pending_action():
    calls = []
    debouncer = Debouncer(0.1, lambda: calls.append(1))
    debouncer.trigger()
    debouncer.cancel()
    time.sleep(0.25)
    assert calls == []


def test_pending_reports_whether_an_action_is_waiting():
    debouncer = Debouncer(0.3, lambda: None)
    assert not debouncer.pending
    debouncer.trigger()
    assert debouncer.pending
    debouncer.cancel()
    assert not debouncer.pending


def test_quiet_period_matches_the_specification():
    # FR-031 says approximately five seconds. If this drifts, the spec and code disagree.
    assert QUIET_PERIOD_SECONDS == 5.0
