import re
from bot import LOGGER
from bot.config import Telegram
from bot.helper.database import Database
from bot.helper.file_size import get_readable_file_size
from bot.helper.index import get_messages
from bot.helper.media import is_media
from bot.helper.topic_parser import parse_topic_hierarchy, get_or_create_folder_path
from bot.telegram import StreamBot
from pyrogram import filters, Client
from pyrogram.types import Message
from os.path import splitext
from pyrogram.errors import FloodWait
from pyrogram.enums.parse_mode import ParseMode
from asyncio import sleep

db = Database()


@StreamBot.on_message(filters.command('start') & filters.private)
async def start(bot: Client, message: Message):
    if "file_" in message.text:
        try:
            usr_cmd = message.text.split("_")[-1]
            data = usr_cmd.split("-")
            message_id, chat_id = data[0], f"-{data[1]}"
            file = await bot.get_messages(int(chat_id), int(message_id))
            media = is_media(file)
            await message.reply_cached_media(file_id=media.file_id, caption=f'**{media.file_name}**')
        except Exception as e:
            print(f"An error occurred: {e}")


@StreamBot.on_message(filters.command('index'))
async def start(bot: Client, message: Message):
    channel_id = message.chat.id
    AUTH_CHANNEL = await db.get_variable('auth_channel')
    if AUTH_CHANNEL is None or AUTH_CHANNEL.strip() == '':
        AUTH_CHANNEL = Telegram.AUTH_CHANNEL
    else:
        AUTH_CHANNEL = [channel.strip() for channel in AUTH_CHANNEL.split(",")]
    if str(channel_id) in AUTH_CHANNEL:
        try:
            last_id = message.id
            start_message = (
                "🔄 Please perform this action only once at the beginning of Surf-Tg usage.\n\n"
                "📋 File listing is currently in progress.\n\n"
                "📂 Auto-creating folders from Topic hierarchy...\n\n"
                "🚫 Please refrain from sending any additional files or indexing other channels until this process completes.\n\n"
                "⏳ Please be patient and wait a few moments."
            )

            wait_msg = await message.reply(text=start_message)
            files = await get_messages(message.chat.id, 1, last_id)
            
            # Process files with topic folders
            files_with_folders = 0
            files_without_folders = []
            
            for file_data in files:
                caption = file_data.get("caption", "")
                topic_path = parse_topic_hierarchy(caption)
                
                if topic_path:
                    folder_id = await get_or_create_folder_path(db, topic_path, str(channel_id))
                    await db.add_tgfile_with_folder(
                        file_data["chat_id"], 
                        str(file_data["msg_id"]), 
                        file_data["hash"], 
                        file_data["title"], 
                        file_data["size"], 
                        file_data["type"],
                        folder_id
                    )
                    files_with_folders += 1
                else:
                    # No topic, add to files without folder reference
                    files_without_folders.append({
                        "chat_id": file_data["chat_id"],
                        "msg_id": file_data["msg_id"],
                        "hash": file_data["hash"],
                        "title": file_data["title"],
                        "size": file_data["size"],
                        "type": file_data["type"]
                    })
            
            # Bulk add files without topic
            if files_without_folders:
                await db.add_btgfiles(files_without_folders)
            
            await wait_msg.delete()
            done_message = (
                f"✅ All your files have been successfully stored in the database. You're all set!\n\n"
                f"📂 Files with Topic folders: {files_with_folders}\n"
                f"📄 Files without Topic: {len(files_without_folders)}\n\n"
                f"📁 You don't need to index again unless you make changes to the database."
            )

            await bot.send_message(chat_id=message.chat.id, text=done_message)
        except FloodWait as e:
            LOGGER.info(f"Sleeping for {str(e.value)}s")
            await sleep(e.value)
            await message.reply(text=f"Got Floodwait of {str(e.value)}s",
                                disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply(text="Channel is not in AUTH_CHANNEL")


@StreamBot.on_message(
    filters.channel
    & (
        filters.document
        | filters.video
    )
)
async def file_receive_handler(bot: Client, message: Message):
    channel_id = message.chat.id
    AUTH_CHANNEL = await db.get_variable('auth_channel')
    if AUTH_CHANNEL is None or AUTH_CHANNEL.strip() == '':
        AUTH_CHANNEL = Telegram.AUTH_CHANNEL
    else:
        AUTH_CHANNEL = [channel.strip() for channel in AUTH_CHANNEL.split(",")]
    if str(channel_id) in AUTH_CHANNEL:
        try:
            file = message.video or message.document
            caption = message.caption or ""
            title = file.file_name or caption or file.file_id
            title, _ = splitext(title)
            title = re.sub(r'[.,|_\',]', ' ', title)
            msg_id = message.id
            hash = file.file_unique_id[:6]
            size = get_readable_file_size(file.file_size)
            type = file.mime_type
            
            # Parse Topic hierarchy from caption
            topic_path = parse_topic_hierarchy(caption)
            folder_id = None
            if topic_path:
                folder_id = await get_or_create_folder_path(db, topic_path, str(channel_id))
                LOGGER.info(f"Auto-created folder path: {' -> '.join(topic_path)} for file: {title}")
            
            # Add file with folder reference
            await db.add_tgfile_with_folder(str(channel_id), str(msg_id), str(hash), str(title), str(size), str(type), folder_id)
        except FloodWait as e:
            LOGGER.info(f"Sleeping for {str(e.value)}s")
            await sleep(e.value)
            await message.reply(text=f"Got Floodwait of {str(e.value)}s",
                                disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply(text="Channel is not in AUTH_CHANNEL")


@StreamBot.on_message(filters.command('createindex'))
async def create_index(bot: Client, message: Message):
    from bot.telegram import UserBot
    
    channel_id = message.chat.id
    AUTH_CHANNEL = await db.get_variable('auth_channel')
    if AUTH_CHANNEL is None or AUTH_CHANNEL.strip() == '':
        AUTH_CHANNEL = Telegram.AUTH_CHANNEL
    else:
        AUTH_CHANNEL = [channel.strip() for channel in AUTH_CHANNEL.split(",")]
    
    if str(channel_id) not in AUTH_CHANNEL:
        await message.reply(text="Channel is not in AUTH_CHANNEL")
        return
    
    try:
        wait_msg = await message.reply(text="📂 Scanning channel messages...")
        
        # ===== STEP 1: Scan channel directly, NO database needed =====
        # In-memory folder tree: { "path_key": { name, first_msg_id, file_count, children: {} } }
        folder_tree = {}  # root level
        total_scanned = 0
        total_with_topic = 0
        
        # Use UserBot if available, else StreamBot
        client = UserBot if Telegram.SESSION_STRING else StreamBot
        
        async for msg in client.get_chat_history(chat_id=channel_id):
            total_scanned += 1
            
            # Show progress every 500 messages
            if total_scanned % 500 == 0:
                try:
                    await wait_msg.edit_text(
                        f"📂 Scanning... {total_scanned} messages scanned\n"
                        f"📁 {total_with_topic} files with topics found"
                    )
                except:
                    pass
            
            # Skip non-file messages
            file = msg.video or msg.document
            if not file:
                continue
            
            caption = msg.caption or ""
            topic_path = parse_topic_hierarchy(caption)
            if not topic_path:
                continue
            
            total_with_topic += 1
            msg_id = msg.id
            
            # Build folder tree in-memory
            current_level = folder_tree
            for i, folder_name in enumerate(topic_path):
                if folder_name not in current_level:
                    current_level[folder_name] = {
                        "first_msg_id": None,
                        "file_count": 0,
                        "total_files": 0,
                        "children": {}
                    }
                
                node = current_level[folder_name]
                
                # Set first_msg_id on ALL nodes in path (not just leaf)
                # This ensures every folder gets a link
                if node["first_msg_id"] is None or msg_id < node["first_msg_id"]:
                    node["first_msg_id"] = msg_id
                
                # Only count files at the leaf folder
                if i == len(topic_path) - 1:
                    node["file_count"] += 1
                
                current_level = node["children"]
        
        if not folder_tree:
            await wait_msg.edit_text(
                f"❌ No Topic folders found after scanning {total_scanned} messages.\n"
                "Make sure file captions have: `Topic: Home -> SubFolder -> ...`"
            )
            return
        
        # ===== STEP 2: Propagate first_msg_id and total_files upward =====
        def propagate(tree):
            for name, node in tree.items():
                child_msg, child_total = propagate(node["children"])
                node["total_files"] = node["file_count"] + child_total
                if node["first_msg_id"] is None:
                    node["first_msg_id"] = child_msg
                elif child_msg is not None and child_msg < node["first_msg_id"]:
                    node["first_msg_id"] = child_msg
            
            # Return earliest msg and total for parent
            earliest = None
            total = 0
            for name, node in tree.items():
                total += node["total_files"]
                if node["first_msg_id"] is not None:
                    if earliest is None or node["first_msg_id"] < earliest:
                        earliest = node["first_msg_id"]
            return earliest, total
        
        propagate(folder_tree)
        
        # ===== STEP 3: Build index message =====
        clean_channel_id = str(channel_id).replace("-100", "")
        base_url = f"https://t.me/c/{clean_channel_id}"
        
        def build_tree_text(tree, depth=0, parent_prefixes=""):
            lines = []
            # Sort by first_msg_id (oldest first), folders without msg_id go last
            sorted_items = sorted(
                tree.items(),
                key=lambda x: x[1]["first_msg_id"] if x[1]["first_msg_id"] is not None else float('inf')
            )
            
            for i, (name, node) in enumerate(sorted_items):
                is_last = (i == len(sorted_items) - 1)
                
                # Tree connectors
                if depth == 0:
                    connector = "📂 "
                else:
                    connector = "┗ " if is_last else "┣ "
                
                # File count - avoid [] brackets as they conflict with Telegram link syntax
                count = f" · {node['total_files']}" if node['total_files'] > 0 else ""
                
                # Build line with link - all folders should have first_msg_id now
                if node["first_msg_id"]:
                    link = f"{base_url}/{node['first_msg_id']}"
                    line = f"{parent_prefixes}{connector}[{name}]({link}){count}"
                else:
                    line = f"{parent_prefixes}{connector}**{name}**"
                
                lines.append(line)
                
                # Recurse children with proper prefix
                if node["children"]:
                    if depth == 0:
                        child_prefix = ""
                    else:
                        child_prefix = "    " if is_last else "┃   "
                    lines.extend(build_tree_text(
                        node["children"], 
                        depth + 1, 
                        parent_prefixes + child_prefix
                    ))
            
            return lines
        
        index_lines = build_tree_text(folder_tree)
        
        # ===== STEP 4: Send index message(s) =====
        header = (
            f"📚 **CHANNEL INDEX**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 {total_scanned} msgs scanned | {total_with_topic} files indexed\n\n"
        )
        footer = "\n\n━━━━━━━━━━━━━━━━━━\n🔄 `/createindex` to refresh"
        
        messages_to_send = []
        current_msg = header
        
        for line in index_lines:
            if len(current_msg) + len(line) + 2 > 3800:
                current_msg += footer
                messages_to_send.append(current_msg)
                current_msg = "📚 **INDEX (cont.)**\n━━━━━━━━━━━━━━━━━━\n\n"
            current_msg += line + "\n"
        
        current_msg += footer
        messages_to_send.append(current_msg)
        
        await wait_msg.delete()
        
        for msg_text in messages_to_send:
            await bot.send_message(
                chat_id=channel_id,
                text=msg_text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
            await sleep(1)
        
        LOGGER.info(f"Created live index: {total_scanned} msgs scanned, {total_with_topic} files with topics")
        
    except FloodWait as e:
        LOGGER.info(f"Sleeping for {str(e.value)}s")
        await sleep(e.value)
        await message.reply(text=f"Got Floodwait of {str(e.value)}s",
                            disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        LOGGER.error(f"Error creating index: {e}")
        import traceback
        traceback.print_exc()
        await message.reply(text=f"❌ Error: {str(e)}")
