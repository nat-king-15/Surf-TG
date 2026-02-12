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
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from os.path import splitext
from pyrogram.errors import FloodWait
from pyrogram.enums.parse_mode import ParseMode
from asyncio import sleep, gather
from urllib.parse import quote

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
            size = file.file_size or 0
            type = file.mime_type
            
            # Parse Topic hierarchy from caption
            topic_path = parse_topic_hierarchy(caption)
            folder_id = None
            if topic_path:
                folder_id = await get_or_create_folder_path(db, topic_path, str(channel_id))
                LOGGER.info(f"Auto-created folder path: {' -> '.join(topic_path)} for file: {title}")
            
            # Add file with folder reference
            await db.add_tgfile_with_folder(str(channel_id), str(msg_id), str(hash), str(title), size, str(type), folder_id)
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


# ═══════════════════════════════════════════════════════════════════
# /browse - Inline Keyboard Folder Browser
# ═══════════════════════════════════════════════════════════════════

ITEMS_PER_PAGE = 8  # items per page in folder view


async def _get_auth_channels():
    """Get list of authorized channels."""
    AUTH_CHANNEL = await db.get_variable('auth_channel')
    if AUTH_CHANNEL is None or AUTH_CHANNEL.strip() == '':
        AUTH_CHANNEL = Telegram.AUTH_CHANNEL
    else:
        AUTH_CHANNEL = [channel.strip() for channel in AUTH_CHANNEL.split(",")]
    return AUTH_CHANNEL


async def _build_folder_keyboard(folder_id, channel_id, page=1):
    """
    Build inline keyboard for a folder showing sub-folders and files.
    Returns (text, keyboard). Optimized: parallel queries, no redundant DB calls.
    """
    if folder_id != "root":
        # Run items + folder info in parallel (2 queries instead of 7)
        items_result, folder_info = await gather(
            db.get_bot_items(folder_id, channel_id, page, ITEMS_PER_PAGE),
            db.get_folder_with_parent(folder_id)
        )
        folders, files, has_more, sub_count, file_count, video_count, pdf_count = items_result
        folder_name_str, parent_id, _ = folder_info
    else:
        folders, files, has_more, sub_count, file_count, video_count, pdf_count = await db.get_bot_items(folder_id, channel_id, page, ITEMS_PER_PAGE)
        folder_name_str = None
        parent_id = None
    
    buttons = []
    
    # Folder buttons (2 per row)
    folder_row = []
    for f in folders:
        fid = str(f['_id'])
        fname = f['name']
        display_name = fname[:20] + "…" if len(fname) > 20 else fname
        btn = InlineKeyboardButton(
            f"📂 {display_name}",
            callback_data=f"bf|{fid}|{channel_id}|1"
        )
        folder_row.append(btn)
        if len(folder_row) == 2:
            buttons.append(folder_row)
            folder_row = []
    if folder_row:
        buttons.append(folder_row)
    
    # File buttons (1 per row)
    for fi in files:
        fid = fi.get('file_id', str(fi.get('msg_id', '')))
        fname = fi.get('name', fi.get('title', 'File'))
        fhash = fi.get('hash', '')
        chat = fi.get('chat_id', channel_id)
        display_name = fname[:28] + "…" if len(fname) > 28 else fname
        ftype = fi.get('file_type', fi.get('type', ''))
        
        if 'video' in (ftype or '').lower():
            icon = "🎬"
        elif 'pdf' in (ftype or '').lower():
            icon = "📕"
        else:
            icon = "📄"
        
        cb_data = f"bfi|{fid}|{chat}|{fhash}|{folder_id}"
        if len(cb_data) > 64:
            cb_data = cb_data[:64]
        
        buttons.append([InlineKeyboardButton(
            f"{icon} {display_name}",
            callback_data=cb_data
        )])
    
    # Navigation row
    nav_row = []
    
    # Back button - uses parent_id from get_folder_with_parent (no extra query)
    if folder_id != "root":
        if parent_id == "root":
            nav_row.append(InlineKeyboardButton("⬅️ Back", callback_data=f"bch|{channel_id}"))
        else:
            nav_row.append(InlineKeyboardButton("⬅️ Back", callback_data=f"bf|{parent_id}|{channel_id}|1"))
    else:
        nav_row.append(InlineKeyboardButton("⬅️ Channels", callback_data="browse_home"))
    
    # Pagination row
    import math
    total_items = sub_count + file_count
    total_pages = max(1, math.ceil(total_items / ITEMS_PER_PAGE))
    
    if total_pages > 1:
        page_row = []
        if page > 1:
            page_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"bf|{folder_id}|{channel_id}|{page-1}"))
        else:
            page_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"bf|{folder_id}|{channel_id}|1"))
        if has_more:
            page_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"bf|{folder_id}|{channel_id}|{page+1}"))
        else:
            page_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"bf|{folder_id}|{channel_id}|{total_pages}"))
        buttons.append(page_row)
    
    # Back button on its own row below pagination
    buttons.append(nav_row)
    
    # Build text header - uses data already fetched (no extra query)
    if folder_id == "root":
        header = "📁 Root"
    else:
        header = f"📁 {folder_name_str}" if folder_name_str else "📁 Folder"
    
    # Build file type breakdown line
    type_parts = []
    if sub_count > 0:
        type_parts.append(f"📂 {sub_count} Folders")
    if video_count > 0:
        type_parts.append(f"🎬 {video_count} Videos")
    if pdf_count > 0:
        type_parts.append(f"📕 {pdf_count} PDFs")
    other_count = file_count - video_count - pdf_count
    if other_count > 0:
        type_parts.append(f"📄 {other_count} Files")
    if not type_parts:
        type_parts.append("📄 0 Files")
    
    type_line = "  |  ".join(type_parts)
    
    text = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{type_line}\n"
    )
    
    if not folders and not files:
        text += "\n⚠️ This folder is empty."
    
    if total_pages > 1:
        text += f"\n📄 Page {page}/{total_pages}"
    
    return text, InlineKeyboardMarkup(buttons) if buttons else None


