import asyncio
import time
from datetime import datetime, timedelta

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ParseMode

from bot import LOGGER
from bot.config import Telegram
from bot.helper.database import Database

db = Database()

# Global semaphore — max concurrent browser instances
_semaphore   = asyncio.Semaphore(Telegram.MAX_CONCURRENT)
_queue_len   = 0
_active      = 0
_total_done  = 0


# ── Import all bypass modules ─────────────────────────────────────────────────
try:
    from bot.utils.mystudyhub_bypass import bypass as bypass_async, get_arolinks_url
    HAS_BYPASS = True
    LOGGER.info("✅ Bypass module loaded successfully")
except ImportError as e:
    HAS_BYPASS = False
    LOGGER.warning(f"❌ Could not import mystudyhub_bypass: {e}")

try:
    from bot.utils.mystudyhub_playwright import bypass as bypass_playwright
    HAS_PLAYWRIGHT = True
    LOGGER.info("✅ Playwright module loaded")
except ImportError:
    HAS_PLAYWRIGHT = False
    LOGGER.warning("⚠️ mystudyhub_playwright not found — mode disabled")

try:
    from bot.utils.mystudyhub_selenium import bypass as bypass_selenium
    HAS_SELENIUM = True
    LOGGER.info("✅ Selenium module loaded")
except ImportError:
    HAS_SELENIUM = False
    LOGGER.warning("⚠️ mystudyhub_selenium not found — mode disabled")


# ── Mode definitions ──────────────────────────────────────────────────────────
MODES = {
    "bypass":     {"label": "🚀 Playwright Async",  "desc": "Sabse fast (Recommended)"},
    "playwright": {"label": "🎭 Playwright Sync",   "desc": "Playwright standalone"},
    "selenium":   {"label": "🕷 Selenium",           "desc": "Selenium based"},
}


# ── Helper ───────────────────────────────────────────────────────────────────
def fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    return f"{int(seconds//60)}m {int(seconds%60)}s"


async def _run_bypass(mode: str, arolinks_url: str) -> dict:
    """Run the appropriate bypass function based on selected mode."""
    if mode == "playwright" and HAS_PLAYWRIGHT:
        return await bypass_playwright(arolinks_url, headless=True)
    elif mode == "selenium" and HAS_SELENIUM:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: bypass_selenium(arolinks_url, headless=True)
        )
    else:
        return await bypass_async(arolinks_url, headless=True, use_chrome=False)


# ── Command Handlers ─────────────────────────────────────────────────────────

@Client.on_message(filters.command("bstatus") & filters.private)
async def cmd_bstatus(client: Client, message: Message):
    text = (
        "📊 *Bypass Bot Status*\n\n"
        f"🟢 Active:      `{_active}/{Telegram.MAX_CONCURRENT}`\n"
        f"⏳ In Queue:    `{_queue_len}`\n"
        f"✅ Total Done:  `{_total_done}`\n\n"
        "*Modes Available:*\n"
        f"  🚀 Playwright Async: `{'✅' if HAS_BYPASS else '❌'}`\n"
        f"  🎭 Playwright Sync:  `{'✅' if HAS_PLAYWRIGHT else '❌'}`\n"
        f"  🕷 Selenium:          `{'✅' if HAS_SELENIUM else '❌'}`"
    )
    await message.reply(text, parse_mode=ParseMode.MARKDOWN)


