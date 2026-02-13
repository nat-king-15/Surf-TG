"""
Topic Parser - Parse Topic hierarchy from channel captions
Extracts folder structure like "Topic: Home -> ENGLISH LIVE BATCH -> ARTICLE"
"""
import re
from typing import Optional


def parse_topic_hierarchy(caption: str) -> Optional[list]:
    """
    Parse Topic field from caption and return folder path list.
    
    Updated Logic:
    1. Extract 'Batch: ...' as root folder.
    2. Extract 'Topic: ...' as subfolders.
    3. Remove 'Home' from Topic path if present at start.
    
    Args:
        caption: Message caption containing Topic/Batch fields
        
    Returns:
        List of folder names from parent to child, or None if no structure found
        Example: ["My Batch 2024", "ENGLISH", "ARTICLE"]
    """
    if not caption:
        return None
    
    final_path = []
    
    # 1. Parse Batch Name (Root Folder)
    # Look for "Batch:" followed by text until newline
    batch_match = re.search(r'Batch\s*:\s*(.+?)(?:\n|$)', caption, re.IGNORECASE)
    if batch_match:
        batch_name = batch_match.group(1).strip()
        if batch_name:
            final_path.append(batch_name)
    
    # 2. Parse Topic Hierarchy (Subfolders)
    # Look for "Topic:" followed by text until newline
    topic_match = re.search(r'Topic\s*:\s*(.+?)(?:\n|$)', caption, re.IGNORECASE)
    if topic_match:
        topic_line = topic_match.group(1).strip()
        if topic_line:
            # Split by "->" separator
            topic_folders = [f.strip() for f in topic_line.split('->')]
            topic_folders = [f for f in topic_folders if f]  # Remove empty strings
            
            # Remove "Home" if it is the first folder
            if topic_folders and topic_folders[0].lower() == "home":
                topic_folders.pop(0)
            
            final_path.extend(topic_folders)
            
    return final_path if final_path else None


async def get_or_create_folder_path(db, folder_path: list, channel_id: str = None) -> Optional[str]:
    """
    Create folder hierarchy if not exists and return the leaf folder ID.
    
    Args:
        db: Database instance
        folder_path: List of folder names from parent to child
        channel_id: Optional channel ID for tracking source
        
    Returns:
        ObjectId string of the leaf (deepest) folder
    """
    if not folder_path:
        return None
    
    parent_id = "root"
    
    for folder_name in folder_path:
        # Get or create this folder under current parent
        folder_id = await db.get_or_create_folder(parent_id, folder_name, channel_id)
        parent_id = folder_id
    
    return parent_id  # Return the final folder ID
