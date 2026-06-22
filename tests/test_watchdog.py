"""Tests for ccremote.watchdog — the WS-liveness watchdog decision logic.

The decision (should we self-exit so launchd relaunches us?) is a pure
function so it is fully testable offline, with no threads, sockets, or lark.
The state holder (set/clear driven by lark's on_reconnecting/on_reconnected
hooks) is exercised too. The network probe and the loop are thin and not
unit-tested here (they touch sockets / sleep)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ccremote import watchdog


# ---- should_restart: the pure decision ----

def test_connected_never_restarts():
    # down_since None == currently connected -> never restart, regardless.
    assert watchdog.should_restart(None, now=10_000, threshold_sec=180,
                                   reachable=True) is False


def test_down_but_within_threshold_does_not_restart():
    # Disconnected for less than the threshold: give lark's own reconnect a
    # full cycle to recover before we step in.
    assert watchdog.should_restart(1000, now=1000 + 179, threshold_sec=180,
                                   reachable=True) is False


def test_down_past_threshold_and_reachable_restarts():
    # Down long enough AND Feishu reachable -> a fresh process will connect.
    assert watchdog.should_restart(1000, now=1000 + 181, threshold_sec=180,
                                   reachable=True) is True


def test_down_past_threshold_but_unreachable_does_not_restart():
    # Network still down: restarting would just spin into another dead
    # connection. Only log and wait.
    assert watchdog.should_restart(1000, now=1000 + 999, threshold_sec=180,
                                   reachable=False) is False


def test_exactly_at_threshold_does_not_restart():
    # Boundary: strictly greater than threshold required.
    assert watchdog.should_restart(1000, now=1000 + 180, threshold_sec=180,
                                   reachable=True) is False


# ---- WatchdogState: driven by lark hooks ----

def test_state_starts_connected():
    s = watchdog.WatchdogState()
    assert s.down_since() is None


def test_mark_disconnected_records_first_time_only():
    s = watchdog.WatchdogState()
    s.mark_disconnected(now=500)
    assert s.down_since() == 500
    # A second on_reconnecting while still down must NOT reset the clock —
    # otherwise the threshold never elapses during a long outage.
    s.mark_disconnected(now=600)
    assert s.down_since() == 500


def test_mark_connected_clears():
    s = watchdog.WatchdogState()
    s.mark_disconnected(now=500)
    s.mark_connected()
    assert s.down_since() is None
    # And a later disconnect starts a fresh clock.
    s.mark_disconnected(now=900)
    assert s.down_since() == 900


# ---- run loop: wiring of decision -> exit, with injected deps ----

def test_run_exits_when_down_past_threshold_and_reachable():
    s = watchdog.WatchdogState()
    s.mark_disconnected(now=0)
    exited = []
    stop = _StopAfter(2)  # run() checks is_set twice/iter; 2 lets the body run once
    watchdog.run(s, threshold_sec=180, interval_sec=60,
                 exit_fn=lambda: exited.append(True),
                 reachable_fn=lambda: True,
                 clock=lambda: 999,         # 999 - 0 = 999 > 180
                 sleep_fn=lambda _x: None,
                 stop=stop)
    assert exited == [True]


def test_run_does_not_exit_when_unreachable():
    s = watchdog.WatchdogState()
    s.mark_disconnected(now=0)
    exited = []
    stop = _StopAfter(3)  # several iterations, must never exit
    watchdog.run(s, threshold_sec=180, interval_sec=60,
                 exit_fn=lambda: exited.append(True),
                 reachable_fn=lambda: False,   # network still down
                 clock=lambda: 999,
                 sleep_fn=lambda _x: None,
                 stop=stop)
    assert exited == []


def test_run_does_not_exit_while_connected():
    s = watchdog.WatchdogState()  # never marked down
    exited = []
    stop = _StopAfter(3)
    watchdog.run(s, threshold_sec=180, interval_sec=60,
                 exit_fn=lambda: exited.append(True),
                 reachable_fn=lambda: True,
                 clock=lambda: 999,
                 sleep_fn=lambda _x: None,
                 stop=stop)
    assert exited == []


class _StopAfter:
    """A stand-in for threading.Event that reports 'set' after N is_set()
    checks, so run()'s loop executes a bounded number of iterations."""
    def __init__(self, n):
        self._n = n
        self._calls = 0

    def is_set(self):
        self._calls += 1
        return self._calls > self._n
