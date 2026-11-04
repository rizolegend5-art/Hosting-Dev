"""Application configuration loaded from environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
BOT_FILES_CHANNEL = os.getenv("BOT_FILES_CHANNEL", "").strip()

DEFAULT_CPU_LIMIT = os.getenv("DEFAULT_CPU_LIMIT", "0.5")
DEFAULT_RAM_LIMIT = os.getenv("DEFAULT_RAM_LIMIT", "256m")
MAX_BOTS_PER_USER = int(os.getenv("MAX_BOTS_PER_USER", "5"))
MAX_ZIP_SIZE = int(os.getenv("MAX_ZIP_SIZE", str(10 * 1024 * 1024)))
ALLOWED_BOT_TYPES = ["python", "nodejs"]

DOCKER_PYTHON_IMAGE = os.getenv("DOCKER_PYTHON_IMAGE", "python:3.11-slim")
DOCKER_NODEJS_IMAGE = os.getenv("DOCKER_NODEJS_IMAGE", "node:20-alpine")
DOCKER_HOST = os.getenv("DOCKER_HOST", "").strip()
USER_BOTS_DIR = str(DATA_DIR / "user_bots")

CLONE_TEMPLATE_DIR = str(BASE_DIR / "clone_template")
MAX_CLONE_BOTS_PER_USER = int(os.getenv("MAX_CLONE_BOTS_PER_USER", "3"))
DEFAULT_CLONE_FEATURES = [
    "welcome_message", "admin_panel", "broadcast", "ban_system",
    "stats", "file_share", "auto_reply"
]
RAINBOW_EMOJIS = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🟤"]
DB_PATH = str(DATA_DIR / "bot.db")
