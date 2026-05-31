"""Tests for appstate.py — in-memory live dashboard state."""
from appstate import AppState


class TestAppState:
    def test_initial_snapshot_defaults(self):
        s = AppState()
        snap = s.snapshot()
        assert snap["mode"] == "DRY-RUN"
        assert snap["events"] == []
        assert snap["last_signal"] is None

    def test_update_mode_live(self):
        s = AppState()
        s.update_mode(live=True)
        assert s.snapshot()["mode"] == "LIVE"

    def test_update_market_fields(self):
        s = AppState()
        s.update_market(price=2000.5, quarter="Q3", in_session=True,
                        next_poll="20:15", levels={"TDO": 1990},
                        bias={"overall": "bullish"}, volume_profile={"poc": 1995})
        snap = s.snapshot()
        assert snap["price"] == 2000.5
        assert snap["quarter"] == "Q3"
        assert snap["in_session"] is True
        assert snap["levels"]["TDO"] == 1990
        assert snap["bias"]["overall"] == "bullish"
        assert snap["volume_profile"]["poc"] == 1995

    def test_update_signal(self):
        s = AppState()
        sig = {"direction": "long", "entry": 2000, "rr": 3.2}
        s.update_signal(sig)
        assert s.snapshot()["last_signal"]["direction"] == "long"

    def test_record_event_appends_newest_last(self):
        s = AppState()
        s.record_event("first", ts="t1")
        s.record_event("second", ts="t2")
        events = s.snapshot()["events"]
        assert len(events) == 2
        assert events[-1]["msg"] == "second"
        assert events[-1]["ts"] == "t2"

    def test_events_ring_buffer_caps(self):
        s = AppState(max_events=50)
        for i in range(60):
            s.record_event(f"e{i}", ts=str(i))
        events = s.snapshot()["events"]
        assert len(events) == 50
        assert events[-1]["msg"] == "e59"   # newest kept
        assert events[0]["msg"] == "e10"    # oldest 10 dropped

    def test_snapshot_is_json_serializable(self):
        import json
        s = AppState()
        s.update_market(price=2000, quarter="Q1", in_session=False,
                        next_poll="x", levels={}, bias={}, volume_profile={})
        s.record_event("hello")
        json.dumps(s.snapshot())  # must not raise
