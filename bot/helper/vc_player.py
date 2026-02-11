import logging
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
from bot.telegram import UserBot
from bot.config import Telegram

LOGGER = logging.getLogger(__name__)

# Global PyTgCalls instance
call = PyTgCalls(UserBot)
_started = False


async def ensure_started():
    """Start PyTgCalls if not already started."""
    global _started
    if not _started:
        await call.start()
        _started = True
        LOGGER.info("PyTgCalls started")


async def start_vc_stream(chat_id: int, stream_url: str, title: str = ""):
    """
    Start streaming a media file in the voice chat of the given chat.
    
    Args:
        chat_id: The chat/channel ID to stream in (with -100 prefix)
        stream_url: Direct URL to the media file
        title: Display title for logging
    """
    await ensure_started()
    
    try:
        LOGGER.info(f"Starting VC stream in {chat_id}: {title}")
        await call.play(
            int(chat_id),
            MediaStream(stream_url),
        )
        return True, "Stream started"
    except Exception as e:
        error_msg = str(e)
        LOGGER.error(f"VC stream error: {error_msg}")
        if "GROUPCALL_NOT_FOUND" in error_msg or "not found" in error_msg.lower():
            return False, "Voice chat is not active. Please start a voice chat in the channel first."
        elif "ALREADY" in error_msg.upper():
            # Already in a call, leave and rejoin
            try:
                await call.leave_call(int(chat_id))
                await call.play(
                    int(chat_id),
                    MediaStream(stream_url),
                )
                return True, "Previous stream stopped, new stream started"
            except Exception as e2:
                return False, f"Error: {str(e2)}"
        return False, f"Error: {error_msg}"


async def stop_vc_stream(chat_id: int):
    """Stop the current VC stream and leave the voice chat."""
    try:
        await call.leave_call(int(chat_id))
        LOGGER.info(f"VC stream stopped in {chat_id}")
        return True, "Stream stopped"
    except Exception as e:
        error_msg = str(e)
        LOGGER.error(f"VC stop error: {error_msg}")
        return False, f"Error: {error_msg}"


async def is_playing(chat_id: int) -> bool:
    """Check if there's an active stream in the chat."""
    try:
        active = await call.played_time(int(chat_id))
        return active is not None
    except Exception:
        return False
