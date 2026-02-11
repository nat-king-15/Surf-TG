import logging
import time
import asyncio
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
from bot.telegram import UserBot
from bot.config import Telegram

LOGGER = logging.getLogger(__name__)

# Global PyTgCalls instance
call = PyTgCalls(UserBot)
_started = False

# Track active streams: {chat_id: {url, title, start_time, seek_offset, paused, ...}}
active_streams = {}

# Cache invite links: {chat_id: invite_link}
_invite_cache = {}

# Auto-refresh tasks: {chat_id: asyncio.Task}
_refresh_tasks = {}


async def ensure_started():
    """Start PyTgCalls if not already started."""
    global _started
    if not _started:
        await call.start()
        _started = True
        LOGGER.info("PyTgCalls started")


async def get_vc_invite_link(chat_id: int) -> str:
    """Get or create invite link for the VC channel."""
    chat_id = int(chat_id)
    if chat_id in _invite_cache:
        return _invite_cache[chat_id]
    
    try:
        link = await UserBot.export_chat_invite_link(chat_id)
        _invite_cache[chat_id] = link
        return link
    except Exception as e:
        LOGGER.warning(f"Could not get invite link via UserBot: {e}")
    
    try:
        from bot.telegram import StreamBot
        link = await StreamBot.export_chat_invite_link(chat_id)
        _invite_cache[chat_id] = link
        return link
    except Exception as e:
        LOGGER.warning(f"Could not get invite link via Bot: {e}")
    
    clean = str(chat_id).replace("-100", "")
    return f"https://t.me/c/{clean}"


async def start_vc_stream(chat_id: int, stream_url: str, title: str = "",
                          seek_seconds: int = 0, msg_id: str = "", src_chat_id: str = "",
                          folder_id: str = "root", file_hash: str = ""):
    """Start streaming a media file in the voice chat."""
    await ensure_started()
    
    try:
        LOGGER.info(f"Starting VC stream in {chat_id}: {title} (seek: {seek_seconds}s)")
        
        ffmpeg_params = f"-ss {seek_seconds}" if seek_seconds > 0 else None
        stream = MediaStream(stream_url, ffmpeg_parameters=ffmpeg_params)
        
        await call.play(int(chat_id), stream)
        
        # Detect duration in background
        duration = await get_media_duration(stream_url)
        
        active_streams[int(chat_id)] = {
            "url": stream_url,
            "title": title,
            "start_time": time.time(),
            "seek_offset": seek_seconds,
            "paused": False,
            "pause_time": 0,
            "msg_id": msg_id,
            "src_chat_id": src_chat_id,
            "folder_id": folder_id,
            "file_hash": file_hash,
            "duration": duration,
        }
        
        return True, "Stream started"
    except Exception as e:
        error_msg = str(e)
        LOGGER.error(f"VC stream error: {error_msg}")
        if "GROUPCALL_NOT_FOUND" in error_msg or "not found" in error_msg.lower():
            return False, "Voice chat not active! Start a VC in the channel first."
        return False, f"Error: {error_msg}"


async def stop_vc_stream(chat_id: int):
    """Stop the current VC stream and leave the voice chat."""
    try:
        stop_auto_refresh(int(chat_id))
        await call.leave_call(int(chat_id))
        info = active_streams.pop(int(chat_id), None)
        LOGGER.info(f"VC stream stopped in {chat_id}")
        return True, "Stream stopped", info
    except Exception as e:
        info = active_streams.pop(int(chat_id), None)
        return False, f"Error: {str(e)}", info


async def pause_vc_stream(chat_id: int):
    """Pause the current VC stream."""
    try:
        # pytgcalls v2 uses call.pause() not call.pause_stream()
        await call.pause(int(chat_id))
        info = active_streams.get(int(chat_id))
        if info:
            info["paused"] = True
            info["pause_time"] = time.time()
        return True, "Stream paused"
    except Exception as e:
        return False, f"Error: {str(e)}"


async def resume_vc_stream(chat_id: int):
    """Resume the current VC stream."""
    try:
        # pytgcalls v2 uses call.resume() not call.resume_stream()
        await call.resume(int(chat_id))
        info = active_streams.get(int(chat_id))
        if info:
            if info["pause_time"] > 0:
                pause_duration = time.time() - info["pause_time"]
                info["start_time"] += pause_duration
            info["paused"] = False
            info["pause_time"] = 0
        return True, "Stream resumed"
    except Exception as e:
        return False, f"Error: {str(e)}"


async def seek_vc_stream(chat_id: int, offset_seconds: int):
    """Seek by restarting the stream with new ffmpeg offset."""
    chat_id = int(chat_id)
    info = active_streams.get(chat_id)
    if not info:
        return False, "No active stream to seek"
    
    current_pos = get_current_position(chat_id)
    new_pos = max(0, current_pos + offset_seconds)
    
    # Clamp to duration if known
    duration = info.get("duration", 0)
    if duration > 0:
        new_pos = min(new_pos, duration)
    
    ffmpeg_params = f"-ss {int(new_pos)}" if new_pos > 0 else None
    stream = MediaStream(info["url"], ffmpeg_parameters=ffmpeg_params)
    
    try:
        await call.play(chat_id, stream)
        info["start_time"] = time.time()
        info["seek_offset"] = int(new_pos)
        info["paused"] = False
        info["pause_time"] = 0
        return True, f"Seeked to {format_time(int(new_pos))}"
    except Exception as e:
        return False, f"Seek error: {str(e)}"


