import os
import logging
import time
import warnings
import requests
import pandas as pd

# ביטול אזהרות מיותרות בטרמינל
warnings.filterwarnings('ignore')

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 2  # 2s, 4s, 8s exponential


# ════════════════════════════════════════════════════════════════════
# MT5 PRIMARY ENGINE — Linux/Docker safe (guarded import)
# ════════════════════════════════════════════════════════════════════
try:
    import MetaTrader5 as mt5  # type: ignore
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False
    logger.info(
        "MetaTrader5 module not importable (likely Linux/Docker) — "
        "primary engine disabled, all requests route to TwelveData fallback"
    )

# Public timeframe → MT5 constant name. Resolved lazily so module imports cleanly when mt5 is None.
_MT5_TIMEFRAME_NAMES = {
    "1m":  "TIMEFRAME_M1",
    "5m":  "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "1h":  "TIMEFRAME_H1",
    "4h":  "TIMEFRAME_H4",
    "1d":  "TIMEFRAME_D1",
}


def _resolve_mt5_timeframe(tf: str):
    """Map user timeframe ('5m', '1h', ...) to mt5.TIMEFRAME_* constant."""
    name = _MT5_TIMEFRAME_NAMES.get(tf)
    if name is None:
        raise ValueError(
            f"Unsupported timeframe '{tf}'. Allowed: {list(_MT5_TIMEFRAME_NAMES)}"
        )
    if not MT5_AVAILABLE:
        raise RuntimeError("MT5 not available — cannot resolve timeframe constant")
    return getattr(mt5, name)


def _init_mt5() -> bool:
    """
    Initialize MT5 terminal. Reads MT5_LOGIN / MT5_PASSWORD / MT5_SERVER from env.
    If all three present → login init. Else → empty init (uses last logged-in local terminal).
    Returns True on success, False on any failure (with warning logged).
    """
    if not MT5_AVAILABLE:
        return False

    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    try:
        if login and password and server:
            try:
                login_int = int(login)
            except ValueError:
                logger.warning("MT5_LOGIN must be int, got '%s' — skipping creds", login)
                ok = mt5.initialize()
            else:
                ok = mt5.initialize(login=login_int, password=password, server=server)
        else:
            ok = mt5.initialize()
    except Exception as e:
        logger.warning("mt5.initialize raised: %s", e)
        return False

    if not ok:
        logger.warning("mt5.initialize failed: %s", mt5.last_error())
        return False

    return True


def get_mt5_candles(
    symbol: str = "XAUUSD",
    timeframe: str = "5m",
    num_candles: int = 150,
) -> pd.DataFrame:
    """
    Primary engine — fetch OHLCV candles from MetaTrader5.

    Returns
    -------
    pd.DataFrame
        DatetimeIndex (UTC-naive, sorted asc).
        Columns: ['Open', 'High', 'Low', 'Close', 'Volume'] (float64).

    Raises
    ------
    RuntimeError
        On any MT5 failure (import/init/symbol/empty data). Caller falls back to TwelveData.
    ValueError
        On unknown timeframe string.
    """
    if not MT5_AVAILABLE:
        raise RuntimeError("MetaTrader5 module not installed/importable")

    tf_const = _resolve_mt5_timeframe(timeframe)

    if not _init_mt5():
        raise RuntimeError("MT5 initialize failed")

    try:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(
                f"MT5 symbol_select failed for '{symbol}': {mt5.last_error()}"
            )

        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, int(num_candles))
        if rates is None or len(rates) == 0:
            raise RuntimeError(
                f"MT5 copy_rates_from_pos returned empty for {symbol} {timeframe}: "
                f"{mt5.last_error()}"
            )

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_convert(None)
        df = df.set_index("time")

        # Volume preference: real_volume if broker provides it, else tick_volume
        if "real_volume" in df.columns and df["real_volume"].sum() > 0:
            vol = df["real_volume"]
        else:
            vol = df["tick_volume"]

        out = pd.DataFrame(
            {
                "Open":   df["open"].astype("float64"),
                "High":   df["high"].astype("float64"),
                "Low":    df["low"].astype("float64"),
                "Close":  df["close"].astype("float64"),
                "Volume": vol.astype("float64"),
            }
        ).sort_index()

        logger.info("MT5: fetched %d %s candles for %s", len(out), timeframe, symbol)
        return out
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
# TWELVEDATA FALLBACK ENGINE — HTTP API, works on any platform
# ════════════════════════════════════════════════════════════════════
TWELVEDATA_BASE_URL = "https://api.twelvedata.com/time_series"

