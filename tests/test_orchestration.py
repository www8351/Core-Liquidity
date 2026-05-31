"""Tests for orchestration.py — session gate, per-cycle dedupe, message format."""
from datetime import datetime
from zoneinfo import ZoneInfo

from orchestration import in_session, CycleGuard, format_signal_message

NY = ZoneInfo("America/New_York")


class TestInSession:
    def test_ny_morning_in_session(self):
        assert in_session(datetime(2026, 5, 5, 9, 0, tzinfo=NY)) is True

    def test_london_open_in_session(self):
        assert in_session(datetime(2026, 5, 5, 3, 0, tzinfo=NY)) is True

    def test_asia_night_out_of_session(self):
        assert in_session(datetime(2026, 5, 5, 22, 0, tzinfo=NY)) is False

    def test_weekend_out_of_session(self):
        # 2026-05-09 is a Saturday
        assert in_session(datetime(2026, 5, 9, 9, 0, tzinfo=NY)) is False


class TestCycleGuard:
    def test_acts_once_per_cycle(self):
        g = CycleGuard()
        key = {"date": "2026-05-05", "cycle_index": 3}
        assert g.should_act(key) is True
        assert g.should_act(key) is False  # same cycle blocked

    def test_new_cycle_allowed(self):
        g = CycleGuard()
        assert g.should_act({"date": "2026-05-05", "cycle_index": 3}) is True
        assert g.should_act({"date": "2026-05-05", "cycle_index": 4}) is True

    def test_new_day_same_index_allowed(self):
        g = CycleGuard()
        assert g.should_act({"date": "2026-05-05", "cycle_index": 3}) is True
        assert g.should_act({"date": "2026-05-06", "cycle_index": 3}) is True


class TestFormatSignalMessage:
    def test_long_signal_contains_key_fields(self):
        sig = {
            "direction": "long", "entry": 2000.0, "sl": 1990.0,
            "tp1": 2015.0, "tp2": 2040.0, "rr": 3.2, "lots": 0.1,
            "confidence": 8, "reason": "all confluences aligned",
            "meta": {"micro_quarter": "Q3", "bias": "bullish"},
        }
        msg = format_signal_message(sig, {"Current": 2000.0})
        assert "LONG" in msg
        assert "2000" in msg
        assert "1990" in msg
        assert "0.1" in msg
        assert "DRY" in msg.upper() or "LIVE" in msg.upper()

    def test_no_trade_message(self):
        sig = {"direction": "none", "reason": "outside Q3 window",
               "meta": {"micro_quarter": "Q1"}}
        msg = format_signal_message(sig, {"Current": 2000.0})
        assert "NO TRADE" in msg.upper()
        assert "Q3" in msg  # reason surfaced
