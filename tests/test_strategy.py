"""Tests for strategy.py — the Quarterly-Theory entry combiner."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import strategy
from strategy import build_signal, evaluate_setup

NY = ZoneInfo("America/New_York")


def levels(price, tmo, two, tdo):
    return {"Current": price, "TMO": tmo, "TWO": two, "TDO": tdo}


def dummy_df():
    idx = pd.date_range("2026-05-05 18:00", periods=3, freq="5min")
    return pd.DataFrame(
        [(1, 2, 0, 1)] * 3, columns=["Open", "High", "Low", "Close"], index=idx
    )


# time inside the Q3 window of the first 90-min cycle (45–67.5 min after 18:00)
Q3_TIME = datetime(2026, 5, 5, 18, 50, tzinfo=NY)
Q1_TIME = datetime(2026, 5, 5, 18, 10, tzinfo=NY)


class TestBuildSignal:
    def test_valid_long_signal(self):
        sig = build_signal(
            direction="long", entry=2000, sl=1990,
            targets=[2015, 2030], balance=10000, risk_pct=0.01,
        )
        assert sig["direction"] == "long"
        assert sig["sl"] == 1990
        assert sig["tp1"] == 2015
        assert sig["tp2"] == 2030
        assert sig["rr"] == pytest.approx(3.0)   # to final target 2030
        assert sig["lots"] == pytest.approx(0.10)

    def test_rr_below_min_rejected(self):
        sig = build_signal(
            direction="long", entry=2000, sl=1990,
            targets=[2020], balance=10000, risk_pct=0.01, min_rr=3.0,
        )
        assert sig["direction"] == "none"
        assert "rr" in sig["reason"].lower()

    def test_zero_lots_rejected(self):
        sig = build_signal(
            direction="long", entry=2000, sl=1990,
            targets=[2030], balance=50, risk_pct=0.01,
        )
        assert sig["direction"] == "none"
        assert "size" in sig["reason"].lower() or "lot" in sig["reason"].lower()


class TestEvaluateSetupGates:
    def test_outside_q3_no_trade(self):
        sig = evaluate_setup(dummy_df(), levels(2050, 2000, 2010, 2020),
                             now=Q1_TIME, balance=10000, risk_pct=0.01)
        assert sig["direction"] == "none"
        assert "q3" in sig["reason"].lower()

    def test_unsynchronized_bias_no_trade(self):
        sig = evaluate_setup(dummy_df(), levels(2005, 2000, 2010, 2020),
                             now=Q3_TIME, balance=10000, risk_pct=0.01)
        assert sig["direction"] == "none"
        assert "synchron" in sig["reason"].lower()

    def test_no_sweep_no_trade(self, monkeypatch):
        monkeypatch.setattr(strategy, "_judas_sweep", lambda df, d: None)
        sig = evaluate_setup(dummy_df(), levels(2050, 2000, 2010, 2020),
                             now=Q3_TIME, balance=10000, risk_pct=0.01)
        assert sig["direction"] == "none"
        assert "sweep" in sig["reason"].lower()


class TestEvaluateSetupHappyPath:
    def test_full_long_setup_executes(self, monkeypatch):
        monkeypatch.setattr(strategy, "_judas_sweep",
                            lambda df, d: {"side": "sellside", "level": 1988})
        monkeypatch.setattr(strategy, "_mss_aligned", lambda df, d: True)
        monkeypatch.setattr(
            strategy, "find_entry_zone",
            lambda df, d, lv, sweep: {
                "entry": 2000, "judas_low": 1988, "judas_high": 2002,
                "targets": [2015, 2040],
            },
        )
        sig = evaluate_setup(dummy_df(), levels(2050, 2000, 2010, 2020),
                             now=Q3_TIME, balance=10000, risk_pct=0.01, buffer=0.5)
        assert sig["direction"] == "long"
        assert sig["sl"] == pytest.approx(1987.5)  # judas_low - buffer
        assert sig["rr"] >= 3.0
        assert sig["meta"]["micro_quarter"] == "Q3"
