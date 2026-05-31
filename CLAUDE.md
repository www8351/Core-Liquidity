# CLAUDE.md — XAUUSD Quarterly-Theory Bot

Guidance for working in this repo. The bot trades/monitors Gold (XAUUSD) using
ICT Quarterly Theory: a **deterministic Python engine** computes signals, an
optional **AI vision report** narrates the market, signals route to **Telegram**
and (when enabled) **MetaTrader 5**, and a **web dashboard** shows live state.

## Run

```bash
pip install -r requirements.txt
python main.py                     # local (Windows = MT5 primary, else TwelveData)
docker-compose up -d               # 24/7 container
python -m pytest                   # full test suite (currently 90 tests)
```

On startup the bot: runs one AI report immediately, starts the dashboard (if
`DASHBOARD_TOKEN` set), then schedules the daily report (08:00 Asia/Jerusalem)
and the strategy poll (every `STRATEGY_POLL_MIN`).

## Architecture (modules)

Pure, unit-tested building blocks (no I/O) — each has a `tests/test_*.py`:

| Module | Responsibility |
|---|---|
| `quarters.py` | True Day anchor (18:00 NY) → 90-min cycle → four 22.5-min micro-quarters Q1–Q4 |
| `smc.py` | FVG, IFVG, swing highs/lows, liquidity sweeps, MSS, OTE 0.62–0.79 fib zone |
| `volume_profile.py` | POC / VAH / VAL, Anchored VWAP |
| `bias.py` | HTF bias vs TMO/TWO/TDO → bullish/bearish/neutral + `synchronized` |
| `risk.py` | position sizing (XAUUSD 100 oz/lot), SL outside Judas range, RRR≥3 gate, scale-out |
| `strategy.py` | combiner = the entry decision chain; produces a `Signal` dict |
| `orchestration.py` | session gate, per-cycle dedupe (`CycleGuard`), Telegram message format |
| `research.py` | load `Research/*.md` + `*.txt` notes into the AI prompt (images handled in main) |
| `appstate.py` | in-memory live state for the dashboard (`AppState`, singleton `STATE`) |
| `execution.py` | MT5 order placement behind the `LIVE_TRADING` gate; `MT5Broker` wrapper |
| `webserver.py` | aiohttp dashboard (token-gated `/api/state`, `/chart.png`; public `/` shell) |

I/O / orchestration layers (exercised by running the bot, not unit-tested):

| File | Responsibility |
|---|---|
| `main.py` | entry point; schedulers; wires engine → risk → execution → Telegram + dashboard |
| `logic.py` | data feed switch (MT5 primary ↔ TwelveData fallback), Quarterly levels, `get_account_balance` |
| `chart_generator.py` | mplfinance TradingView-style PNG (`gold_chart.png`) |

### Strategy spec → code map
- Q1–Q4 / 90-min cycle → `quarters.quarter_info`
- HTF bias sync → `bias.htf_bias`
- Q2 Judas sweep → `strategy._judas_sweep` (sweep *against* bias) over `smc.detect_liquidity_sweeps`
- MSS confirms bias → `strategy._mss_aligned` over `smc.detect_mss`
- IFVG / OTE retest → `strategy.find_entry_zone` (`smc.find_ifvgs`, `smc.ote_zone`)
- SL outside Judas range → `risk.place_stop`; RRR≥3 → `risk.compute_rr`/`meets_min_rr`
- Sizing/scaling → `risk.position_size`/`scale_out_levels`

The full decision chain lives in `strategy.evaluate_setup`; the intraday loop is
`main.run_strategy_cycle` (session-gated, one action per 90-min cycle).

## Data feeds
`logic.get_gold_candles` tries **MT5** first (Windows, local terminal), falls
back to **TwelveData** (HTTP, any platform). TwelveData `XAU/USD` has **no real
volume** → `volume_profile` is skipped that cycle (POC unavailable). Live MT5
trading requires the terminal running on Windows.

## Dashboard
aiohttp server embedded in the bot loop. Open `http://<host>:<port>/` (public
shell) and enter the token in the box, or use `?token=...`. Data routes
(`/api/state`, `/chart.png`) are token-gated (constant-time compare). Four
sections: ① Status+mode ② Levels+Bias+POC ③ Last signal ④ Chart+log. Page polls
`/api/state` every `DASHBOARD_REFRESH_SEC`. Off unless `DASHBOARD_TOKEN` is set.

## Configuration (env / `.env`)
See `.env.example` for the full template. Key vars:

