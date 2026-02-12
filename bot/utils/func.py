"""
Utility functions for the Save-Restricted-Content-Bot features.
Includes: link parsing, filename sanitization, thumbnail generation,
video metadata extraction, premium management, and database helpers.
"""
import re
import os
import math
import asyncio
import logging
from datetime import datetime, timedelta

import pytz
from bot.config import Telegram

LOGGER = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Link Parsing
# ═══════════════════════════════════════════════════════════════════

def parse_link(link: str) -> tuple:
    """
    Parse a Telegram message link and extract chat_id and message_id.
    
    Supports:
        - https://t.me/c/1234567890/123
        - https://t.me/username/123
        - https://t.me/b/botusername/123 (bot deep links)
    
    Returns:
        (chat_id: int or str, message_id: int) or (None, None)
    """
    link = link.strip()

    # Private channel link: t.me/c/CHANNEL_ID/MSG_ID
    match = re.match(r'https?://t\.me/c/(\d+)/(\d+)', link)
    if match:
        chat_id = int(f"-100{match.group(1)}")
        msg_id = int(match.group(2))
        return chat_id, msg_id

    # Public channel/group link: t.me/USERNAME/MSG_ID
    match = re.match(r'https?://t\.me/([a-zA-Z_]\w+)/(\d+)', link)
    if match:
        username = match.group(1)
        msg_id = int(match.group(2))
        # Skip known Telegram paths
        if username.lower() in ("c", "s", "b", "joinchat", "addstickers", "share"):
            return None, None
        return username, msg_id

    return None, None


def parse_batch_links(start_link: str, end_link: str) -> tuple:
    """
    Parse batch start and end links, validate they're from the same chat.
    
    Returns:
        (chat_id, start_msg_id, end_msg_id) or (None, None, None)
    """
    chat1, start_id = parse_link(start_link)
    chat2, end_id = parse_link(end_link)

    if chat1 is None or chat2 is None:
        return None, None, None

    # Normalize for comparison
    if str(chat1) != str(chat2):
        return None, None, None

    if start_id > end_id:
        start_id, end_id = end_id, start_id

    return chat1, start_id, end_id


# ═══════════════════════════════════════════════════════════════════
# Filename Sanitization
# ═══════════════════════════════════════════════════════════════════

def sanitize_filename(name: str, max_length: int = 60) -> str:
    """Clean a filename: remove invalid characters, truncate, etc."""
    if not name:
        return "file"
    # Remove path separators and potentially dangerous chars
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    # Replace multiple spaces/underscores with single space
    name = re.sub(r'[\s_]+', ' ', name).strip()
    # Truncate
    if len(name) > max_length:
        base, ext = os.path.splitext(name)
        name = base[:max_length - len(ext)] + ext
    return name or "file"


def apply_rename(filename: str, rename_tag: str) -> str:
    """Apply rename tag to filename. Supports prefix/suffix patterns."""
    if not rename_tag:
        return filename
    base, ext = os.path.splitext(filename)
    # If rename_tag contains {filename}, substitute it
    if "{filename}" in rename_tag:
        return rename_tag.replace("{filename}", base) + ext
    # Otherwise, prepend as prefix
    return f"{rename_tag} {base}{ext}"


def apply_caption(caption_template: str, filename: str, filesize: str = "") -> str:
    """Apply caption template. Supports {filename}, {filesize} placeholders."""
    if not caption_template:
        return filename
    result = caption_template
    base, _ = os.path.splitext(filename)
    result = result.replace("{filename}", base)
    result = result.replace("{filesize}", filesize)
    return result


def apply_replacements(text: str, replacements: dict) -> str:
    """Apply word replacement pairs to text."""
    if not replacements:
        return text
    for find_word, replace_word in replacements.items():
        text = text.replace(find_word, replace_word)
    return text


def apply_delete_words(text: str, delete_words: list) -> str:
    """Remove specified words from text."""
    if not delete_words:
        return text
    for word in delete_words:
        text = text.replace(word, "")
    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ═══════════════════════════════════════════════════════════════════
# Thumbnail & Video Metadata
# ═══════════════════════════════════════════════════════════════════

async def generate_thumbnail(file_path: str, output_path: str = None) -> str:
    """
    Generate a thumbnail from a video file using ffmpeg.
    
    Returns:
        Path to the generated thumbnail, or None on failure.
    """
    if not output_path:
        output_path = f"{file_path}_thumb.jpg"

    try:
        cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-vframes", "1", "-an",
            "-s", "320x320",
            "-ss", "1",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        if os.path.exists(output_path):
            return output_path
    except Exception as e:
        LOGGER.error(f"Thumbnail generation failed: {e}")

    return None


async def get_video_metadata(file_path: str) -> dict:
    """
    Extract video metadata (duration, width, height) using cv2 if available.
    Falls back to default values if cv2 is not installed.
    
    Returns:
        {"duration": int, "width": int, "height": int}
    """
    metadata = {"duration": 0, "width": 0, "height": 0}

    try:
        import cv2
        cap = cv2.VideoCapture(file_path)
        if cap.isOpened():
            metadata["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            metadata["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if fps > 0:
                metadata["duration"] = int(frame_count / fps)
            cap.release()
    except ImportError:
        LOGGER.warning("cv2 not installed, video metadata extraction disabled")
    except Exception as e:
        LOGGER.error(f"Video metadata extraction failed: {e}")

    return metadata


# ═══════════════════════════════════════════════════════════════════
# Progress Bar
# ═══════════════════════════════════════════════════════════════════

def progress_bar(current: int, total: int, length: int = 20) -> str:
    """Generate a text progress bar."""
    if total == 0:
        return "▓" * length
    filled = int(length * current / total)
    bar = "▓" * filled + "░" * (length - filled)
    percent = current / total * 100
    return f"[{bar}] {percent:.1f}%"


def human_readable_size(size_bytes: int) -> str:
    """Convert bytes to human readable format."""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(size_bytes, 1024)))
    i = min(i, len(units) - 1)
    s = round(size_bytes / (1024 ** i), 2)
    return f"{s} {units[i]}"


def human_readable_time(seconds: int) -> str:
    """Convert seconds to human readable time format."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    else:
        h, remainder = divmod(seconds, 3600)
        m, s = divmod(remainder, 60)
        return f"{h}h {m}m {s}s"


# ═══════════════════════════════════════════════════════════════════
# Premium Helpers
# ═══════════════════════════════════════════════════════════════════

def get_ist_now() -> datetime:
    """Get current time in IST timezone."""
    return datetime.now(pytz.timezone("Asia/Kolkata"))


def format_expiry(expiry_dt: datetime) -> str:
    """Format a datetime for display."""
    if not expiry_dt:
        return "N/A"
    ist = pytz.timezone("Asia/Kolkata")
    if expiry_dt.tzinfo is None:
        expiry_dt = ist.localize(expiry_dt)
    return expiry_dt.strftime("%d-%b-%Y %I:%M %p IST")


def time_remaining(expiry_dt: datetime) -> str:
    """Get human readable time remaining until expiry."""
    if not expiry_dt:
        return "N/A"
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    if expiry_dt.tzinfo is None:
        expiry_dt = ist.localize(expiry_dt)
    delta = expiry_dt - now
    if delta.total_seconds() <= 0:
        return "Expired"
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes = remainder // 60
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    return " ".join(parts) if parts else "< 1m"
