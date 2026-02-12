import os
import time
import asyncio
import logging
import tempfile
import yt_dlp
import yt_dlp
import aiofiles
from pyrogram import Client, filters
from pyrogram.types import Message
from bot.telegram import StreamBot
from bot.config import Telegram
from bot.helper.func import get_video_metadata, screenshot
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, COMM, APIC

logger = logging.getLogger(__name__)

ongoing_downloads = {}

def get_readable_time(seconds: int) -> str:
    count = 0
    ping_time = ""
    time_list = []
    time_suffix_list = ["s", "m", "h", "days"]
    while count < 4:
        count += 1
        remainder, result = divmod(seconds, 60) if count < 3 else divmod(seconds, 24)
        if seconds == 0 and remainder == 0:
            break
        time_list.append(int(result))
        seconds = int(remainder)
    for x in range(len(time_list)):
        time_list[x] = str(time_list[x]) + time_suffix_list[x]
    if len(time_list) == 4:
        ping_time += time_list.pop() + ", "
    time_list.reverse()
    ping_time += ":".join(time_list)
    return ping_time

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

async def progress_bar(current, total, status_msg, start):
    now = time.time()
    diff = now - start
    if round(diff % 5.00) == 0 or current == total:
        speed = current / diff
        percentage = current * 100 / total
        time_to_completion = round((total - current) / speed) * 1000
        time_to_completion = get_readable_time(time_to_completion / 1000)
        speed = get_readable_file_size(speed) + "/s"
        uploaded = f"{get_readable_file_size(current)}/{get_readable_file_size(total)}"
        pass_str = "●" * int(percentage / 5) + "○" * (20 - int(percentage / 5))
        
        try:
            await status_msg.edit(
                f"**{status_msg.text.splitlines()[0]}**\n"
                f"[{pass_str}] {round(percentage, 2)}%\n\n"
                f"**Speed:** {speed}\n"
                f"**Done:** {uploaded}\n"
                f"**ETA:** {time_to_completion}"
            )
        except:
            pass

async def download_thumbnail(url, path):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                with open(path, 'wb') as f:
                    f.write(await response.read())
    return path

@StreamBot.on_message(filters.command(['dl', 'adl']))
async def ytdl_command(client, message: Message):
    user_id = message.from_user.id
    if user_id in ongoing_downloads:
        await message.reply("You already have an ongoing download.")
        return

    if len(message.command) < 2:
        await message.reply(f"Usage: /{message.command[0]} <link>")
        return

    url = message.command[1]
    is_audio = message.command[0] == 'adl'
    ongoing_downloads[user_id] = True

    status_msg = await message.reply("Downloading...")
    
    try:
        ydl_opts = {
            'format': 'bestaudio/best' if is_audio else 'best',
            'outtmpl': f'downloads/{user_id}_%(title)s.%(ext)s',
            'cookiefile': 'cookies.txt' if Telegram.YT_COOKIES else None, # Needs handling of cookies str to file
            'quiet': True,
        }
        
        # Handle Cookies
        cookie_file = None
        if Telegram.YT_COOKIES:
             with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
                 f.write(Telegram.YT_COOKIES)
                 cookie_file = f.name
                 ydl_opts['cookiefile'] = cookie_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=True)
            filename = ydl.prepare_filename(info)
            if is_audio:
                # rename to mp3 if needed or check ext
                base, ext = os.path.splitext(filename)
                if ext != '.mp3':
                    # yt-dlp might have merged/converted, checking file existence
                    # For simplicity, if bestaudio is not mp3, we might want postprocessors.
                    # But let's assume yt-dlp logic handles it or we upload as is.
                    pass
        
        if not os.path.exists(filename):
            await status_msg.edit("Download failed.")
            return

        await status_msg.edit("Uploading...")
        start_time = time.time()
        
        if is_audio:
            await client.send_audio(
                message.chat.id,
                filename,
                caption=info.get('title', 'Audio'),
                progress=progress_bar,
                progress_args=(status_msg, start_time)
            )
        else:
            # Video Metadata
            metadata = await get_video_metadata(filename)
            duration = metadata['duration']
            width = metadata['width']
            height = metadata['height']
            thumb = await screenshot(filename, duration, str(user_id))

            await client.send_video(
                message.chat.id,
                filename,
                caption=info.get('title', 'Video'),
                duration=duration,
                width=width,
                height=height,
                thumb=thumb,
                progress=progress_bar,
                progress_args=(status_msg, start_time)
            )
            
            if thumb and os.path.exists(thumb):
                os.remove(thumb)

        await status_msg.delete()
        if os.path.exists(filename):
            os.remove(filename)
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)

    except Exception as e:
        await status_msg.edit(f"Error: {e}")
        logger.error(f"YTDL Error: {e}")
    finally:
        if user_id in ongoing_downloads:
            del ongoing_downloads[user_id]
