"""Tests for the Quarterly Theory time engine (quarters.py).

Quarterly Theory (Daye): the *True Day* opens at 18:00 America/New_York.
The 90-minute algorithmic cycle tiles the day from that anchor; each cycle is
split into four 22.5-minute micro-quarters: Q1 accumulation, Q2 manipulation
(Judas), Q3 distribution (true move), Q4 continuation/reversal.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from quarters import true_day_open, quarter_info

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def ny(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=NY)


class TestTrueDayOpen:
    def test_open_is_1800_ny_same_evening(self):
        # 20:00 NY on the 5th -> true day opened 18:00 NY on the 5th
        assert true_day_open(ny(2026, 5, 5, 20, 0)) == ny(2026, 5, 5, 18, 0)

    def test_before_1800_belongs_to_previous_open(self):
        # 09:00 NY on the 5th -> true day opened 18:00 NY on the 4th
        assert true_day_open(ny(2026, 5, 5, 9, 0)) == ny(2026, 5, 4, 18, 0)

    def test_exactly_1800_opens_new_day(self):
        assert true_day_open(ny(2026, 5, 5, 18, 0)) == ny(2026, 5, 5, 18, 0)

    def test_accepts_utc_input_and_normalizes(self):
        # 22:00 UTC == 18:00 EDT (May, DST) -> opens that day's true day
        ts = datetime(2026, 5, 5, 22, 0, tzinfo=UTC)
        assert true_day_open(ts) == ny(2026, 5, 5, 18, 0)

    def test_naive_datetime_rejected(self):
        with pytest.raises(ValueError):
            true_day_open(datetime(2026, 5, 5, 20, 0))


class TestQuarterInfo:
    def test_first_cycle_first_quarter(self):
        # 18:00 NY = start of cycle 0, micro Q1
        info = quarter_info(ny(2026, 5, 5, 18, 0))
        assert info["cycle_index"] == 0
        assert info["micro_quarter"] == "Q1"

    def test_micro_q2_at_22_5_minutes(self):
        info = quarter_info(ny(2026, 5, 5, 18, 23))  # 23 min in -> Q2
        assert info["cycle_index"] == 0
        assert info["micro_quarter"] == "Q2"

    def test_micro_q3_at_45_minutes(self):
        info = quarter_info(ny(2026, 5, 5, 18, 46))
        assert info["micro_quarter"] == "Q3"

    def test_micro_q4_at_67_5_minutes(self):
        info = quarter_info(ny(2026, 5, 5, 19, 8))  # 68 min -> Q4
        assert info["micro_quarter"] == "Q4"

    def test_second_cycle_after_90_minutes(self):
        info = quarter_info(ny(2026, 5, 5, 19, 30))  # 90 min -> next cycle, Q1
        assert info["cycle_index"] == 1
        assert info["micro_quarter"] == "Q1"

    def test_quarter_boundaries_returned(self):
        info = quarter_info(ny(2026, 5, 5, 18, 10))  # inside cycle 0 Q1
        assert info["quarter_start"] == ny(2026, 5, 5, 18, 0)
        # Q1 spans 22.5 min -> ends 18:22:30
        assert info["quarter_end"] == datetime(2026, 5, 5, 18, 22, 30, tzinfo=NY)

    def test_is_q3_helper_flag(self):
        assert quarter_info(ny(2026, 5, 5, 18, 50))["is_q3"] is True
        assert quarter_info(ny(2026, 5, 5, 18, 10))["is_q3"] is False
