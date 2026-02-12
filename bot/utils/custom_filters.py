"""
Custom Pyrogram filters and user step management for multi-stage flows (login, settings).
"""
from pyrogram import filters

# In-memory store for user steps: {user_id: {"step": str, "data": dict}}
_user_steps = {}


def set_user_step(user_id: int, step: str, data: dict = None):
    """Set the current step for a user in a multi-stage flow."""
    _user_steps[user_id] = {"step": step, "data": data or {}}


def get_user_step(user_id: int) -> dict:
    """Get the current step info for a user. Returns None if not in a flow."""
    return _user_steps.get(user_id)


def clear_user_step(user_id: int):
    """Remove user from any active flow."""
    _user_steps.pop(user_id, None)


def update_user_data(user_id: int, key: str, value):
    """Update a specific data field in the user's current step."""
    if user_id in _user_steps:
        _user_steps[user_id]["data"][key] = value


async def _login_in_progress_filter(_, __, message):
    """Check if the user is currently in a login flow."""
    if not message.from_user:
        return False
    step_info = get_user_step(message.from_user.id)
    return step_info is not None and step_info["step"].startswith("login_")


# Custom filter: matches when user is in login flow
login_in_progress = filters.create(_login_in_progress_filter, name="login_in_progress")


async def _settings_in_progress_filter(_, __, message):
    """Check if the user is currently in a settings input flow."""
    if not message.from_user:
        return False
    step_info = get_user_step(message.from_user.id)
    return step_info is not None and step_info["step"].startswith("settings_")


# Custom filter: matches when user is in settings input flow
settings_in_progress = filters.create(_settings_in_progress_filter, name="settings_in_progress")
