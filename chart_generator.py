"""
TradingView-style candlestick chart generator for XAUUSD.

Renders a dark-theme 5-minute candlestick PNG using mplfinance with the
exact TradingView green (#089981) / red (#f23645) palette.

Public API:
    generate_gold_chart(df, filename="gold_chart.png", num_candles=200, title=None) -> str
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd
import mplfinance as mpf

logger = logging.getLogger(__name__)

# TradingView exact palette
TV_GREEN = "#089981"
TV_RED   = "#f23645"
TV_BG    = "#131722"   # TradingView dark chart background
TV_PANEL = "#1e222d"   # secondary panel (volume area)
TV_GRID  = "#2a2e39"   # subtle grid
TV_TEXT  = "#d1d4dc"   # axis/tick text
TV_WICK  = "#787b86"   # neutral wick color (TV uses near-grey)


def _build_tradingview_style() -> dict:
    """Construct an mplfinance style matching TradingView's dark theme."""
    market_colors = mpf.make_marketcolors(
        up=TV_GREEN,
        down=TV_RED,
        edge={"up": TV_GREEN, "down": TV_RED},
        wick={"up": TV_GREEN, "down": TV_RED},
        volume={"up": TV_GREEN, "down": TV_RED},
        inherit=False,
    )

    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=market_colors,
        facecolor=TV_BG,
        edgecolor=TV_GRID,
        figcolor=TV_BG,
        gridcolor=TV_GRID,
        gridstyle="-",
        gridaxis="both",
        rc={
            "axes.labelcolor":   TV_TEXT,
            "axes.edgecolor":    TV_GRID,
            "xtick.color":       TV_TEXT,
            "ytick.color":       TV_TEXT,
            "axes.titlecolor":   TV_TEXT,
            "axes.facecolor":    TV_BG,
            "figure.facecolor":  TV_BG,
            "savefig.facecolor": TV_BG,
            "grid.alpha": 0.25,
            "font.size":  9,
        },
    )
    return style


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce input frame to mplfinance contract:
      - DatetimeIndex
      - Columns: Open, High, Low, Close, Volume (capitalized)
    Accepts either capitalized or lowercase columns from the data layer.
    """
    if df is None or df.empty:
        raise ValueError("generate_gold_chart: input DataFrame is empty")

    rename_map = {
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    required = ["Open", "High", "Low", "Close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"generate_gold_chart: missing required columns {missing}")

    if "Volume" not in df.columns:
        df = df.assign(Volume=0.0)

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    return df.sort_index()


def generate_gold_chart(
    df: pd.DataFrame,
    filename: str = "gold_chart.png",
    num_candles: int = 200,
    title: Optional[str] = None,
) -> str:
    """
    Render a TradingView-style candlestick PNG for the given OHLCV frame.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV with DatetimeIndex. Columns may be capitalized or lowercase.
    filename : str
        Output PNG path (relative or absolute).
    num_candles : int
        Tail-slice size; chart shows the most recent N candles.
    title : str, optional
        Chart title. Defaults to "XAUUSD - 5min".

    Returns
    -------
    str
        Absolute path of the written PNG.
    """
    data = _normalize_ohlcv(df).tail(int(num_candles))

    if data.empty:
        raise ValueError("generate_gold_chart: no candles to plot after tail slice")

    style = _build_tradingview_style()
    chart_title = title or "XAUUSD - 5min"

    show_volume = bool(data["Volume"].sum() > 0)

    out_path = os.path.abspath(filename)

    mpf.plot(
        data,
        type="candle",
        style=style,
        title=chart_title,
        ylabel="Price (USD)",
        ylabel_lower="Volume" if show_volume else "",
        volume=show_volume,
        figsize=(14, 7),
        figratio=(16, 9),
        tight_layout=True,
        datetime_format="%m-%d %H:%M",
        xrotation=15,
        savefig=dict(fname=out_path, dpi=150, bbox_inches="tight"),
    )

    logger.info("Chart written: %s (%d candles)", out_path, len(data))
    return out_path
