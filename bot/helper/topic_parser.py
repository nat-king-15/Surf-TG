"""
Topic Parser - Parse Topic hierarchy from channel captions
Extracts folder structure like "Topic: Home -> ENGLISH LIVE BATCH -> ARTICLE"
"""
import re
from typing import Optional


def parse_topic_hierarchy(caption: str) -> Optional[list]:
    """
    Parse Topic field from caption and return folder path list.
    
    Args:
        caption: Message caption containing Topic field
        
    Returns:
        List of folder names from parent to child, or None if no Topic found
        Example: ["Home", "ENGLISH LIVE BATCH", "ARTICLE"]
    """
    if not caption:
        return None
    
    # Match "Topic:" or "Topic :" followed by the path
    topic_match = re.search(r'Topic\s*:\s*(.+?)(?:\n|$)', caption, re.IGNORECASE)
    if not topic_match:
        return None
    
    topic_line = topic_match.group(1).strip()
    if not topic_line:
        return None
    
    # Split by " -> " delimiter
    folders = [folder.strip() for folder in topic_line.split('->')]
    folders = [f for f in folders if f]  # Remove empty strings
    
    return folders if folders else None


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
