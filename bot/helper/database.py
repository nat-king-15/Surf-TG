from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
from bson import ObjectId
from bot.config import Telegram
import re


class Database:
    def __init__(self):
        MONGODB_URI = Telegram.DATABASE_URL
        self.mongo_client = AsyncIOMotorClient(MONGODB_URI)
        self.db = self.mongo_client["surftg"]
        self.collection = self.db["playlist"]
        self.config = self.db["config"]
        self.files = self.db["files"]
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
