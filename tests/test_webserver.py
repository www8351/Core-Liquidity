"""Tests for webserver.py — aiohttp dashboard, token-gated."""
from appstate import AppState
from webserver import create_app

TOKEN = "secret123"


def app_with_state():
    state = AppState()
    state.update_market(price=2000.0, quarter="Q3", in_session=True,
                        next_poll="20:15", levels={"TDO": 1990},
                        bias={"overall": "bullish"}, volume_profile={"poc": 1995})
    return create_app(state, token=TOKEN, chart_path="does_not_exist.png")


class TestTokenGate:
    async def test_no_token_rejected(self, aiohttp_client):
        client = await aiohttp_client(app_with_state())
        resp = await client.get("/api/state")
        assert resp.status == 401

    async def test_bad_token_rejected(self, aiohttp_client):
        client = await aiohttp_client(app_with_state())
        resp = await client.get("/api/state", params={"token": "wrong"})
        assert resp.status == 401

    async def test_good_token_via_query(self, aiohttp_client):
        client = await aiohttp_client(app_with_state())
        resp = await client.get("/api/state", params={"token": TOKEN})
        assert resp.status == 200
        data = await resp.json()
        assert data["mode"] == "DRY-RUN"
        assert data["price"] == 2000.0
        assert data["quarter"] == "Q3"

    async def test_good_token_via_header(self, aiohttp_client):
        client = await aiohttp_client(app_with_state())
        resp = await client.get("/api/state", headers={"X-Token": TOKEN})
        assert resp.status == 200


class TestRoutes:
    async def test_root_serves_html_without_token(self, aiohttp_client):
        # the page shell is public (holds no data); the token box lets the user
        # authenticate the /api/state calls from the browser
        client = await aiohttp_client(app_with_state())
        resp = await client.get("/")
        assert resp.status == 200
        assert "text/html" in resp.headers["Content-Type"]
        body = await resp.text()
        assert "XAUUSD" in body

    async def test_api_still_gated_when_root_public(self, aiohttp_client):
        client = await aiohttp_client(app_with_state())
        assert (await client.get("/api/state")).status == 401
        assert (await client.get("/chart.png")).status == 401

    async def test_chart_404_when_missing(self, aiohttp_client):
        client = await aiohttp_client(app_with_state())
        resp = await client.get("/chart.png", params={"token": TOKEN})
        assert resp.status == 404
