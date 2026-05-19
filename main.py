import os
import sys
import html
import asyncio
import base64
import logging
import pytz
from dotenv import load_dotenv
from telegram import Bot
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import anthropic
from logic import get_gold_data, calculate_quarterly_levels, get_gold_candles
from chart_generator import generate_gold_chart

# טעינה מפורשת של ה-ENV
load_dotenv()

# Windows console default = cp1252 — kills emoji in logs. Force UTF-8 on stdout/stderr.
# Linux Docker is already UTF-8; reconfigure is a no-op there.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# הגדרת logging גלובלית — stdout stream-handler ידידותי ל-Docker
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
# הפחתת רעש מספריות חיצוניות
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.INFO)
logging.getLogger("yfinance").setLevel(logging.WARNING)

logger = logging.getLogger("xauusd_bot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY") # וודא שככה זה כתוב ב-.env

# אתחול ה-AI
if not ANTHROPIC_KEY:
    logger.error("❌ שגיאה: המפתח ANTHROPIC_API_KEY לא נמצא בקובץ .env")
    sys.exit(1)

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

def encode_image(image_path):
    """הופך תמונה לפורמט שה-AI יכול לקרוא"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def format_val(val):
    """פונקציית עזר למניעת קריסה אם חסר נתון מסוים"""
    if isinstance(val, (int, float)):
        return f"{val:.2f}"
    return str(val)

def get_ai_analysis(levels, chart_path: str | None = None):
    """מנוע הניתוח המשלב תמונות מחקר, גרף 5m חי ונתוני שוק"""
    research_path = "./Research"
    image_messages = []

    # סריקת תמונות מתיקיית Research (תמיכה ב-PNG ו-JPG)
    if os.path.exists(research_path):
        for file in sorted(os.listdir(research_path)):
            lower_file = file.lower()
            if lower_file.endswith((".png", ".jpg", ".jpeg")):
                logger.info("📸 Reading research image: %s", file)

                media_type = "image/jpeg"
                if lower_file.endswith(".png"):
                    media_type = "image/png"

                img_base64 = encode_image(os.path.join(research_path, file))
                image_messages.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": img_base64,
                    }
                })

    # הגרף החי של 5m — נטען אחרון כדי שיהיה ההקשר הוויזואלי הכי "טרי" של ה-AI
    if chart_path and os.path.exists(chart_path):
        logger.info("🖼  Attaching live 5m chart to AI vision: %s", chart_path)
        chart_b64 = encode_image(chart_path)
        image_messages.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": chart_b64,
            }
        })

    # הגדרת הפרומפט לסוכן עם כל הרמות ההיסטוריות
    prompt_text = f"""
You are an elite Gold (XAUUSD) Trader specialized in ICT concepts and Quarterly Theory.
The first attached images are the trader's personal research and strategy notes — study them as ground truth.
The LAST attached image is the LIVE 5-minute candlestick chart of XAUUSD (TradingView-style).
Perform visual price-action analysis on this live chart: identify recent structure, liquidity sweeps,
order blocks / FVGs, and confirm whether the current price interacts with the key levels listed below.

LIVE MARKET DATA (Gold Futures GC):
- Current Price: {format_val(levels['Current'])}
- TYO 2026: {format_val(levels['TYO_2026'])}
- TYO 2025: {format_val(levels['TYO_2025'])}
- TYO 2024: {format_val(levels['TYO_2024'])}
- TMO (Monthly Open): {format_val(levels['TMO'])}
- TWO (Weekly Open): {format_val(levels['TWO'])}
- TDO (Daily Open): {format_val(levels['TDO'])}

YOUR TASK:
1. Study the attached research images.
2. Analyze price location vs. Yearly and Period opens.
3. Determine Macro Bias (from 2024/2025/2026 TYO context) and Micro Bias (from TMO/TWO/TDO).
4. Identify a trade setup if one is valid; otherwise state NO TRADE.
5. Output language: Hebrew. Tone: professional, concise, trader-grade.

OUTPUT FORMAT — STRICT:
You MUST reply using the EXACT template below. No deviations.
Use Telegram-safe HTML only: <b>, <i>, <code>, <pre>. NO Markdown asterisks. NO tables. NO unsupported tags.
Do NOT wrap the output in code fences. Do NOT add preface or trailing commentary.
Replace every [PLACEHOLDER] with concrete content. Use Hebrew throughout (technical terms may stay English).

