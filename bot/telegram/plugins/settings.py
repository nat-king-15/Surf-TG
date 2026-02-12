"""
Settings plugin: User configuration via inline keyboards.
Commands: /settings — change chat ID, rename tag, caption, replacements, delete words,
    thumbnail, reset settings, remove thumbnail.
Matches source bot's settings.py feature set.
"""
import os
import re
import logging
from pyrogram import filters, Client
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from pyrogram.enums.parse_mode import ParseMode

from bot.telegram import StreamBot
from bot.config import Telegram
from bot.helper.database import Database
from bot.utils.custom_filters import (
    settings_in_progress,
    set_user_step,
    get_user_step,
    clear_user_step,
)

LOGGER = logging.getLogger(__name__)
db = Database()


# ═══════════════════════════════════════════════════════════════════
# Settings keyboard layout (matches source)
# ═══════════════════════════════════════════════════════════════════

def _settings_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Set Chat ID", callback_data="st_chat"),
            InlineKeyboardButton("🏷️ Set Rename Tag", callback_data="st_rename"),
        ],
        [
            InlineKeyboardButton("📋 Set Caption", callback_data="st_caption"),
            InlineKeyboardButton("🔄 Replace Words", callback_data="st_replace"),
        ],
        [
            InlineKeyboardButton("🗑️ Remove Words", callback_data="st_delword"),
            InlineKeyboardButton("🔄 Reset Settings", callback_data="st_reset"),
        ],
        [
            InlineKeyboardButton("🖼️ Set Thumbnail", callback_data="st_thumb"),
            InlineKeyboardButton("❌ Remove Thumbnail", callback_data="st_remthumb"),
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data="show_start"),
        ],
    ])


