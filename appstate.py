"""In-memory live state for the monitoring dashboard.

The bot runs single-threaded on one asyncio loop, so a plain object with no
locks is safe: writers (run_strategy_cycle / run_agent) and the reader (the
web handler) never run concurrently. `snapshot()` returns a JSON-serializable
copy for the /api/state endpoint.
"""
from __future__ import annotations

from collections import deque


class AppState:
    def __init__(self, max_events: int = 50, started_at: str | None = None):
        self._mode = "DRY-RUN"
        self._started_at = started_at
        self._market: dict = {
            "price": None, "quarter": None, "in_session": None,
            "next_poll": None, "levels": {}, "bias": {}, "volume_profile": {},
        }
        self._last_signal: dict | None = None
        self._events: deque = deque(maxlen=max_events)

    def update_mode(self, live: bool) -> None:
        self._mode = "LIVE" if live else "DRY-RUN"

    def update_market(self, price=None, quarter=None, in_session=None,
                      next_poll=None, levels=None, bias=None, volume_profile=None) -> None:
        self._market.update({
            "price": price, "quarter": quarter, "in_session": in_session,
            "next_poll": next_poll, "levels": levels or {},
            "bias": bias or {}, "volume_profile": volume_profile or {},
        })

    def update_signal(self, signal: dict) -> None:
        self._last_signal = signal

    def record_event(self, msg: str, ts: str | None = None) -> None:
        self._events.append({"ts": ts, "msg": msg})

    def snapshot(self) -> dict:
        return {
            "mode": self._mode,
            "started_at": self._started_at,
            "price": self._market["price"],
            "quarter": self._market["quarter"],
            "in_session": self._market["in_session"],
            "next_poll": self._market["next_poll"],
            "levels": dict(self._market["levels"]),
            "bias": dict(self._market["bias"]),
            "volume_profile": dict(self._market["volume_profile"]),
            "last_signal": self._last_signal,
            "events": list(self._events),
        }


# Process-wide singleton imported by main.py and the web server.
STATE = AppState()