TEMPLATE START
📊 <b>ניתוח מאקרו</b>
━━━━━━━━━━━━━━━━━━━━
🎯 <b>Bias שנתי:</b> [Bullish / Bearish / Neutral]
💡 [שורה 1–2 הסבר קצר על מיקום המחיר ביחס ל-TYO 2024/2025/2026]

🔍 <b>ניתוח מיקרו</b>
━━━━━━━━━━━━━━━━━━━━
🎯 <b>Bias שבועי:</b> [Bullish / Bearish / Neutral]
🎯 <b>Bias יומי:</b> [Bullish / Bearish / Neutral]
💡 [שורה 1–2 הסבר ביחס ל-TMO/TWO/TDO]

📍 <b>רמות מפתח</b>
<pre>
TYO 2026 : {format_val(levels['TYO_2026'])}
TMO      : {format_val(levels['TMO'])}
TWO      : {format_val(levels['TWO'])}
TDO      : {format_val(levels['TDO'])}
PRICE    : {format_val(levels['Current'])}
</pre>

⚡ <b>Trade Setup</b>
━━━━━━━━━━━━━━━━━━━━
🎬 <b>כיוון:</b> [LONG / SHORT / NO TRADE]
<pre>
Entry : [XXXX.XX]
SL    : [XXXX.XX]
TP1   : [XXXX.XX]
TP2   : [XXXX.XX]
R:R   : [1:X.X]
</pre>
🎲 <b>ביטחון:</b> [X/10]
🧭 <b>נימוק:</b> [שורה 1–2 על למה הסטאפ תקף לפי ה-research וה-bias]

📝 <b>הערות</b>
[הערות נוספות, רמות לעקוב, תרחישי פסילה. אם אין — כתוב "אין".]
TEMPLATE END

