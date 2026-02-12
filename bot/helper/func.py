import time
import os
import re
import cv2
import logging
import asyncio
from datetime import datetime
from bot.config import Telegram
from pyrogram import enums
# Initialize database instance for helper functions

# Initialize database instance for helper functions
db = Database()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

PUBLIC_LINK_PATTERN = re.compile(r'(https?://)?(t\.me|telegram\.me)/([^/]+)(/(\d+))?')
PRIVATE_LINK_PATTERN = re.compile(r'(https?://)?(t\.me|telegram\.me)/c/(\d+)(/(\d+))?')
VIDEO_EXTENSIONS = {"mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "mpeg", "mpg", "3gp"}

def is_private_link(link):
    return bool(PRIVATE_LINK_PATTERN.match(link))

def thumbnail(sender):
    return f'{sender}.jpg' if os.path.exists(f'{sender}.jpg') else None

def hhmmss(seconds):
    return time.strftime('%H:%M:%S', time.gmtime(seconds))

def E(L):   
    private_match = re.match(r'https://t\.me/c/(\d+)/(?:\d+/)?(\d+)', L)
    public_match = re.match(r'https://t\.me/([^/]+)/(?:\d+/)?(\d+)', L)
    
    if private_match:
        return f'-100{private_match.group(1)}', int(private_match.group(2)), 'private'
    elif public_match:
        return public_match.group(1), int(public_match.group(2)), 'public'
    
    return None, None, None

def get_display_name(user):
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    elif user.last_name:
        return user.last_name
    elif user.username:
        return user.username
    else:
        return "Unknown User"

def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '_', filename)

def get_dummy_filename(info):
    file_type = info.get("type", "file")
    extension = {
        "video": "mp4",
        "photo": "jpg",
        "document": "pdf",
        "audio": "mp3"
    }.get(file_type, "bin")
    
    return f"downloaded_file_{int(time.time())}.{extension}"

async def is_private_chat(event):
    return event.chat.type == "private"

async def process_text_with_rules(user_id, text):
    if not text:
        return ""
    
    try:
        replacements = await db.get_user_data_key(user_id, "replacement_words", {})
        delete_words = await db.get_user_data_key(user_id, "delete_words", [])
        
        processed_text = text
        for word, replacement in replacements.items():
            processed_text = processed_text.replace(word, replacement)
        
        if delete_words:
            words = processed_text.split()
            filtered_words = [w for w in words if w not in delete_words]
            processed_text = " ".join(filtered_words)
        
        return processed_text
    except Exception as e:
        logger.error(f"Error processing text with rules: {e}")
        return text

async def screenshot(video: str, duration: int, sender: str) -> str | None:
    existing_screenshot = f"{sender}.jpg"
    if os.path.exists(existing_screenshot):
        return existing_screenshot

    time_stamp = hhmmss(duration // 2)
    output_file = datetime.now().isoformat("_", "seconds").replace(":", "-") + ".jpg"

    cmd = [
        "ffmpeg",
        "-ss", time_stamp,
        "-i", video,
        "-frames:v", "1",
        output_file,
        "-y"
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()

    if os.path.isfile(output_file):
        return output_file
    else:
        # print(f"FFmpeg Error: {stderr.decode().strip()}")
        return None

async def get_video_metadata(file_path):
    default_values = {'width': 1, 'height': 1, 'duration': 1}
    
    def _extract_metadata():
        try:
            vcap = cv2.VideoCapture(file_path)
            if not vcap.isOpened():
                return default_values

            width = round(vcap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = round(vcap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = vcap.get(cv2.CAP_PROP_FPS)
            frame_count = vcap.get(cv2.CAP_PROP_FRAME_COUNT)

            if fps <= 0:
                print(f"Warning: Invalid FPS ({fps}) for {file_path}")
                return default_values

            duration = round(frame_count / fps)
            # Ensure duration is at least 1 second to avoid division by zero
            if duration <= 0:
                duration = 1

            vcap.release()
            return {'width': width, 'height': height, 'duration': duration}
        except Exception as e:
            logger.error(f"Error in video_metadata for {file_path}: {e}")
            return default_values
    
    return await asyncio.to_thread(_extract_metadata)

async def rename_file(file, sender):
    try:
        delete_words = await db.get_user_data_key(sender, 'delete_words', [])
        custom_rename_tag = await db.get_user_data_key(sender, 'rename_tag', '')
        replacements = await db.get_user_data_key(sender, 'replacement_words', {})
        
        last_dot_index = str(file).rfind('.')
        if last_dot_index != -1 and last_dot_index != 0:
            ggn_ext = str(file)[last_dot_index + 1:]
            if ggn_ext.isalpha() and len(ggn_ext) <= 9:
                if ggn_ext.lower() in VIDEO_EXTENSIONS:
                    original_file_name = str(file)[:last_dot_index]
                    file_extension = 'mp4'
                else:
                    original_file_name = str(file)[:last_dot_index]
                    file_extension = ggn_ext
            else:
                original_file_name = str(file)[:last_dot_index]
                file_extension = 'mp4'
        else:
            original_file_name = str(file)
            file_extension = 'mp4'
        
        for word in delete_words:
            original_file_name = original_file_name.replace(word, '')
        
        for word, replace_word in replacements.items():
            original_file_name = original_file_name.replace(word, replace_word)
        
        new_file_name = f'{original_file_name} {custom_rename_tag}.{file_extension}'
        
        os.rename(file, new_file_name)
        return new_file_name
    except Exception as e:
        logger.error(f"Rename error: {e}")
        return file

async def subscribe(client, message):
    if not Telegram.FORCE_SUB:
        return True
    try:
        user = await client.get_chat_member(Telegram.FORCE_SUB, message.from_user.id)
        if user.status in [enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.MEMBER]:
            return True
    except UserNotParticipant:
        pass
    except Exception as e:
        logger.error(f"Subscribe check error: {e}")
    
    return False

def get_link(msg_id):
    if Telegram.LOG_GROUP:
        return f"https://t.me/c/{str(Telegram.LOG_GROUP)[4:]}/{msg_id}"
    return None
