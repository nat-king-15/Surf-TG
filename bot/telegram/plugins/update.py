import os
import sys
import json
import asyncio
import logging
from subprocess import run as srun, PIPE
from pyrogram import filters, Client
from pyrogram.types import Message
from pyrogram.enums.parse_mode import ParseMode
from bot.config import Telegram
from bot.telegram import StreamBot

LOGGER = logging.getLogger(__name__)

UPDATE_FLAG_FILE = ".update_flag"


def is_owner(_, __, message: Message) -> bool:
    """Check if the message sender is the bot owner."""
    return message.from_user and message.from_user.id == Telegram.OWNER_ID


owner_filter = filters.create(is_owner)


@StreamBot.on_message(filters.command('update') & filters.private & owner_filter)
async def update_bot(bot: Client, message: Message):
    """Pull latest code from GitHub, install deps, and restart the bot."""
    if Telegram.OWNER_ID == 0:
        await message.reply("❌ `OWNER_ID` is not set in config.env!", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await message.reply("📥 **Pulling latest code from GitHub...**", parse_mode=ParseMode.MARKDOWN)

    # Step 1: Git Pull
    try:
        repo = Telegram.UPSTREAM_REPO
        branch = Telegram.UPSTREAM_BRANCH
        pull_cmd = f"git fetch origin && git reset --hard origin/{branch}"
        result = srun(pull_cmd, shell=True, capture_output=True, text=True, cwd=os.getcwd())

        if result.returncode != 0:
            # Try initializing git if not a repo
            init_cmd = (
                f"git init -q && "
                f"git remote add origin {repo} 2>/dev/null; "
                f"git fetch origin -q && "
                f"git reset --hard origin/{branch} -q"
            )
            result = srun(init_cmd, shell=True, capture_output=True, text=True, cwd=os.getcwd())

        if result.returncode == 0:
            await status_msg.edit_text(
                "✅ **Code updated!**\n\n📦 **Installing dependencies...**",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            error = result.stderr[:500] if result.stderr else "Unknown error"
            await status_msg.edit_text(
                f"❌ **Git pull failed!**\n```\n{error}\n```",
                parse_mode=ParseMode.MARKDOWN
            )
            return
    except Exception as e:
        await status_msg.edit_text(f"❌ **Git error:** `{str(e)}`", parse_mode=ParseMode.MARKDOWN)
        return

    # Step 2: Install dependencies
    try:
        # Detect if running in venv
        if os.path.exists("venv/bin/pip"):
            pip_cmd = "./venv/bin/pip install -r requirements.txt --quiet"
        else:
            pip_cmd = "pip install -r requirements.txt --quiet"

        pip_result = srun(pip_cmd, shell=True, capture_output=True, text=True, cwd=os.getcwd())

        if pip_result.returncode != 0:
            LOGGER.warning(f"Pip install warning: {pip_result.stderr[:200]}")
    except Exception as e:
        LOGGER.warning(f"Pip install error: {e}")

    # Step 3: Save update flag for post-restart notification
    flag_data = {
        "chat_id": message.chat.id,
        "message_id": status_msg.id
    }
    with open(UPDATE_FLAG_FILE, "w") as f:
        json.dump(flag_data, f)

    # Step 4: Show restarting status
    await status_msg.edit_text(
        "✅ **Code updated!**\n"
        "📦 **Dependencies installed!**\n\n"
        "🔄 **Restarting bot...**",
        parse_mode=ParseMode.MARKDOWN
    )

    LOGGER.info("Bot update triggered by owner. Restarting...")

    # Step 5: Restart the process
    await asyncio.sleep(1)

    # Determine the correct python executable
    if os.path.exists("venv/bin/python3"):
        python = "./venv/bin/python3"
    else:
        python = sys.executable

    os.execv(python, [python, "-m", "bot"])


@StreamBot.on_message(filters.command('update') & filters.private & ~owner_filter)
async def update_unauthorized(bot: Client, message: Message):
    """Respond to unauthorized /update attempts."""
    await message.reply("❌ You are not authorized to update this bot.", parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════
# /logs - View bot logs in Telegram
# ═══════════════════════════════════════════════════════════════════

LOG_FILE = "log.txt"


@StreamBot.on_message(filters.command('logs') & filters.private & owner_filter)
async def view_logs(bot: Client, message: Message):
    """
    Send bot logs to the owner.
    Usage:
      /logs        → last 50 lines as message
      /logs 100    → last 100 lines as message
      /logs file   → send full log.txt as document
    """
    if Telegram.OWNER_ID == 0:
        await message.reply("❌ `OWNER_ID` is not set in config.env!", parse_mode=ParseMode.MARKDOWN)
        return

    if not os.path.exists(LOG_FILE):
        await message.reply("❌ Log file not found.", parse_mode=ParseMode.MARKDOWN)
        return

    # Parse argument
    args = message.text.strip().split(maxsplit=1)
    arg = args[1].strip().lower() if len(args) > 1 else ""

    # /logs file → send as document
    if arg == "file":
        try:
            file_size = os.path.getsize(LOG_FILE)
            size_mb = file_size / (1024 * 1024)
            await message.reply_document(
                document=LOG_FILE,
                caption=f"📋 **Bot Logs**\n💾 Size: {size_mb:.2f} MB",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await message.reply(f"❌ Error sending log file: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    # /logs [N] → send last N lines as text (default 50)
    try:
        num_lines = int(arg) if arg.isdigit() else 50
        num_lines = min(num_lines, 200)  # cap at 200 to avoid flood
    except ValueError:
        num_lines = 50

    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        total = len(all_lines)
        tail = all_lines[-num_lines:]
        log_text = "".join(tail).strip()

        if not log_text:
            await message.reply("📋 Log file is empty.", parse_mode=ParseMode.MARKDOWN)
            return

        header = f"📋 **Bot Logs** (last {len(tail)} of {total} lines)\n━━━━━━━━━━━━━━━━━━\n\n"

        # Telegram message limit is ~4096 chars
        max_len = 4096 - len(header) - 20
        if len(log_text) > max_len:
            log_text = log_text[-max_len:]
            # Find first newline to avoid partial line
            nl = log_text.find('\n')
            if nl != -1:
                log_text = log_text[nl + 1:]
            header = f"📋 **Bot Logs** (truncated, last ~{len(tail)} lines)\n━━━━━━━━━━━━━━━━━━\n\n"

        await message.reply(
            f"{header}`{log_text}`",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        LOGGER.error(f"Error reading logs: {e}")
        await message.reply(f"❌ Error reading logs: `{e}`", parse_mode=ParseMode.MARKDOWN)


@StreamBot.on_message(filters.command('logs') & filters.private & ~owner_filter)
async def logs_unauthorized(bot: Client, message: Message):
    """Respond to unauthorized /logs attempts."""
    await message.reply("❌ You are not authorized to view logs.", parse_mode=ParseMode.MARKDOWN)
