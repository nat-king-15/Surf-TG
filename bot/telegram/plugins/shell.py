import asyncio
import os
import time
from bot.telegram import StreamBot
from bot.config import Telegram
from pyrogram import filters
from pyrogram.types import Message

# Get authorized users (Owner + Sudo)
def get_authorized_users():
    users = {Telegram.OWNER_ID}
    if Telegram.SUDO_USERS:
        users.update(Telegram.SUDO_USERS)
    return users

@StreamBot.on_message(filters.command(["sh", "shell", "bash"]))
async def shell_command(client, message: Message):
    if message.from_user.id not in get_authorized_users():
        return

    if len(message.command) < 2:
        return await message.reply("Give a command to run.")

    cmd = message.text.split(maxsplit=1)[1]
    
    start_time = time.time()
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    end_time = time.time()
    
    stdout = stdout.decode().strip()
    stderr = stderr.decode().strip()
    
    output = ""
    if stdout:
        output += f"**Output:**\n`{stdout}`\n"
    if stderr:
        output += f"**Error:**\n`{stderr}`\n"
        
    if not output:
        output = "**No Output**"
        
    if len(output) > 4090:
        with open("output.txt", "w", encoding="utf-8") as f:
            f.write(output)
        await message.reply_document(
            document="output.txt",
            caption=f"**Command:** `{cmd}`\n**Time:** `{round(end_time - start_time, 3)}s`",
            quote=True
        )
        os.remove("output.txt")
    else:
        await message.reply(
            f"**Command:** `{cmd}`\n**Time:** `{round(end_time - start_time, 3)}s`\n\n{output}",
            quote=True
        )