# Standard timeframe → TwelveData interval string (consumed by wrapper in Step 3)
_TD_INTERVAL_MAP = {
    "1m":  "1min",
    "5m":  "5min",
    "15m": "15min",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1day",
}


def get_twelvedata_candles(
    symbol: str = "XAU/USD",
    interval: str = "5min",
    outputsize: int = 150,
    timeout: int = 15,
) -> pd.DataFrame:
    """
    Fallback engine — fetch OHLCV from TwelveData REST API.

    Parameters
    ----------
    symbol : str
        TwelveData-native symbol (e.g. 'XAU/USD').
    interval : str
        TwelveData-native interval ('1min', '5min', '15min', '30min', '1h', '4h', '1day', ...).
    outputsize : int
        Number of candles to request.
    timeout : int
        HTTP timeout per attempt, seconds.

    Returns
    -------
    pd.DataFrame
        Identical contract to get_mt5_candles():
        DatetimeIndex (UTC-naive, sorted oldest→newest),
        columns ['Open', 'High', 'Low', 'Close', 'Volume'] (float64).

    Raises
    ------
    RuntimeError
        On missing API key, TwelveData error response, empty payload, or repeated HTTP failure.
    """
    api_key = os.getenv("TWELVEDATA_API_KEY")
    if not api_key:
        raise RuntimeError("TWELVEDATA_API_KEY not set in environment")

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": int(outputsize),
        "apikey": api_key,
        "order": "ASC",  # oldest → newest, no client-side reverse needed
        "format": "JSON",
    }

    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(TWELVEDATA_BASE_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()

            if payload.get("status") == "error":
                # TwelveData uses HTTP 200 + status=error for things like rate-limit / bad symbol
                raise RuntimeError(
                    f"TwelveData error: code={payload.get('code')} msg={payload.get('message')}"
                )

            values = payload.get("values")
            if not values:
                raise RuntimeError("TwelveData returned empty 'values' array")

            df = pd.DataFrame(values)
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime").sort_index()

            for col in ("open", "high", "low", "close"):
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

            # XAU/USD on TwelveData has no real volume — synthesize 0.0 to keep contract consistent
            if "volume" in df.columns:
                vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0).astype("float64")
            else:
                vol = pd.Series(0.0, index=df.index, dtype="float64")

            out = pd.DataFrame(
                {
                    "Open":   df["open"],
                    "High":   df["high"],
                    "Low":    df["low"],
                    "Close":  df["close"],
                    "Volume": vol,
                }
            )

            logger.info(
                "TwelveData: fetched %d %s candles for %s", len(out), interval, symbol
            )
            return out

        except Exception as e:
            last_err = e
            backoff = INITIAL_BACKOFF_SEC * (2 ** (attempt - 1))
            logger.warning(
                "TwelveData attempt %d/%d failed (%s) — retrying in %ds",
                attempt, MAX_RETRIES, e, backoff,
            )
            if attempt < MAX_RETRIES:
                time.sleep(backoff)

    raise RuntimeError(
        f"TwelveData failed after {MAX_RETRIES} attempts — {last_err}"
    )


# ════════════════════════════════════════════════════════════════════
# MASTER WRAPPER — primary/fallback switcher
# ════════════════════════════════════════════════════════════════════
# Per-engine symbol map. MT5 uses 'XAUUSD' (broker-specific, may need override
# via env if broker uses 'XAUUSD.r' / 'XAUUSDm' etc.). TwelveData uses 'XAU/USD'.
_MT5_SYMBOL = os.getenv("MT5_SYMBOL", "XAUUSD")
_TD_SYMBOL = os.getenv("TWELVEDATA_SYMBOL", "XAU/USD")


