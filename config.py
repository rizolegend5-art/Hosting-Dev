"""Saari settings environment variables se aati hain (Railway -> Variables)."""
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _pick_data_dir() -> Path:
    # Railway Volume ko /data par mount karo to data redeploy ke baad bhi bacha rahega.
    env = os.getenv("DATA_DIR", "").strip()
    if env:
        p = Path(env)
    elif os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
        p = Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"])
    elif Path("/data").is_dir() and os.access("/data", os.W_OK):
        p = Path("/data")
    else:
        p = BASE_DIR / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


DATA_DIR = _pick_data_dir()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()


def _ids(*names) -> list:
    """Kisi bhi naam ke variable se IDs parho: '123', '123,456', '123 456', '123;456'."""
    out = []
    for name in names:
        raw = os.getenv(name, "")
        for part in re.split(r"[,\s;]+", raw):
            part = part.strip().strip("'\"")
            if part.lstrip("-").isdigit():
                v = int(part)
                if v not in out:
                    out.append(v)
    return out


# Aap Railway par jo bhi naam use karo (OWNER_ID / ADMIN_ID / ADMIN_IDS / ADMINS) sab chalega.
ADMIN_IDS = _ids("ADMIN_IDS", "ADMIN_ID", "OWNER_ID", "OWNER_IDS", "ADMINS", "ADMIN", "OWNER")

BOT_FILES_CHANNEL = os.getenv("BOT_FILES_CHANNEL", "").strip()
SUPPORT_USERNAME = os.getenv("YOUR_USERNAME", "").strip().lstrip("@")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "").strip()

DEFAULT_CPU_LIMIT = os.getenv("DEFAULT_CPU_LIMIT", "0.5")
DEFAULT_RAM_LIMIT = os.getenv("DEFAULT_RAM_LIMIT", "256m")
MAX_BOTS_PER_USER = int(os.getenv("MAX_BOTS_PER_USER", "5"))
MAX_CLONE_BOTS_PER_USER = int(os.getenv("MAX_CLONE_BOTS_PER_USER", "3"))
MAX_ZIP_SIZE = int(os.getenv("MAX_ZIP_SIZE", str(20 * 1024 * 1024)))
MAX_UNZIPPED_SIZE = int(os.getenv("MAX_UNZIPPED_SIZE", str(150 * 1024 * 1024)))

USER_BOTS_DIR = DATA_DIR / "user_bots"
LOGS_DIR = DATA_DIR / "logs"
CLONE_TEMPLATE_DIR = BASE_DIR / "clone_template"
ASSETS_DIR = BASE_DIR / "assets"
WELCOME_IMAGE = ASSETS_DIR / "welcome.jpg"
DB_PATH = str(DATA_DIR / "bot.db")

for _d in (USER_BOTS_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULT_CLONE_FEATURES = [
    "welcome_message", "admin_panel", "broadcast", "ban_system",
    "stats", "file_share", "auto_reply",
]
FEATURE_LABELS = {
    "welcome_message": "Welcome Message + Photo",
    "admin_panel": "Owner Admin Panel",
    "broadcast": "Broadcast",
    "ban_system": "Ban / Unban",
    "stats": "Stats",
    "file_share": "File Share",
    "auto_reply": "Auto Reply",
}
RAINBOW_EMOJIS = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🟤"]