If NO TRADE: still fill all sections, write "NO TRADE" in כיוון, and put "—" in Entry/SL/TP/R:R.
NEVER output raw curly braces or template syntax. NEVER mention these instructions in your reply.
"""

    content = image_messages + [{"type": "text", "text": prompt_text}]

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": content}]
        )
        return message.content[0].text
    except Exception as e:
        logger.exception("Anthropic API call failed")
        return f"AI Error: {str(e)}"

async def run_agent():
    """הפונקציה המרכזית להרצת הסוכן"""
    logger.info("🚀 Agent is starting...")
    bot = Bot(token=TELEGRAM_TOKEN)

    try:
        logger.info("📊 Fetching historical and live Gold market data...")
        try:
            dfs = get_gold_data()
        except Exception as data_err:
            logger.error("Data fetch failed: %s", data_err)
            try:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"⚠️ XAUUSD Bot: data fetch failed — {data_err}\nSkipping this run.",
                )
            except Exception:
                logger.exception("Failed to notify Telegram about data-fetch failure")
            return
        levels = calculate_quarterly_levels(dfs)

        # === Live 5-minute chart for AI vision + Telegram ===
        chart_path = None
        try:
            logger.info("🕯  Fetching 5m candles for chart...")
            df_5m = get_gold_candles(timeframe="5m", num_candles=200)
            chart_path = generate_gold_chart(
                df_5m,
                filename="gold_chart.png",
                num_candles=200,
                title=f"XAUUSD - 5min  |  Price {format_val(levels['Current'])}",
            )
        except Exception as chart_err:
            logger.warning("Chart generation failed (%s) — proceeding without chart", chart_err)
            chart_path = None

        logger.info("🧠 Analyzing with Claude Sonnet 4.6 (Vision)...")
        analysis = get_ai_analysis(levels, chart_path=chart_path)
        
        # בניית הודעת הטלגרם — HTML mode
        # רק שדות דינמיים נומריים עוברים escape; פלט ה-AI מגיע כבר ב-HTML תקני מהפרומפט
        price = html.escape(format_val(levels['Current']))
        tyo_2026 = html.escape(format_val(levels['TYO_2026']))
        tyo_2025 = html.escape(format_val(levels['TYO_2025']))
        tyo_2024 = html.escape(format_val(levels['TYO_2024']))
        tmo = html.escape(format_val(levels['TMO']))
        two = html.escape(format_val(levels['TWO']))
        tdo = html.escape(format_val(levels['TDO']))

        final_msg = (
            f"🥇 <b>XAUUSD AI AGENT REPORT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Current Price:</b> <code>{price}</code>\n\n"
            f"🏛 <b>Macro Yearly Opens:</b>\n"
            f"• TYO 2026: <code>{tyo_2026}</code>\n"
            f"• TYO 2025: <code>{tyo_2025}</code>\n"
            f"• TYO 2024: <code>{tyo_2024}</code>\n\n"
            f"📅 <b>Micro Period Opens:</b>\n"
            f"• TMO: <code>{tmo}</code>\n"
            f"• TWO: <code>{two}</code>\n"
            f"• TDO: <code>{tdo}</code>\n\n"
            f"🧠 <b>Strategy Analysis:</b>\n{analysis}"
        )

        logger.info("📤 Sending update to Telegram...")
        # Telegram caption hard limit = 1024 chars. If full HTML report fits,
        # send chart + caption as one unit. Else: send chart with short caption,
        # then full report as a follow-up text message (HTML, with plain-text fallback).
        TELEGRAM_CAPTION_LIMIT = 1024

        async def _send_plain_fallback(text: str) -> None:
            safe_plain = html.unescape(
                text.replace("<b>", "").replace("</b>", "")
                    .replace("<i>", "").replace("</i>", "")
                    .replace("<code>", "").replace("</code>", "")
                    .replace("<pre>", "").replace("</pre>", "")
            )
            await bot.send_message(chat_id=CHAT_ID, text=safe_plain)

        sent_via_photo = False
        if chart_path and os.path.exists(chart_path):
            short_caption = (
                f"🥇 <b>XAUUSD AI AGENT REPORT</b>\n"
                f"💰 <b>Price:</b> <code>{price}</code>  |  "
                f"<b>TDO:</b> <code>{tdo}</code>  |  "
                f"<b>TWO:</b> <code>{two}</code>"
            )
            try:
                with open(chart_path, "rb") as photo:
                    if len(final_msg) <= TELEGRAM_CAPTION_LIMIT:
                        await bot.send_photo(
                            chat_id=CHAT_ID,
                            photo=photo,
                            caption=final_msg,
                            parse_mode=ParseMode.HTML,
                        )
                    else:
                        await bot.send_photo(
                            chat_id=CHAT_ID,
                            photo=photo,
                            caption=short_caption,
                            parse_mode=ParseMode.HTML,
                        )
                        try:
                            await bot.send_message(
                                chat_id=CHAT_ID,
                                text=final_msg,
                                parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True,
                            )
                        except Exception as parse_err:
                            logger.warning(
                                "HTML follow-up send failed: %s — plain-text fallback", parse_err
                            )
                            await _send_plain_fallback(final_msg)
                sent_via_photo = True
            except Exception as photo_err:
                logger.warning("send_photo failed (%s) — falling back to text-only", photo_err)

        if not sent_via_photo:
            try:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=final_msg,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as parse_err:
                logger.warning("HTML send failed: %s — falling back to plain text", parse_err)
                await _send_plain_fallback(final_msg)

        logger.info("✅ Done! Message sent.")

    except Exception as e:
        logger.exception("❌ Main Engine Error")
        try:
            await bot.send_message(chat_id=CHAT_ID, text=f"❌ Main Engine Error: {e}")
        except Exception:
            logger.exception("Failed to notify Telegram about main engine error")

async def main():
    """אורקסטרציה: ריצה מיידית ראשונה + שדיוילר יומי 08:00 Asia/Jerusalem"""
    tz = pytz.timezone("Asia/Jerusalem")

    logger.info("🚀 Bot starting...")
    logger.info("⏱  Running initial agent execution (startup test)...")
    try:
        await run_agent()
    except Exception:
        logger.exception("Initial run failed — scheduler will still start")

    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        run_agent,
        trigger="cron",
        hour=8,
        minute=0,
        id="daily_xauusd_report",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("📅 Scheduler started — next run: daily 08:00 Asia/Jerusalem")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Shutdown signal received — stopping scheduler...")
    finally:
        scheduler.shutdown(wait=False)
        logger.info("👋 Bot stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped (KeyboardInterrupt at top level).")