def get_gold_candles(timeframe: str = "5m", num_candles: int = 150) -> pd.DataFrame:
    """
    Master data switcher — tries MT5 primary, auto-falls back to TwelveData on failure.

    Parameters
    ----------
    timeframe : str
        Standard token: '1m', '5m', '15m', '1h', '4h', '1d'.
    num_candles : int
        Number of candles to request.

    Returns
    -------
    pd.DataFrame
        Unified contract: DatetimeIndex (UTC-naive, sorted asc),
        columns ['Open', 'High', 'Low', 'Close', 'Volume'] (float64).

    Raises
    ------
    ValueError
        If timeframe is not in the supported set.
    RuntimeError
        If both MT5 and TwelveData fail.
    """
    if timeframe not in _MT5_TIMEFRAME_NAMES:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. Allowed: {list(_MT5_TIMEFRAME_NAMES)}"
        )

    # === Primary: MT5 ===
    if MT5_AVAILABLE:
        try:
            df = get_mt5_candles(
                symbol=_MT5_SYMBOL,
                timeframe=timeframe,
                num_candles=num_candles,
            )
            if df is not None and not df.empty:
                return df
            logger.warning("MT5 returned empty DataFrame — falling back to TwelveData")
        except Exception as e:
            logger.warning("MT5 primary failed (%s) — falling back to TwelveData", e)
    else:
        logger.debug(
            "MT5 not available on this platform — routing %s/%s straight to TwelveData",
            _TD_SYMBOL, timeframe,
        )

    # === Fallback: TwelveData ===
    td_interval = _TD_INTERVAL_MAP.get(timeframe)
    if td_interval is None:
        # Defensive — already validated above, but in case maps drift
        raise RuntimeError(f"No TwelveData interval mapping for timeframe '{timeframe}'")

    return get_twelvedata_candles(
        symbol=_TD_SYMBOL,
        interval=td_interval,
        outputsize=num_candles,
    )


def get_account_balance(default: float = 10000.0) -> float:
    """Account balance for position sizing.

    Prefers the live MT5 account balance; falls back to the ACCOUNT_BALANCE env
    var, then to `default`. Never raises — sizing must always get a number.
    """
    if MT5_AVAILABLE and _init_mt5():
        try:
            info = mt5.account_info()
            if info is not None:
                return float(info.balance)
        except Exception as e:
            logger.warning("mt5.account_info failed: %s", e)
        finally:
            try:
                mt5.shutdown()
            except Exception:
                pass
    env = os.getenv("ACCOUNT_BALANCE")
    if env:
        try:
            return float(env)
        except ValueError:
            logger.warning("ACCOUNT_BALANCE not a number: %r", env)
    return default


def get_gold_data():
    """
    Orchestrator — fetches the two timeframes downstream consumers need:
      • Daily (1d)  — 800 candles ≈ 3+ years, covers TYO 2024 / 2025 / 2026 + TMO + TWO.
      • Hourly (1h) — 200 candles ≈ 8 trading days, sufficient for TDO + current price.

    Both timeframes routed through get_gold_candles → MT5 primary, TwelveData fallback.
    Return signature preserved so calculate_quarterly_levels works unchanged.
    """
    df_daily = get_gold_candles(timeframe="1d", num_candles=800)
    df_intraday = get_gold_candles(timeframe="1h", num_candles=200)
    return df_daily, df_intraday

def calculate_quarterly_levels(dfs):
    """מחשב את כל רמות ה-Open (TYO, TMO, TWO, TDO)"""
    df_daily, df_intraday = dfs
    
    # מחיר נוכחי (לפי הנתון האחרון מהשעתי)
    current_price = float(df_intraday['Close'].iloc[-1])
    
    def get_yearly_open(year):
        df_year = df_daily[df_daily.index.year == year]
        if not df_year.empty:
            return float(df_year['Open'].iloc[0])
        return "N/A"

    # פתיחות שנתיות
    tyo_2026 = get_yearly_open(2026)
    tyo_2025 = get_yearly_open(2025)
    tyo_2024 = get_yearly_open(2024)

    # פתיחה חודשית (TMO)
    current_month = df_daily.index[-1].month
    current_year = df_daily.index[-1].year
    df_month = df_daily[(df_daily.index.year == current_year) & (df_daily.index.month == current_month)]
    tmo = float(df_month['Open'].iloc[0]) if not df_month.empty else "N/A"

    # פתיחה שבועית (TWO) - יום שני
    df_daily['Weekday'] = df_daily.index.weekday
    df_recent_mondays = df_daily[df_daily['Weekday'] == 0]
    two = float(df_recent_mondays['Open'].iloc[-1]) if not df_recent_mondays.empty else "N/A"

    # פתיחה יומית (TDO)
    today = df_intraday.index[-1].date()
    df_today = df_intraday[df_intraday.index.date == today]
    
    tdo = "N/A"
    if not df_today.empty:
        # ננסה למצוא שעה 07:00, אם אין ניקח את הפתיחה של היום
        df_0700 = df_today[df_today.index.hour == 7]
        if not df_0700.empty:
            tdo = float(df_0700['Open'].iloc[0])
        else:
            tdo = float(df_today['Open'].iloc[0])

    return {
        "Current": current_price,
        "TYO_2026": tyo_2026,
        "TYO_2025": tyo_2025,
        "TYO_2024": tyo_2024,
        "TMO": tmo,
        "TWO": two,
        "TDO": tdo
    }