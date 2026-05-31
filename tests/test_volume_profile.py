"""Tests for volume_profile.py — POC/VAH/VAL and Anchored VWAP."""
import pandas as pd
import pytest

from volume_profile import volume_profile, avwap


def make_dfv(rows):
    """rows: (open, high, low, close, volume)."""
    idx = pd.date_range("2026-05-05 18:00", periods=len(rows), freq="5min")
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"], index=idx)


class TestVolumeProfile:
    def test_poc_at_dominant_price(self):
        df = make_dfv([
            (100, 100, 100, 100, 1),
            (110, 110, 110, 110, 1),
            (100, 100, 100, 100, 100),  # dominant volume at 100
        ])
        vp = volume_profile(df, bins=24)
        assert abs(vp["poc"] - 100) < abs(vp["poc"] - 110)

    def test_value_area_brackets_poc(self):
        df = make_dfv([
            (100, 101, 99, 100, 5),
            (102, 103, 101, 102, 10),
            (104, 105, 103, 104, 50),  # POC region
            (106, 107, 105, 106, 8),
        ])
        vp = volume_profile(df, bins=24)
        assert vp["val"] <= vp["poc"] <= vp["vah"]
        assert vp["vah"] <= 107
        assert vp["val"] >= 99

    def test_zero_volume_raises(self):
        df = make_dfv([(100, 101, 99, 100, 0), (100, 101, 99, 100, 0)])
        with pytest.raises(ValueError):
            volume_profile(df, bins=10)


class TestAVWAP:
    def test_avwap_from_anchor(self):
        # typical = (H+L+C)/3 ; tp*v summed / v summed
        df = make_dfv([
            (9, 10, 8, 9, 10),    # typ=9  -> 90
            (15, 20, 10, 15, 5),  # typ=15 -> 75
        ])
        series = avwap(df, df.index[0])
        assert series.iloc[-1] == pytest.approx(11.0)  # 165/15

    def test_avwap_anchor_midway(self):
        df = make_dfv([
            (9, 10, 8, 9, 10),
            (15, 20, 10, 15, 5),
            (12, 12, 12, 12, 5),  # typ=12 -> 60
        ])
        # anchor at index[1]: (75 + 60) / (5 + 5) = 13.5
        series = avwap(df, df.index[1])
        assert series.iloc[-1] == pytest.approx(13.5)
