"""Tests for bias.py — HTF True-Open bias synchronization."""
from bias import htf_bias


def lv(price, tmo, two, tdo):
    return {"Current": price, "TMO": tmo, "TWO": two, "TDO": tdo}


class TestHTFBias:
    def test_all_bullish_is_synchronized_bullish(self):
        b = htf_bias(lv(2050, 2000, 2010, 2020))
        assert b["monthly"] == "bullish"
        assert b["weekly"] == "bullish"
        assert b["daily"] == "bullish"
        assert b["overall"] == "bullish"
        assert b["synchronized"] is True

    def test_all_bearish_is_synchronized_bearish(self):
        b = htf_bias(lv(1950, 2000, 2010, 2020))
        assert b["overall"] == "bearish"
        assert b["synchronized"] is True

    def test_mixed_is_neutral_and_not_synchronized(self):
        b = htf_bias(lv(2005, 2000, 2010, 2020))  # above TMO, below TWO/TDO
        assert b["overall"] == "neutral"
        assert b["synchronized"] is False

    def test_na_levels_ignored(self):
        b = htf_bias(lv(2050, 2000, "N/A", 2020))
        # only monthly + daily evaluable; both bullish -> synchronized bullish
        assert b["weekly"] == "neutral"
        assert b["overall"] == "bullish"
        assert b["synchronized"] is True

    def test_price_equal_open_is_neutral(self):
        b = htf_bias(lv(2000, 2000, 2000, 2000))
        assert b["overall"] == "neutral"
        assert b["synchronized"] is False
