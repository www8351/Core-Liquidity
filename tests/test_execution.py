"""Tests for execution.py — order routing gated by LIVE_TRADING."""
import pytest

from execution import place_order, is_live_trading, build_order_request


class FakeBroker:
    def __init__(self):
        self.calls = []

    def market_order(self, side, volume, sl, tp, comment=""):
        self.calls.append({"side": side, "volume": volume, "sl": sl, "tp": tp, "comment": comment})
        return {"retcode": "DONE", "order": 12345}


def long_signal():
    return {
        "direction": "long", "entry": 2000, "sl": 1990,
        "tp1": 2015, "tp2": 2040, "lots": 0.1, "rr": 3.0, "reason": "ok", "meta": {},
    }


class TestIsLiveTrading:
    def test_defaults_false(self, monkeypatch):
        monkeypatch.delenv("LIVE_TRADING", raising=False)
        assert is_live_trading() is False

    def test_true_when_set(self, monkeypatch):
        monkeypatch.setenv("LIVE_TRADING", "true")
        assert is_live_trading() is True

    def test_false_for_zero(self, monkeypatch):
        monkeypatch.setenv("LIVE_TRADING", "0")
        assert is_live_trading() is False


class TestBuildOrderRequest:
    def test_long_request(self):
        req = build_order_request(long_signal(), symbol="XAUUSD")
        assert req["side"] == "buy"
        assert req["volume"] == 0.1
        assert req["sl"] == 1990
        assert req["tp"] == 2015          # resting order uses first target
        assert req["symbol"] == "XAUUSD"

    def test_short_request_side(self):
        sig = long_signal() | {"direction": "short"}
        assert build_order_request(sig, symbol="XAUUSD")["side"] == "sell"


class TestPlaceOrder:
    def test_no_trade_is_skipped(self):
        broker = FakeBroker()
        res = place_order({"direction": "none", "reason": "no setup"}, broker=broker, live=True)
        assert res["status"] == "skipped"
        assert broker.calls == []

    def test_dry_run_does_not_call_broker(self):
        broker = FakeBroker()
        res = place_order(long_signal(), broker=broker, live=False)
        assert res["status"] == "dry_run"
        assert res["request"]["volume"] == 0.1
        assert broker.calls == []

    def test_live_calls_broker(self):
        broker = FakeBroker()
        res = place_order(long_signal(), broker=broker, live=True)
        assert res["status"] == "sent"
        assert len(broker.calls) == 1
        assert broker.calls[0]["side"] == "buy"
        assert broker.calls[0]["volume"] == 0.1

    def test_zero_lots_skipped_even_when_live(self):
        broker = FakeBroker()
        sig = long_signal() | {"lots": 0.0}
        res = place_order(sig, broker=broker, live=True)
        assert res["status"] == "skipped"
        assert broker.calls == []
