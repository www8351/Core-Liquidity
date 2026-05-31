"""aiohttp monitoring dashboard, embedded in the bot's asyncio loop.

All routes are guarded by a token (query `?token=` or header `X-Token`),
compared constant-time. The page polls /api/state every few seconds and
renders four sections: Status, Levels+Bias, Last Signal, Chart+Log.
"""
from __future__ import annotations

import hmac
import logging
import os

from aiohttp import web

logger = logging.getLogger(__name__)

REFRESH_SECONDS = int(os.getenv("DASHBOARD_REFRESH_SEC", "5"))


def _check_token(request: web.Request, token: str) -> bool:
    provided = request.query.get("token") or request.headers.get("X-Token") or ""
    return hmac.compare_digest(str(provided), token)


# The index page is a public shell (no data); the user enters the token there
# to authenticate the data calls. Everything else stays gated.
_PUBLIC_PATHS = {"/"}


@web.middleware
async def _token_middleware(request: web.Request, handler):
    if request.path not in _PUBLIC_PATHS:
        token = request.app["token"]
        if not _check_token(request, token):
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def _handle_state(request: web.Request) -> web.Response:
    return web.json_response(request.app["state"].snapshot())


async def _handle_chart(request: web.Request) -> web.Response:
    path = request.app["chart_path"]
    if not os.path.exists(path):
        return web.json_response({"error": "no chart yet"}, status=404)
    return web.FileResponse(path)


async def _handle_index(request: web.Request) -> web.Response:
    return web.Response(text=_PAGE_HTML, content_type="text/html")


def create_app(state, token: str, chart_path: str = "gold_chart.png") -> web.Application:
    app = web.Application(middlewares=[_token_middleware])
    app["state"] = state
    app["token"] = token
    app["chart_path"] = chart_path
    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/state", _handle_state)
    app.router.add_get("/chart.png", _handle_chart)
    return app


async def start_dashboard(state, host: str, port: int, token: str,
                          chart_path: str = "gold_chart.png"):
    """Start the dashboard on the current loop. Returns (runner, site)."""
    app = create_app(state, token=token, chart_path=chart_path)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("📊 Dashboard live on http://%s:%d  (token required)", host, port)
    return runner, site


_PAGE_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>XAUUSD Bot Dashboard</title>
<style>
  :root { color-scheme: dark; }
  body { background:#0e1117; color:#e6e6e6; font:14px/1.5 system-ui,sans-serif; margin:0; padding:18px; }
  h1 { font-size:18px; margin:0 0 14px; }
  .grid { display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); }
  .card { background:#161b22; border:1px solid #21262d; border-radius:10px; padding:14px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.05em; color:#8b949e; margin:0 0 10px; }
  .row { display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid #21262d; }
  .row:last-child { border-bottom:0; }
  .k { color:#8b949e; } .v { font-variant-numeric:tabular-nums; }
  .pill { padding:2px 8px; border-radius:999px; font-weight:600; font-size:12px; }
  .live { background:#3fb95033; color:#3fb950; } .dry { background:#d2992233; color:#d29922; }
  .long { color:#3fb950; } .short { color:#f85149; } .none { color:#8b949e; }
  pre { background:#0d1117; border:1px solid #21262d; border-radius:6px; padding:8px; overflow:auto; max-height:240px; font-size:12px; margin:0; }
  img { width:100%; border-radius:6px; border:1px solid #21262d; }
  #err { color:#f85149; min-height:18px; }
</style></head>
<body>
<h1>🥇 XAUUSD Quarterly-Theory Bot <span id="mode" class="pill"></span></h1>
<div class="card" style="margin-bottom:14px">
  <span class="k">Token</span>
  <input id="tok" type="password" placeholder="enter dashboard token"
         style="background:#0d1117;color:#e6e6e6;border:1px solid #21262d;border-radius:6px;padding:5px 8px;min-width:220px">
  <button id="save" style="background:#238636;color:#fff;border:0;border-radius:6px;padding:6px 12px;cursor:pointer">Connect</button>
</div>
<div id="err"></div>
<div class="grid">
  <div class="card"><h2>① Status</h2><div id="status"></div></div>
  <div class="card"><h2>② Levels &amp; Bias</h2><div id="levels"></div></div>
  <div class="card"><h2>③ Last Signal</h2><div id="signal"></div></div>
  <div class="card"><h2>④ Chart &amp; Log</h2><img id="chart" alt="chart"><pre id="log"></pre></div>
</div>
<script>
let TOKEN = new URLSearchParams(location.search).get('token')
           || localStorage.getItem('qt_token') || '';
const REFRESH = %REFRESH% * 1000;
const $ = id => document.getElementById(id);
function saveToken(){ TOKEN = $('tok').value.trim(); localStorage.setItem('qt_token', TOKEN); tick(); }
function rows(obj){ return Object.entries(obj).map(([k,v])=>
  `<div class="row"><span class="k">${k}</span><span class="v">${v??'—'}</span></div>`).join(''); }
function fmt(v){ return (typeof v==='number') ? v.toFixed(2) : (v??'—'); }
async function tick(){
  try{
    const r = await fetch('/api/state?token='+encodeURIComponent(TOKEN));
    if(!r.ok){ $('err').textContent='auth/error: HTTP '+r.status; return; }
    $('err').textContent='';
    const s = await r.json();
    const m=$('mode'); m.textContent=s.mode; m.className='pill '+(s.mode==='LIVE'?'live':'dry');
    $('status').innerHTML = rows({Quarter:s.quarter, 'In session':s.in_session,
      'Next poll':s.next_poll, Started:s.started_at});
    const b=s.bias||{};
    $('levels').innerHTML = rows({Price:fmt(s.price), ...s.levels,
      Bias:(b.overall||'—'), Synced:b.synchronized,
      POC:fmt((s.volume_profile||{}).poc)});
    const sig=s.last_signal;
    if(sig && sig.direction && sig.direction!=='none'){
      $('signal').innerHTML = `<div class="row"><span class="k">Direction</span>`+
        `<span class="v ${sig.direction}">${sig.direction.toUpperCase()}</span></div>`+
        rows({Entry:fmt(sig.entry), SL:fmt(sig.sl), TP1:fmt(sig.tp1), TP2:fmt(sig.tp2),
              'R:R':sig.rr?('1:'+Number(sig.rr).toFixed(1)):'—', Lots:sig.lots,
              Confidence:(sig.confidence??'—')+'/10'});
    } else {
      $('signal').innerHTML = `<div class="row"><span class="k">Direction</span>`+
        `<span class="v none">NO TRADE</span></div>`+
        rows({Reason:(sig?sig.reason:'—')});
    }
    $('chart').src='/chart.png?token='+encodeURIComponent(TOKEN)+'&t='+Date.now();
    $('log').textContent=(s.events||[]).map(e=>`${e.ts||''}  ${e.msg}`).join('\\n');
  }catch(e){ $('err').textContent='fetch failed: '+e; }
}
$('tok').value = TOKEN;
$('save').addEventListener('click', saveToken);
$('tok').addEventListener('keydown', e => { if(e.key==='Enter') saveToken(); });
tick(); setInterval(tick, REFRESH);
</script></body></html>""".replace("%REFRESH%", str(REFRESH_SECONDS))
