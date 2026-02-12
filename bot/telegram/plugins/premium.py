"""
Premium plugin: Owner-only commands for managing premium users.
Commands: /add, /rem, /users (list premium users).
Matches source bot's add_premium_handler format exactly.
"""
import logging
from datetime import timedelta
from pyrogram import filters, Client
from pyrogram.types import Message
from pyrogram.enums.parse_mode import ParseMode

from bot.telegram import StreamBot
from bot.config import Telegram
from bot.helper.database import Database
from bot.utils.func import format_expiry

LOGGER = logging.getLogger(__name__)
db = Database()


def _is_owner(user_id: int) -> bool:
    """Check if user is the bot owner."""
    return user_id == Telegram.OWNER_ID


# ═══════════════════════════════════════════════════════════════════
# /add - Grant premium to a user
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("add") & filters.private)
async def add_premium(bot: Client, message: Message):
    """
    Grant premium to a user. Owner only.
    Format: /add user_id duration_value duration_unit
    Example: /add 123456 1 week
    """
    if not _is_owner(message.from_user.id):
        await message.reply("❌ This command is restricted to the bot owner.")
        return

    args = message.text.strip().split()
    if len(args) != 4:
        await message.reply(
            "📝 **Add Premium User**\n\n"
            "Usage: `/add user_id duration_value duration_unit`\n"
            "Example: `/add 123456 1 week`\n\n"
            "**Valid duration units:**\n"
            "• `min` — minutes\n"
            "• `hours` — hours\n"
            "• `days` — days\n"
            "• `weeks` — weeks\n"
            "• `month` — months\n"
            "• `year` — years\n"
            "• `decades` — decades",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        target_id = int(args[1])
        duration_value = int(args[2])
        duration_unit = args[3].lower()
    except ValueError:
        await message.reply("❌ Invalid user ID or duration value. Both must be integers.")
        return

    valid_units = ["min", "hours", "days", "weeks", "month", "year", "decades"]
    if duration_unit not in valid_units:
        await message.reply(
            f"❌ Invalid duration unit. Choose from: {', '.join(valid_units)}"
        )
        return

    success, result = await db.add_premium(target_id, duration_value, duration_unit)

    if success:
        expiry_str = format_expiry(result)
        await message.reply(
            f"✅ User {target_id} added as premium member\n"
            f"Subscription valid until: {expiry_str} (IST)",
            parse_mode=ParseMode.MARKDOWN,
        )
        # Notify the user
        try:
            await bot.send_message(
                target_id,
                f"✅ You have been added as premium member\n"
                f"**Validity upto**: {expiry_str} (IST)",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
    else:
        await message.reply(f"❌ Failed to add premium user: {result}")


# ═══════════════════════════════════════════════════════════════════
# /rem - Revoke premium from a user
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("rem") & filters.private)
async def remove_premium(bot: Client, message: Message):
    """Revoke premium from a user. Owner only."""
    if not _is_owner(message.from_user.id):
        return

    args = message.text.split()
    if len(args) != 2:
        await message.reply(
            "Usage: `/rem user_id`\nExample: `/rem 123456789`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        target_id = int(args[1])
    except ValueError:
        await message.reply("❌ Invalid user ID. Please provide a valid numeric user ID.")
        return

    is_prem = await db.is_premium(target_id)
    if not is_prem:
        await message.reply(
            f"❌ User {target_id} does not have a premium subscription.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await db.remove_premium(target_id)
    await message.reply(
        f"✅ Premium subscription successfully removed from user `{target_id}`.",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        await bot.send_message(
            target_id,
            "⚠️ Your premium subscription has been removed by the administrator.",
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# /users - List premium users
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("users") & filters.private)
async def list_premium_users(bot: Client, message: Message):
    """List all active premium users. Owner only."""
    if not _is_owner(message.from_user.id):
        await message.reply("❌ Owner-only command.")
        return

    premium_list = await db.get_all_premium_users()

    if not premium_list:
        await message.reply("ℹ️ No active premium users.")
        return

    text = "👑 **Premium Users**\n━━━━━━━━━━━━━━━━━━\n\n"
    for i, doc in enumerate(premium_list, 1):
        expiry = doc.get("expiry")
        expiry_str = format_expiry(expiry)
        text += f"{i}. `{doc['_id']}` — Expires: {expiry_str}\n"

    text += f"\n**Total:** {len(premium_list)} active"
    await message.reply(text, parse_mode=ParseMode.MARKDOWN)
