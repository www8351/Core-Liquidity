"""Tests for risk.py — position sizing, SL placement, RRR, scaling."""
import pytest

from risk import position_size, compute_rr, meets_min_rr, place_stop, scale_out_levels


class TestPositionSize:
    def test_one_percent_risk_xauusd(self):
        # balance 10000, risk 1% = $100. SL 10 points. XAUUSD contract = 100 oz.
        # risk/lot = 10 * 100 = $1000 -> 0.10 lots
        r = position_size(balance=10000, risk_pct=0.01, entry=2000, sl=1990)
        assert r["lots"] == pytest.approx(0.10)
        assert r["risk_amount"] == pytest.approx(100.0)

    def test_lots_floored_to_step(self):
        # raw 0.137 -> floored to 0.13 at 0.01 step
        r = position_size(balance=10000, risk_pct=0.01, entry=2000, sl=1992.7)
        assert r["lots"] == pytest.approx(0.13)

    def test_min_lot_floor_returns_zero_when_too_small(self):
        # tiny balance can't afford min lot -> 0 (no trade)
        r = position_size(balance=50, risk_pct=0.01, entry=2000, sl=1990, min_lot=0.01)
        assert r["lots"] == 0.0

    def test_zero_sl_distance_raises(self):
        with pytest.raises(ValueError):
            position_size(balance=10000, risk_pct=0.01, entry=2000, sl=2000)


class TestRR:
    def test_long_rr(self):
        assert compute_rr(entry=2000, sl=1990, tp=2030) == pytest.approx(3.0)

    def test_short_rr(self):
        assert compute_rr(entry=2000, sl=2010, tp=1970) == pytest.approx(3.0)

    def test_meets_min_rr(self):
        assert meets_min_rr(3.0) is True
        assert meets_min_rr(2.9) is False
        assert meets_min_rr(5.0, min_rr=3.0) is True


class TestStopPlacement:
    def test_long_stop_below_judas_low_with_buffer(self):
        sl = place_stop(side="long", judas_low=1990, judas_high=2005, buffer=0.5)
        assert sl == pytest.approx(1989.5)

    def test_short_stop_above_judas_high_with_buffer(self):
        sl = place_stop(side="short", judas_low=1990, judas_high=2005, buffer=0.5)
        assert sl == pytest.approx(2005.5)


class TestScaleOut:
    def test_two_targets_split_evenly(self):
        levels = scale_out_levels(targets=[2010, 2030], fractions=[0.5, 0.5])
        assert levels == [(2010, 0.5), (2030, 0.5)]

    def test_fractions_must_sum_to_one(self):
        with pytest.raises(ValueError):
            scale_out_levels(targets=[2010, 2030], fractions=[0.5, 0.4])

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            scale_out_levels(targets=[2010], fractions=[0.5, 0.5])
