from pyrogram import filters, Client
from pyrogram.types import Message
from bot import LOGGER
from bot.telegram import StreamBot
from bot.helper.database import Database
from bot.config import Telegram

db = Database()

async def get_auth_channels():
    """Helper to get auth channels list from DB or Config"""
    auth_channel_str = await db.get_variable('auth_channel')
    if auth_channel_str is None or auth_channel_str.strip() == '':
        return [str(c) for c in Telegram.AUTH_CHANNEL]
    else:
        return [channel.strip() for channel in auth_channel_str.split(",")]

@StreamBot.on_message(filters.command("cleanservice"))
async def clean_service_toggle(bot: Client, message: Message):
    """Toggle auto-deletion of service messages."""
    # Check if user is admin/owner (Sudo or Owner)
    user_id = message.from_user.id
    if user_id != Telegram.OWNER_ID and user_id not in Telegram.SUDO_USERS:
        return

    if len(message.command) != 2:
        await message.reply("Usage: `/cleanservice on` or `/cleanservice off`")
        return
    
    status = message.command[1].lower()
    if status == "on":
        await db.update_variable("clean_service_msgs", True)
        await message.reply("✅ Auto-delete service messages: **ENABLED**\n\nService messages (e.g. 'Live stream ended') in Auth Channels will now be deleted.")
    elif status == "off":
        await db.update_variable("clean_service_msgs", False)
        await message.reply("❌ Auto-delete service messages: **DISABLED**")
    else:
        await message.reply("Usage: `/cleanservice on` or `/cleanservice off`")

@StreamBot.on_message(filters.service & filters.channel)
async def service_message_handler(bot: Client, message: Message):
    """Detect and delete service messages if enabled."""
    try:
        # Check if feature is enabled
        is_enabled = await db.get_variable("clean_service_msgs")
        if not is_enabled:
            return

        # Check if channel is an Auth Channel
        channel_id = str(message.chat.id)
        auth_channels = await get_auth_channels()
        
        # Also consider the ID with/without -100 prefix just in case configuration varies
        clean_channel_id = channel_id.replace("-100", "")
        
        # Check if current chat is in auth channels
        is_auth = False
        if channel_id in auth_channels:
            is_auth = True
        else:
            # Check against normalized IDs in auth_channels
            for ac in auth_channels:
                if ac.replace("-100", "") == clean_channel_id:
                    is_auth = True
                    break
        
        if is_auth:
            await message.delete()
            LOGGER.info(f"Auto-deleted service message in {channel_id}")
            
    except Exception as e:
        LOGGER.error(f"Error in service_message_handler: {e}")