# ═══════════════════════════════════════════════════════════════════
# /settings - Show settings menu
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("settings") & filters.private)
async def settings_menu(bot: Client, message: Message):
    """Show the settings inline keyboard."""
    await message.reply(
        "⚙️ **Customize settings for your files...**",
        reply_markup=_settings_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════
# Callback handlers — prompts & immediate actions
# ═══════════════════════════════════════════════════════════════════

PROMPT_ACTIONS = {
    "st_chat": {
        "step": "settings_chat",
        "msg": (
            "Send me the ID of that chat (with -100 prefix):\n\n"
            "__👉 **Note:** if you are using custom bot then your bot should be admin in that chat, "
            "if not then this bot should be admin.__\n"
            "👉 __If you want to upload in a topic group and in a specific topic then pass chat id as "
            "**-100CHANNELID/TOPIC_ID** for example: **-1004783898/12**__"
        ),
    },
    "st_rename": {
        "step": "settings_rename",
        "msg": "Send me the rename tag:",
    },
    "st_caption": {
        "step": "settings_caption",
        "msg": "Send me the caption:",
    },
    "st_replace": {
        "step": "settings_replace",
        "msg": "Send me the replacement words in the format: `'WORD(s)' 'REPLACEWORD'`",
    },
    "st_delword": {
        "step": "settings_delword",
        "msg": "Send words separated by space to delete them from caption/filename...",
    },
    "st_thumb": {
        "step": "settings_thumb",
        "msg": "Please send the photo you want to set as the thumbnail.",
    },
}


@StreamBot.on_callback_query(filters.regex(r"^st_"))
async def settings_callback(bot: Client, query: CallbackQuery):
    """Handle settings inline button callbacks."""
    user_id = query.from_user.id
    action = query.data

    # ─── Show settings menu ───
    if action == "st_menu":
        await query.message.edit_text(
            "⚙️ **Customize settings for your files...**",
            reply_markup=_settings_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        await query.answer()
        return

    # ─── Prompt-based actions (need user input) ───
    if action in PROMPT_ACTIONS:
        info = PROMPT_ACTIONS[action]
        set_user_step(user_id, info["step"])
        await query.message.reply(
            f"{info['msg']}\n\n(Send /cancel to cancel)",
            parse_mode=ParseMode.MARKDOWN,
        )
        await query.answer()
        return

    # ─── Reset all settings ───
    if action == "st_reset":
        try:
            settings = await db.get_settings(user_id)
            for key in ["chat_id", "rename_tag", "caption", "replacements", "delete_words", "thumbnail"]:
                await db.clear_setting(user_id, key)
            # Remove thumbnail file
            thumb_path = f"{user_id}.jpg"
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
            await query.answer("✅ All settings reset!", show_alert=True)
            await query.message.reply("✅ All settings reset successfully. To logout, click /logout")
        except Exception as e:
            await query.answer(f"Error: {e}", show_alert=True)
        return

    # ─── Remove thumbnail ───
    if action == "st_remthumb":
        thumb_path = f"{user_id}.jpg"
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
            await db.clear_setting(user_id, "thumbnail")
            await query.answer("✅ Thumbnail removed!", show_alert=True)
            await query.message.reply("Thumbnail removed successfully!")
        else:
            await query.answer("No thumbnail found to remove.", show_alert=True)
        return

    await query.answer()


# ═══════════════════════════════════════════════════════════════════
# Handle settings text input
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.private & settings_in_progress & ~filters.command(["cancel", "settings"]))
async def handle_settings_input(bot: Client, message: Message):
    """Handle multi-step settings conversation."""
    user_id = message.from_user.id
    step_info = get_user_step(user_id)
    if not step_info:
        return

    step = step_info["step"]

    # ─── Chat ID ───
    if step == "settings_chat":
        try:
            chat_id = message.text.strip()
            await db.update_setting(user_id, "chat_id", chat_id)
            clear_user_step(user_id)
            await message.reply("✅ Chat ID set successfully!")
        except Exception as e:
            await message.reply(f"❌ Error setting chat ID: {e}")

    # ─── Rename tag ───
    elif step == "settings_rename":
        rename_tag = message.text.strip()
        await db.update_setting(user_id, "rename_tag", rename_tag)
        clear_user_step(user_id)
        await message.reply(f"✅ Rename tag set to: {rename_tag}")

    # ─── Caption ───
    elif step == "settings_caption":
        caption = message.text
        await db.update_setting(user_id, "caption", caption)
        clear_user_step(user_id)
        await message.reply("✅ Caption set successfully!")

    # ─── Replace words ───
    elif step == "settings_replace":
        match = re.match(r"'(.+)'\s+'(.+)'", message.text)
        if not match:
            await message.reply("❌ Invalid format. Usage: `'WORD(s)' 'REPLACEWORD'`")
            return
        word, replacement = match.groups()
        settings = await db.get_settings(user_id)
        # Check if word is in delete list
        if word in settings.get("delete_words", []):
            await message.reply(f"❌ The word '{word}' is in the delete list and cannot be replaced.")
            clear_user_step(user_id)
            return
        replacements = settings.get("replacements", {})
        replacements[word] = replacement
        await db.update_setting(user_id, "replacements", replacements)
        clear_user_step(user_id)
        await message.reply(f"✅ Replacement saved: '{word}' → '{replacement}'")

    # ─── Delete words ───
    elif step == "settings_delword":
        words = message.text.split()
        settings = await db.get_settings(user_id)
        existing = settings.get("delete_words", [])
        existing = list(set(existing + words))
        await db.update_setting(user_id, "delete_words", existing)
        clear_user_step(user_id)
        await message.reply(f"✅ Words added to delete list: {', '.join(words)}")

    # ─── Thumbnail ───
    elif step == "settings_thumb":
        if message.photo:
            try:
                thumb_path = f"{user_id}.jpg"
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
                await message.download(file_name=thumb_path)
                await db.update_setting(user_id, "thumbnail", thumb_path)
                clear_user_step(user_id)
                await message.reply("✅ Thumbnail saved successfully!")
            except Exception as e:
                await message.reply(f"❌ Error saving thumbnail: {e}")
        else:
            await message.reply("❌ Please send a photo. Operation cancelled.")
            clear_user_step(user_id)


# ═══════════════════════════════════════════════════════════════════
# /cancel - Cancel settings flow
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("cancel") & filters.private & settings_in_progress)
async def cancel_settings(bot: Client, message: Message):
    """Cancel the active settings flow."""
    clear_user_step(message.from_user.id)
    await message.reply("❌ Settings operation cancelled.")
