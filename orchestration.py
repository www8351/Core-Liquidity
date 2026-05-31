"""Pure orchestration helpers used by the intraday strategy loop.

Kept free of I/O so they are unit-testable; main.py supplies data, the broker,
and Telegram delivery around them.
"""
from __future__ import annotations

import os
from datetime import datetime

from execution import is_live_trading

# Trading window in NY hours [start, end). Default 02:00–16:00 NY covers the
# London session through the New York session. Override via env.
SESSION_START_HOUR = int(os.getenv("SESSION_START_HOUR", "2"))
SESSION_END_HOUR = int(os.getenv("SESSION_END_HOUR", "16"))


def in_session(now: datetime) -> bool:
    """True during the London+NY window on weekdays (NY time)."""
    if now.weekday() >= 5:  # Sat/Sun
        return False
    return SESSION_START_HOUR <= now.hour < SESSION_END_HOUR


class CycleGuard:
    """Ensures at most one action per (date, 90-min cycle) so a 5-minute poll
    cannot fire duplicate orders inside the same Q3 window."""

    def __init__(self):
        self._acted: set[tuple[str, int]] = set()

    def should_act(self, key: dict) -> bool:
        k = (key["date"], key["cycle_index"])
        if k in self._acted:
            return False
        self._acted.add(k)
        return True


def _fmt(v) -> str:
    return f"{v:.2f}" if isinstance(v, (int, float)) else str(v)


def format_signal_message(signal: dict, levels: dict) -> str:
    """Telegram-safe HTML summary of a deterministic signal."""
    mode = "LIVE" if is_live_trading() else "DRY-RUN"
    meta = signal.get("meta", {})
    q = meta.get("micro_quarter", "?")

    if signal["direction"] == "none":
        return (
            f"⚪️ <b>XAUUSD Quarterly-Theory</b>  [{mode}]\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>NO TRADE</b>  (quarter {q})\n"
            f"💬 {signal.get('reason', '')}\n"
            f"💰 Price: <code>{_fmt(levels.get('Current'))}</code>"
        )

    arrow = "🟢" if signal["direction"] == "long" else "🔴"
    return (
        f"{arrow} <b>XAUUSD {signal['direction'].upper()}</b>  [{mode}]\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 Quarter: <b>{q}</b>  |  Bias: <b>{meta.get('bias', '?')}</b>\n"
        f"<pre>\n"
        f"Entry : {_fmt(signal['entry'])}\n"
        f"SL    : {_fmt(signal['sl'])}\n"
        f"TP1   : {_fmt(signal['tp1'])}\n"
        f"TP2   : {_fmt(signal['tp2'])}\n"
        f"R:R   : 1:{signal['rr']:.1f}\n"
        f"Lots  : {signal['lots']}\n"
        f"</pre>\n"
        f"🎲 Confidence: <b>{signal.get('confidence', '?')}/10</b>\n"
        f"🧭 {signal.get('reason', '')}"
    )
