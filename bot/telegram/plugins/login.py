"""
Login plugin: User session management via Pyrogram.
Commands: /login, /logout, /setbot, /rembot
Multi-step conversation flow for phone → code → password authentication.
"""
import logging
from pyrogram import filters, Client
from pyrogram.types import Message
from pyrogram.errors import (
    PhoneCodeInvalid,
    PhoneCodeExpired,
    SessionPasswordNeeded,
    PasswordHashInvalid,
    FloodWait,
)

from bot.telegram import StreamBot
from bot.config import Telegram
from bot.helper.database import Database
from bot.utils.encrypt import encrypt, decrypt
from bot.utils.custom_filters import (
    login_in_progress,
    set_user_step,
    get_user_step,
    clear_user_step,
    update_user_data,
)

LOGGER = logging.getLogger(__name__)
db = Database()


# ═══════════════════════════════════════════════════════════════════
# /login - Start login flow
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("login") & filters.private)
async def login_start(bot: Client, message: Message):
    """Start the login flow — ask for phone number."""
    user_id = message.from_user.id

    # Check if already logged in
    existing = await db.get_session(user_id)
    if existing:
        await message.reply(
            "✅ You are already logged in.\n\n"
            "Use /logout to log out first, then /login again.",
        )
        return

    set_user_step(user_id, "login_phone")
    await message.reply(
        "📱 **Login to your Telegram Account**\n\n"
        "Please send your phone number with country code.\n"
        "Example: `+919876543210`\n\n"
        "Send /cancel to abort.",
    )


# ═══════════════════════════════════════════════════════════════════
# Handle login conversation steps
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.private & login_in_progress & ~filters.command(["cancel", "login", "logout"]))
async def handle_login_steps(bot: Client, message: Message):
    """Handle multi-step login conversation."""
    user_id = message.from_user.id
    step_info = get_user_step(user_id)

    if not step_info:
        return

    step = step_info["step"]
    data = step_info["data"]

    # ─── Step 1: Phone number ───
    if step == "login_phone":
        phone = message.text.strip()
        if not phone.startswith("+"):
            await message.reply("❌ Please include country code (e.g. `+919876543210`)")
            return

        status_msg = await message.reply("📲 Sending verification code...")

        try:
            # Create a temporary Pyrogram client for this user
            user_client = Client(
                name=f"user_{user_id}",
                api_id=Telegram.API_ID,
                api_hash=Telegram.API_HASH,
                in_memory=True,
            )
            await user_client.connect()

            sent_code = await user_client.send_code(phone)

            update_user_data(user_id, "phone", phone)
            update_user_data(user_id, "phone_code_hash", sent_code.phone_code_hash)
            update_user_data(user_id, "client", user_client)
            set_user_step(user_id, "login_code", data={
                "phone": phone,
                "phone_code_hash": sent_code.phone_code_hash,
                "client": user_client,
            })

            await status_msg.edit_text(
                "✅ Code sent!\n\n"
                "📩 Please enter the verification code you received.\n"
                "Format: `1 2 3 4 5` (with spaces to avoid Telegram blocking)\n\n"
                "Send /cancel to abort."
            )

        except FloodWait as e:
            await status_msg.edit_text(f"⚠️ FloodWait: Please try again after {e.value} seconds.")
            clear_user_step(user_id)
        except Exception as e:
            LOGGER.error(f"Login phone error for {user_id}: {e}")
            await status_msg.edit_text(f"❌ Error: {str(e)}")
            clear_user_step(user_id)

    # ─── Step 2: Verification code ───
    elif step == "login_code":
        code = message.text.strip().replace(" ", "").replace("-", "")
        user_client = data.get("client")
        phone = data.get("phone")
        phone_code_hash = data.get("phone_code_hash")

        if not user_client or not phone:
            await message.reply("❌ Session expired. Please /login again.")
            clear_user_step(user_id)
            return

        status_msg = await message.reply("🔐 Verifying code...")

        try:
            await user_client.sign_in(
                phone_number=phone,
                phone_code_hash=phone_code_hash,
                phone_code=code,
            )

            # Success — export session
            session_string = await user_client.export_session_string()
            encrypted = encrypt(session_string)
            await db.save_session(user_id, encrypted)
            await user_client.disconnect()

            clear_user_step(user_id)
            await status_msg.edit_text(
                "✅ **Login Successful!**\n\n"
                "Your session has been saved securely (encrypted).\n"
                "You can now use features that require your account.\n\n"
                "Use /logout to remove your session."
            )

        except SessionPasswordNeeded:
            # 2FA is enabled
            set_user_step(user_id, "login_password", data=data)
            await status_msg.edit_text(
                "🔑 **Two-Factor Authentication**\n\n"
                "Your account has 2FA enabled.\n"
                "Please enter your password.\n\n"
                "Send /cancel to abort."
            )

        except PhoneCodeInvalid:
            await status_msg.edit_text(
                "❌ Invalid code. Please try again.\n"
                "Send the code with spaces: `1 2 3 4 5`"
            )

        except PhoneCodeExpired:
            await status_msg.edit_text("❌ Code expired. Please /login again.")
            if user_client:
                await user_client.disconnect()
            clear_user_step(user_id)

        except Exception as e:
            LOGGER.error(f"Login code error for {user_id}: {e}")
            await status_msg.edit_text(f"❌ Error: {str(e)}")
            if user_client:
                await user_client.disconnect()
            clear_user_step(user_id)

    # ─── Step 3: 2FA Password ───
    elif step == "login_password":
        password = message.text.strip()
        user_client = data.get("client")

        if not user_client:
            await message.reply("❌ Session expired. Please /login again.")
            clear_user_step(user_id)
            return

        status_msg = await message.reply("🔐 Verifying password...")

        try:
            await user_client.check_password(password)

            # Success — export session
            session_string = await user_client.export_session_string()
            encrypted = encrypt(session_string)
            await db.save_session(user_id, encrypted)
            await user_client.disconnect()

            clear_user_step(user_id)

            # Delete the password message for security
            try:
                await message.delete()
            except Exception:
                pass

            await status_msg.edit_text(
                "✅ **Login Successful!**\n\n"
                "Your session has been saved securely (encrypted).\n"
                "You can now use features that require your account.\n\n"
                "Use /logout to remove your session."
            )

        except PasswordHashInvalid:
            await status_msg.edit_text(
                "❌ Wrong password. Please try again.\n\n"
                "Send /cancel to abort."
            )

        except Exception as e:
            LOGGER.error(f"Login password error for {user_id}: {e}")
            await status_msg.edit_text(f"❌ Error: {str(e)}")
            if user_client:
                await user_client.disconnect()
            clear_user_step(user_id)


