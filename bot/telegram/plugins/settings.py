from pyrogram import filters, Client, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from bot.telegram import StreamBot
from bot.helper.database import Database
import os
import asyncio

db = Database()

# Conversation states
conversations = {}

MESS = 'Customize settings for your files...'

# Utility to get buttons
def get_settings_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('📝 Set Chat ID', callback_data='setchat'),
            InlineKeyboardButton('🏷️ Set Rename Tag', callback_data='setrename')
        ],
        [
            InlineKeyboardButton('📋 Set Caption', callback_data='setcaption'),
            InlineKeyboardButton('🔄 Replace Words', callback_data='setreplacement')
        ],
        [
            InlineKeyboardButton('🗑️ Remove Words', callback_data='delete'),
            InlineKeyboardButton('🔄 Reset Settings', callback_data='reset')
        ],
        [
            InlineKeyboardButton('🔑 Session Login', callback_data='login_callback'), # Redirects to /login logic or prompts
            InlineKeyboardButton('🚪 Logout', callback_data='logout_callback')
        ],
        [
            InlineKeyboardButton('🖼️ Set Thumbnail', callback_data='setthumb'),
            InlineKeyboardButton('❌ Remove Thumbnail', callback_data='remthumb')
        ],
        [
            InlineKeyboardButton('❌ Close', callback_data='close')
        ]
    ])

@StreamBot.on_message(filters.command('settings'))
async def settings_command(client, message: Message):
    await message.reply(MESS, reply_markup=get_settings_buttons())

@StreamBot.on_callback_query()
async def callback_query_handler(client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data
    
    if data == 'close':
        await query.message.delete()
        return

    if data == 'login_callback':
        await query.answer("Use /login command to login.")
        return

    if data == 'logout_callback':
        if await db.remove_user_session(user_id):
            await query.answer("Logged out successfully.", show_alert=True)
        else:
            await query.answer("You are not logged in.", show_alert=True)
        return

    if data == 'reset':
        try:
            await db.delete_user_data_key(user_id, 'delete_words')
            await db.delete_user_data_key(user_id, 'replacement_words')
            await db.delete_user_data_key(user_id, 'rename_tag')
            await db.delete_user_data_key(user_id, 'caption')
            await db.delete_user_data_key(user_id, 'chat_id')
            
            thumbnail_path = f'{user_id}.jpg'
            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
            
            await query.answer("Settings reset successfully!", show_alert=True)
        except Exception as e:
            await query.answer(f"Error: {e}", show_alert=True)
        return

    if data == 'remthumb':
        thumbnail_path = f'{user_id}.jpg'
        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)
            await query.answer("Thumbnail removed!", show_alert=True)
        else:
            await query.answer("No thumbnail found.", show_alert=True)
        return

    # Handle conversation start
    prompts = {
        'setchat': "Send me the ID of that chat (with -100 prefix).\n\nIf you want to upload in topic group, pass: -100CHANNELID/TOPIC_ID",
        'setrename': "Send me the rename tag:",
        'setcaption': "Send me the caption:",
        'setreplacement': "Send me the replacement words in the format: 'WORD(s)' 'REPLACEWORD'",
        'delete': "Send words separated by space to delete them from caption/filename...",
        'setthumb': "Please send the photo you want to set as the thumbnail."
    }

    if data in prompts:
        conversations[user_id] = {'type': data}
        await query.message.reply(
            f"{prompts[data]}\n\n(Send /cancel to cancel)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="cancel_conv")]])
        )
        await query.answer()

@StreamBot.on_callback_query(filters.regex("cancel_conv"))
async def cancel_conv_callback(client, query: CallbackQuery):
    user_id = query.from_user.id
    if user_id in conversations:
        del conversations[user_id]
    await query.message.edit("Cancelled.")

@StreamBot.on_message(filters.command('cancel'))
async def cancel_command(client, message: Message):
    user_id = message.from_user.id
    if user_id in conversations:
        del conversations[user_id]
        await message.reply("Cancelled.")

@StreamBot.on_message(filters.private & ~filters.command(['settings', 'login', 'logout', 'cancel']))
async def handle_conversation_input(client, message: Message):
    user_id = message.from_user.id
    if user_id not in conversations:
        return

    conv_type = conversations[user_id]['type']
    
    try:
        if conv_type == 'setchat':
            chat_id = message.text.strip()
            await db.save_user_data(user_id, 'chat_id', chat_id)
            await message.reply("✅ Chat ID set successfully!")
            
        elif conv_type == 'setrename':
            rename_tag = message.text.strip()
            await db.save_user_data(user_id, 'rename_tag', rename_tag)
            await message.reply(f"✅ Rename tag set to: {rename_tag}")
            
        elif conv_type == 'setcaption':
            caption = message.text.strip() # Don't strip if they want spaces? Pyrogram strips by default? No.
            await db.save_user_data(user_id, 'caption', caption)
            await message.reply("✅ Caption set successfully!")
            
        elif conv_type == 'setreplacement':
            import re
            match = re.match(r"'(.+)' '(.+)'", message.text)
            if not match:
                await message.reply("❌ Invalid format. Usage: 'WORD(s)' 'REPLACEWORD'")
            else:
                word, replace_word = match.groups()
                delete_words = await db.get_user_data_key(user_id, 'delete_words', [])
                if word in delete_words:
                    await message.reply(f"❌ '{word}' is in delete list.")
                else:
                    replacements = await db.get_user_data_key(user_id, 'replacement_words', {})
                    replacements[word] = replace_word
                    await db.save_user_data(user_id, 'replacement_words', replacements)
                    await message.reply(f"✅ Replacement saved: '{word}' -> '{replace_word}'")

        elif conv_type == 'delete':
            words = message.text.split()
            delete_words = await db.get_user_data_key(user_id, 'delete_words', [])
            delete_words = list(set(delete_words + words))
            await db.save_user_data(user_id, 'delete_words', delete_words)
            await message.reply(f"✅ Words added to delete list: {', '.join(words)}")

        elif conv_type == 'setthumb':
            if message.photo:
                path = await message.download(file_name=f"{user_id}.jpg")
                await message.reply("✅ Thumbnail saved successfully!")
            else:
                await message.reply("❌ Please send a photo.")
                return # Don't delete conversation so they can try again? Or cancel?
                
    except Exception as e:
        await message.reply(f"Error: {e}")
    
    if user_id in conversations:
        del conversations[user_id]
