import os
import sys
import json
import asyncio
import logging
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


async def _run_shell(cmd: str, cwd: str = None) -> tuple:
    """Run shell command asynchronously. Returns (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd or os.getcwd(),
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


@StreamBot.on_message(filters.command('update') & filters.private & owner_filter)
async def update_bot(bot: Client, message: Message):
    """Pull latest code from GitHub, install deps, and restart the bot."""
    if Telegram.OWNER_ID == 0:
        await message.reply("❌ `OWNER_ID` is not set in config.env!", parse_mode=ParseMode.MARKDOWN)
        return

    repo = Telegram.UPSTREAM_REPO
    branch = Telegram.UPSTREAM_BRANCH

    if not repo:
        await message.reply("❌ `UPSTREAM_REPO` is not set in config!", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await message.reply("📥 **Pulling latest code from GitHub...**", parse_mode=ParseMode.MARKDOWN)

    # Step 1: Ensure git remote 'origin' points to the correct repo
    try:
        # Check if git is initialized
        rc, _, _ = await _run_shell("git rev-parse --is-inside-work-tree")
        if rc != 0:
            # Not a git repo — initialize
            await _run_shell("git init -q")
            await _run_shell(f"git remote add origin {repo}")
            LOGGER.info("Initialized git repo and added origin remote")
        else:
            # Git repo exists — ensure origin is correct
            rc, current_url, _ = await _run_shell("git remote get-url origin")
            if rc != 0:
                # origin doesn't exist, add it
                await _run_shell(f"git remote add origin {repo}")
            elif current_url.strip() != repo:
                # origin points to wrong repo, update it
                await _run_shell(f"git remote set-url origin {repo}")
                LOGGER.info(f"Updated origin remote: {current_url.strip()} → {repo}")

        # Fetch and hard reset
        rc, stdout, stderr = await _run_shell(f"git fetch origin {branch} --depth=1")
        if rc != 0:
            await status_msg.edit_text(
                f"❌ **Git fetch failed!**\n```\n{stderr[:500]}\n```",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        rc, stdout, stderr = await _run_shell(f"git reset --hard origin/{branch}")
        if rc != 0:
            await status_msg.edit_text(
                f"❌ **Git reset failed!**\n```\n{stderr[:500]}\n```",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        await status_msg.edit_text(
            "✅ **Code updated!**\n\n📦 **Installing dependencies...**",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ **Git error:** `{str(e)}`", parse_mode=ParseMode.MARKDOWN)
        return

    # Step 2: Install dependencies (async)
    try:
        if os.path.exists("venv/bin/pip"):
            pip_cmd = "./venv/bin/pip install -r requirements.txt --quiet"
        elif os.path.exists("venv/Scripts/pip.exe"):
            pip_cmd = "venv\\Scripts\\pip install -r requirements.txt --quiet"
        else:
            pip_cmd = f"{sys.executable} -m pip install -r requirements.txt --quiet"

        rc, _, stderr = await _run_shell(pip_cmd)
        if rc != 0:
            LOGGER.warning(f"Pip install warning: {stderr[:200]}")
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

    # Step 5: Properly stop the bot, then restart
    await asyncio.sleep(1)

    # Determine the correct python executable
    if os.path.exists("venv/bin/python3"):
        python = os.path.abspath("venv/bin/python3")
    elif os.path.exists("venv/Scripts/python.exe"):
        python = os.path.abspath("venv\\Scripts\\python.exe")
    else:
        python = sys.executable

    # Stop the bot client gracefully before exec
    try:
        await bot.stop()
    except Exception:
        pass

    # Replace current process with fresh one
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


# ═══════════════════════════════════════════════════════════════════
# /status - Show bot config & debug info
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command('status') & filters.private & owner_filter)
async def status_command(bot: Client, message: Message):
    """Show current bot config values for debugging."""
    from bot import __version__
    
    base_url = Telegram.BASE_URL or "(empty)"
    env_base = os.getenv("BASE_URL", "(not set)")
    
    await message.reply(
        f"🤖 **Surf-TG v{__version__}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌐 **BASE\\_URL (config):** `{base_url}`\n"
        f"🌐 **BASE\\_URL (env):** `{env_base}`\n"
        f"🔌 **PORT:** `{Telegram.PORT}`\n"
        f"📺 **AUTH\\_CHANNEL:** `{Telegram.AUTH_CHANNEL}`\n"
        f"👤 **OWNER\\_ID:** `{Telegram.OWNER_ID}`\n"
        f"🔧 **WORKERS:** `{Telegram.WORKERS}`\n"
        f"🎨 **THEME:** `{Telegram.THEME}`\n",
        parse_mode=ParseMode.MARKDOWN
    )
