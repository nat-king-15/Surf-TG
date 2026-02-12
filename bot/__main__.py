from asyncio import get_event_loop, sleep as asleep, gather
from traceback import format_exc
import json
import os

from aiohttp import web
from pyrogram import idle
from pyrogram.enums.parse_mode import ParseMode

from bot import __version__, LOGGER
from bot.config import Telegram
from bot.server import web_server
from bot.telegram import StreamBot, UserBot
from bot.telegram.clients import initialize_clients

loop = get_event_loop()

UPDATE_FLAG_FILE = ".update_flag"


async def _send_update_notification():
    """Check for update flag and notify owner that bot restarted successfully."""
    try:
        if not os.path.exists(UPDATE_FLAG_FILE):
            return
        
        with open(UPDATE_FLAG_FILE, "r") as f:
            flag_data = json.load(f)
        
        os.remove(UPDATE_FLAG_FILE)
        
        chat_id = flag_data.get("chat_id")
        message_id = flag_data.get("message_id")
        
        if chat_id:
            try:
                await StreamBot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=(
                        "✅ **Bot updated successfully!**\n\n"
                        f"🤖 **Natking-TG v{__version__}** is now running.\n"
                        "🟢 Status: Online"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                # If edit fails, send a new message
                await StreamBot.send_message(
                    chat_id=chat_id,
                    text=(
                        "✅ **Bot updated & restarted successfully!**\n\n"
                        f"🤖 **Natking-TG v{__version__}** is now running.\n"
                        "🟢 Status: Online"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            LOGGER.info(f"Update notification sent to {chat_id}")
    except Exception as e:
        LOGGER.warning(f"Could not send update notification: {e}")

async def start_services():
    LOGGER.info(f'Initializing Natking-TG v-{__version__}')
    await asleep(1.2)
    
    await StreamBot.start()
    StreamBot.username = StreamBot.me.username
    LOGGER.info(f"Bot Client : [@{StreamBot.username}]")
    if len(Telegram.SESSION_STRING) != 0:
        await UserBot.start()
        UserBot.username = UserBot.me.username or UserBot.me.first_name or UserBot.me.id
        LOGGER.info(f"User Client : {UserBot.username}")
    
    await asleep(1.2)
    LOGGER.info("Initializing Multi Clients")
    await initialize_clients()
    
    await asleep(2)
    LOGGER.info('Initalizing Surf Web Server..')
    server = web.AppRunner(await web_server())
    LOGGER.info("Server CleanUp!")
    await server.cleanup()
    
    await asleep(2)
    LOGGER.info("Server Setup Started !")
    
    await server.setup()
    await web.TCPSite(server, '0.0.0.0', Telegram.PORT).start()

    LOGGER.info("Natking-TG Started Revolving !")
    
    # Post-restart notification (after /update command)
    await _send_update_notification()
    
    await idle()

async def stop_clients():
    await StreamBot.stop()
    if len(Telegram.SESSION_STRING) != 0:
        await UserBot.stop()


if __name__ == '__main__':
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        LOGGER.info('Service Stopping...')
    except Exception:
        LOGGER.error(format_exc())
    finally:
        loop.run_until_complete(stop_clients())
        loop.stop()
