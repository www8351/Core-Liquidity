"""Volume Profile (POC / VAH / VAL) and Anchored VWAP.

Volume profile bins the session's traded range by price and accumulates each
candle's volume into the bin containing its typical price ((H+L+C)/3). The
Point of Control is the highest-volume bin; the Value Area is the contiguous
band around the POC holding `value_area_pct` of total volume (70% default).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VALUE_AREA_PCT = 0.70


def _typical_price(df: pd.DataFrame) -> pd.Series:
    return (df["High"] + df["Low"] + df["Close"]) / 3.0


def volume_profile(df: pd.DataFrame, bins: int = 24,
                   value_area_pct: float = VALUE_AREA_PCT) -> dict:
    """Return {poc, vah, val, value_area_pct} for the candles in `df`."""
    total_vol = float(df["Volume"].sum())
    if total_vol <= 0:
        raise ValueError("volume profile requires positive total volume")

    typ = _typical_price(df).to_numpy()
    vol = df["Volume"].to_numpy(dtype="float64")

    lo, hi = float(df["Low"].min()), float(df["High"].max())
    if hi == lo:  # flat range — single price level
        return {"poc": lo, "vah": hi, "val": lo, "value_area_pct": value_area_pct}

    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    # clip typical prices into the last bin so hi lands inside
    bin_idx = np.clip(np.digitize(typ, edges) - 1, 0, bins - 1)

    hist = np.zeros(bins)
    for b, v in zip(bin_idx, vol):
        hist[b] += v

    poc_bin = int(hist.argmax())

    # expand outward from the POC bin until value_area_pct of volume is captured
    target = total_vol * value_area_pct
    included = {poc_bin}
    captured = hist[poc_bin]
    lo_b = hi_b = poc_bin
    while captured < target and (lo_b > 0 or hi_b < bins - 1):
        down = hist[lo_b - 1] if lo_b > 0 else -1.0
        up = hist[hi_b + 1] if hi_b < bins - 1 else -1.0
        if up >= down:
            hi_b += 1
            included.add(hi_b)
            captured += hist[hi_b]
        else:
            lo_b -= 1
            included.add(lo_b)
            captured += hist[lo_b]

    return {
        "poc": float(centers[poc_bin]),
        "vah": float(edges[max(included) + 1]),
        "val": float(edges[min(included)]),
        "value_area_pct": value_area_pct,
    }


def avwap(df: pd.DataFrame, anchor) -> pd.Series:
    """Anchored VWAP from `anchor` (an index label) to the end of `df`.

    Returns a Series indexed by the candles from the anchor onward.
    """
    seg = df.loc[anchor:]
    typ = _typical_price(seg)
    cum_pv = (typ * seg["Volume"]).cumsum()
    cum_v = seg["Volume"].cumsum()
    return cum_pv / cum_v