@Client.on_message(filters.command("getkey") & filters.private)
async def cmd_getkey(client: Client, message: Message):
    user_id = message.from_user.id

    # 1. Premium User Check
    is_premium = await db.is_premium(user_id)
    if not is_premium:
        await message.reply(
            "💎 **Premium Feature Only**\n\n"
            "This command (`/getkey`) is restricted to **Premium Users** only.\n\n"
            "Please use `/plans` to see available premium subscriptions.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # 2. Daily Cooldown Check
    last_time = await db.get_last_token_time(user_id)
    if last_time:
        time_diff = datetime.utcnow() - last_time
        if time_diff < timedelta(hours=24):
            remaining = timedelta(hours=24) - time_diff
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await message.reply(
                "⏳ **Cooldown Active**\n\n"
                "You can only generate one token every 24 hours.\n"
                f"Please try again in: `{hours}h {minutes}m`.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

    # Show mode selection keyboard
    keyboard = []
    
    if HAS_BYPASS:
        keyboard.append([InlineKeyboardButton(
            f"{MODES['bypass']['label']} — {MODES['bypass']['desc']}",
            callback_data="mode:bypass"
        )])
        
    keyboard.append([InlineKeyboardButton(
        f"{MODES['playwright']['label']} — {MODES['playwright']['desc']}"
        + ("" if HAS_PLAYWRIGHT else " ❌"),
        callback_data="mode:playwright"
    )])
    
    keyboard.append([InlineKeyboardButton(
        f"{MODES['selenium']['label']} — {MODES['selenium']['desc']}"
        + ("" if HAS_SELENIUM else " ❌"),
        callback_data="mode:selenium"
    )])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply(
        "🔑 *Key Generation Mode Chuno:*\n\n"
        "Neeche diye gaye options me se ek select karo 👇",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
    )


@Client.on_callback_query(filters.regex(r"^mode:"))
async def cb_mode_select(client: Client, query: CallbackQuery):
    """Handle mode button press → run bypass."""
    global _queue_len, _active, _total_done

    # Check premium and cooldown again in callback just to be safe
    user_id = query.from_user.id
    if not await db.is_premium(user_id):
        await query.answer("You need Premium to use this.", show_alert=True)
        return
        
    last_time = await db.get_last_token_time(user_id)
    if last_time and (datetime.utcnow() - last_time) < timedelta(hours=24):
        await query.answer("Cooldown is active. Wait 24 hours.", show_alert=True)
        return

    # Parse selected mode
    data = query.data  # e.g. "mode:bypass"
    mode = data.split(":")[1] if ":" in data else "bypass"

    # Check if mode is available
    if mode == "bypass" and not HAS_BYPASS:
        await query.message.edit_text("❌ Bypass mode available nahi hai.")
        return
    if mode == "playwright" and not HAS_PLAYWRIGHT:
        await query.message.edit_text("❌ Playwright Sync mode available nahi hai.")
        return
    if mode == "selenium" and not HAS_SELENIUM:
        await query.message.edit_text("❌ Selenium mode available nahi hai.")
        return

    user = query.from_user
    user_str = f"{user.first_name} (@{user.username or user.id})"
    mode_label = MODES.get(mode, {}).get("label", mode)
    LOGGER.info(f"[/getkey] {mode_label} mode — {user_str}")

    # ── Queue check ──────────────────────────────────────────────────────────
    if _queue_len > 0 or _active >= Telegram.MAX_CONCURRENT:
        pos = _queue_len + 1
        await query.message.edit_text(
            f"📋 *Queue me ho!* Position: `#{pos}`\n"
            f"⏳ Abhi `{_active}` keys generate ho rahi hain.\n"
            f"Mode: {mode_label}\n"
            "Apni baari aane par automatically start ho jaega...",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await query.message.edit_text(
            f"⏳ *Shuru ho rahi hai...*\nMode: *{mode_label}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    _queue_len += 1

    # ── Wait for semaphore ───────────────────────────────────────────────────
    async with _semaphore:
        _queue_len -= 1
        _active    += 1
        start_time  = time.time()

        # Status message
        status_text = (
            f"⏳ *Key generate ho rahi hai...*\n"
            f"Mode: *{mode_label}*\n\n"
            "_Kripya 40-60 seconds wait karein..._"
        )
        await query.message.edit_text(status_text, parse_mode=ParseMode.MARKDOWN)

        # ── Run bypass ───────────────────────────────────────────────────────
        token      = None
        verify_url = None
        error_msg  = None

        try:
            # Step 1: Get arolinks URL
            if HAS_BYPASS:
                arolinks_url = get_arolinks_url()
            else:
                raise Exception("Cannot fetch URL because getting Arolinks source module failed.")
                
            if not arolinks_url:
                raise Exception("AroLinks URL nahi mila. Site down ho sakti hai.")

            LOGGER.info(f"[bypass:{mode}] starting for {user_str}")

            # Step 2: Run selected mode
            result = await _run_bypass(mode, arolinks_url)

            token      = result.get("token")
            raw_verify = result.get("verify_url") or ""
            # Always use mystudyhub verify URL
            if token:
                if "mystudyhub.shop/token/verify/" in raw_verify:
                    verify_url = raw_verify
                else:
                    verify_url = f"https://web.mystudyhub.shop/token/verify/{token}"
            else:
                verify_url = ""

            if not token:
                raise Exception("Token nahi mila. Bypass fail hua.")

            elapsed = time.time() - start_time
            _total_done += 1
            LOGGER.info(f"[bypass:{mode}] success — {token} ({fmt_time(elapsed)})")

            # SAVE TO DATABASE
            await db.save_token_history(user_id, token, mode)

        except Exception as e:
            error_msg = str(e)[:300]
            elapsed   = time.time() - start_time
            LOGGER.error(f"[bypass:{mode}] FAILED for {user_str}: {e}")

        finally:
            _active -= 1

        # ── Send result ──────────────────────────────────────────────────────
        if token:
            reply = (
                f"✅ *Key Generate Ho Gayi!*\n\n"
                f"🔑 *Token:*\n`{token}`\n\n"
                f"🔗 *Verify URL:*\n{verify_url}\n\n"
                f"⏱ Time: `{fmt_time(elapsed)}` | Mode: `{mode_label}`"
            )
            await query.message.edit_text(reply, parse_mode=ParseMode.MARKDOWN)
        else:
            short_err = (error_msg or "Unknown error")[:300]
            reply = (
                f"❌ *Key Generate Nahi Hui*\n\n"
                f"Mode: `{mode_label}`\n"
                f"Error: `{short_err}`\n\n"
                f"⏱ Time: `{fmt_time(elapsed)}`\n\n"
                "_Thodi der baad `/getkey` dobara try karein._"
            )
            try:
                await query.message.edit_text(reply, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await query.message.edit_text(
                    f"❌ Key generate nahi hui.\nMode: {mode_label}\nTime: {fmt_time(elapsed)}\nDobara /getkey try karein."
                )
