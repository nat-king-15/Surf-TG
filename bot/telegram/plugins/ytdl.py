"""
YouTube/URL download plugin via yt-dlp.
Commands: /ytdl, /adl (audio-only download).
Supports YouTube, Instagram, Twitter, and other yt-dlp supported sites.
"""
import logging
import asyncio
import os
import time
from pyrogram import filters, Client
from pyrogram.types import Message
from pyrogram.enums.parse_mode import ParseMode

from bot.telegram import StreamBot
from bot.config import Telegram
from bot.helper.database import Database
from bot.utils.func import (
    progress_bar,
    human_readable_size,
    sanitize_filename,
)

LOGGER = logging.getLogger(__name__)
db = Database()

# Track active downloads
active_ytdl = {}


def _get_ydl_opts(user_id: int, audio_only: bool = False) -> dict:
    """Build yt-dlp options."""
    download_dir = f"downloads/ytdl/{user_id}"
    os.makedirs(download_dir, exist_ok=True)

    opts = {
        "outtmpl": f"{download_dir}/%(title)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": 2_000_000_000,  # 2GB
    }

    if audio_only:
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }],
        })
    else:
        opts["format"] = "best[filesize<=2G]/best"

    # Add cookies if configured
    if Telegram.YT_COOKIES and os.path.exists(Telegram.YT_COOKIES):
        opts["cookiefile"] = Telegram.YT_COOKIES

    return opts


async def _download_and_upload(bot: Client, message: Message, url: str, audio_only: bool = False):
    """Download a URL with yt-dlp and upload to Telegram."""
    user_id = message.from_user.id

    # Check usage limit
    remaining = await db.get_remaining_limit(user_id)
    if remaining == 0:
        await message.reply(
            "❌ **Daily limit reached!**\n"
            "Use /plans to upgrade to Premium."
        )
        return

    status_msg = await message.reply("⏳ Fetching video info...")

    try:
        import yt_dlp
    except ImportError:
        await status_msg.edit_text("❌ yt-dlp is not installed. Please install it: `pip install yt-dlp`")
        return

    opts = _get_ydl_opts(user_id, audio_only)
    file_path = None

    try:
        # Extract info first
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ydl.extract_info(url, download=False)
            )

        if not info:
            await status_msg.edit_text("❌ Could not fetch video info.")
            return

        title = info.get("title", "video")
        duration = info.get("duration", 0)
        filesize = info.get("filesize") or info.get("filesize_approx") or 0

        size_str = human_readable_size(filesize) if filesize else "Unknown"

        await status_msg.edit_text(
            f"📥 **Downloading...**\n\n"
            f"📄 {title[:50]}\n"
            f"💾 Size: {size_str}\n"
            f"⏱ Duration: {duration // 60}m {duration % 60}s"
        )

        # Download
        active_ytdl[user_id] = True

        def _do_download():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=True)

        result = await asyncio.get_event_loop().run_in_executor(None, _do_download)

        if not result:
            await status_msg.edit_text("❌ Download failed.")
            return

        # Find downloaded file
        ext = result.get("ext", "mp4")
        if audio_only:
            ext = "mp3"
        safe_title = sanitize_filename(result.get("title", "video"))
        download_dir = f"downloads/ytdl/{user_id}"

        # Find the actual downloaded file
        file_path = None
        for f in os.listdir(download_dir):
            fpath = os.path.join(download_dir, f)
            if os.path.isfile(fpath):
                file_path = fpath
                break

        if not file_path or not os.path.exists(file_path):
            await status_msg.edit_text("❌ Downloaded file not found.")
            return

        # Check file size
        actual_size = os.path.getsize(file_path)
        if actual_size > 2_000_000_000:
            await status_msg.edit_text("❌ File too large for Telegram (>2GB).")
            return

        await status_msg.edit_text(
            f"📤 **Uploading...**\n\n"
            f"📄 {safe_title}\n"
            f"💾 {human_readable_size(actual_size)}"
        )

        # Get settings for destination
        settings = await db.get_settings(user_id)
        target_chat = settings.get("chat_id") or user_id

        # Upload
        if audio_only:
            await bot.send_audio(
                chat_id=int(target_chat) if str(target_chat).lstrip("-").isdigit() else target_chat,
                audio=file_path,
                caption=f"🎵 **{safe_title}**",
                parse_mode=ParseMode.MARKDOWN,
                duration=duration,
                title=safe_title,
            )
        else:
            thumb = settings.get("thumbnail")
            await bot.send_video(
                chat_id=int(target_chat) if str(target_chat).lstrip("-").isdigit() else target_chat,
                video=file_path,
                caption=f"🎬 **{safe_title}**",
                parse_mode=ParseMode.MARKDOWN,
                duration=duration,
                thumb=thumb,
                supports_streaming=True,
            )

        await db.increment_usage(user_id)
        await status_msg.edit_text(f"✅ **Upload complete!**\n📄 {safe_title}")

    except Exception as e:
        LOGGER.error(f"ytdl error for {user_id}: {e}")
        await status_msg.edit_text(f"❌ Error: {str(e)[:200]}")

    finally:
        active_ytdl.pop(user_id, None)
        # Cleanup
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        # Clean download directory
        download_dir = f"downloads/ytdl/{user_id}"
        if os.path.exists(download_dir):
            for f in os.listdir(download_dir):
                try:
                    os.remove(os.path.join(download_dir, f))
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════
# /ytdl - Download video from URL
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("ytdl") & filters.private)
async def ytdl_command(bot: Client, message: Message):
    """Download a video from URL using yt-dlp."""
    user_id = message.from_user.id

    if user_id in active_ytdl:
        await message.reply("⚠️ You already have an active download. Please wait.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "🎬 **Video Download**\n\n"
            "Usage: `/ytdl <url>`\n\n"
            "Supported: YouTube, Instagram, Twitter, and 1000+ sites.\n"
            "Example: `/ytdl https://www.youtube.com/watch?v=dQw4w9WgXcQ`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = args[1].strip()
    await _download_and_upload(bot, message, url, audio_only=False)


# ═══════════════════════════════════════════════════════════════════
# /adl - Download audio from URL
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("adl") & filters.private)
async def adl_command(bot: Client, message: Message):
    """Download audio from URL using yt-dlp (extracts to mp3)."""
    user_id = message.from_user.id

    if user_id in active_ytdl:
        await message.reply("⚠️ You already have an active download. Please wait.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "🎵 **Audio Download**\n\n"
            "Usage: `/adl <url>`\n\n"
            "Downloads audio as MP3 (320kbps).\n"
            "Example: `/adl https://www.youtube.com/watch?v=dQw4w9WgXcQ`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = args[1].strip()
    await _download_and_upload(bot, message, url, audio_only=True)
