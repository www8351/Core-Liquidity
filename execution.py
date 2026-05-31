"""Order execution — MetaTrader5 routing behind a hard LIVE_TRADING gate.

SAFETY: live order placement happens ONLY when the env var LIVE_TRADING is
truthy AND the caller passes a real broker. The default is dry-run: the signal
is sized and logged but no order is sent. Flip LIVE_TRADING=true only after
dry-run signals have been observed and trusted.
"""
from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def is_live_trading() -> bool:
    return os.getenv("LIVE_TRADING", "false").strip().lower() in _TRUTHY


def build_order_request(signal: dict, symbol: str = "XAUUSD",
                        deviation: int = 20, magic: int = 778899) -> dict:
    """Translate a Signal into a broker-agnostic market-order request.

    The resting order carries the first target as its TP; further scale-out
    targets are managed separately by the trade-management layer.
    """
    side = "buy" if signal["direction"] == "long" else "sell"
    return {
        "symbol": symbol,
        "side": side,
        "volume": signal["lots"],
        "price": signal["entry"],
        "sl": signal["sl"],
        "tp": signal["tp1"],
        "deviation": deviation,
        "magic": magic,
        "comment": "QT-Q3",
    }


def place_order(signal: dict, broker=None, symbol: str = "XAUUSD",
                live: bool | None = None) -> dict:
    """Route a signal to execution.

    Returns one of:
      {"status": "skipped", ...}  — no trade or zero size
      {"status": "dry_run", "request": {...}}  — sized but not sent
      {"status": "sent", "result": ...}  — live order placed via broker
    """
    if signal.get("direction") not in ("long", "short"):
        return {"status": "skipped", "reason": signal.get("reason", "no direction")}
    if signal.get("lots", 0) <= 0:
        return {"status": "skipped", "reason": "zero position size"}

    request = build_order_request(signal, symbol=symbol)
    live = is_live_trading() if live is None else live

    if not live:
        logger.info("DRY-RUN order (LIVE_TRADING off): %s", request)
        return {"status": "dry_run", "request": request}

    if broker is None:
        return {"status": "skipped", "reason": "live but no broker available"}

    logger.warning("LIVE order: %s", request)
    result = broker.market_order(
        side=request["side"], volume=request["volume"],
        sl=request["sl"], tp=request["tp"], comment=request["comment"],
    )
    return {"status": "sent", "result": result, "request": request}


class MT5Broker:
    """Thin MetaTrader5 order wrapper. Imported lazily so the module loads on
    Linux/Docker where MetaTrader5 is unavailable."""

    def __init__(self, symbol: str = "XAUUSD", deviation: int = 20, magic: int = 778899):
        import MetaTrader5 as mt5  # noqa: lazy import, Windows-only
        self.mt5 = mt5
        self.symbol = symbol
        self.deviation = deviation
        self.magic = magic

    def market_order(self, side: str, volume: float, sl: float, tp: float, comment: str = ""):
        mt5 = self.mt5
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        try:
            if not mt5.symbol_select(self.symbol, True):
                raise RuntimeError(f"symbol_select failed: {mt5.last_error()}")
            tick = mt5.symbol_info_tick(self.symbol)
            if tick is None:
                raise RuntimeError(f"no tick for {self.symbol}: {mt5.last_error()}")

            if side == "buy":
                order_type, price = mt5.ORDER_TYPE_BUY, tick.ask
            else:
                order_type, price = mt5.ORDER_TYPE_SELL, tick.bid

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.symbol,
                "volume": float(volume),
                "type": order_type,
                "price": float(price),
                "sl": float(sl),
                "tp": float(tp),
                "deviation": self.deviation,
                "magic": self.magic,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                raise RuntimeError(f"order_send failed: {getattr(result, 'comment', mt5.last_error())}")
            return result
        finally:
            mt5.shutdown()
