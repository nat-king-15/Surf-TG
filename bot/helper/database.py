from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
from bson import ObjectId
from bot.config import Telegram
from datetime import datetime, timedelta
import re
import pytz


class Database:
    def __init__(self):
        MONGODB_URI = Telegram.DATABASE_URL
        self.mongo_client = AsyncIOMotorClient(MONGODB_URI)
        self.db = self.mongo_client[Telegram.MONGO_DB]
        self.collection = self.db["playlist"]
        self.config = self.db["config"]
        self.files = self.db["files"]
        # New collections for Save-Restricted-Content-Bot features
        self.users = self.db["users"]
        self.premium_users = self.db["premium_users"]
        self.user_settings = self.db["user_settings"]
        self.user_sessions = self.db["user_sessions"]
        self.daily_usage = self.db["daily_usage"]
        self.plans = self.db["plans"]
        # Indexes for browse performance - handled async separately or just defined here
        # Motor create_index is awaitable, but __init__ cannot be async.
        # We can rely on background index creation or call a setup method.
        # For now, let's just attempt creation in a fire-and-forget manner if possible,
        # but motor doesn't support that easily in sync init. 
        # Ideally, we should have an async init method.
        # However, for simplicity and since indexes likely exist, we'll skip explicit re-creation in __init__ 
        # or assume the user runs a migration script if needed. 
        # Actually, let's keep it but we'd need an event loop to run it.
        # To avoid breaking init, we will leave index creation to run later or just assume it's done.

    async def _create_indexes(self):
         await self.collection.create_index([("parent_folder", 1), ("type", 1), ("source_channel", 1)], background=True)
         await self.collection.create_index([("parent_folder", 1), ("type", 1), ("chat_id", 1)], background=True)
         await self.collection.create_index([("file_id", 1), ("chat_id", 1)], background=True)

    async def create_folder(self, parent_id, folder_name, thumbnail):
        folder = {"parent_folder": parent_id, "name": folder_name,
                  "thumbnail": thumbnail, "type": "folder"}
        await self.collection.insert_one(folder)

    async def delete(self, document_id):
        try:
            has_child_documents = await self.collection.count_documents(
                {'parent_folder': document_id}) > 0
            if has_child_documents:
                await self.collection.delete_many(
                    {'parent_folder': document_id})
            result = await self.collection.delete_one({'_id': ObjectId(document_id)})
            return result.deleted_count > 0
        except Exception as e:
            print(f'An error occurred: {e}')
            return False

    async def edit(self, id, name, thumbnail):
        result = await self.collection.update_one({"_id": ObjectId(id)}, {
            "$set": {"name": name, "thumbnail": thumbnail}})
        return result.modified_count > 0

    async def search_DbFolder(self, query):
        words = re.findall(r'\w+', query.lower())
        regex_pattern = '.*'.join(f'(?=.*{re.escape(word)})' for word in words)
        regex_query = {'$regex': f'.*{regex_pattern}.*', '$options': 'i'}
        myquery = {'type': 'folder', 'name': regex_query}
        cursor = self.collection.find(myquery).sort('_id', ASCENDING)
        return [{'_id': str(x['_id']), 'name': x['name']} for x in await cursor.to_list(length=None)]

    async def add_json(self, data):
        await self.collection.insert_many(data)

    async def get_Dbfolder(self, parent_id="root", page=1, per_page=50):
        query = {"parent_folder": parent_id, "type": "folder"} if parent_id != 'root' else {
            "parent_folder": 'root', "type": "folder"}
        if parent_id != 'root':
            offset = (int(page) - 1) * per_page
            cursor = self.collection.find(query).skip(offset).limit(per_page)
            return await cursor.to_list(length=per_page)
        else:
            cursor = self.collection.find(query)
            return await cursor.to_list(length=None)

    async def get_dbFiles(self, parent_id=None, page=1, per_page=50):
        query = {"parent_folder": parent_id, "type": "file"}
        offset = (int(page) - 1) * per_page
        cursor = self.collection.find(query).sort(
            'file_id', ASCENDING).skip(offset).limit(per_page)
        return await cursor.to_list(length=per_page)

    async def get_info(self, id):
        query = {'_id': ObjectId(id)}
        if document := await self.collection.find_one(query):
            return document.get('name', None)
        else:
            return None

    async def search_dbfiles(self, id, query, page=1, per_page=50):
        words = re.findall(r'\w+', query.lower())
        regex_pattern = '.*'.join(f'(?=.*{re.escape(word)})' for word in words)
        regex_query = {'$regex': f'.*{regex_pattern}.*', '$options': 'i'}
        query = {'type': 'file', 'parent_folder': id, 'name': regex_query}
        offset = (int(page) - 1) * per_page
        cursor = self.collection.find(query).sort(
            'file_id', ASCENDING).skip(offset).limit(per_page)
        return await cursor.to_list(length=per_page)

    async def update_config(self, theme, auth_channel):
        bot_id = Telegram.BOT_TOKEN.split(":", 1)[0]
        config = await self.config.find_one({"_id": bot_id})
        if config is None:
            result = await self.config.insert_one(
                {"_id": bot_id, "theme": theme, "auth_channel": auth_channel})
            return result.inserted_id is not None
        else:
            result = await self.config.update_one({"_id": bot_id}, {
                "$set": {"theme": theme, "auth_channel": auth_channel}})
            return result.modified_count > 0

    async def get_variable(self, key):
        bot_id = Telegram.BOT_TOKEN.split(":", 1)[0]
        config = await self.config.find_one({"_id": bot_id})
        return config.get(key) if config is not None else None

    async def update_variable(self, key, value):
        bot_id = Telegram.BOT_TOKEN.split(":", 1)[0]
        config = await self.config.find_one({"_id": bot_id})
        if config is None:
            # Create config with this key
            result = await self.config.insert_one(
                {"_id": bot_id, key: value})
            return result.inserted_id is not None
        else:
            # Update existing config
            result = await self.config.update_one({"_id": bot_id}, {
                "$set": {key: value}})
            return result.modified_count > 0

    async def list_tgfiles(self, id, page=1, per_page=50):
        query = {'chat_id': id}
        offset = (int(page) - 1) * per_page
        cursor = self.files.find(query).sort(
            'msg_id', ASCENDING).skip(offset).limit(per_page)
        return await cursor.to_list(length=per_page)

    async def add_tgfiles(self, chat_id, file_id, hash, name, size, file_type):
        if fetch_old := await self.files.find_one({"chat_id": chat_id, "hash": hash}):
            return
        file = {"chat_id": chat_id, "msg_id": file_id,
                "hash": hash, "title": name, "size": size, "type": file_type}
        await self.files.insert_one(file)


    async def search_tgfiles(self, id, query, page=1, per_page=50):
        words = re.findall(r'\w+', query.lower())
        regex_pattern = '.*'.join(f'(?=.*{re.escape(word)})' for word in words)
        regex_query = {'$regex': f'.*{regex_pattern}.*', '$options': 'i'}
        query = {'chat_id': id, 'title': regex_query}
        offset = (int(page) - 1) * per_page
        cursor = self.files.find(query).sort(
            'msg_id', ASCENDING).skip(offset).limit(per_page)
        return await cursor.to_list(length=per_page)
    
    async def add_btgfiles(self, data):
        if data:
            await self.files.insert_many(data)

    async def get_or_create_folder(self, parent_id: str, folder_name: str, channel_id: str = None) -> str:
        """
        Get existing folder or create new one and return its ID.
        
        Args:
            parent_id: Parent folder ID or "root"
            folder_name: Name of the folder to find/create
            channel_id: Optional source channel ID
            
        Returns:
            String ID of the folder (ObjectId as string)
        """
        # Check if folder already exists
        query = {"parent_folder": parent_id, "name": folder_name, "type": "folder"}
        existing = await self.collection.find_one(query)
        
        if existing:
            return str(existing['_id'])
        
        # Create new folder
        folder = {
            "parent_folder": parent_id,
            "name": folder_name,
            "thumbnail": "",
            "type": "folder",
            "auto_created": True  # Mark as auto-created from Topic
        }
        if channel_id:
            folder["source_channel"] = channel_id
            
        result = await self.collection.insert_one(folder)
        return str(result.inserted_id)

    async def add_tgfile_with_folder(self, chat_id, file_id, hash, name, size, file_type, folder_id=None):
        """
        Add file to database with optional topic folder reference.
        Also adds to playlist collection if folder_id is provided.
        """
        # Add to files collection (existing behavior)
        if fetch_old := await self.files.find_one({"chat_id": chat_id, "hash": hash}):
            # File already exists in files collection, but may need to add to playlist
            pass
        else:
            file = {"chat_id": chat_id, "msg_id": file_id,
                    "hash": hash, "title": name, "size": size, "type": file_type}
            if folder_id:
                file["topic_folder_id"] = folder_id
            await self.files.insert_one(file)
        
        # Also add to playlist collection for folder view if folder_id provided
        if folder_id:
            existing_in_playlist = await self.collection.find_one({
                "chat_id": chat_id, "file_id": int(file_id), "parent_folder": folder_id, "type": "file"
            })
            if not existing_in_playlist:
                # Thumbnail URL from the channel's thumbnail API
                thumbnail = f"/api/thumb/{chat_id}?id={file_id}"
                playlist_file = {
                    "chat_id": chat_id,
                    "parent_folder": folder_id,
                    "file_id": int(file_id),
                    "hash": hash,
                    "name": name,
                    "size": size,
                    "file_type": file_type,
                    "thumbnail": thumbnail,
                    "type": "file"
                }
                await self.collection.insert_one(playlist_file)

    async def get_topic_index(self, chat_id):
        """
        Build topic folder hierarchy with first msg_id for Telegram channel index.
        Returns dict: {folder_id: {name, parent_id, first_msg_id, children: []}}
        """
        # Get all auto-created folders for this channel
        cursor = self.collection.find({
            "source_channel": chat_id, 
            "auto_created": True, 
            "type": "folder"
        })
        folders = await cursor.to_list(length=None)
        
        # Build folder map
        folder_map = {}
        for f in folders:
            fid = str(f['_id'])
            folder_map[fid] = {
                "name": f['name'],
                "parent_id": f['parent_folder'],
                "first_msg_id": None,
                "file_count": 0,
                "total_files": 0,  # includes children's files
                "children": []
            }
        
        # Get all files with topic_folder_id for this channel
        cursor = self.files.find({
            "chat_id": chat_id,
            "topic_folder_id": {"$exists": True}
        }).sort("msg_id", ASCENDING)
        files = await cursor.to_list(length=None)
        
        # Assign first_msg_id to each folder
        for file_doc in files:
            folder_id = file_doc.get("topic_folder_id")
            if folder_id in folder_map:
                folder_map[folder_id]["file_count"] += 1
                if folder_map[folder_id]["first_msg_id"] is None:
                    folder_map[folder_id]["first_msg_id"] = file_doc["msg_id"]
        
        # Build parent-child relationships
        for fid, fdata in folder_map.items():
            parent = fdata["parent_id"]
            if parent in folder_map:
                folder_map[parent]["children"].append(fid)
        
        # Propagate first_msg_id up: if parent has no first_msg_id, use child's
        def propagate_up(fid):
            fdata = folder_map[fid]
            earliest_msg = fdata["first_msg_id"]
            total = fdata["file_count"]
            
            for child_id in fdata["children"]:
                child_msg, child_total = propagate_up(child_id)
                total += child_total
                if child_msg is not None:
                    if earliest_msg is None or int(child_msg) < int(earliest_msg):
                        earliest_msg = child_msg
            
            fdata["first_msg_id"] = earliest_msg
            fdata["total_files"] = total
            return earliest_msg, total
        
        # Find root folders (parent_id = "root")
        root_folders = [fid for fid, fdata in folder_map.items() if fdata["parent_id"] == "root"]
        
        # Propagate from roots
        for root_id in root_folders:
            propagate_up(root_id)
        
        return folder_map, root_folders

    async def get_bot_items(self, parent_id="root", channel_id=None, page=1, per_page=8):
        """
        Get folders + files for inline keyboard, folders first, with correct pagination.
        Returns (folders_list, files_list, has_more, total_folders, total_files, video_count, pdf_count).
        """
        folder_query = {"parent_folder": parent_id, "type": "folder"}
        file_query = {"parent_folder": parent_id, "type": "file"}
        if channel_id:
            folder_query["source_channel"] = channel_id
            file_query["chat_id"] = channel_id

        total_folders = await self.collection.count_documents(folder_query)
        total_files = await self.collection.count_documents(file_query)
        total_items = total_folders + total_files

        # Count videos and PDFs separately
        video_query = {**file_query, "file_type": {"$regex": "video", "$options": "i"}}
        pdf_query = {**file_query, "file_type": {"$regex": "pdf", "$options": "i"}}
        video_count = await self.collection.count_documents(video_query)
        pdf_count = await self.collection.count_documents(pdf_query)

        offset = (int(page) - 1) * per_page
        folders = []
        files = []

        if offset < total_folders:
            folder_limit = min(per_page, total_folders - offset)
            cursor = self.collection.find(folder_query).sort('_id', ASCENDING).skip(offset).limit(folder_limit)
            folders = await cursor.to_list(length=folder_limit)
            remaining = per_page - len(folders)
            if remaining > 0 and total_files > 0:
                cursor = self.collection.find(file_query).sort('file_id', ASCENDING).limit(remaining)
                files = await cursor.to_list(length=remaining)
        elif offset < total_items:
            file_skip = offset - total_folders
            cursor = self.collection.find(file_query).sort('file_id', ASCENDING).skip(file_skip).limit(per_page)
            files = await cursor.to_list(length=per_page)

        has_more = (offset + per_page) < total_items
        return folders, files, has_more, total_folders, total_files, video_count, pdf_count

    async def get_folder_with_parent(self, folder_id):
        """Get folder name + parent info in a single query."""
        doc = await self.collection.find_one({'_id': ObjectId(folder_id)})
        if doc:
            return doc.get('name', 'Folder'), doc.get('parent_folder', 'root'), doc.get('source_channel', None)
        return 'Folder', 'root', None

    async def get_parent_folder(self, folder_id):
        """Get parent folder ID for back navigation."""
        query = {'_id': ObjectId(folder_id)}
        doc = await self.collection.find_one(query)
        if doc:
            return doc.get('parent_folder', 'root'), doc.get('source_channel', None)
        return 'root', None

    async def count_folder_children(self, folder_id, channel_id=None):
        """Count sub-folders and files in a folder."""
        folder_query = {"parent_folder": folder_id, "type": "folder"}
        file_query = {"parent_folder": folder_id, "type": "file"}
        if channel_id:
            folder_query["source_channel"] = channel_id
        folders = await self.collection.count_documents(folder_query)
        files = await self.collection.count_documents(file_query)
        return folders, files

    # ═══════════════════════════════════════════════════════════════════
    # User Management
    # ═══════════════════════════════════════════════════════════════════

    async def save_user(self, user_id: int, name: str = ""):
        """Upsert user record."""
        await self.users.update_one(
            {"_id": user_id},
            {"$set": {"name": name, "last_seen": datetime.utcnow()},
             "$setOnInsert": {"joined": datetime.utcnow()}},
            upsert=True
        )

    async def get_user(self, user_id: int) -> dict:
        """Fetch user data."""
        return await self.users.find_one({"_id": user_id})

    async def get_all_users_count(self) -> int:
        """Get total registered users."""
        return await self.users.count_documents({})

    # ═══════════════════════════════════════════════════════════════════
    # Premium Management
    # ═══════════════════════════════════════════════════════════════════

    async def is_premium(self, user_id: int) -> bool:
        """Check if user has active premium."""
        doc = await self.premium_users.find_one({"_id": user_id})
        if not doc:
            return False
        expiry = doc.get("expiry")
        if expiry and expiry > datetime.utcnow():
            return True
        # Expired — clean up
        await self.premium_users.delete_one({"_id": user_id})
        return False

    async def add_premium(self, user_id: int, duration_value: int, duration_unit: str):
        """
        Grant premium to a user. Returns (True, expiry_date) or (False, error_msg).
        Valid units: min, hours, days, weeks, month, year, decades.
        """
        try:
            now = datetime.utcnow()
            unit_map = {
                "min": timedelta(minutes=duration_value),
                "hours": timedelta(hours=duration_value),
                "days": timedelta(days=duration_value),
                "weeks": timedelta(weeks=duration_value),
                "month": timedelta(days=30 * duration_value),
                "year": timedelta(days=365 * duration_value),
                "decades": timedelta(days=3650 * duration_value),
            }
            delta = unit_map.get(duration_unit)
            if delta is None:
                return False, "Invalid duration unit"

            expiry = now + delta
            await self.premium_users.update_one(
                {"_id": user_id},
                {"$set": {
                    "expiry": expiry,
                    "granted_at": now,
                    "expireAt": expiry,
                }},
                upsert=True,
            )
            # TTL index for auto-cleanup of expired docs
            await self.premium_users.create_index("expireAt", expireAfterSeconds=0)
            return True, expiry
        except Exception as e:
            return False, str(e)

    async def remove_premium(self, user_id: int):
        """Revoke premium from a user."""
        await self.premium_users.delete_one({"_id": user_id})

    async def get_premium_expiry(self, user_id: int):
        """Get premium expiry datetime. Returns None if not premium."""
        doc = await self.premium_users.find_one({"_id": user_id})
        if doc:
            return doc.get("expiry")
        return None

    async def transfer_premium(self, from_id: int, to_id: int):
        """Transfer remaining premium time. Returns (True, expiry) or (False, None)."""
        doc = await self.premium_users.find_one({"_id": from_id})
        if not doc or not doc.get("expiry"):
            return False, None
        expiry = doc["expiry"]
        if expiry <= datetime.utcnow():
            return False, None
        # Remove from source
        await self.premium_users.delete_one({"_id": from_id})
        # Grant to target with same expiry
        await self.premium_users.update_one(
            {"_id": to_id},
            {"$set": {
                "expiry": expiry,
                "granted_at": datetime.utcnow(),
                "expireAt": expiry,
                "transferred_from": from_id,
            }},
            upsert=True,
        )
        return True, expiry

    async def get_premium_users_count(self) -> int:
        """Get count of active premium users."""
        return await self.premium_users.count_documents(
            {"expiry": {"$gt": datetime.utcnow()}}
        )

    async def get_all_premium_users(self) -> list:
        """Get list of all active premium users."""
        cursor = self.premium_users.find(
            {"expiry": {"$gt": datetime.utcnow()}}
        )
        return await cursor.to_list(length=None)

    # ═══════════════════════════════════════════════════════════════════
    # User Settings
    # ═══════════════════════════════════════════════════════════════════

    async def get_settings(self, user_id: int) -> dict:
        """Get user settings. Returns defaults if none set."""
        doc = await self.user_settings.find_one({"_id": user_id})
        defaults = {
            "chat_id": None,
            "rename_tag": "",
            "caption": "",
            "replacements": {},
            "delete_words": [],
            "thumbnail": None,
        }
        if doc:
            defaults.update({k: v for k, v in doc.items() if k != "_id"})
        return defaults

    async def update_setting(self, user_id: int, key: str, value):
        """Update a single user setting."""
        await self.user_settings.update_one(
            {"_id": user_id},
            {"$set": {key: value}},
            upsert=True
        )

    async def clear_setting(self, user_id: int, key: str):
        """Remove a single user setting (reset to default)."""
        await self.user_settings.update_one(
            {"_id": user_id},
            {"$unset": {key: ""}}
        )

    # ═══════════════════════════════════════════════════════════════════
    # Session & Bot Token Storage
    # ═══════════════════════════════════════════════════════════════════

    async def save_session(self, user_id: int, encrypted_session: str):
        """Store encrypted user session string."""
        await self.user_sessions.update_one(
            {"_id": user_id},
            {"$set": {"session": encrypted_session, "updated_at": datetime.utcnow()}},
            upsert=True
        )

    async def get_session(self, user_id: int) -> str:
        """Get encrypted session string. Returns None if not set."""
        doc = await self.user_sessions.find_one({"_id": user_id})
        if doc:
            return doc.get("session")
        return None

    async def delete_session(self, user_id: int):
        """Delete user session."""
        await self.user_sessions.update_one(
            {"_id": user_id},
            {"$unset": {"session": ""}}
        )

    async def save_bot_token(self, user_id: int, token: str):
        """Store custom bot token for a user."""
        await self.user_sessions.update_one(
            {"_id": user_id},
            {"$set": {"bot_token": token}},
            upsert=True
        )

    async def get_bot_token(self, user_id: int) -> str:
        """Get custom bot token. Returns None if not set."""
        doc = await self.user_sessions.find_one({"_id": user_id})
        if doc:
            return doc.get("bot_token")
        return None

    async def delete_bot_token(self, user_id: int):
        """Delete custom bot token."""
        await self.user_sessions.update_one(
            {"_id": user_id},
            {"$unset": {"bot_token": ""}}
        )

    # ═══════════════════════════════════════════════════════════════════
    # Daily Usage Tracking
    # ═══════════════════════════════════════════════════════════════════

    async def increment_usage(self, user_id: int) -> int:
        """Increment daily usage counter. Returns new count."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        result = await self.daily_usage.find_one_and_update(
            {"_id": f"{user_id}_{today}"},
            {"$inc": {"count": 1}},
            upsert=True,
            return_document=True
        )
        return result.get("count", 1) if result else 1

    async def get_usage(self, user_id: int) -> int:
        """Get today's usage count for a user."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        doc = await self.daily_usage.find_one({"_id": f"{user_id}_{today}"})
        return doc.get("count", 0) if doc else 0

    async def get_remaining_limit(self, user_id: int) -> int:
        """
        Get remaining downloads for today.
        Returns -1 for unlimited (premium with 0 limit).
        """
        is_prem = await self.is_premium(user_id)
        limit = Telegram.PREMIUM_LIMIT if is_prem else Telegram.FREEMIUM_LIMIT

        if limit == 0:
            return -1  # Unlimited

        used = await self.get_usage(user_id)
        return max(0, limit - used)

    async def is_channel_bound_to_premium(self, chat_id: int) -> bool:
        """Check if chat_id is linked to any active premium user's settings."""
        # Chat ID is stored as string in settings
        chat_id_str = str(chat_id)
        # Find all users who have this chat_id in settings
        cursor = self.user_settings.find({"chat_id": chat_id_str})
        async for setting in cursor:
            user_id = setting["_id"]
            if await self.is_premium(user_id):
                return True
        return False

    # ═══════════════════════════════════════════════════════════════════
    # Plan Management (Dynamic)
    # ═══════════════════════════════════════════════════════════════════

    async def get_plans(self) -> dict:
        """Get all available plans. Returns {key: plan_data}."""
        cursor = self.db.plans.find({})
        plans = {}
        async for plan in cursor:
            plans[plan["_id"]] = {
                "l": plan["label"],
                "du": plan["duration"],
                "u": plan["unit"],
                "p": plan["price"],  # Price in text/INR
            }
        return plans

    async def add_plan(self, key: str, duration: int, unit: str, price: str, label: str):
        """Add or update a plan."""
        await self.db.plans.update_one(
            {"_id": key},
            {"$set": {
                "duration": duration,
                "unit": unit,
                "price": price,
                "label": label
            }},
            upsert=True
        )

    async def delete_plan(self, key: str):
        """Delete a plan."""
        result = await self.db.plans.delete_one({"_id": key})
        return result.deleted_count > 0
