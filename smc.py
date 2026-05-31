"""Smart Money Concepts primitives — pure functions over OHLC DataFrames.

Every function takes a pandas DataFrame with columns Open/High/Low/Close and a
DatetimeIndex (ascending). Detectors return plain dicts/lists so the strategy
layer and tests stay decoupled from pandas internals.
"""
from __future__ import annotations

import pandas as pd

_FIB_OTE_LOW = 0.62
_FIB_OTE_MID = 0.705
_FIB_OTE_HIGH = 0.79


def find_fvgs(df: pd.DataFrame) -> list[dict]:
    """Three-candle Fair Value Gaps.

    Bullish FVG: candle[i].Low > candle[i-2].High  -> gap (c0.High, c2.Low)
    Bearish FVG: candle[i].High < candle[i-2].Low  -> gap (c2.High, c0.Low)
    Each gap gets a `filled` flag (True if a later candle traded back into it).
    """
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    idx = df.index
    out: list[dict] = []

    for i in range(2, len(df)):
        # bullish
        if lows[i] > highs[i - 2]:
            bottom, top = float(highs[i - 2]), float(lows[i])
            filled = bool((lows[i + 1:] <= bottom).any())
            out.append({"type": "bullish", "bottom": bottom, "top": top,
                        "index": idx[i], "pos": i, "filled": filled})
        # bearish
        elif highs[i] < lows[i - 2]:
            bottom, top = float(highs[i]), float(lows[i - 2])
            filled = bool((highs[i + 1:] >= top).any())
            out.append({"type": "bearish", "bottom": bottom, "top": top,
                        "index": idx[i], "pos": i, "filled": filled})
    return out


def find_ifvgs(df: pd.DataFrame) -> list[dict]:
    """Inversion FVGs — an FVG that price has closed through, flipping polarity.

    A bullish FVG whose zone is later closed *below* becomes bearish resistance.
    A bearish FVG whose zone is later closed *above* becomes bullish support.
    """
    closes = df["Close"].to_numpy()
    out: list[dict] = []
    for fvg in find_fvgs(df):
        after = closes[fvg["pos"] + 1:]
        if fvg["type"] == "bullish" and (after < fvg["bottom"]).any():
            out.append({"type": "bearish", "bottom": fvg["bottom"], "top": fvg["top"],
                        "index": fvg["index"], "origin": "ifvg"})
        elif fvg["type"] == "bearish" and (after > fvg["top"]).any():
            out.append({"type": "bullish", "bottom": fvg["bottom"], "top": fvg["top"],
                        "index": fvg["index"], "origin": "ifvg"})
    return out


def find_swings(df: pd.DataFrame, left: int = 2, right: int = 2) -> dict:
    """Fractal swing highs/lows. A swing high is strictly greater than `left`
    bars before and `right` bars after it; mirror for swing lows.

    Returns {"highs": [(timestamp, price), ...], "lows": [...]} with positions
    available via the parallel keys "high_pos" / "low_pos".
    """
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    idx = df.index
    sh, sl, sh_pos, sl_pos = [], [], [], []

    for i in range(left, len(df) - right):
        window_h = highs[i - left:i + right + 1]
        if highs[i] == window_h.max() and (window_h == highs[i]).sum() == 1:
            sh.append((idx[i], float(highs[i])))
            sh_pos.append(i)
        window_l = lows[i - left:i + right + 1]
        if lows[i] == window_l.min() and (window_l == lows[i]).sum() == 1:
            sl.append((idx[i], float(lows[i])))
            sl_pos.append(i)

    return {"highs": sh, "lows": sl, "high_pos": sh_pos, "low_pos": sl_pos}


def detect_liquidity_sweeps(df: pd.DataFrame, left: int = 2, right: int = 2) -> list[dict]:
    """Sweeps of prior swing liquidity that fail to hold.

    Buyside sweep: a later candle's High pierces a swing high but Close falls back below it.
    Sellside sweep: a later candle's Low pierces a swing low but Close closes back above it.
    """
    swings = find_swings(df, left=left, right=right)
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    closes = df["Close"].to_numpy()
    idx = df.index
    out: list[dict] = []

    for pos, (_, level) in zip(swings["high_pos"], swings["highs"]):
        for j in range(pos + right + 1, len(df)):
            if highs[j] > level and closes[j] < level:
                out.append({"side": "buyside", "level": level, "index": idx[j], "pos": j})
                break
    for pos, (_, level) in zip(swings["low_pos"], swings["lows"]):
        for j in range(pos + right + 1, len(df)):
            if lows[j] < level and closes[j] > level:
                out.append({"side": "sellside", "level": level, "index": idx[j], "pos": j})
                break
    return out


def detect_mss(df: pd.DataFrame, left: int = 2, right: int = 2) -> dict | None:
    """Market Structure Shift — a close beyond the most recent confirmed swing.

    Bullish MSS: a candle closes above the last confirmed swing high.
    Bearish MSS: a candle closes below the last confirmed swing low.
    Returns the most recent shift, or None if structure has not shifted.
    """
    swings = find_swings(df, left=left, right=right)
    closes = df["Close"].to_numpy()
    idx = df.index
    candidates: list[dict] = []

    for pos, (_, level) in zip(swings["high_pos"], swings["highs"]):
        for j in range(pos + right + 1, len(df)):
            if closes[j] > level:
                candidates.append({"direction": "bullish", "level": level,
                                   "index": idx[j], "pos": j})
                break
    for pos, (_, level) in zip(swings["low_pos"], swings["lows"]):
        for j in range(pos + right + 1, len(df)):
            if closes[j] < level:
                candidates.append({"direction": "bearish", "level": level,
                                   "index": idx[j], "pos": j})
                break

    if not candidates:
        return None
    return max(candidates, key=lambda c: c["pos"])


def ote_zone(swing_low: float, swing_high: float, direction: str) -> dict:
    """Optimal Trade Entry zone — the 0.62–0.79 retracement of an impulse leg.

    direction="long": retrace down from the high (entry on a pullback to buy).
    direction="short": retrace up from the low (entry on a pullback to sell).
    """
    rng = swing_high - swing_low
    if direction == "long":
        f62 = swing_high - _FIB_OTE_LOW * rng
        f705 = swing_high - _FIB_OTE_MID * rng
        f79 = swing_high - _FIB_OTE_HIGH * rng
    elif direction == "short":
        f62 = swing_low + _FIB_OTE_LOW * rng
        f705 = swing_low + _FIB_OTE_MID * rng
        f79 = swing_low + _FIB_OTE_HIGH * rng
    else:
        raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")

    return {
        "fib_0_62": f62,
        "fib_0_705": f705,
        "fib_0_79": f79,
        "start": min(f62, f79),
        "end": max(f62, f79),
        "direction": direction,
    }
