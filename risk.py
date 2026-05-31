"""Risk management — position sizing, stop placement, RRR, scaling.

Sizing assumes the XAUUSD standard contract of 100 oz, so a $1 price move is
$100 per 1.00 lot. All knobs (contract size, lot step, min/max lot, min RRR)
are parameters with sensible defaults and can be overridden by the caller.
"""
from __future__ import annotations

import math

CONTRACT_SIZE = 100          # oz per 1.00 lot (XAUUSD standard)
LOT_STEP = 0.01
MIN_LOT = 0.01
MAX_LOT = 100.0
MIN_RR = 3.0                 # spec: minimum expected risk:reward 1:3


def position_size(balance: float, risk_pct: float, entry: float, sl: float,
                  contract_size: float = CONTRACT_SIZE, lot_step: float = LOT_STEP,
                  min_lot: float = MIN_LOT, max_lot: float = MAX_LOT) -> dict:
    """Lots to trade so that hitting `sl` loses exactly `balance * risk_pct`.

    Returns {lots, risk_amount, risk_per_lot, sl_distance}. `lots` is floored to
    `lot_step`; if the floored size is below `min_lot` it returns 0.0 (no trade).
    """
    sl_distance = abs(entry - sl)
    if sl_distance == 0:
        raise ValueError("stop-loss distance cannot be zero")

    risk_amount = balance * risk_pct
    risk_per_lot = sl_distance * contract_size
    raw_lots = risk_amount / risk_per_lot

    lots = math.floor(raw_lots / lot_step + 1e-9) * lot_step
    lots = min(lots, max_lot)
    if lots < min_lot:
        lots = 0.0

    return {
        "lots": round(lots, 2),
        "risk_amount": risk_amount,
        "risk_per_lot": risk_per_lot,
        "sl_distance": sl_distance,
    }


def compute_rr(entry: float, sl: float, tp: float) -> float:
    """Reward-to-risk ratio = |tp - entry| / |entry - sl|."""
    risk = abs(entry - sl)
    if risk == 0:
        raise ValueError("risk (entry-sl) cannot be zero")
    return abs(tp - entry) / risk


def meets_min_rr(rr: float, min_rr: float = MIN_RR) -> bool:
    return rr >= min_rr


def place_stop(side: str, judas_low: float, judas_high: float, buffer: float = 0.0) -> float:
    """Stop loss placed strictly outside the Q2 Judas-swing manipulation range.

    long  -> below the swing low  (judas_low - buffer)
    short -> above the swing high (judas_high + buffer)
    """
    if side == "long":
        return judas_low - buffer
    if side == "short":
        return judas_high + buffer
    raise ValueError(f"side must be 'long' or 'short', got {side!r}")


def scale_out_levels(targets: list[float], fractions: list[float]) -> list[tuple[float, float]]:
    """Pair partial-exit price targets with the fraction of position to close.

    `fractions` must match `targets` in length and sum to 1.0.
    """
    if len(targets) != len(fractions):
        raise ValueError("targets and fractions must be the same length")
    if abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("fractions must sum to 1.0")
    return list(zip(targets, fractions))
