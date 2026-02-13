"""
Batch plugin: Download messages from Telegram channels/groups.
Commands: /batch, /single, /cancel (or /stop).
Matches source bot's conversational flow:
  /batch → user sends start link → user sends count → process begins.
  /single → user sends link → process single message.
Requires /setbot (custom bot token) to be set first.
"""
import os
import re
import time
import json
import asyncio
import logging
from typing import Dict, Any, Optional

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FileReferenceExpired

from bot.telegram import StreamBot
from bot.config import Telegram
from bot.helper.database import Database
from bot.utils.encrypt import decrypt
from bot.utils.func import (
    get_video_metadata,
    generate_thumbnail,
)
from bot.utils.custom_filters import login_in_progress, settings_in_progress, get_user_step

LOGGER = logging.getLogger(__name__)
db = Database()

# ─── In-memory state ───
CONV_STATE: Dict[int, dict] = {}          # conversation steps per user
ACTIVE_USERS: Dict[str, dict] = {}        # active batch tracking
USER_BOTS: Dict[int, Client] = {}         # cached custom bot clients
USER_CLIENTS: Dict[int, Client] = {}      # cached user session clients
PROGRESS: Dict[int, int] = {}             # dedup progress edits

ACTIVE_USERS_FILE = "active_users.json"


# ═══════════════════════════════════════════════════════════════════
# Active user tracking (persisted to JSON)
# ═══════════════════════════════════════════════════════════════════

