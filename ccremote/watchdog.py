"""WS-liveness watchdog for the bridge.

The bridge's lark WebSocket can die (e.g. `keepalive ping timeout` after a
network switch) while the process stays alive — lark's own reconnect sometimes
never recovers, so the bridge sits "alive but not connected to Feishu" and
messages stop arriving. launchd is configured with KeepAlive={SuccessfulExit:
false} + ThrottleInterval, so a *non-zero exit* gets us a fresh process (and a
brand-new connection) within seconds.

This module decides WHEN to take that exit. Liveness is tracked via lark's own
public `on_reconnecting` / `on_reconnected` hooks (no SDK modification) — so it
does NOT depend on the user sending messages: a quiet chat is not a dead one.
A separate watchdog thread polls on a fixed interval and, only when the link
has been down past a threshold AND Feishu is actually reachable again, exits so
launchd relaunches. If the network is still down it just logs and waits —
restarting into an unreachable network would only spin into another dead
connection.

`should_restart` is a pure function so the policy is fully unit-testable
offline; the thread loop and socket probe are thin wrappers around it.
"""

import logging
import os
import socket
import threading
import time

log = logging.getLogger("bridge.watchdog")


def should_restart(down_since, now, threshold_sec, reachable):
    """Pure decision: should the bridge self-exit so launchd relaunches it?

    - down_since is None  -> connected; never restart.
    - down for <= threshold_sec -> still within lark's own reconnect window; wait.
    - down for > threshold_sec but Feishu unreachable -> network still down; wait.
    - down for > threshold_sec AND reachable -> yes, a fresh process will connect.
    """
    if down_since is None:
        return False
    if now - down_since <= threshold_sec:
        return False
    return bool(reachable)


class WatchdogState:
    """Tracks when the WS link went down. Driven by lark's reconnect hooks.

    mark_disconnected/mark_connected may be called from lark's async loop while
    the watchdog thread reads down_since(); a lock keeps that race clean."""

    def __init__(self):
        self._down_since = None
        self._lock = threading.Lock()

    def mark_disconnected(self, now):
        """Record the link as down. Idempotent while already down: the first
        timestamp wins, so a long outage's clock is not reset by repeated
        on_reconnecting fires (which would stop the threshold ever elapsing)."""
        with self._lock:
            if self._down_since is None:
                self._down_since = now

    def mark_connected(self):
        """Clear the down state — the link is healthy again."""
        with self._lock:
            self._down_since = None

    def down_since(self):
        with self._lock:
            return self._down_since


def feishu_reachable(host="open.feishu.cn", port=443, timeout=5):
    """Best-effort TCP reachability probe. True if we can open a socket to
    Feishu. Never raises — any failure means 'not reachable'."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def run(state, threshold_sec, interval_sec, exit_fn=None, reachable_fn=None,
        clock=None, sleep_fn=None, stop=None):
    """Watchdog loop. Every interval_sec, if the link has been down past
    threshold_sec and Feishu is reachable, call exit_fn (default os._exit(1))
    so launchd relaunches the bridge with a fresh connection. Otherwise log and
    keep waiting. Runs until `stop` (a threading.Event) is set, if given.

    Injectable deps (exit_fn/reachable_fn/clock/sleep_fn/stop) keep it testable;
    defaults wire the real os/socket/time."""
    exit_fn = exit_fn or (lambda: os._exit(1))
    reachable_fn = reachable_fn or feishu_reachable
    clock = clock or time.time
    sleep_fn = sleep_fn or time.sleep

    while not (stop and stop.is_set()):
        sleep_fn(interval_sec)
        if stop and stop.is_set():
            break
        ds = state.down_since()
        if ds is None:
            continue
        down_for = int(clock() - ds)
        if down_for <= threshold_sec:
            log.warning(f"WS link down for {down_for}s (threshold {threshold_sec}s); "
                        "waiting for lark auto-reconnect")
            continue
        if not reachable_fn():
            log.warning(f"WS link down for {down_for}s but Feishu unreachable; "
                        "network still down — only waiting, not restarting")
            continue
        log.error(f"WS link down for {down_for}s and Feishu reachable; "
                  "exiting so launchd relaunches with a fresh connection")
        exit_fn()
        return  # exit_fn normally does not return; guard for the injected case


def start_thread(state, threshold_sec, interval_sec):
    """Spawn the watchdog as a daemon thread (always running, independent of
    user activity). Returns the thread."""
    t = threading.Thread(
        target=run, args=(state, threshold_sec, interval_sec),
        name="ws-watchdog", daemon=True)
    t.start()
    return t
