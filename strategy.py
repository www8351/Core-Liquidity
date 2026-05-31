"""Quarterly-Theory entry combiner.

Implements the spec's decision logic:

    IF (now == Q3_window) AND (HTF_bias synchronized):
        IF (Q2 Judas swing completed) AND (liquidity sweep):
            IF (MSS confirms bias) AND (retest at IFVG/OTE):
                EXECUTE

`evaluate_setup` orchestrates the gates and returns a Signal dict. The heavy
lifting (sweep / MSS / retest detection) lives in module-level helpers so they
can be unit-tested and, where useful, substituted in tests.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from quarters import quarter_info
from bias import htf_bias
from smc import detect_liquidity_sweeps, detect_mss, find_fvgs, find_ifvgs, find_swings, ote_zone
from risk import position_size, compute_rr, meets_min_rr, place_stop, MIN_RR


def _no_trade(reason: str, meta: dict | None = None) -> dict:
    return {
        "direction": "none", "entry": None, "sl": None, "tp1": None, "tp2": None,
        "rr": None, "lots": 0.0, "confidence": 0, "reason": reason, "meta": meta or {},
    }


def build_signal(direction: str, entry: float, sl: float, targets: list[float],
                 balance: float, risk_pct: float, min_rr: float = MIN_RR,
                 confidence: int = 5, meta: dict | None = None) -> dict:
    """Assemble and validate a trade signal. RR is measured to the final target."""
    if direction not in ("long", "short"):
        raise ValueError("direction must be 'long' or 'short'")
    if not targets:
        raise ValueError("at least one target required")

    final_tp = targets[-1]
    rr = compute_rr(entry, sl, final_tp)
    if not meets_min_rr(rr, min_rr):
        return _no_trade(f"RR {rr:.2f} below minimum {min_rr}", meta)

    size = position_size(balance=balance, risk_pct=risk_pct, entry=entry, sl=sl)
    if size["lots"] <= 0:
        return _no_trade("position size below minimum lot (account too small / SL too wide)", meta)

    return {
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": targets[0],
        "tp2": targets[-1],
        "rr": rr,
        "lots": size["lots"],
        "risk_amount": size["risk_amount"],
        "confidence": confidence,
        "reason": "all confluences aligned",
        "meta": meta or {},
    }


def _judas_sweep(df: pd.DataFrame, direction: str) -> dict | None:
    """The Q2 manipulation sweeps liquidity *against* the bias: a bullish setup
    needs a sellside sweep (Judas down); a bearish setup needs a buyside sweep."""
    want = "sellside" if direction == "long" else "buyside"
    sweeps = [s for s in detect_liquidity_sweeps(df) if s["side"] == want]
    return sweeps[-1] if sweeps else None


def _mss_aligned(df: pd.DataFrame, direction: str) -> bool:
    mss = detect_mss(df)
    want = "bullish" if direction == "long" else "bearish"
    return mss is not None and mss["direction"] == want


def find_entry_zone(df: pd.DataFrame, direction: str, levels: dict,
                    sweep: dict) -> dict | None:
    """Locate the IFVG/OTE retest entry after the sweep+MSS.

    Builds the impulse leg from the recent swing range, derives the OTE zone,
    and returns entry/judas range/targets when current price sits in an aligned
    IFVG or the OTE band. Returns None if no qualifying retest exists.
    """
    swings = find_swings(df)
    if not swings["highs"] or not swings["lows"]:
        return None
    swing_high = max(p for _, p in swings["highs"])
    swing_low = min(p for _, p in swings["lows"])
    price = float(df["Close"].iloc[-1])

    ote = ote_zone(swing_low, swing_high, direction)
    aligned_ifvg = [z for z in find_ifvgs(df)
                    if z["type"] == ("bullish" if direction == "long" else "bearish")]

    in_ote = ote["start"] <= price <= ote["end"]
    in_ifvg = any(z["bottom"] <= price <= z["top"] for z in aligned_ifvg)
    if not (in_ote or in_ifvg):
        return None

    if direction == "long":
        targets = [levels.get("TWO"), swing_high]
    else:
        targets = [levels.get("TWO"), swing_low]
    targets = [t for t in targets if isinstance(t, (int, float))]

    return {
        "entry": price,
        "judas_low": swing_low,
        "judas_high": swing_high,
        "targets": targets,
    }


def evaluate_setup(df: pd.DataFrame, levels: dict, now: datetime,
                   balance: float, risk_pct: float, buffer: float = 0.0,
                   min_rr: float = MIN_RR) -> dict:
    """Run the full Quarterly-Theory gate chain and return a Signal dict."""
    qi = quarter_info(now)
    meta = {"micro_quarter": qi["micro_quarter"], "cycle_index": qi["cycle_index"]}

    if not qi["is_q3"]:
        return _no_trade(f"outside Q3 execution window (currently {qi['micro_quarter']})", meta)

    b = htf_bias(levels)
    meta["bias"] = b["overall"]
    if not b["synchronized"]:
        return _no_trade("HTF bias not synchronized across TMO/TWO/TDO", meta)

    direction = "long" if b["overall"] == "bullish" else "short"

    sweep = _judas_sweep(df, direction)
    if sweep is None:
        return _no_trade("no Q2 Judas liquidity sweep against bias", meta)

    if not _mss_aligned(df, direction):
        return _no_trade("no MSS confirming bias after sweep", meta)

    zone = find_entry_zone(df, direction, levels, sweep)
    if zone is None:
        return _no_trade("price not at IFVG/OTE retest", meta)

    sl = place_stop(direction, judas_low=zone["judas_low"],
                    judas_high=zone["judas_high"], buffer=buffer)

    return build_signal(
        direction=direction, entry=zone["entry"], sl=sl, targets=zone["targets"],
        balance=balance, risk_pct=risk_pct, min_rr=min_rr,
        confidence=8, meta=meta,
    )
