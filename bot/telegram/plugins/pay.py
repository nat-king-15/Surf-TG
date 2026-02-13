"""
Payment plugin: Manual UPI payment + Dynamic Plan Management.
Commands: 
- /plans (or /pay) — show premium plans & payment instructions
- /addplan, /delplan, /listplans — Owner only
"""
import logging
from pyrogram import filters, Client
from pyrogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)
from pyrogram.enums.parse_mode import ParseMode

from bot.telegram import StreamBot
from bot.config import Telegram
from bot.helper.database import Database

LOGGER = logging.getLogger(__name__)
db = Database()

# ═══════════════════════════════════════════════════════════════════
# /plans (or /pay) — Display premium plans
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command(["plans", "pay"]) & filters.private)
async def plans_handler(bot: Client, message: Message):
    """Show available premium subscription plans from DB."""
    # Fetch plans from DB
    plans = await db.get_plans()
    
    # Fallback to Config if DB is empty (migration aid)
    if not plans and hasattr(Telegram, 'PREMIUM_PLANS'):
        # Convert config plans to DB format for display
        plans = {}
        for k, v in Telegram.PREMIUM_PLANS.items():
             plans[k] = {
                 "l": v["l"],
                 "du": v["du"],
                 "u": v["u"],
                 "p": f"{v['s']} Stars" # Fallback price
             }

    if not plans:
        await message.reply_text("❌ No plans available at the moment.")
        return

    # Build text
    text = "💎 **Premium Plans**\n━━━━━━━━━━━━━━━━━━\n\n"
    
    for key, plan in plans.items():
        text += f"📌 **{plan['l']}**\n"
        text += f"   ⏳ Duration: {plan['du']} {plan['u']}\n"
        text += f"   💰 Price: {plan['p']}\n\n"

    text += (
        "💳 **Payment Method**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Pay via UPI to:\n"
        f"`{Telegram.OWNER_ID}@upi` (Replace with actual UPI)\n\n" # Placeholder, owner should update message or we add config
        "**After Payment:**\n"
        "1. Take a screenshot of the payment.\n"
        f"2. Send it to the Owner: [Click Here](tg://user?id={Telegram.OWNER_ID})\n"
        "3. Wait for activation.\n\n"
        "⚠️ **Note:** This is a manual process. Please be patient."
    )
    
    # We can add a direct link button to owner
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Contact Owner", user_id=Telegram.OWNER_ID)]
    ])

    await message.reply_text(text, reply_markup=kb, disable_web_page_preview=True)


# ═══════════════════════════════════════════════════════════════════
# Owner Commands: Plan Management
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("addplan"))
async def add_plan_command(bot: Client, message: Message):
    """
    Add/Update a plan.
    Usage: /addplan <key> <duration> <unit> <price> <label>
    Example: /addplan d 1 days ₹10 Daily
    """
    if message.from_user.id != Telegram.OWNER_ID and message.from_user.id not in Telegram.SUDO_USERS:
        # Silently ignore or reply for debugging?
        # For this troubleshooting session, I'll reply with ID.
        # await message.reply_text(f"❌ Unauthorized. Your ID: `{message.from_user.id}` vs Owner: `{Telegram.OWNER_ID}`")
        return
        
    try:
        args = message.text.split(None, 5)
        if len(args) < 6:
            await message.reply_text(
                "❌ Usage: `/addplan <key> <duration> <unit> <price> <label>`\n\n"
                "Example: `/addplan d 1 days 10Rs Daily`"
            )
            return

        key = args[1]
        duration = int(args[2])
        unit = args[3]
        price = args[4]
        label = args[5]

        # Validate unit
        valid_units = ["min", "hours", "days", "weeks", "month", "year"]
        if unit not in valid_units:
             await message.reply_text(f"❌ Invalid unit. Use: {', '.join(valid_units)}")
             return

        await db.add_plan(key, duration, unit, price, label)
        await message.reply_text(f"✅ Plan `{label}` ({key}) added/updated!")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


@StreamBot.on_message(filters.command("delplan"))
async def del_plan_command(bot: Client, message: Message):
    """
    Delete a plan.
    Usage: /delplan <key>
    """
    if message.from_user.id != Telegram.OWNER_ID and message.from_user.id not in Telegram.SUDO_USERS:
        return

    try:
        if len(message.command) < 2:
            await message.reply_text("❌ Usage: `/delplan <key>`")
            return
        
        key = message.command[1]
        if await db.delete_plan(key):
            await message.reply_text(f"✅ Plan `{key}` deleted.")
        else:
            await message.reply_text(f"❌ Plan `{key}` not found.")
    except Exception as e:
         await message.reply_text(f"❌ Error: {e}")


@StreamBot.on_message(filters.command("listplans"))
async def list_plans_command(bot: Client, message: Message):
    """List all configured plans (Raw)."""
    if message.from_user.id != Telegram.OWNER_ID and message.from_user.id not in Telegram.SUDO_USERS:
        return

    plans = await db.get_plans()
    if not plans:
        await message.reply_text("📂 No plans in database.")
        return
        
    text = "📋 **Configured Plans**\n\n"
    for key, val in plans.items():
        text += f"🆔 `{key}`\n"
        text += f"🏷️ {val['l']}\n"
        text += f"⏳ {val['du']} {val['u']}\n"
        text += f"💰 {val['p']}\n"
        text += "──────────────\n"
    
    await message.reply_text(text)
