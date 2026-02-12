import os
import re
import time
import asyncio
import json
import logging
from typing import Dict, Any, Optional

from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pyrogram.errors import UserNotParticipant, FloodWait

from bot.config import Telegram
from bot.telegram import StreamBot
from bot.helper.database import Database
from bot.helper.func import (
    get_user_data_key, process_text_with_rules, is_premium_user, E,
    screenshot, thumbnail, get_video_metadata, rename_file, sanitize_filename,
    subscribe
)
from bot.helper.encrypt import dcs
from bot.helper.custom_filters import login_in_progress

db = Database()
logger = logging.getLogger(__name__)

# Active Users Management
ACTIVE_USERS = {}
ACTIVE_USERS_FILE = "active_users.json"
UB: Dict[int, Client] = {} # User Bots
UC: Dict[int, Client] = {} # User Clients

# Constants
FREEMIUM_LIMIT = Telegram.FREEMIUM_LIMIT
PREMIUM_LIMIT = Telegram.PREMIUM_LIMIT
API_ID = Telegram.API_ID
API_HASH = Telegram.API_HASH
LOG_GROUP = Telegram.LOG_GROUP

# States
Z = {} 

def load_active_users():
    try:
        if os.path.exists(ACTIVE_USERS_FILE):
            with open(ACTIVE_USERS_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception:
        return {}

async def save_active_users_to_file():
    try:
        with open(ACTIVE_USERS_FILE, 'w') as f:
            json.dump(ACTIVE_USERS, f)
    except Exception as e:
        logger.error(f"Error saving active users: {e}")

async def add_active_batch(user_id: int, batch_info: Dict[str, Any]):
    ACTIVE_USERS[str(user_id)] = batch_info
    await save_active_users_to_file()

def is_user_active(user_id: int) -> bool:
    return str(user_id) in ACTIVE_USERS

async def update_batch_progress(user_id: int, current: int, success: int):
    if str(user_id) in ACTIVE_USERS:
        ACTIVE_USERS[str(user_id)]["current"] = current
        ACTIVE_USERS[str(user_id)]["success"] = success
        await save_active_users_to_file()

async def request_batch_cancel(user_id: int):
    if str(user_id) in ACTIVE_USERS:
        ACTIVE_USERS[str(user_id)]["cancel_requested"] = True
        await save_active_users_to_file()
        return True
    return False

def should_cancel(user_id: int) -> bool:
    user_str = str(user_id)
    return user_str in ACTIVE_USERS and ACTIVE_USERS[user_str].get("cancel_requested", False)

async def remove_active_batch(user_id: int):
    if str(user_id) in ACTIVE_USERS:
        del ACTIVE_USERS[str(user_id)]
        await save_active_users_to_file()

ACTIVE_USERS = load_active_users()

# Client Helpers
async def get_ubot(uid):
    bt = await db.get_user_data_key(uid, "bot_token", None)
    if not bt: return None
    if uid in UB: return UB.get(uid)
    try:
        # Using a new session for each user's bot
        bot = Client(f"user_bot_{uid}", bot_token=bt, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await bot.start()
        UB[uid] = bot
        return bot
    except Exception as e:
        logger.error(f"Error starting bot for user {uid}: {e}")
        return None

async def get_uclient(uid):
    session_string = await db.get_user_session(uid)
    if not session_string: return None
    if uid in UC: return UC.get(uid)
    try:
        # Decrypt session string if needed, or assume handled by db getter if we stored it raw
        # Assuming database stores RAW session string for now as logic in login.py saves raw
        # But if source encrypted it, we might need to decrypt.
        # login.py saves: await temp_client.export_session_string() -> Clean string.
        # But if using migrated data, it relies on dcs.
        # Let's try dcs(session_string) if retrieval fails or just blindly use it.
        # In my login.py I saved raw string.
        
        # NOTE: dcs is for decrypting if we encrypted it.
        # I'll implement a check.
        try:
             ss = dcs(session_string)
        except:
             ss = session_string

        client = Client(f"user_client_{uid}", session_string=ss, api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await client.start()
        UC[uid] = client
        return client
    except Exception as e:
        logger.error(f"Error starting user client for {uid}: {e}")
        return None

# Progress Bar
async def progress_bar(current, total, status_msg, start):
    now = time.time()
    diff = now - start
    if round(diff % 5.00) == 0 or current == total:
        speed = current / diff
        percentage = current * 100 / total
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        
        pass_str = "●" * int(percentage / 5) + "○" * (20 - int(percentage / 5))
        
        try:
            await status_msg.edit(
                f"**Downloading...**\n"
                f"[{pass_str}] {round(percentage, 2)}%\n"
            )
        except:
            pass

# Message Processing
async def get_msg(bot_client, user_client, chat_id, message_id, link_type):
    try:
        if link_type == 'public':
            return await bot_client.get_messages(chat_id, message_id)
        else:
            if user_client:
                 return await user_client.get_messages(chat_id, message_id)
            return None
    except Exception as e:
        logger.error(f"Error fetching message: {e}")
        return None

async def process_msg(bot_client, user_client, message, dest_chat_id, link_type, user_id, chat_id):
    try:
        # Processing Logic
        # 1. Download
        status_msg = await bot_client.send_message(dest_chat_id, "Downloading...")
        start_time = time.time()
        
        file_path = await message.download(
            progress=progress_bar,
            progress_args=(status_msg, start_time)
        )
        
        if not file_path:
            await status_msg.edit("Download failed.")
            return "Failed"
            
        await status_msg.edit("Renaming...")
        renamed_file = await rename_file(file_path, user_id)
        
        await status_msg.edit("Uploading...")
        
        # Upload
        caption = message.caption or ""
        # Apply caption rules
        caption = await process_text_with_rules(user_id, caption)
        user_caption = await db.get_user_data_key(user_id, 'caption', '')
        if user_caption:
            caption = f"{caption}\n\n{user_caption}"

        md = await get_video_metadata(renamed_file)
        thumb = await screenshot(renamed_file, md['duration'], str(user_id))
        
        if renamed_file.endswith(('.mp4', '.mkv', '.avi')):
             await bot_client.send_video(
                 dest_chat_id,
                 renamed_file,
                 caption=caption,
                 duration=md['duration'],
                 width=md['width'],
                 height=md['height'],
                 thumb=thumb
             )
        elif renamed_file.endswith(('.mp3', '.flac')):
             await bot_client.send_audio(
                 dest_chat_id,
                 renamed_file,
                 caption=caption,
                 thumb=thumb
             )
        else:
             await bot_client.send_document(
                 dest_chat_id,
                 renamed_file,
                 caption=caption,
                 thumb=thumb
             )

        await status_msg.delete()
        if os.path.exists(renamed_file):
            os.remove(renamed_file)
        if thumb and os.path.exists(thumb):
            os.remove(thumb)
            
        return "Done"
        
    except Exception as e:
        logger.error(f"Processing Error: {e}")
        return f"Error: {e}"

# Handlers
@StreamBot.on_message(filters.command(['batch', 'single']))
async def batch_command(client, message: Message):
    uid = message.from_user.id
    cmd = message.command[0]

    if Telegram.FREEMIUM_LIMIT == 0 and not await db.is_premium_user(uid):
        await message.reply("This bot is for Premium users only.")
        return

    if is_user_active(uid):
        await message.reply("You have an active task. Use /cancel to stop it.")
        return
        
    ubot = await get_ubot(uid)
    if not ubot:
        await message.reply("Please set your bot token using /settings -> Session Login (or implement /setbot)")
        return
        
    Z[uid] = {'step': 'start' if cmd == 'batch' else 'start_single'}
    await message.reply(f'Send {"start link..." if cmd == "batch" else "link to process"}.')

@StreamBot.on_message(filters.command('cancel'))
async def cancel_command(client, message: Message):
    uid = message.from_user.id
    if is_user_active(uid):
        await request_batch_cancel(uid)
        await message.reply("Cancellation requested.")
    else:
        await message.reply("No active task.")

@StreamBot.on_message(filters.private & filters.text & ~filters.command(['batch', 'single', 'cancel', 'login', 'logout', 'settings', 'dl', 'adl']) & ~login_in_progress)
async def batch_text_handler(client, message: Message):
    uid = message.from_user.id
    if uid not in Z: return
    
    state = Z[uid]
    step = state.get('step')
    
    if step == 'start' or step == 'start_single':
        link = message.text
        chat_id_str, message_id, link_type = E(link)
        
        if not chat_id_str or not message_id:
            await message.reply("Invalid link.")
            del Z[uid]
            return
            
        state.update({'cid': chat_id_str, 'mid': message_id, 'lt': link_type})
        
        if step == 'start':
            state['step'] = 'count'
            await message.reply("How many messages?")
        else:
            # Single Process
            await message.reply("Processing single link...")
            ubot = await get_ubot(uid)
            uclient = await get_uclient(uid)
            
            if not uclient:
                 await message.reply("User session required for restricted content. Login via /login.")
                 del Z[uid]
                 return
                 
            try:
                msg = await get_msg(ubot, uclient, chat_id_str, message_id, link_type)
                if msg:
                     await process_msg(client, uclient, msg, message.chat.id, link_type, uid, chat_id_str)
                     await message.reply("Done.")
                else:
                     await message.reply("Message not found or inaccessible.")
            except Exception as e:
                await message.reply(f"Error: {e}")
            finally:
                del Z[uid]

    elif step == 'count':
        if not message.text.isdigit():
            await message.reply("Please enter a number.")
            return
            
        count = int(message.text)
        max_limit = Telegram.PREMIUM_LIMIT if await db.is_premium_user(uid) else Telegram.FREEMIUM_LIMIT
        
        if count > max_limit:
            await message.reply(f"Limit is {max_limit}.")
            return
            
        await message.reply("Starting batch...")
        
        ubot = await get_ubot(uid)
        uclient = await get_uclient(uid)
        
        if not uclient:
             await message.reply("User session required. Login via /login.")
             del Z[uid]
             return
             
        initial_mid = state['mid']
        chat_id_str = state['cid']
        link_type = state['lt']
        
        success = 0
        await add_active_batch(uid, {"total": count, "current": 0, "success": 0})
        
        try:
            for i in range(count):
                if should_cancel(uid):
                    await message.reply("Batch cancelled.")
                    break
                
                mid = initial_mid + i
                try:
                    msg = await get_msg(ubot, uclient, chat_id_str, mid, link_type)
                    if msg:
                        res = await process_msg(client, uclient, msg, message.chat.id, link_type, uid, chat_id_str)
                        if res == "Done":
                            success += 1
                except Exception as e:
                    logger.error(f"Batch error at {mid}: {e}")
                
                await update_batch_progress(uid, i + 1, success)
                await asyncio.sleep(3) # Avoid FloodWait
            
            await message.reply(f"Batch completed. Success: {success}/{count}")
            
        finally:
            await remove_active_batch(uid)
            del Z[uid]
