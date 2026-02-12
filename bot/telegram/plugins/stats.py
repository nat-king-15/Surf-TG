import time
from pyrogram import Client, filters
from pyrogram.types import Message
from bot.telegram import StreamBot
from bot.helper.database import Database
from bot.config import Telegram
import shutil
import psutil

db = Database()

@StreamBot.on_message(filters.command('stats') & filters.user(Telegram.OWNER_ID))
async def stats_command(client, message: Message):
    users_count = await db.db.users.count_documents({})
    premium_count = await db.db.premium_users.count_documents({})
    
    # System Stats
    total, used, free = shutil.disk_usage(".")
    total = get_readable_file_size(total)
    used = get_readable_file_size(used)
    free = get_readable_file_size(free)
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    
    await message.reply(
        f"**Bot Statistics**\n\n"
        f"**Users:** {users_count}\n"
        f"**Premium Users:** {premium_count}\n\n"
        f"**Disk Total:** {total}\n"
        f"**Disk Used:** {used}\n"
        f"**Disk Free:** {free}\n"
        f"**CPU:** {cpu}%\n"
        f"**RAM:** {ram}%"
    )

def get_readable_file_size(size_in_bytes) -> str:
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    try:
        return f'{round(size_in_bytes, 2)}{["B", "KB", "MB", "GB", "TB", "PB"][index]}'
    except IndexError:
        return "File too large"
