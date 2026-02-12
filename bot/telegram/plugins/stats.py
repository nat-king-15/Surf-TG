"""
Stats plugin: User status, transfer premium, and admin broadcasting.
Commands: /mystatus, /transfer, /broadcast (owner only).
"""
import logging
from pyrogram import filters, Client
from pyrogram.types import Message
from pyrogram.enums.parse_mode import ParseMode

from bot.telegram import StreamBot
from bot.config import Telegram
from bot.helper.database import Database
from bot.utils.func import format_expiry, time_remaining

LOGGER = logging.getLogger(__name__)
db = Database()


# ═══════════════════════════════════════════════════════════════════
# /mystatus - User's account status
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("mystatus") & filters.private)
async def my_status(bot: Client, message: Message):
    """Show user's account status, premium info, and usage."""
    user_id = message.from_user.id

    is_prem = await db.is_premium(user_id)
    usage = await db.get_usage(user_id)
    remaining = await db.get_remaining_limit(user_id)

    # Check session
    has_session = bool(await db.get_session(user_id))
    has_bot = bool(await db.get_bot_token(user_id))

    text = "📊 **Your Status**\n━━━━━━━━━━━━━━━━━━\n\n"

    if is_prem:
        expiry = await db.get_premium_expiry(user_id)
        text += f"💎 **Plan:** Premium\n"
        text += f"📅 **Expires:** {format_expiry(expiry)}\n"
        text += f"⏳ **Remaining:** {time_remaining(expiry)}\n"
        limit_text = "Unlimited" if remaining == -1 else str(remaining)
        text += f"📥 **Today's Usage:** {usage} / {limit_text}\n"
    else:
        text += f"🆓 **Plan:** Free\n"
        text += f"📥 **Today's Usage:** {usage} / {Telegram.FREEMIUM_LIMIT}\n"
        text += f"📊 **Remaining:** {remaining}\n"

    text += f"\n🔐 **Session:** {'✅ Logged in' if has_session else '❌ Not logged in'}\n"
    text += f"🤖 **Custom Bot:** {'✅ Set' if has_bot else '❌ Not set'}\n"

    text += "\n━━━━━━━━━━━━━━━━━━\n"
    text += "Use /plans to upgrade • /settings to configure"

    await message.reply(text, parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════
# /transfer - Transfer premium to another user
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("transfer") & filters.private)
async def transfer_premium(bot: Client, message: Message):
    """Transfer remaining premium time to another user."""
    user_id = message.from_user.id

    args = message.text.split()
    if len(args) < 2:
        await message.reply(
            "🔄 **Transfer Premium**\n\n"
            "Usage: `/transfer <user_id>`\n"
            "Transfers your remaining premium time to that user.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        target_id = int(args[1])
    except ValueError:
        await message.reply("❌ Invalid user ID. Please provide a valid numeric user ID.")
        return

    if target_id == user_id:
        await message.reply("❌ You cannot transfer premium to yourself.")
        return

    if not await db.is_premium(user_id):
        await message.reply("❌ You don't have a premium subscription to transfer.")
        return

    # Check if target already has premium
    if await db.is_premium(target_id):
        await message.reply("❌ The target user already has a premium subscription.")
        return

    success, expiry = await db.transfer_premium(user_id, target_id)
    if success:
        expiry_str = format_expiry(expiry)
        await message.reply(
            f"✅ Premium subscription successfully transferred to `{target_id}`.\n"
            f"Your premium access has been removed.",
            parse_mode=ParseMode.MARKDOWN,
        )
        # Notify the target
        try:
            await bot.send_message(
                target_id,
                f"🎁 You have received a premium subscription transfer from user `{user_id}`.\n"
                f"Your premium is valid until {expiry_str} (IST).",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        # Notify owner
        try:
            await bot.send_message(
                Telegram.OWNER_ID,
                f"♻️ Premium Transfer: {user_id} → {target_id}. Expiry: {expiry_str}",
            )
        except Exception:
            pass
    else:
        await message.reply("❌ Transfer failed. Your premium may have expired.")


# ═══════════════════════════════════════════════════════════════════
# /broadcast - Send message to all users (owner only)
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("broadcast") & filters.private)
async def broadcast(bot: Client, message: Message):
    """Broadcast a message to all registered users. Owner only."""
    if message.from_user.id != Telegram.OWNER_ID:
        await message.reply("❌ Owner-only command.")
        return

    if not message.reply_to_message:
        await message.reply(
            "📢 **Broadcast**\n\n"
            "Reply to a message with /broadcast to send it to all users."
        )
        return

    status_msg = await message.reply("📢 Broadcasting...")

    total = 0
    success = 0
    failed = 0

    # Iterate all users
    cursor = db.users.find({}, {"_id": 1})
    async for user_doc in cursor:
        total += 1
        try:
            await message.reply_to_message.copy(chat_id=user_doc["_id"])
            success += 1
        except Exception:
            failed += 1

        if total % 20 == 0:
            try:
                await status_msg.edit_text(
                    f"📢 Broadcasting...\n✅ {success} | ❌ {failed} / {total}"
                )
            except Exception:
                pass

    await status_msg.edit_text(
        f"📢 **Broadcast Complete!**\n\n"
        f"📊 Total: {total}\n"
        f"✅ Sent: {success}\n"
        f"❌ Failed: {failed}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════
# /botstats - Bot statistics (owner only)
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("botstats") & filters.private)
async def bot_stats(bot: Client, message: Message):
    """Show bot statistics. Owner only."""
    if message.from_user.id != Telegram.OWNER_ID:
        await message.reply("❌ Owner-only command.")
        return

    total_users = await db.get_all_users_count()
    premium_count = await db.get_premium_users_count()

    text = (
        "📊 **Bot Statistics**\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 **Total Users:** {total_users}\n"
        f"💎 **Premium Users:** {premium_count}\n"
        f"🆓 **Free Users:** {total_users - premium_count}\n"
    )

    await message.reply(text, parse_mode=ParseMode.MARKDOWN)