@StreamBot.on_message(filters.command('browse') & filters.private)
async def browse_command(bot: Client, message: Message):
    """Show channels to browse as inline keyboard buttons."""
    try:
        auth_channels = await _get_auth_channels()
        
        if not auth_channels:
            await message.reply("❌ No channels configured.")
            return
        
        buttons = []
        for ch_id in auth_channels:
            try:
                chat = await StreamBot.get_chat(int(ch_id))
                title = chat.title or chat.first_name or str(ch_id)
                display = title[:30] + "…" if len(title) > 30 else title
                buttons.append([InlineKeyboardButton(
                    f"📺 {display}",
                    callback_data=f"bch|{ch_id}"
                )])
            except Exception:
                buttons.append([InlineKeyboardButton(
                    f"📺 Channel {ch_id}",
                    callback_data=f"bch|{ch_id}"
                )])
        
        await message.reply(
            "📚 **Browse Channel Files**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Select a channel to browse its files:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        LOGGER.error(f"Browse command error: {e}")
        await message.reply(f"❌ Error: {str(e)}")


@StreamBot.on_callback_query(filters.regex(r'^browse_home$'))
async def browse_home_callback(bot: Client, query: CallbackQuery):
    """Go back to channel list."""
    try:
        auth_channels = await _get_auth_channels()
        buttons = []
        for ch_id in auth_channels:
            try:
                chat = await StreamBot.get_chat(int(ch_id))
                title = chat.title or chat.first_name or str(ch_id)
                display = title[:30] + "…" if len(title) > 30 else title
                buttons.append([InlineKeyboardButton(
                    f"📺 {display}",
                    callback_data=f"bch|{ch_id}"
                )])
            except Exception:
                buttons.append([InlineKeyboardButton(
                    f"📺 Channel {ch_id}",
                    callback_data=f"bch|{ch_id}"
                )])
        
        await query.message.edit_text(
            "📚 **Browse Channel Files**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Select a channel to browse its files:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()
    except Exception as e:
        LOGGER.error(f"Browse home callback error: {e}")
        await query.answer(f"Error: {str(e)}", show_alert=True)


@StreamBot.on_callback_query(filters.regex(r'^bch\|'))
async def browse_channel_callback(bot: Client, query: CallbackQuery):
    """User clicked a channel - show root folders."""
    try:
        _, channel_id = query.data.split("|", 1)
        
        try:
            chat = await StreamBot.get_chat(int(channel_id))
            channel_name = chat.title or "Channel"
        except Exception:
            channel_name = "Channel"
        
        text, keyboard = await _build_folder_keyboard("root", channel_id, page=1)
        
        header = f"📺 **{channel_name}**\n{text}"
        
        await query.message.edit_text(
            header,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()
    except Exception as e:
        LOGGER.error(f"Browse channel callback error: {e}")
        await query.answer(f"Error: {str(e)}", show_alert=True)


@StreamBot.on_callback_query(filters.regex(r'^bf\|'))
async def browse_folder_callback(bot: Client, query: CallbackQuery):
    """User clicked a folder - show its contents."""
    try:
        parts = query.data.split("|")
        # bf|folder_id|channel_id|page
        folder_id = parts[1]
        channel_id = parts[2]
        page = int(parts[3]) if len(parts) > 3 else 1
        
        text, keyboard = await _build_folder_keyboard(folder_id, channel_id, page)
        
        # Add "Now Playing" banner if VC is active
        from bot.helper.vc_player import is_vc_playing, get_current_position, format_time
        vc_info = is_vc_playing()
        if vc_info:
            vc_title = vc_info["title"][:20] + "…" if len(vc_info["title"]) > 20 else vc_info["title"]
            vc_pos = format_time(int(get_current_position(vc_info["chat_id"])))
            vc_dur = format_time(vc_info.get("duration", 0)) if vc_info.get("duration", 0) > 0 else "?"
            text = f"🔊 **Now Playing:** {vc_title} `{vc_pos}/{vc_dur}`\n\n{text}"
            # Add Stop button at top of keyboard
            vc_chat_id = vc_info["chat_id"]
            vc_btn = [InlineKeyboardButton("⏹ Stop VC", callback_data=f"bvs|{vc_chat_id}"),
                      InlineKeyboardButton("🔊 Open Player", callback_data=f"bvo|{vc_chat_id}")]
            keyboard.inline_keyboard.insert(0, vc_btn)
        
        await query.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()
    except Exception as e:
        LOGGER.error(f"Browse folder callback error: {e}")
        await query.answer(f"Error: {str(e)}", show_alert=True)


@StreamBot.on_callback_query(filters.regex(r'^bfi\|'))
async def browse_file_callback(bot: Client, query: CallbackQuery):
    """User clicked a file - show action menu."""
    try:
        parts = query.data.split("|")
        # bfi|msg_id|chat_id|hash|folder_id
        msg_id = parts[1]
        chat_id = parts[2]
        file_hash = parts[3] if len(parts) > 3 else ""
        folder_id = parts[4] if len(parts) > 4 else "root"
        
        # Get file info from DB (fast) instead of Telegram API (slow)
        fname = "File"
        fsize = "?"
        # Try both int and string types for file_id/chat_id to handle type mismatches
        file_doc = await db.collection.find_one({"file_id": int(msg_id), "chat_id": chat_id, "type": "file"})
        if not file_doc:
            file_doc = await db.collection.find_one({"file_id": int(msg_id), "chat_id": int(chat_id), "type": "file"})
        if not file_doc:
            file_doc = await db.collection.find_one({"file_id": str(msg_id), "chat_id": chat_id, "type": "file"})
        file_type = ""
        if file_doc:
            fname = file_doc.get('name', file_doc.get('title', 'File'))
            file_type = file_doc.get('file_type', '')
            raw_size = file_doc.get('size', file_doc.get('file_size', 0))
            if isinstance(raw_size, str) and not raw_size.isdigit():
                fsize = raw_size
            elif raw_size is not None:
                fsize = get_readable_file_size(int(raw_size))
            else:
                fsize = "?"
        
        # Build URLs
        clean_chat_id = str(chat_id).replace("-100", "")
        base_url = Telegram.BASE_URL.rstrip('/')
        encoded_name = quote(fname, safe='')
        stream_url = f"{base_url}/{clean_chat_id}/{encoded_name}?id={msg_id}&hash={file_hash}"
        watch_url = f"{base_url}/watch/{clean_chat_id}?id={msg_id}&hash={file_hash}"
        msg_url = f"https://t.me/c/{clean_chat_id}/{msg_id}"
        
        # Build action buttons based on file type
        buttons = []
        is_video = file_type and ('video' in file_type.lower())
        is_pdf = file_type and ('pdf' in file_type.lower())
        
        if is_video:
            buttons.append([InlineKeyboardButton("▶️ Watch/Stream", url=watch_url)])
            buttons.append([InlineKeyboardButton("🔊 Play in VC", callback_data=f"bvc|{msg_id}|{chat_id}|{file_hash}")])
        elif is_pdf:
            buttons.append([InlineKeyboardButton("📄 Open PDF", url=stream_url)])
            buttons.append([InlineKeyboardButton("⬇️ Download", url=stream_url)])
        else:
            buttons.append([InlineKeyboardButton("📂 Open File", url=stream_url)])
            buttons.append([InlineKeyboardButton("⬇️ Download", url=stream_url)])
        
        buttons.append([InlineKeyboardButton("📥 Send to Bot", callback_data=f"bs|{msg_id}|{chat_id}")])
        buttons.append([InlineKeyboardButton("💬 Jump to Message", url=msg_url)])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"bf|{folder_id}|{chat_id}|1")])
        
        action_buttons = InlineKeyboardMarkup(buttons)
        
        display_name = fname[:35] + "…" if len(fname) > 35 else fname
        file_icon = "🎬" if is_video else "📄" if is_pdf else "📁"
        await query.message.edit_text(
            f"{file_icon} **{display_name}**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💾 Size: {fsize}\n\n"
            f"Choose an action:",
            reply_markup=action_buttons,
            parse_mode=ParseMode.MARKDOWN
        )
        await query.answer()
    except Exception as e:
        LOGGER.error(f"Browse file callback error: {e}")
        await query.answer(f"Error: {str(e)}", show_alert=True)