# ═══════════════════════════════════════════════════════════════════
# /cancel - Cancel login flow
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("cancel") & filters.private & login_in_progress)
async def cancel_login(bot: Client, message: Message):
    """Cancel the active login flow."""
    user_id = message.from_user.id
    step_info = get_user_step(user_id)

    # Disconnect any active client
    if step_info and step_info.get("data", {}).get("client"):
        try:
            await step_info["data"]["client"].disconnect()
        except Exception:
            pass

    clear_user_step(user_id)
    await message.reply("❌ Login cancelled.")


# ═══════════════════════════════════════════════════════════════════
# /logout - Remove saved session
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("logout") & filters.private)
async def logout(bot: Client, message: Message):
    """Terminate the Telegram session and delete from DB."""
    user_id = message.from_user.id
    existing = await db.get_session(user_id)

    if not existing:
        await message.reply("ℹ️ You are not logged in.")
        return

    status_msg = await message.reply("🔄 Logging out...")

    try:
        # Decrypt and terminate the actual Telegram session
        session_string = decrypt(existing)
        temp_client = Client(
            name=f"logout_{user_id}",
            api_id=Telegram.API_ID,
            api_hash=Telegram.API_HASH,
            session_string=session_string,
            in_memory=True,
            no_updates=True,
        )
        await temp_client.start()
        await temp_client.log_out()
    except Exception as e:
        LOGGER.warning(f"Could not terminate session for {user_id}: {e}")

    # Always remove from DB regardless of termination success
    await db.delete_session(user_id)
    await status_msg.edit_text(
        "✅ **Logged out successfully.**\n\n"
        "Your Telegram session has been terminated and deleted from our database."
    )


# ═══════════════════════════════════════════════════════════════════
# /setbot - Set custom bot token
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("setbot") & filters.private)
async def set_bot_token(bot: Client, message: Message):
    """Set a custom bot token for forwarding."""
    user_id = message.from_user.id

    if len(message.command) < 2:
        await message.reply(
            "📝 **Set Custom Bot Token**\n\n"
            "Usage: `/setbot <bot_token>`\n"
            "Example: `/setbot 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`\n\n"
            "Get a token from @BotFather."
        )
        return

    token = message.command[1].strip()

    # Basic validation
    if ":" not in token or len(token) < 30:
        await message.reply("❌ Invalid bot token format.")
        return

    # Test the token
    try:
        test_client = Client(
            name=f"test_{user_id}",
            api_id=Telegram.API_ID,
            api_hash=Telegram.API_HASH,
            bot_token=token,
            in_memory=True,
            no_updates=True,
        )
        await test_client.start()
        bot_info = test_client.me
        await test_client.stop()

        await db.save_bot_token(user_id, token)

        # Delete the message containing the token for security
        try:
            await message.delete()
        except Exception:
            pass

        await bot.send_message(
            user_id,
            f"✅ **Bot token set!**\n\n"
            f"Bot: @{bot_info.username}\n"
            f"Files will be forwarded via this bot.\n\n"
            f"Use /rembot to remove it."
        )

    except Exception as e:
        await message.reply(f"❌ Invalid token: {str(e)}")


# ═══════════════════════════════════════════════════════════════════
# /rembot - Remove custom bot token
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command("rembot") & filters.private)
async def remove_bot_token(bot: Client, message: Message):
    """Remove the custom bot token."""
    user_id = message.from_user.id
    existing = await db.get_bot_token(user_id)

    if not existing:
        await message.reply("ℹ️ No custom bot token set.")
        return

    await db.delete_bot_token(user_id)
    await message.reply("✅ Custom bot token removed.")