async def seek_to_position(chat_id: int, position_seconds: int):
    """Seek to an absolute position."""
    chat_id = int(chat_id)
    info = active_streams.get(chat_id)
    if not info:
        return False, "No active stream"
    
    position_seconds = max(0, position_seconds)
    duration = info.get("duration", 0)
    if duration > 0:
        position_seconds = min(position_seconds, duration)
    
    ffmpeg_params = f"-ss {position_seconds}" if position_seconds > 0 else None
    stream = MediaStream(info["url"], ffmpeg_parameters=ffmpeg_params)
    
    try:
        await call.play(chat_id, stream)
        info["start_time"] = time.time()
        info["seek_offset"] = position_seconds
        info["paused"] = False
        info["pause_time"] = 0
        return True, f"Jumped to {format_time(position_seconds)}"
    except Exception as e:
        return False, f"Jump error: {str(e)}"


def get_current_position(chat_id: int) -> float:
    """Get the estimated current playback position in seconds."""
    info = active_streams.get(int(chat_id))
    if not info:
        return 0
    if info["paused"] and info["pause_time"] > 0:
        elapsed = info["pause_time"] - info["start_time"]
    else:
        elapsed = time.time() - info["start_time"]
    return info["seek_offset"] + elapsed


def format_time(seconds: int) -> str:
    """Format seconds into HH:MM:SS or MM:SS string."""
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


async def get_media_duration(url: str) -> int:
    """Get media duration in seconds using ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'quiet',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        duration = float(stdout.decode().strip())
        LOGGER.info(f"Detected duration: {duration}s for {url[:80]}")
        return int(duration)
    except Exception as e:
        LOGGER.warning(f"Could not detect duration: {e}")
        return 0


def build_progress_bar(current_seconds: int, total_duration: int = 0, total_width: int = 15) -> str:
    """Build a text progress bar based on actual duration."""
    if total_duration <= 0:
        total_duration = 7200
    filled = min(total_width, int((current_seconds / total_duration) * total_width))
    empty = total_width - filled
    return "▓" * filled + "░" * empty


def get_stream_info(chat_id: int) -> dict:
    """Get info about the active stream."""
    return active_streams.get(int(chat_id), None)


def is_vc_playing() -> dict:
    """Check if any VC stream is active. Returns first active stream info or None."""
    for chat_id, info in active_streams.items():
        return {"chat_id": chat_id, **info}
    return None


# --- Auto-refresh ---

def start_auto_refresh(chat_id: int, message, bot):
    """Start auto-refreshing the player display every 5 seconds."""
    stop_auto_refresh(chat_id)
    task = asyncio.create_task(_auto_refresh_loop(chat_id, message, bot))
    _refresh_tasks[int(chat_id)] = task


def stop_auto_refresh(chat_id: int):
    """Stop auto-refresh for a chat."""
    task = _refresh_tasks.pop(int(chat_id), None)
    if task and not task.done():
        task.cancel()


async def _auto_refresh_loop(chat_id: int, message, bot):
    """Background loop to refresh the player display every 5 seconds."""
    try:
        while int(chat_id) in active_streams:
            await asyncio.sleep(5)
            info = active_streams.get(int(chat_id))
            if not info:
                break
            
            try:
                from bot.helper.vc_player import get_current_position, format_time, build_progress_bar, get_vc_invite_link
                
                display_name = info["title"][:30] + "…" if len(info["title"]) > 30 else info["title"]
                pos = int(get_current_position(chat_id))
                is_paused = info.get("paused", False)
                status_emoji = "⏸" if is_paused else "▶️"
                status_text = "Paused" if is_paused else "Playing"
                duration = info.get("duration", 0)
                bar = build_progress_bar(pos, duration)
                dur_text = f" / {format_time(duration)}" if duration > 0 else ""
                
                # Build controls inline
                from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
                
                invite_link = await get_vc_invite_link(chat_id)
                
                pause_btn = InlineKeyboardButton(
                    "▶️ Resume" if is_paused else "⏸ Pause",
                    callback_data=f"{'bvr' if is_paused else 'bvp'}|{chat_id}"
                )
                
                SEGMENTS = 8
                total = duration if duration > 0 else 7200
                seg_dur = max(1, total // SEGMENTS)
                progress_bar = []
                for i in range(SEGMENTS):
                    seg_start = i * seg_dur
                    symbol = "▓" if pos >= seg_start else "░"
                    progress_bar.append(
                        InlineKeyboardButton(symbol, callback_data=f"bvj|{chat_id}|{seg_start}")
                    )
                
                controls = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("⏪ -30s", callback_data=f"bvk|{chat_id}|-30"),
                        pause_btn,
                        InlineKeyboardButton("⏩ +30s", callback_data=f"bvk|{chat_id}|30"),
                    ],
                    progress_bar,
                    [
                        InlineKeyboardButton("⏹ Stop", callback_data=f"bvs|{chat_id}"),
                        InlineKeyboardButton("🔊 Join VC", url=invite_link),
                        InlineKeyboardButton("⬅️ Back", callback_data=f"bvb|{chat_id}"),
                    ],
                ])
                
                await message.edit_text(
                    f"🔊 **Now Playing in VC**\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🎬 {display_name}\n\n"
                    f"`{bar}` {format_time(pos)}{dur_text}\n\n"
                    f"{status_emoji} Status: {status_text}",
                    reply_markup=controls,
                    parse_mode="Markdown"
                )
            except Exception as e:
                if "MESSAGE_NOT_MODIFIED" in str(e):
                    continue
                LOGGER.debug(f"Auto-refresh error: {e}")
                break
    except asyncio.CancelledError:
        pass
    except Exception as e:
        LOGGER.debug(f"Auto-refresh loop ended: {e}")