def _load_active_users():
    try:
        if os.path.exists(ACTIVE_USERS_FILE):
            with open(ACTIVE_USERS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


async def _save_active_users():
    try:
        with open(ACTIVE_USERS_FILE, "w") as f:
            json.dump(ACTIVE_USERS, f)
    except Exception as e:
        LOGGER.error(f"Save active users error: {e}")


ACTIVE_USERS = _load_active_users()


def is_user_active(uid: int) -> bool:
    return str(uid) in ACTIVE_USERS


def should_cancel(uid: int) -> bool:
    return ACTIVE_USERS.get(str(uid), {}).get("cancel_requested", False)


async def add_active_batch(uid: int, info: dict):
    ACTIVE_USERS[str(uid)] = info
    await _save_active_users()


async def update_batch_progress(uid: int, current: int, success: int):
    if str(uid) in ACTIVE_USERS:
        ACTIVE_USERS[str(uid)]["current"] = current
        ACTIVE_USERS[str(uid)]["success"] = success
        await _save_active_users()


async def request_cancel(uid: int) -> bool:
    if str(uid) in ACTIVE_USERS:
        ACTIVE_USERS[str(uid)]["cancel_requested"] = True
        await _save_active_users()
        return True
    return False


async def remove_active_batch(uid: int):
    ACTIVE_USERS.pop(str(uid), None)
    await _save_active_users()


# ═══════════════════════════════════════════════════════════════════
# Link parser (matches source's E function)
# ═══════════════════════════════════════════════════════════════════

def parse_link(url: str):
    """Parse a t.me link → (chat_id_or_username, msg_id, 'public'|'private')."""
    priv = re.match(r"https://t\.me/c/(\d+)/(?:\d+/)?(\d+)", url)
    pub = re.match(r"https://t\.me/([^/]+)/(?:\d+/)?(\d+)", url)
    if priv:
        return f"-100{priv.group(1)}", int(priv.group(2)), "private"
    if pub:
        return pub.group(1), int(pub.group(2)), "public"
    return None, None, None


# ═══════════════════════════════════════════════════════════════════
# Client helpers
# ═══════════════════════════════════════════════════════════════════

async def get_user_bot(uid: int) -> Optional[Client]:
    """Get (or start) the user's custom bot client."""
    token = await db.get_bot_token(uid)
    if not token:
        return None
    if uid in USER_BOTS:
        return USER_BOTS[uid]
    try:
        bot = Client(
            f"ubot_{uid}",
            bot_token=token,
            api_id=Telegram.API_ID,
            api_hash=Telegram.API_HASH,
            in_memory=True,
            no_updates=True,
        )
        await bot.start()
        USER_BOTS[uid] = bot
        return bot
    except Exception as e:
        LOGGER.error(f"User bot start error for {uid}: {e}")
        return None


async def get_user_client(uid: int) -> Optional[Client]:
    """Get (or start) the user's session client."""
    if uid in USER_CLIENTS:
        return USER_CLIENTS[uid]
    enc_session = await db.get_session(uid)
    if not enc_session:
        return None
    try:
        ss = decrypt(enc_session)
        client = Client(
            f"ucli_{uid}",
            api_id=Telegram.API_ID,
            api_hash=Telegram.API_HASH,
            session_string=ss,
            in_memory=True,
            no_updates=True,
        )
        await client.start()
        # Refresh dialogs so private chats resolve
        async for _ in client.get_dialogs(limit=100):
            pass
        USER_CLIENTS[uid] = client
        return client
    except Exception as e:
        LOGGER.error(f"User client error for {uid}: {e}")
        return None


async def get_msg(ubot: Client, uclient: Optional[Client], chat_id, msg_id: int, link_type: str):
    """Fetch a message using the user's bot and/or session client, with fallbacks."""
    try:
        if link_type == "public":
            # Try with user bot first
            try:
                msg = await ubot.get_messages(chat_id, msg_id)
                if msg and not getattr(msg, "empty", False):
                    return msg
            except Exception:
                pass
            # Try with user session client
            if uclient:
                try:
                    msg = await uclient.get_messages(chat_id, msg_id)
                    if msg and not getattr(msg, "empty", False):
                        return msg
                except Exception:
                    pass
            return None
        else:
            # Private — must use user session client
            if not uclient:
                return None
            for cid in [chat_id, f"-{str(chat_id)[4:]}" if str(chat_id).startswith("-100") else chat_id]:
                try:
                    msg = await uclient.get_messages(cid, msg_id)
                    if msg and not getattr(msg, "empty", False):
                        return msg
                except Exception:
                    continue
            # Final fallback — refresh dialogs
            try:
                async for _ in uclient.get_dialogs(limit=200):
                    pass
                msg = await uclient.get_messages(chat_id, msg_id)
                if msg and not getattr(msg, "empty", False):
                    return msg
            except Exception:
                pass
            return None
    except Exception as e:
        LOGGER.error(f"get_msg error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# Progress callback
# ═══════════════════════════════════════════════════════════════════

def sanitize_filename(filename: str) -> str:
    return re.sub(r'[<>:"/\\|?*\']', "_", filename).strip(" .")[:255]


async def progress(current, total, bot, chat_id, msg_id, start_time):
    """Progress callback for downloads/uploads."""
    pct = current / total * 100
    interval = 10 if total >= 100 * 1024**2 else 20 if total >= 50 * 1024**2 else 30
    step = int(pct // interval) * interval
    if msg_id not in PROGRESS or PROGRESS[msg_id] != step or pct >= 100:
        PROGRESS[msg_id] = step
        c_mb = current / 1024**2
        t_mb = total / 1024**2
        bar = "🟢" * int(pct / 10) + "🔴" * (10 - int(pct / 10))
        elapsed = time.time() - start_time
        speed = current / elapsed / 1024**2 if elapsed > 0 else 0
        eta = time.strftime("%M:%S", time.gmtime((total - current) / (speed * 1024**2))) if speed > 0 else "00:00"
        try:
            await bot.edit_message_text(
                chat_id, msg_id,
                f"__**Processing...**__\n\n{bar}\n\n"
                f"⚡ **Completed**: {c_mb:.2f} MB / {t_mb:.2f} MB\n"
                f"📊 **Done**: {pct:.2f}%\n"
                f"🚀 **Speed**: {speed:.2f} MB/s\n"
                f"⏳ **ETA**: {eta}",
            )
        except Exception:
            pass
        if pct >= 100:
            PROGRESS.pop(msg_id, None)


# ═══════════════════════════════════════════════════════════════════
# Process a single fetched message → download + upload
# ═══════════════════════════════════════════════════════════════════

async def process_msg(bot_client, uclient, msg, dest_chat_id, link_type, uid, chat_ident):
    """Download a message and re-upload it to the destination chat."""
    try:
        settings = await db.get_settings(uid)
        cfg_chat = settings.get("chat_id")
        target_chat = int(dest_chat_id)
        reply_to = None

        if cfg_chat:
            if "/" in str(cfg_chat):
                parts = str(cfg_chat).split("/", 1)
                target_chat = int(parts[0])
                reply_to = int(parts[1]) if len(parts) > 1 else None
            else:
                target_chat = int(cfg_chat)

        if msg.media:
            # Build caption
            orig_caption = msg.caption or ""
            user_caption = settings.get("caption", "")
            # Apply word replacements & deletions
            processed = orig_caption
            for word, repl in settings.get("replacements", {}).items():
                processed = processed.replace(word, repl)
            for word in settings.get("delete_words", []):
                processed = processed.replace(word, "")
            final_text = f"{processed}\n\n{user_caption}" if processed and user_caption else user_caption or processed

            # Download
            start_time = time.time()
            prog_msg = await bot_client.send_message(int(dest_chat_id), "Downloading...")

            # Determine filename
            file_name = None
            if msg.video and msg.video.file_name:
                file_name = sanitize_filename(msg.video.file_name)
            elif msg.audio and msg.audio.file_name:
                file_name = sanitize_filename(msg.audio.file_name)
            elif msg.document and msg.document.file_name:
                file_name = sanitize_filename(msg.document.file_name)
            else:
                file_name = f"{time.time()}"

            try:
                downloaded = await uclient.download_media(
                    msg,
                    file_name=file_name,
                    progress=progress,
                    progress_args=(bot_client, int(dest_chat_id), prog_msg.id, start_time),
                )
            except FileReferenceExpired:
                # Re-fetch message to get a fresh file reference
                LOGGER.info(f"File reference expired for msg {msg.id}, re-fetching...")
                try:
                    msg = await uclient.get_messages(msg.chat.id, msg.id)
                except Exception:
                    try:
                        msg = await bot_client.get_messages(msg.chat.id, msg.id)
                    except Exception:
                        pass
                start_time = time.time()
                downloaded = await uclient.download_media(
                    msg,
                    file_name=file_name,
                    progress=progress,
                    progress_args=(bot_client, int(dest_chat_id), prog_msg.id, start_time),
                )

            if not downloaded:
                await prog_msg.edit_text("Failed to download.")
                return "Failed."

            # Rename with user settings (rename tag, delete/replace words)
            try:
                rename_tag = settings.get("rename_tag", "")
                if rename_tag:
                    base, ext = os.path.splitext(downloaded)
                    new_name = f"{os.path.basename(base)} {rename_tag}{ext}"
                    new_path = os.path.join(os.path.dirname(downloaded), sanitize_filename(new_name))
                    os.rename(downloaded, new_path)
                    downloaded = new_path
            except Exception as e:
                LOGGER.warning(f"Rename error: {e}")

            # Upload
            await prog_msg.edit_text("Uploading...")
            start_time = time.time()
            thumb = f"{uid}.jpg" if os.path.exists(f"{uid}.jpg") else None

            try:
                ext = os.path.splitext(downloaded)[1].lower()
                video_exts = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp"}
                audio_exts = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus"}

                if msg.video or (msg.document and ext in video_exts):
                    meta = await get_video_metadata(downloaded)
                    th = thumb or await generate_thumbnail(downloaded)
                    await bot_client.send_video(
                        target_chat, video=downloaded, caption=final_text,
                        thumb=th, width=meta["width"], height=meta["height"],
                        duration=meta["duration"],
                        progress=progress, progress_args=(bot_client, int(dest_chat_id), prog_msg.id, start_time),
                        reply_to_message_id=reply_to,
                    )
                elif msg.audio or (msg.document and ext in audio_exts):
                    await bot_client.send_audio(
                        target_chat, audio=downloaded, caption=final_text, thumb=thumb,
                        progress=progress, progress_args=(bot_client, int(dest_chat_id), prog_msg.id, start_time),
                        reply_to_message_id=reply_to,
                    )
                elif msg.photo:
                    await bot_client.send_photo(
                        target_chat, photo=downloaded, caption=final_text,
                        reply_to_message_id=reply_to,
                    )
                elif msg.sticker:
                    await bot_client.send_sticker(target_chat, msg.sticker.file_id, reply_to_message_id=reply_to)
                elif msg.video_note:
                    await bot_client.send_video_note(
                        target_chat, video_note=downloaded, reply_to_message_id=reply_to,
                    )
                elif msg.voice:
                    await bot_client.send_voice(
                        target_chat, downloaded, reply_to_message_id=reply_to,
                    )
                elif msg.document:
                    await bot_client.send_document(
                        target_chat, document=downloaded, caption=final_text, thumb=thumb,
                        progress=progress, progress_args=(bot_client, int(dest_chat_id), prog_msg.id, start_time),
                        reply_to_message_id=reply_to,
                    )
                else:
                    await bot_client.send_document(
                        target_chat, document=downloaded, caption=final_text,
                        reply_to_message_id=reply_to,
                    )
            except Exception as e:
                await prog_msg.edit_text(f"Upload failed: {str(e)[:30]}")
                if os.path.exists(downloaded):
                    os.remove(downloaded)
                return "Failed."

            if os.path.exists(downloaded):
                os.remove(downloaded)
            await prog_msg.delete()
            return "Done."

        elif msg.text:
            await bot_client.send_message(target_chat, text=msg.text, reply_to_message_id=reply_to)
            return "Sent."

    except Exception as e:
        LOGGER.error(f"process_msg error: {e}")
        return f"Error: {str(e)[:50]}"


# ═══════════════════════════════════════════════════════════════════
# /batch & /single — Conversational start
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command(["batch", "single"]) & filters.private)
async def batch_or_single_cmd(bot: Client, message: Message):
    """Start batch/single download flow (requires /setbot first)."""
    uid = message.from_user.id
    cmd = message.command[0]

    # Check freemium limit
    if Telegram.FREEMIUM_LIMIT == 0 and not await db.is_premium(uid):
        await message.reply_text("This bot does not provide free services. Get a subscription from the owner.")
        return

    # Check usage
    remaining = await db.get_remaining_limit(uid)
    if remaining == 0:
        await message.reply_text("❌ Daily limit reached. Try again tomorrow or upgrade to premium.")
        return

    status = await message.reply_text("Doing some checks, hold on...")

    if is_user_active(uid):
        await status.edit("You have an active task. Use /stop to cancel it.")
        return

    # Require /setbot
    ubot = await get_user_bot(uid)
    if not ubot:
        await status.edit("Add your bot with /setbot first.")
        return

    if cmd == "batch":
        CONV_STATE[uid] = {"step": "start"}
        await status.edit("Send the start link...")
    else:
        CONV_STATE[uid] = {"step": "start_single"}
        await status.edit("Send the link you want to process.")


# ═══════════════════════════════════════════════════════════════════
# /cancel & /stop — Cancel active batch
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command(["cancel", "stop"]) & filters.private)
async def cancel_batch(bot: Client, message: Message):
    """Cancel active batch or conversation."""
    uid = message.from_user.id

    # Don't handle cancel if user is in settings/login flow — let those plugins handle it
    step_info = get_user_step(uid)
    if step_info and step_info["step"].startswith("settings_"):
        return  # Let settings plugin handle it
    if step_info and step_info["step"].startswith("login_"):
        return  # Let login plugin handle it

    if is_user_active(uid):
        ok = await request_cancel(uid)
        if ok:
            await message.reply_text("Cancellation requested. Will stop after current download completes.")
        else:
            await message.reply_text("Failed to request cancellation.")
    elif uid in CONV_STATE:
        CONV_STATE.pop(uid, None)
        await message.reply_text("❌ Operation cancelled.")
    else:
        await message.reply_text("No active batch process found.")


# ═══════════════════════════════════════════════════════════════════
# Text handler — Conversational flow
# ═══════════════════════════════════════════════════════════════════

EXCLUDED_COMMANDS = [
    "start", "batch", "cancel", "login", "logout", "stop", "set",
    "pay", "plans", "single", "setbot", "rembot", "settings",
    "mystatus", "transfer", "broadcast", "botstats", "add", "rem",
    "users", "help", "dl", "adl", "ytdl",
]


@StreamBot.on_message(
    filters.text & filters.private
    & ~login_in_progress
    & ~settings_in_progress
    & ~filters.command(EXCLUDED_COMMANDS)
)
async def batch_text_handler(bot: Client, message: Message):
    """Handle batch/single conversation steps."""
    uid = message.from_user.id
    if uid not in CONV_STATE:
        return

    step = CONV_STATE[uid].get("step")
    ubot = await get_user_bot(uid)
    if not ubot:
        await message.reply("Add your bot with /setbot first.")
        CONV_STATE.pop(uid, None)
        return

    # ─── Step: Receive start link for /batch ───
    if step == "start":
        chat_id, msg_id, lt = parse_link(message.text)
        if not chat_id or not msg_id:
            await message.reply_text("Invalid link format.")
            CONV_STATE.pop(uid, None)
            return
        CONV_STATE[uid].update({"step": "count", "cid": chat_id, "sid": msg_id, "lt": lt})
        await message.reply_text("How many messages?")

    # ─── Step: Receive link for /single ───
    elif step == "start_single":
        chat_id, msg_id, lt = parse_link(message.text)
        if not chat_id or not msg_id:
            await message.reply_text("Invalid link format.")
            CONV_STATE.pop(uid, None)
            return

        status = await message.reply_text("Processing...")
        uclient = await get_user_client(uid)
        if not uclient:
            await status.edit("Cannot proceed without user session. Use /login first.")
            CONV_STATE.pop(uid, None)
            return

        try:
            msg = await get_msg(ubot, uclient, chat_id, msg_id, lt)
            if msg:
                res = await process_msg(ubot, uclient, msg, str(message.chat.id), lt, uid, chat_id)
                await status.edit(f"1/1: {res}")
                await db.increment_usage(uid)
            else:
                await status.edit("Message not found.")
        except Exception as e:
            await status.edit(f"Error: {str(e)[:50]}")
        finally:
            CONV_STATE.pop(uid, None)

    # ─── Step: Receive count for /batch ───
    elif step == "count":
        if not message.text.isdigit():
            await message.reply_text("Enter a valid number.")
            return

        count = int(message.text)
        is_prem = await db.is_premium(uid)
        max_limit = Telegram.PREMIUM_LIMIT if is_prem else Telegram.FREEMIUM_LIMIT

        if max_limit > 0 and count > max_limit:
            await message.reply_text(f"Maximum limit is {max_limit}.")
            return

        info = CONV_STATE[uid]
        chat_id = info["cid"]
        start_id = info["sid"]
        lt = info["lt"]
        success = 0

        status = await message.reply_text("Processing batch...")
        uclient = await get_user_client(uid)

        if not uclient:
            await status.edit("Missing user session. Use /login first.")
            CONV_STATE.pop(uid, None)
            return

        if is_user_active(uid):
            await status.edit("Active task exists.")
            CONV_STATE.pop(uid, None)
            return

        await add_active_batch(uid, {
            "total": count,
            "current": 0,
            "success": 0,
            "cancel_requested": False,
            "progress_message_id": status.id,
        })

        try:
            for j in range(count):
                if should_cancel(uid):
                    await status.edit(f"Cancelled at {j}/{count}. Success: {success}")
                    break

                await update_batch_progress(uid, j, success)
                mid = start_id + j

                try:
                    msg = await get_msg(ubot, uclient, chat_id, mid, lt)
                    if msg:
                        res = await process_msg(ubot, uclient, msg, str(message.chat.id), lt, uid, chat_id)
                        if "Done" in res or "Sent" in res:
                            success += 1
                            await db.increment_usage(uid)
                except Exception as e:
                    try:
                        await status.edit(f"{j+1}/{count}: Error - {str(e)[:30]}")
                    except Exception:
                        pass

                await asyncio.sleep(10)

            if j + 1 == count:
                await message.reply_text(f"Batch Completed ✅ Success: {success}/{count}")
        finally:
            await remove_active_batch(uid)
            CONV_STATE.pop(uid, None)
