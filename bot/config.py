from os import getenv
from dotenv import load_dotenv
from pathlib import Path

if Path("config.env").exists():
    load_dotenv("config.env", override=True)

class Telegram:
    API_ID = int(getenv("API_ID", "0"))
    API_HASH = getenv("API_HASH", "")
    BOT_TOKEN = getenv("BOT_TOKEN", "")
    PORT = int(getenv("PORT", 8080))
    SESSION_STRING = getenv("SESSION_STRING", "")
    BASE_URL = getenv("BASE_URL", "").rstrip('/')
    DATABASE_URL = getenv("DATABASE_URL", "")
    AUTH_CHANNEL = [channel.strip() for channel in getenv("AUTH_CHANNEL", "").split(",") if channel.strip()]
    THEME = getenv("THEME", "quartz").lower()
    USERNAME = getenv("USERNAME", "admin")
    PASSWORD = getenv("PASSWORD", "admin")
    ADMIN_USERNAME = getenv("ADMIN_USERNAME", "natkingTG")
    ADMIN_PASSWORD = getenv("ADMIN_PASSWORD", "natkingTG")
    SLEEP_THRESHOLD = int(getenv('SLEEP_THRESHOLD', '60'))
    WORKERS = int(getenv('WORKERS', '10'))
    MULTI_CLIENT = getenv('MULTI_CLIENT', 'False')
    HIDE_CHANNEL = getenv('HIDE_CHANNEL', 'False')
    OWNER_ID = int(getenv('OWNER_ID', '0'))
    SUDO_USERS = {int(x) for x in getenv("SUDO_USERS", "").split() if x.isdigit()}
    UPSTREAM_REPO = getenv('UPSTREAM_REPO', 'https://github.com/nat-king-15/Surf-TG')
    UPSTREAM_BRANCH = getenv('UPSTREAM_BRANCH', 'main')
    
    # New Configs
    FREEMIUM_LIMIT = int(getenv("FREEMIUM_LIMIT", "0"))
    PREMIUM_LIMIT = int(getenv("PREMIUM_LIMIT", "500"))
    YT_COOKIES = getenv("YT_COOKIES", "")
    INSTA_COOKIES = getenv("INSTA_COOKIES", "")
    LOG_GROUP = int(getenv("LOG_GROUP", "-1001234456"))
    FORCE_SUB = int(getenv("FORCE_SUB", "-10012345567"))
    # Support multiple owner IDs separated by space
    OWNER_ID = [int(x) for x in getenv("OWNER_ID", "0").split()] if getenv("OWNER_ID") else []
    STRING = getenv("STRING", None)
    
    # Encryption
    MASTER_KEY = getenv("MASTER_KEY", "sensitive_master_key")
    IV_KEY = getenv("IV_KEY", "sensitive_iv_key")

    # Payment Config
    P0 = {
        "d": {"l": "1 Day", "s": 50, "du": 1, "u": "days"},
        "w": {"l": "1 Week", "s": 150, "du": 1, "u": "weeks"},
        "m": {"l": "1 Month", "s": 400, "du": 1, "u": "month"}
    }

