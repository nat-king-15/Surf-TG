import logging
import time
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
from bot.telegram import UserBot
from bot.config import Telegram

LOGGER = logging.getLogger(__name__)

# Global PyTgCalls instance
call = PyTgCalls(UserBot)
_started = False

# Track active streams: {chat_id: {url, title, start_time, seek_offset, paused}}
active_streams = {}


async def ensure_started():
    """Start PyTgCalls if not already started."""
    global _started
    if not _started:
        await call.start()
        _started = True
        LOGGER.info("PyTgCalls started")


async def start_vc_stream(chat_id: int, stream_url: str, title: str = "", seek_seconds: int = 0):
    """
    Start streaming a media file in the voice chat of the given chat.
    
    Args:
        chat_id: The chat/channel ID to stream in (with -100 prefix)
        stream_url: Direct URL to the media file
        title: Display title for logging
        seek_seconds: Seek position in seconds (0 = start from beginning)
    """
    await ensure_started()
    
    try:
        LOGGER.info(f"Starting VC stream in {chat_id}: {title} (seek: {seek_seconds}s)")
        
        # Build ffmpeg parameters for seeking
        ffmpeg_params = ""
        if seek_seconds > 0:
            ffmpeg_params = f"-ss {seek_seconds}"
        
        stream = MediaStream(
            stream_url,
            ffmpeg_parameters=ffmpeg_params if ffmpeg_params else None,
        )
        
        # Try to play (will join VC automatically)
        try:
            await call.play(int(chat_id), stream)
        except Exception as e:
            if "ALREADY" in str(e).upper() or "already" in str(e).lower():
                await call.leave_call(int(chat_id))
                await call.play(int(chat_id), stream)
            else:
                raise
        
        # Track stream info
        active_streams[int(chat_id)] = {
            "url": stream_url,
            "title": title,
            "start_time": time.time(),
            "seek_offset": seek_seconds,
            "paused": False,
            "pause_time": 0,
        }
        
        return True, "Stream started"
    except Exception as e:
        error_msg = str(e)
        LOGGER.error(f"VC stream error: {error_msg}")
        if "GROUPCALL_NOT_FOUND" in error_msg or "not found" in error_msg.lower():
            return False, "❌ Voice chat not active!\nPlease start a voice chat in the channel first."
        return False, f"Error: {error_msg}"


async def stop_vc_stream(chat_id: int):
    """Stop the current VC stream and leave the voice chat."""
    try:
        await call.leave_call(int(chat_id))
        active_streams.pop(int(chat_id), None)
        LOGGER.info(f"VC stream stopped in {chat_id}")
        return True, "Stream stopped"
    except Exception as e:
        error_msg = str(e)
        LOGGER.error(f"VC stop error: {error_msg}")
        return False, f"Error: {error_msg}"


async def pause_vc_stream(chat_id: int):
    """Pause the current VC stream."""
    try:
        await call.pause_stream(int(chat_id))
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
        await call.resume_stream(int(chat_id))
        info = active_streams.get(int(chat_id))
        if info:
            # Adjust start_time to account for pause duration
            if info["pause_time"] > 0:
                pause_duration = time.time() - info["pause_time"]
                info["start_time"] += pause_duration
            info["paused"] = False
            info["pause_time"] = 0
        return True, "Stream resumed"
    except Exception as e:
        return False, f"Error: {str(e)}"


async def seek_vc_stream(chat_id: int, offset_seconds: int):
    """
    Seek the stream by restarting with a new ffmpeg offset.
    offset_seconds: positive = forward, negative = backward
    """
    chat_id = int(chat_id)
    info = active_streams.get(chat_id)
    if not info:
        return False, "No active stream to seek"
    
    # Calculate current position
    current_pos = get_current_position(chat_id)
    new_pos = max(0, current_pos + offset_seconds)
    
    # Restart stream at new position
    success, msg = await start_vc_stream(
        chat_id, info["url"], info["title"], seek_seconds=int(new_pos)
    )
    
    if success:
        return True, f"Seeked to {format_time(int(new_pos))}"
    return False, msg


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
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def get_stream_info(chat_id: int) -> dict:
    """Get info about the active stream."""
    return active_streams.get(int(chat_id), None)