@StreamBot.on_callback_query(filters.regex(r'^bs\|'))
async def browse_send_file_callback(bot: Client, query: CallbackQuery):
    """User chose 'Send to Bot' - send the file directly."""
    try:
        parts = query.data.split("|")
        # bs|msg_id|chat_id
        msg_id = parts[1]
        chat_id = parts[2]
        
        await bot.copy_message(
            chat_id=query.from_user.id,
            from_chat_id=int(chat_id),
            message_id=int(msg_id)
        )
        await query.answer("📥 Sending file...")
    except Exception as e:
        LOGGER.error(f"Send file error: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


@StreamBot.on_callback_query(filters.regex(r'^bvc\|'))
async def browse_vc_play_callback(bot: Client, query: CallbackQuery):
    """User clicked 'Play in VC' - stream video in auth channel voice chat."""
    try:
        from bot.helper.vc_player import start_vc_stream, get_vc_invite_link, build_progress_bar, format_time
        
        parts = query.data.split("|")
        # bvc|msg_id|chat_id|hash
        msg_id = parts[1]
        chat_id = parts[2]
        file_hash = parts[3] if len(parts) > 3 else ""
        
        # Build stream URL
        clean_chat_id = str(chat_id).replace("-100", "")
        base_url = Telegram.BASE_URL.rstrip('/')
        
        # Get file info from DB
        fname = "stream"
        folder_id = "root"
        file_doc = await db.collection.find_one({"file_id": int(msg_id), "chat_id": chat_id, "type": "file"})
        if not file_doc:
            file_doc = await db.collection.find_one({"file_id": int(msg_id), "chat_id": int(chat_id), "type": "file"})
        if file_doc:
            fname = file_doc.get('name', file_doc.get('title', 'stream'))
            folder_id = file_doc.get('parent_folder', 'root')
        
        encoded_name = quote(fname, safe='')
        stream_url = f"{base_url}/{clean_chat_id}/{encoded_name}?id={msg_id}&hash={file_hash}"
        
        # Use auth channel for VC
        vc_chat_id = int(Telegram.AUTH_CHANNEL[0]) if Telegram.AUTH_CHANNEL else int(chat_id)
        
        success, message = await start_vc_stream(
            vc_chat_id, stream_url, fname,
            msg_id=msg_id, src_chat_id=chat_id,
            folder_id=str(folder_id), file_hash=file_hash
        )
        
        if success:
            from bot.helper.vc_player import start_auto_refresh, get_stream_info
            # Get invite link for Join VC button
            invite_link = await get_vc_invite_link(vc_chat_id)
            
            info = get_stream_info(vc_chat_id)
            duration = info.get("duration", 0) if info else 0
            dur_text = f" / {format_time(duration)}" if duration > 0 else ""
            display_name = fname[:30] + "…" if len(fname) > 30 else fname
            bar = build_progress_bar(0, duration)
            controls = await _build_vc_controls(vc_chat_id, False, 0, invite_link, duration)
            msg = await query.message.edit_text(
                f"🔊 **Now Playing in VC**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎬 {display_name}\n\n"
                f"`{bar}` 0:00{dur_text}\n\n"
                f"▶️ Status: Playing",
                reply_markup=controls,
                parse_mode=ParseMode.MARKDOWN
            )
            # Start auto-refresh every 5 seconds
            start_auto_refresh(vc_chat_id, query.message, bot)
            await query.answer("🔊 Starting VC stream...")
        else:
            try:
                # Attempt to show alert if possible, or send modification
                await query.message.edit_text(f"❌ Failed to start VC: {message}\n\nplease try again or check logs.")
            except:
                 pass
            # Also try to answer if not answered yet, though we are late
            try:
                await query.answer(f"❌ {message}", show_alert=True)
            except:
                pass
    except Exception as e:
        LOGGER.error(f"VC play error: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def _build_vc_controls(vc_chat_id: int, is_paused: bool = False, current_pos: int = 0, invite_link: str = None, duration: int = 0):
    """Build inline keyboard with clickable progress bar + controls + join VC."""
    from bot.helper.vc_player import get_vc_invite_link
    
    pause_btn = InlineKeyboardButton(
        "▶️ Resume" if is_paused else "⏸ Pause",
        callback_data=f"{'bvr' if is_paused else 'bvp'}|{vc_chat_id}"
    )
    
    # Get invite link if not provided
    if not invite_link:
        invite_link = await get_vc_invite_link(vc_chat_id)
    
    # Build clickable progress bar: 32 segments (4 rows of 8)
    SEGMENTS = 32
    COLS = 8
    total = duration if duration > 0 else 7200
    seg_dur = max(1, total // SEGMENTS)
    
    progress_grid = []
    current_row = []
    
    for i in range(SEGMENTS):
        seg_start = i * seg_dur
        # Determine if this segment is "filled" (current pos is past this segment's start)
        # Use a slightly different logic for fine-grained bars:
        # If pos is within this segment, show a special marker (e.g. 🔘 or 🟢)
        # If pos is past this segment, show filled (▓)
        # If pos is before, show empty (░)
        
        if current_pos >= seg_start + seg_dur:
            symbol = "▓"
        elif current_pos >= seg_start:
            symbol = "🔘"  # Current segment
        else:
            symbol = "░"
            
        current_row.append(
            InlineKeyboardButton(symbol, callback_data=f"bvj|{vc_chat_id}|{seg_start}")
        )
        
        if len(current_row) == COLS:
            progress_grid.append(current_row)
            current_row = []
    
    if current_row:
        progress_grid.append(current_row) # Should not happen if SEGMENTS % COLS == 0
    
    buttons = [
        # Row 1: Seek controls
        [
            InlineKeyboardButton("⏪ -30s", callback_data=f"bvk|{vc_chat_id}|-30"),
            pause_btn,
            InlineKeyboardButton("⏩ +30s", callback_data=f"bvk|{vc_chat_id}|30"),
        ],
        # Rows 2-5: Clickable progress grid (32 segments)
        *progress_grid,
        # Row 6: Stop, Join VC, Back
        [
            InlineKeyboardButton("⏹ Stop", callback_data=f"bvs|{vc_chat_id}"),
            InlineKeyboardButton("🔊 Join VC", url=invite_link),
            InlineKeyboardButton("⬅️ Back", callback_data=f"bvb|{vc_chat_id}"),
        ],
    ]
    
    return InlineKeyboardMarkup(buttons)


async def _update_player_display(query, vc_chat_id: int, status_text: str = "Playing"):
    """Update the player message with current position and progress bar."""
    from bot.helper.vc_player import get_stream_info, get_current_position, format_time, build_progress_bar
    
    info = get_stream_info(vc_chat_id)
    if not info:
        return
    
    display_name = info["title"][:30] + "…" if len(info["title"]) > 30 else info["title"]
    pos = int(get_current_position(vc_chat_id))
    is_paused = info.get("paused", False)
    status_emoji = "⏸" if is_paused else "▶️"
    duration = info.get("duration", 0)
    bar = build_progress_bar(pos, duration)
    dur_text = f" / {format_time(duration)}" if duration > 0 else ""
    
    controls = await _build_vc_controls(vc_chat_id, is_paused, pos, duration=duration)
    
    try:
        await query.message.edit_text(
            f"🔊 **Now Playing in VC**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎬 {display_name}\n\n"
            f"`{bar}` {format_time(pos)}{dur_text}\n\n"
            f"{status_emoji} Status: {status_text}",
            reply_markup=controls,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        pass  # Message not modified


@StreamBot.on_callback_query(filters.regex(r'^bvp\|'))
async def browse_vc_pause_callback(bot: Client, query: CallbackQuery):
    """Pause VC stream."""
    try:
        from bot.helper.vc_player import pause_vc_stream
        parts = query.data.split("|")
        vc_chat_id = int(parts[1])
        
        success, msg = await pause_vc_stream(vc_chat_id)
        if success:
            await query.answer("⏸ Paused")
            await _update_player_display(query, vc_chat_id, "Paused")
        else:
            await query.answer(f"❌ {msg}", show_alert=True)
    except Exception as e:
        await query.answer(f"❌ {str(e)}", show_alert=True)


@StreamBot.on_callback_query(filters.regex(r'^bvr\|'))
async def browse_vc_resume_callback(bot: Client, query: CallbackQuery):
    """Resume VC stream."""
    try:
        from bot.helper.vc_player import resume_vc_stream
        parts = query.data.split("|")
        vc_chat_id = int(parts[1])
        
        success, msg = await resume_vc_stream(vc_chat_id)
        if success:
            await query.answer("▶️ Resumed")
            await _update_player_display(query, vc_chat_id, "Playing")
        else:
            await query.answer(f"❌ {msg}", show_alert=True)
    except Exception as e:
        await query.answer(f"❌ {str(e)}", show_alert=True)


@StreamBot.on_callback_query(filters.regex(r'^bvk\|'))
async def browse_vc_seek_callback(bot: Client, query: CallbackQuery):
    """Seek VC stream ±30 seconds."""
    try:
        from bot.helper.vc_player import seek_vc_stream
        parts = query.data.split("|")
        vc_chat_id = int(parts[1])
        offset = int(parts[2])
        
        await query.answer(f"{'⏩' if offset > 0 else '⏪'} {'+' if offset > 0 else ''}{offset}s")
        success, msg = await seek_vc_stream(vc_chat_id, offset)
        if success:
            await _update_player_display(query, vc_chat_id, "Playing")
        else:
            await query.answer(f"❌ {msg}", show_alert=True)
    except Exception as e:
        await query.answer(f"❌ {str(e)}", show_alert=True)


@StreamBot.on_callback_query(filters.regex(r'^bvj\|'))
async def browse_vc_jump_callback(bot: Client, query: CallbackQuery):
    """Jump to a specific time position."""
    try:
        from bot.helper.vc_player import seek_to_position, format_time
        parts = query.data.split("|")
        vc_chat_id = int(parts[1])
        position = int(parts[2])
        
        await query.answer(f"⏭ Jump to {format_time(position)}")
        success, msg = await seek_to_position(vc_chat_id, position)
        if success:
            await _update_player_display(query, vc_chat_id, "Playing")
        else:
            await query.answer(f"❌ {msg}", show_alert=True)
    except Exception as e:
        await query.answer(f"❌ {str(e)}", show_alert=True)


@StreamBot.on_callback_query(filters.regex(r'^bvb\|'))
async def browse_vc_back_callback(bot: Client, query: CallbackQuery):
    """Back button from VC player - go to browse root (VC keeps playing)."""
    try:
        from bot.helper.vc_player import get_stream_info, stop_auto_refresh
        parts = query.data.split("|")
        vc_chat_id = int(parts[1])
        
        # Stop auto-refresh for this message since we're leaving the player view
        stop_auto_refresh(vc_chat_id)
        
        info = get_stream_info(vc_chat_id)
        if info and info.get("src_chat_id"):
            # Go back to the folder where the file was
            channel_id = info["src_chat_id"]
            folder_id = info.get("folder_id", "root")
            query.data = f"bf|{folder_id}|{channel_id}|1"
            await browse_folder_callback(bot, query)
        else:
            # Fallback: go to browse home
            query.data = "browse_home"
            await browse_home_callback(bot, query)
        await query.answer()
    except Exception as e:
        await query.answer(f"❌ {str(e)}", show_alert=True)


@StreamBot.on_callback_query(filters.regex(r'^bvo\|'))
async def browse_vc_open_player_callback(bot: Client, query: CallbackQuery):
    """Re-open the VC player from the Now Playing banner."""
    try:
        from bot.helper.vc_player import get_stream_info, start_auto_refresh
        parts = query.data.split("|")
        vc_chat_id = int(parts[1])
        
        info = get_stream_info(vc_chat_id)
        if info:
            status = "Paused" if info.get("paused") else "Playing"
            await _update_player_display(query, vc_chat_id, status)
            # Restart auto-refresh for this message
            start_auto_refresh(vc_chat_id, query.message, bot)
            await query.answer()
        else:
            await query.answer("No active stream", show_alert=True)
    except Exception as e:
        await query.answer(f"❌ {str(e)}", show_alert=True)


@StreamBot.on_callback_query(filters.regex(r'^bvs\|'))
async def browse_vc_stop_callback(bot: Client, query: CallbackQuery):
    """Stop VC stream and navigate back to file action menu."""
    try:
        from bot.helper.vc_player import stop_vc_stream
        parts = query.data.split("|")
        vc_chat_id = int(parts[1])
        
        success, message, stream_info = await stop_vc_stream(vc_chat_id)
        await query.answer("⏹ Stream stopped")
        
        # Navigate back to file action menu
        # bfi format: bfi|msg_id|chat_id|hash|folder_id
        if stream_info and stream_info.get("msg_id") and stream_info.get("src_chat_id"):
            back_msg_id = stream_info["msg_id"]
            back_chat_id = stream_info["src_chat_id"]
            back_folder = stream_info.get("folder_id", "root")
            back_hash = stream_info.get("file_hash", "")
            query.data = f"bfi|{back_msg_id}|{back_chat_id}|{back_hash}|{back_folder}"
            await browse_file_callback(bot, query)
        else:
            await query.message.edit_text(
                "⏹ **VC Stream Stopped**\n\n"
                "Use /browse to start browsing again.",
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        LOGGER.error(f"VC stop error: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)

