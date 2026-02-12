from pyrogram import Client, filters
from pyrogram.types import Message
from bot.telegram import StreamBot
from bot.helper.database import Database
from bot.config import Telegram
import asyncio

db = Database()

from bot.helper.custom_filters import set_user_step, get_user_step

# Login states
STEP_PHONE = 1
STEP_CODE = 2
STEP_PASSWORD = 3

login_cache = {}

@StreamBot.on_message(filters.command('login'))
async def login_command(client, message: Message):
    user_id = message.from_user.id
    
    # Check if already logged in
    existing_session = await db.get_user_session(user_id)
    if existing_session:
        return await message.reply("You are already logged in.\nUse /logout to remove your session.")

    login_cache[user_id] = {'step': STEP_PHONE}
    set_user_step(user_id, STEP_PHONE)
    await message.reply(
        "Please send your phone number with country code\nExample: `+12345678900`"
    )

@StreamBot.on_message(filters.command('logout'))
async def logout_command(client, message: Message):
    user_id = message.from_user.id
    if await db.remove_user_session(user_id):
        set_user_step(user_id, None)
        await message.reply("Logged out successfully.")
    else:
        await message.reply("You are not logged in.")

@StreamBot.on_message(filters.private & filters.text & ~filters.command('login') & ~filters.command('logout'))
async def handle_login_steps(client, message: Message):
    user_id = message.from_user.id
    if user_id not in login_cache:
        return

    step = login_cache[user_id].get('step')
    
    try:
        if step == STEP_PHONE:
            phone_number = message.text.strip()
            # Create a temporary client to generate session string
            temp_client = Client(
                f"temp_{user_id}",
                api_id=Telegram.API_ID,
                api_hash=Telegram.API_HASH,
                phone_number=phone_number,
                in_memory=True
            )
            await temp_client.connect()
            
            try:
                sent_code = await temp_client.send_code(phone_number)
                login_cache[user_id]['client'] = temp_client
                login_cache[user_id]['phone_hash'] = sent_code.phone_code_hash
                login_cache[user_id]['phone_number'] = phone_number
                login_cache[user_id]['step'] = STEP_CODE
                
                await message.reply(
                    "Code sent to your Telegram account.\n\n"
                    "Format: `1 2 3 4 5` (Space between numbers)\n"
                    "Please send the code:"
                )
            except Exception as e:
                await temp_client.disconnect()
                del login_cache[user_id]
                await message.reply(f"Error sending code: {e}")

        elif step == STEP_CODE:
            code = message.text.replace(" ", "")
            temp_client = login_cache[user_id]['client']
            phone_hash = login_cache[user_id]['phone_hash']
            phone_number = login_cache[user_id]['phone_number']
            
            try:
                await temp_client.sign_in(phone_number, phone_hash, code)
                session_string = await temp_client.export_session_string()
                await db.save_user_session(user_id, session_string)
                await temp_client.disconnect()
                del login_cache[user_id]
                set_user_step(user_id, None)
                await message.reply("Login successful! Session saved.")
            except Exception as e:
                if "PASSWORD_REQUIRED" in str(e):
                    login_cache[user_id]['step'] = STEP_PASSWORD
                    set_user_step(user_id, STEP_PASSWORD)
                    await message.reply("Two-step verification enabled.\nPlease send your password:")
                else:
                    await temp_client.disconnect()
                    del login_cache[user_id]
                    set_user_step(user_id, None)
                    await message.reply(f"Error signing in: {e}")

        elif step == STEP_PASSWORD:
            password = message.text
            temp_client = login_cache[user_id]['client']
            
            try:
                await temp_client.check_password(password)
                session_string = await temp_client.export_session_string()
                await db.save_user_session(user_id, session_string)
                await temp_client.disconnect()
                del login_cache[user_id]
                set_user_step(user_id, None)
                await message.reply("Login successful! Session saved.")
            except Exception as e:
                await temp_client.disconnect()
                del login_cache[user_id]
                set_user_step(user_id, None)
                await message.reply(f"Error checking password: {e}")

    except Exception as e:
        if user_id in login_cache and 'client' in login_cache[user_id]:
            await login_cache[user_id]['client'].disconnect()
        del login_cache[user_id]
        set_user_step(user_id, None)
        await message.reply(f"An unexpected error occurred: {e}")
