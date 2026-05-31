"""Tests for Smart Money Concepts primitives (smc.py)."""
import pandas as pd
import pytest

from smc import find_swings, find_fvgs, find_ifvgs, detect_liquidity_sweeps, detect_mss, ote_zone


def make_df(rows):
    """rows: list of (open, high, low, close). Index = sequential minutes."""
    idx = pd.date_range("2026-05-05 18:00", periods=len(rows), freq="5min")
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)


class TestFVG:
    def test_bullish_fvg_detected(self):
        # candle0 high=10, candle2 low=12 -> bullish gap (10,12)
        df = make_df([
            (9, 10, 8, 9),     # c0
            (10, 13, 9, 12),   # c1 (displacement)
            (12, 14, 12, 13),  # c2  low(12) > c0 high(10)
        ])
        fvgs = find_fvgs(df)
        bull = [f for f in fvgs if f["type"] == "bullish"]
        assert len(bull) == 1
        assert bull[0]["bottom"] == 10
        assert bull[0]["top"] == 12

    def test_bearish_fvg_detected(self):
        # candle0 low=20, candle2 high=18 -> bearish gap (18,20)
        df = make_df([
            (21, 22, 20, 21),
            (20, 21, 17, 18),
            (18, 18, 16, 17),
        ])
        fvgs = find_fvgs(df)
        bear = [f for f in fvgs if f["type"] == "bearish"]
        assert len(bear) == 1
        assert bear[0]["bottom"] == 18
        assert bear[0]["top"] == 20

    def test_no_fvg_when_no_gap(self):
        df = make_df([
            (10, 11, 9, 10),
            (10, 12, 9, 11),
            (11, 12, 10, 11),  # low 10 <= c0 high 11 -> no gap
        ])
        assert find_fvgs(df) == []


class TestIFVG:
    def test_bullish_fvg_inverts_to_bearish_when_closed_below(self):
        # bullish FVG (10,12) then later candle closes below 10 -> bearish IFVG
        df = make_df([
            (9, 10, 8, 9),
            (10, 13, 9, 12),
            (12, 14, 12, 13),
            (12, 13, 11, 12),
            (11, 11, 8, 9),    # closes below 10 -> inversion
        ])
        ifvgs = find_ifvgs(df)
        assert any(i["type"] == "bearish" and i["top"] == 12 and i["bottom"] == 10 for i in ifvgs)


class TestSwings:
    def test_swing_high_and_low(self):
        df = make_df([
            (1, 2, 0, 1),
            (1, 3, 1, 2),
            (2, 5, 2, 4),   # swing high (idx2)
            (4, 4, 3, 3),
            (3, 3, 1, 2),
            (2, 2, 0, 1),   # ...
            (1, 6, 0, 5),
        ])
        swings = find_swings(df, left=2, right=2)
        high_prices = [p for _, p in swings["highs"]]
        assert 5 in high_prices


class TestLiquiditySweep:
    def test_buyside_sweep_wicks_above_then_closes_below(self):
        # swing high 12 at an interior bar; later candle wicks to 12.5 but closes 11.5
        df = make_df([
            (10, 10, 9, 9),
            (10, 12, 9, 11),   # swing high 12 (interior)
            (11, 11, 10, 10),
            (10, 12.5, 10, 11.5),  # sweep: high>12, close<12
        ])
        sweeps = detect_liquidity_sweeps(df, left=1, right=1)
        assert any(s["side"] == "buyside" and s["level"] == 12 for s in sweeps)

    def test_sellside_sweep_wicks_below_then_closes_above(self):
        df = make_df([
            (10, 11, 10, 11),
            (9, 10, 8, 9),      # swing low 8 (interior)
            (10, 11, 10, 11),
            (11, 12, 7.5, 9),   # sweep low<8 close>8
        ])
        sweeps = detect_liquidity_sweeps(df, left=1, right=1)
        assert any(s["side"] == "sellside" and s["level"] == 8 for s in sweeps)


class TestMSS:
    def test_bullish_mss_close_above_last_swing_high(self):
        # a confirmed swing high at 10, then a close above it -> bullish MSS
        df = make_df([
            (10, 11, 9, 10),
            (9, 9, 8, 8),
            (9, 10, 8, 9),    # swing high 10 (>neighbors)
            (8, 8.5, 7, 8),
            (8, 12, 8, 11),   # close 11 > 10 -> bullish MSS
        ])
        mss = detect_mss(df, left=1, right=1)
        assert mss is not None
        assert mss["direction"] == "bullish"

    def test_no_mss_in_clean_uptrend_without_break(self):
        df = make_df([
            (1, 2, 1, 2),
            (2, 3, 2, 3),
            (3, 4, 3, 4),
        ])
        # not enough confirmed swings to call a shift
        assert detect_mss(df, left=1, right=1) is None


class TestOTE:
    def test_bullish_ote_zone(self):
        z = ote_zone(swing_low=100, swing_high=200, direction="long")
        assert z["fib_0_62"] == pytest.approx(138.0)
        assert z["fib_0_79"] == pytest.approx(121.0)
        # entry zone bounded by the two fibs
        assert z["start"] == pytest.approx(121.0)
        assert z["end"] == pytest.approx(138.0)

    def test_bearish_ote_zone(self):
        z = ote_zone(swing_low=100, swing_high=200, direction="short")
        # short retraces up: 100 + 0.62*100 = 162 ; 100 + 0.79*100 = 179
        assert z["fib_0_62"] == pytest.approx(162.0)
        assert z["fib_0_79"] == pytest.approx(179.0)

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError):
            ote_zone(100, 200, "sideways")
