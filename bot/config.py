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

    # --- Save-Restricted-Content-Bot Features ---
    MONGO_DB = getenv("MONGO_DB", "surftg")

    # Encryption keys for session strings (AES-GCM)
    MASTER_KEY = getenv("MASTER_KEY", "default_master_key_change_me_32!")
    IV_KEY = getenv("IV_KEY", "default_iv_key_16")

    # Force subscription channel (empty = disabled)
    FORCE_SUB = getenv("FORCE_SUB", "")

    # Usage limits per day
    FREEMIUM_LIMIT = int(getenv("FREEMIUM_LIMIT", "25"))
    PREMIUM_LIMIT = int(getenv("PREMIUM_LIMIT", "0"))  # 0 = unlimited

    # Premium plan config — matches source bot's P0 format
    # s=stars, du=duration value, u=duration unit, l=label
    PREMIUM_PLANS = {
        "d": {
            "s": int(getenv("PLAN_D_S", "1")),
            "du": int(getenv("PLAN_D_DU", "1")),
            "u": getenv("PLAN_D_U", "days"),
            "l": getenv("PLAN_D_L", "Daily"),
        },
        "w": {
            "s": int(getenv("PLAN_W_S", "3")),
            "du": int(getenv("PLAN_W_DU", "1")),
            "u": getenv("PLAN_W_U", "weeks"),
            "l": getenv("PLAN_W_L", "Weekly"),
        },
        "m": {
            "s": int(getenv("PLAN_M_S", "5")),
            "du": int(getenv("PLAN_M_DU", "1")),
            "u": getenv("PLAN_M_U", "month"),
            "l": getenv("PLAN_M_L", "Monthly"),
        },
    }

    # yt-dlp cookies file (optional)
    YT_COOKIES = getenv("YT_COOKIES", "")