| Var | Default | Purpose |
|---|---|---|
| `TELEGRAM_TOKEN`, `CHAT_ID` | — | Telegram delivery (required) |
| `ANTHROPIC_API_KEY` | — | Claude vision report (required) |
| `TWELVEDATA_API_KEY` | — | fallback data feed |
| `MT5_LOGIN/PASSWORD/SERVER/SYMBOL` | — | MT5 feed + live execution |
| `RISK_PCT` | `0.01` | fraction of balance risked per trade |
| `SL_BUFFER` | `0.5` | extra price beyond Judas range for the stop |
| `STRATEGY_POLL_MIN` | `5` | strategy evaluation cadence (minutes) |
| `ACCOUNT_BALANCE` | `10000` | sizing fallback when MT5 balance unavailable |
| `SESSION_START_HOUR`/`SESSION_END_HOUR` | `2`/`16` | NY-hour trading window (London+NY) |
| `QT_TRUE_DAY_OPEN_HOUR` | `18` | True Day open hour (NY) |
| `DASHBOARD_TOKEN` | — | **required to enable** the dashboard |
| `DASHBOARD_HOST`/`DASHBOARD_PORT` | `0.0.0.0`/`8080` | bind address / port |
| `LIVE_TRADING` | `false` | **see Safety** |

## Safety — real money
`LIVE_TRADING` defaults **false** (dry-run): the bot computes, sizes, and posts
signals to Telegram/dashboard but places **no MT5 orders**. Set `true` only after
watching dry-run signals and trusting them. `execution.place_order` is the single
gate; never bypass it. Dashboard data routes must stay token-gated when bound to
`0.0.0.0`. `.env` holds live secrets — never commit it (it is gitignored).

## Conventions
- TDD: write the failing test first, then minimal code (see existing `tests/`).
- Pure logic stays I/O-free and testable; `main.py`/`logic.py` hold the side effects.
- Timezones: strategy/quarters use America/New_York; the daily report cron uses Asia/Jerusalem.

---

# Strategy Spec (source of truth for the engine)

Entry Strategy
Primary Bias Alignment: Synchronize current price action against High Time Frame (HTF) "True Opens": True Monthly Open (TMO), True Weekly Open (TWO), and True Daily Open (TDO).
Bullish Bias: Price trades and holds above HTF opens.
Bearish Bias: Price trades and holds below HTF opens.
Time-Based Framework (Quarterly Theory): Execution is restricted to the 90-minute algorithmic cycle, divided into four 22.5-minute quarters.
Q1 (Accumulation): Observe range establishment; identify the "Anchor Price" or Inversion Fair Value Gap (IFVG).
Q2 (Manipulation/Judas Swing): Wait for a sharp move against the primary bias intended to sweep liquidity.
Q3 (Distribution): This is the "True Move." Execute trades as price reverses from manipulation and aligns with HTF bias.
Technical Triggers and Confirmation:
Liquidity Sweep: Requires a sweep of HTF or LTF liquidity (Buy-side or Sell-side).
Market Structure Shift (MSS): Confirmation of trend reversal following a liquidity grab.
Fair Value Gap (FVG) / IFVG: Price must return to a Fair Value Gap or an Inversion FVG (where a previous gap now acts as support/resistance) for entry.
Optimal Trade Entry (OTE): Entry zone prioritized within the 0.62 to 0.79 Fibonacci retracement levels.
Volume Profile Confluence:
Failed Auction: Price breaks below Value Area Low (VAL) or above Value Area High (VAH) and immediately reverses back inside the value area.
Point of Control (POC): Use the POC as a magnet for price or as a significant level of interest.
AVWAP Rejection: Confirmation via rejection from the Anchored VWAP (AVWAP) level.

    IF (Current_Time == Q3_Window) AND (HTF_Bias == Synchronized):
        IF (Q2_Judas_Swing == Completed) AND (Liquidity_Sweep == True):
            IF (Price_Action == MSS) AND (Retest == IFVG_or_OTE):
                EXECUTE ENTRY

Exit Strategy
Stop Loss (SL) Placement:
Judas Swing Protection: SL must be placed strictly outside the liquidity sweep/manipulation range of the Q2 Judas Swing.
Technical Invalidation: SL placed below the low of a bullish liquidity grab or above the high of a bearish liquidity grab.
Take Profit (TP) Targets:
Liquidity Objectives: Targets set at opposing liquidity pools (e.g., Target NYC High or Previous Day High for longs).
Volume Profile Targets: Targets set at the Point of Control (POC) or opposing Value Area boundaries (VAH/VAL).
Fixed RRR Targets: Specific use of 1:3 or higher risk-to-reward metrics.
Trade Management:
Scaling Out: Scale out of positions at predetermined levels rather than closing the entire position at once.
Trailing Logic: Secure profits as price moves aggressively toward HTF liquidity.

Risk/Reward Ratio (RRR)
Standard Target: Minimum expected RRR is 1:3.
High-Probability Setups: ICT-based models (HTF POI + MSS + FVG + OTE).

Execution Rules
Operating Assets: Primarily Gold (XAUUSD); design generalizes to major FX/crypto.
Time Constraints:
Trading is strictly forbidden during the Q1 Accumulation phase.
Prioritize London and New York session opens for liquidity and volatility.
Asset-Specific Constraints:
Gold (XAUUSD): Monitor DXY for inverse correlation during manipulation phases (not yet wired — no DXY feed).
Operational Checklist:
1. Determine Bias (HTF Sync).
2. Wait for Q1 range.
3. Identify Q2 Judas Swing (Liquidity Hunt).
4. Execute in Q3 upon IFVG/OTE retest.
5. Set SL outside manipulation range.
