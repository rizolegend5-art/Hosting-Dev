#!/usr/bin/env python3
"""
===============================================================================
RIZO X NB TECH Hype V10.7 — Ultimate Bot & Project Hosting Platform
Part 1: Core System Engine, SQLite Schema, User/Credit Management, Base Models
===============================================================================
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import html
import json
import logging
import os
import platform
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from telegram import (
    InlineKeyboardButton as TelegramInlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton as TelegramKeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ═════════════════════════════════════════════════════════════════════════════
# GLOBAL CONSTANTS & CONFIGURATION (DIRECT EMBEDDED - NO .ENV NEEDED)
# ═════════════════════════════════════════════════════════════════════════════

BOT_TOKEN = "8931197214:AAFx97EUZ3fp5YirZKZ6EZq6ZLz2-3ajZqg"
OWNER_ID = 7638086103

BRAND_NAME = "RIZO X NB TECH"
OWNER_NAME = "RIZO$ BADSHAH"
VERSION = "10.7 (Hype Ultimate)"

CHANNEL_LINKS = [
    "https://t.me/rizoxnbtech",
    "https://t.me/rizoxbots",
    "https://t.me/rizoxbots",
    "https://t.me/premimumxfree",
]
CHANNEL_USERNAMES = ["@rizoxnbtech", "@BADSHAHATECH_channel", "@rizoxbots", "@premimumxfree"]
CHANNEL_NAMES = ["RIZO X NB TECH", "NB tech", "RIZO X NB TECH BOTS", "RIZO X NB TECH Premium"]

MAX_FILE_MB = 50
MAX_ZIP_EXPANDED_MB = 250
DEFAULT_CREDITS = 5
CREDIT_PER_UPLOAD = 1
PREMIUM_BONUS_CREDITS = 100

DAILY_UPLOAD_LIMIT_FREE = 3
DAILY_UPLOAD_LIMIT_PREMIUM = 50
MAX_RUNNING_FREE = 2
MAX_RUNNING_PREMIUM = 15

MAX_LOG_CHARS = 4000
AUTO_INSTALL_DEPENDENCIES = True
ENFORCE_RESOURCE_LIMITS = False
FORCE_JOIN_ENABLED = True
AUTO_RESTART_ENABLED = True
MAINTENANCE_MODE_DEFAULT = False

BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
PROJECTS_DIR = BASE_DIR / "projects_data"
LOGS_DIR = BASE_DIR / "process_logs"
DATA_FILE = BASE_DIR / "bot_data.json"
DB_FILE = BASE_DIR / "RIZO_v10.db"

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

START_TIME = time.time()

# ═════════════════════════════════════════════════════════════════════════════
# LOGGING SYSTEM
# ═════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(BASE_DIR / "bot_system.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("RIZOXHostEngine")

# ═════════════════════════════════════════════════════════════════════════════
# SQLITE DATABASE CONTROLLER
# ═════════════════════════════════════════════════════════════════════════════

class DatabaseManager:
    def __init__(self, db_path: Path = DB_FILE):
        self.db_path = db_path
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Users Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    is_approved INTEGER DEFAULT 0,
                    is_premium INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    credits INTEGER DEFAULT 5,
                    daily_uploads INTEGER DEFAULT 0,
                    last_upload_date TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Hosted Projects Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    display_name TEXT,
                    entry_file TEXT,
                    folder_path TEXT,
                    log_file TEXT,
                    is_running INTEGER DEFAULT 0,
                    auto_restart INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
            """)
            # Analytics & Admin Settings
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()

    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    def add_or_update_user(self, user_id: int, username: str, first_name: str) -> None:
        with self.get_connection() as conn:
            user = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not user:
                is_owner_flag = 1 if user_id == OWNER_ID else 0
                conn.execute(
                    "INSERT INTO users (user_id, username, first_name, is_approved, is_premium, credits) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, username, first_name, is_owner_flag, is_owner_flag, 999999 if is_owner_flag else DEFAULT_CREDITS)
                )
            else:
                conn.execute(
                    "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                    (username, first_name, user_id)
                )
            conn.commit()

    def update_credits(self, user_id: int, delta: int) -> int:
        with self.get_connection() as conn:
            conn.execute("UPDATE users SET credits = MAX(0, credits + ?) WHERE user_id = ?", (delta, user_id))
            conn.commit()
            row = conn.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row["credits"] if row else 0

db = DatabaseManager()

# ═════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES & UTILITIES
# ═════════════════════════════════════════════════════════════════════════════

def esc(text: Any) -> str:
    """Escape HTML characters safely."""
    return html.escape(str(text)) if text else ""

def format_box(title: str, lines: List[str]) -> str:
    """Generate signature RIZO style UI boxes."""
    content = "\n".join(f"┃ {line}" if line else "┃" for line in lines)
    return f"<b>╭━━〔 {esc(title)} 〕━━┈⊷</b>\n{content}\n<b>╰━━━━━━━━━━━━━━━┈⊷</b>"

def get_system_uptime() -> str:
    diff = int(time.time() - START_TIME)
    days, remainder = divmod(diff, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    return f"{hours}h {minutes}m {seconds}s"
# ═════════════════════════════════════════════════════════════════════════════
# PROCESS & RUNTIME MANAGEMENT SYSTEM
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ScriptProcess:
    project_id: str
    user_id: int
    display_name: str
    entry_file: str
    folder: str
    log_path: str
    proc: Optional[subprocess.Popen[Any]] = None
    started_at: float = field(default_factory=time.time)
    restarts: int = 0
    auto_restart: bool = AUTO_RESTART_ENABLED
    desired_running: bool = False
    runtime: str = "python"

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def pid(self) -> str:
        return str(self.proc.pid) if self.proc and self.running else "N/A"

    @property
    def exit_code(self) -> str:
        if self.proc is None:
            return "Not Started"
        if self.running:
            return "Active (0)"
        return str(self.proc.returncode)

    def serialize(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "display_name": self.display_name,
            "entry_file": self.entry_file,
            "folder": self.folder,
            "log_path": self.log_path,
            "started_at": self.started_at,
            "restarts": self.restarts,
            "auto_restart": self.auto_restart,
            "desired_running": self.desired_running,
            "runtime": self.runtime,
        }

class ExecutionEngine:
    def __init__(self) -> None:
        self.active_processes: Dict[str, ScriptProcess] = {}

    def install_requirements(self, project_folder: Path) -> Tuple[bool, str]:
        """Automatically detect requirements.txt and install packages."""
        req_file = project_folder / "requirements.txt"
        if not req_file.exists():
            return True, "No requirements.txt found. Skipping auto-install."

        logger.info(f"Installing dependencies for project at {project_folder}")
        try:
            cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file)]
            result = subprocess.run(
                cmd,
                cwd=project_folder,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return True, "Dependencies installed successfully."
            return False, f"Pip Install Failed:\n{result.stdout[-1000:]}"
        except subprocess.TimeoutExpired:
            return False, "Dependency installation timed out (max 120s)."
        except Exception as e:
            return False, f"Error installing dependencies: {str(e)}"

    def locate_entry_point(self, project_folder: Path) -> Optional[Path]:
        """Detect primary .py entry file automatically."""
        common_names = ["main.py", "bot.py", "app.py", "index.py", "run.py"]
        for name in common_names:
            candidate = project_folder / name
            if candidate.exists():
                return candidate

        # Fallback to first python file found
        py_files = list(project_folder.rglob("*.py"))
        if py_files:
            return py_files[0]
        return None

    def start_script(self, item: ScriptProcess) -> Tuple[bool, str]:
        """Spawn sub-process safely with background logging."""
        if item.running:
            return False, "Project is already running!"

        folder_path = Path(item.folder)
        entry_path = Path(item.entry_file)

        if not entry_path.exists():
            return False, f"Entry file missing: {entry_path.name}"

        # Handle requirements installation if enabled
        if AUTO_INSTALL_DEPENDENCIES:
            success, msg = self.install_requirements(folder_path)
            if not success:
                return False, f"Dependency Error: {msg}"

        try:
            log_handle = open(item.log_path, "a", encoding="utf-8", errors="replace", buffering=1)
            
            # Start subprocess detached
            cmd = [sys.executable, "-u", str(entry_path)]
            proc = subprocess.Popen(
                cmd,
                cwd=str(folder_path),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=(os.name != "nt"),
            )

            item.proc = proc
            item.started_at = time.time()
            item.desired_running = True
            self.active_processes[item.project_id] = item

            # Update DB State
            with db.get_connection() as conn:
                conn.execute("UPDATE projects SET is_running = 1 WHERE project_id = ?", (item.project_id,))
                conn.commit()

            return True, "Project started successfully!"
        except Exception as e:
            logger.exception("Failed to spawn process")
            return False, f"Process Launch Error: {str(e)}"

    def stop_script(self, project_id: str) -> Tuple[bool, str]:
        """Kill running process safely."""
        item = self.active_processes.get(project_id)
        if not item or not item.running or not item.proc:
            return False, "Project is not running."

        try:
            item.desired_running = False
            if os.name == "nt":
                item.proc.terminate()
            else:
                os.killpg(os.getpgid(item.proc.pid), signal.SIGTERM)

            try:
                item.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    item.proc.kill()
                else:
                    os.killpg(os.getpgid(item.proc.pid), signal.SIGKILL)

            # Update DB State
            with db.get_connection() as conn:
                conn.execute("UPDATE projects SET is_running = 0 WHERE project_id = ?", (project_id,))
                conn.commit()

            return True, "Project stopped successfully."
        except Exception as e:
            return False, f"Error stopping process: {str(e)}"

    def fetch_logs(self, log_path: str, lines_count: int = 100) -> str:
        """Fetch last N lines from runtime logs."""
        path = Path(log_path)
        if not path.exists():
            return "No logs generated yet."

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.readlines()
                return "".join(content[-lines_count:])
        except Exception as e:
            return f"Error reading logs: {str(e)}"

engine = ExecutionEngine()

# ═════════════════════════════════════════════════════════════════════════════
# ZIP UNZIPPER & FILE VALIDATION HANDLERS
# ═════════════════════════════════════════════════════════════════════════════

def process_uploaded_archive(file_path: Path, extract_to: Path) -> Tuple[bool, str, Optional[Path]]:
    """Extract ZIP archives and validate size & contents."""
    if not zipfile.is_zipfile(file_path):
        return False, "Invalid ZIP archive.", None

    total_size = 0
    try:
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            for member in zip_ref.infolist():
                total_size += member.file_size
                if total_size > (MAX_ZIP_EXPANDED_MB * 1024 * 1024):
                    return False, f"ZIP contents exceed maximum limit of {MAX_ZIP_EXPANDED_MB}MB.", None

            zip_ref.extractall(extract_to)

        entry_file = engine.locate_entry_point(extract_to)
        if not entry_file:
            return False, "No valid `.py` entry file found inside the ZIP.", None

        return True, "Archive extracted successfully.", entry_file
    except Exception as e:
        return False, f"Extraction Error: {str(e)}", None
# ═════════════════════════════════════════════════════════════════════════════
# FORCE JOIN & USER PERMISSION CHECKERS
# ═════════════════════════════════════════════════════════════════════════════

async def check_force_join(bot: Any, user_id: int) -> bool:
    """Verify if user is joined in all mandatory channels."""
    if not FORCE_JOIN_ENABLED or user_id == OWNER_ID:
        return True

    for channel in CHANNEL_USERNAMES:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except TelegramError:
            logger.warning(f"Could not verify status for user {user_id} in {channel}")
            continue
    return True

def force_join_keyboard() -> InlineKeyboardMarkup:
    """Generate dynamic join links and verification button."""
    buttons = []
    for idx, (link, name) in enumerate(zip(CHANNEL_LINKS, CHANNEL_NAMES)):
        buttons.append([InlineKeyboardButton(f"📢 Join {name}", url=link)])
    buttons.append([InlineKeyboardButton("✅ Verify Membership", callback_data="verify_join")])
    return InlineKeyboardMarkup(buttons)

# ═════════════════════════════════════════════════════════════════════════════
# NAVIGATION & KEYBOARD BUILDERS
# ═════════════════════════════════════════════════════════════════════════════

def main_dashboard_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Construct dynamic main menu based on user tier."""
    rows = [
        [KeyboardButton("🚀 ʜᴏsᴛ ᴘʀᴏᴊᴇᴄᴛ"), KeyboardButton("📂 ᴍʏ ᴘʀᴏᴊᴇᴄᴛs")],
        [KeyboardButton("🧾 ʟɪᴠᴇ ʟᴏɢs"), KeyboardButton("⚙️ ᴄᴏɴᴛʀᴏʟs")],
        [KeyboardButton("💳 ᴡᴀʟʟᴇᴛ"), KeyboardButton("📊 ᴀᴄᴄᴏᴜɴᴛ")],
    ]
    if user_id == OWNER_ID:
        rows.append([KeyboardButton("👑 ᴀᴅᴍɪɴ ᴄᴇɴᴛᴇʀ")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def project_action_keyboard(project_id: str, is_running: bool) -> InlineKeyboardMarkup:
    """Inline control panel for individual projects."""
    status_btn = (
        InlineKeyboardButton("🛑 Stop Project", callback_data=f"p_stop:{project_id}")
        if is_running
        else InlineKeyboardButton("▶️ Start Project", callback_data=f"p_start:{project_id}")
    )
    buttons = [
        [status_btn, InlineKeyboardButton("📜 Logs", callback_data=f"p_logs:{project_id}")],
        [
            InlineKeyboardButton("🔄 Restart", callback_data=f"p_restart:{project_id}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"p_delete:{project_id}"),
        ],
        [InlineKeyboardButton("🔙 Back to List", callback_data="list_projects")],
    ]
    return InlineKeyboardMarkup(buttons)

# ═════════════════════════════════════════════════════════════════════════════
# USER COMMAND & BOT HANDLERS
# ═════════════════════════════════════════════════════════════════════════════

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command and dashboard initialization."""
    user = update.effective_user
    if not user or not update.effective_message:
        return

    # Sync User in Database
    db.add_or_update_user(user.id, user.username or "", user.first_name)
    user_data = db.get_user(user.id)

    if user_data and user_data["is_banned"]:
        await update.effective_message.reply_text("🚫 Your access to this platform has been suspended.")
        return

    # Force Join Gate
    if not await check_force_join(context.bot, user.id):
        await update.effective_message.reply_text(
            format_box(
                "ACCESS RESTRICTED",
                [
                    "You must join all our official channels to use this bot.",
                    "Click the buttons below to join, then press 'Verify'.",
                ],
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=force_join_keyboard(),
        )
        return

    tier = "👑 Owner" if user.id == OWNER_ID else ("💎 Premium" if user_data["is_premium"] else "✅ Approved User")
    credits = user_data["credits"] if user_data else 0

    text = format_box(
        f"⚡ {BRAND_NAME} ⚡",
        [
            f"👤 <b>Welcome:</b> {esc(user.first_name)}",
            f"🆔 <b>User ID:</b> <code>{user.id}</code>",
            f"🎖 <b>Plan:</b> {tier}",
            f"💳 <b>Credits:</b> <code>{credits}</code>",
            f"⏱ <b>Engine Uptime:</b> <code>{get_system_uptime()}</code>",
            "",
            "👇 Choose an action from the menu below:",
        ],
    )
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=main_dashboard_keyboard(user.id)
    )

async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process incoming .py and .zip project uploads."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg or not msg.document:
        return

    user_data = db.get_user(user.id)
    if not user_data or user_data["is_banned"]:
        await msg.reply_text("🚫 Action denied.")
        return

    if user_data["credits"] < CREDIT_PER_UPLOAD and user.id != OWNER_ID:
        await msg.reply_text("❌ You do not have enough credits to deploy a project!")
        return

    doc = msg.document
    filename = doc.file_name or "script.py"
    ext = Path(filename).suffix.lower()

    if ext not in [".py", ".zip"]:
        await msg.reply_text("❌ Unsupported file format! Please upload a `.py` file or a compressed `.zip` project.")
        return

    status_msg = await msg.reply_text("📥 <i>Downloading project file...</i>", parse_mode=ParseMode.HTML)

    # Unique project path creation
    project_id = hashlib.md5(f"{user.id}_{time.time()}".encode()).hexdigest()[:10]
    folder_path = PROJECTS_DIR / str(user.id) / project_id
    folder_path.mkdir(parents=True, exist_ok=True)

    file_path = folder_path / filename
    telegram_file = await context.bot.get_file(doc.file_id)
    await telegram_file.download_to_drive(file_path)

    entry_file: Optional[Path] = None

    if ext == ".zip":
        await status_msg.edit_text("📦 <i>Extracting archive and resolving entry point...</i>", parse_mode=ParseMode.HTML)
        success, err_msg, extracted_entry = process_uploaded_archive(file_path, folder_path)
        if not success or not extracted_entry:
            await status_msg.edit_text(f"❌ <b>Extraction Failed:</b> {err_msg}", parse_mode=ParseMode.HTML)
            return
        entry_file = extracted_entry
    else:
        entry_file = file_path

    log_file = LOGS_DIR / f"{project_id}.log"
    proc_item = ScriptProcess(
        project_id=project_id,
        user_id=user.id,
        display_name=filename,
        entry_file=str(entry_file),
        folder=str(folder_path),
        log_path=str(log_file),
    )

    await status_msg.edit_text("⚙️ <i>Installing requirements and spawning process...</i>", parse_mode=ParseMode.HTML)
    success, launch_msg = engine.start_script(proc_item)

    if success:
        # Save project into DB
        with db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO projects (project_id, user_id, display_name, entry_file, folder_path, log_file, is_running)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
                (project_id, user.id, filename, str(entry_file), str(folder_path), str(log_file)),
            )
            conn.commit()

        # Deduct credits
        if user.id != OWNER_ID:
            db.update_credits(user.id, -CREDIT_PER_UPLOAD)

        await status_msg.edit_text(
            format_box(
                "PROJECT DEPLOYED",
                [
                    f"🚀 <b>Name:</b> {esc(filename)}",
                    f"🔑 <b>ID:</b> <code>{project_id}</code>",
                    f"⚡ <b>Status:</b> Active",
                    f"💳 <b>Credits Remaining:</b> <code>{db.get_user(user.id)['credits']}</code>",
                ],
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=project_action_keyboard(project_id, True),
        )
    else:
        await status_msg.edit_text(f"❌ <b>Deployment Error:</b> {launch_msg}", parse_mode=ParseMode.HTML)
# ═════════════════════════════════════════════════════════════════════════════
# CALLBACK QUERY ENGINE & ACTION HANDLERS
# ═════════════════════════════════════════════════════════════════════════════

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Central router for all inline button queries."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    data = query.data
    user = update.effective_user
    if not user:
        return

    # Force Join Verification Callback
    if data == "verify_join":
        if await check_force_join(context.bot, user.id):
            await query.edit_message_text(
                "✅ <b>Verification Successful!</b>\n\nAap ab bot ke saare features access kar sakte hain.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await query.edit_message_text(
                "❌ <b>Verification Failed!</b>\n\nAapne abhi tak saare channels join nahi kiye. Kripya pehle saare channels join karein.",
                parse_mode=ParseMode.HTML,
                reply_markup=force_join_keyboard(),
            )
        return

    # List Projects Callback
    if data == "list_projects":
        await list_user_projects(update, context)
        return

    # Project Action Handlers (p_start, p_stop, p_restart, p_logs, p_delete)
    if ":" in data:
        action, project_id = data.split(":", 1)
        
        with db.get_connection() as conn:
            proj = conn.execute(
                "SELECT * FROM projects WHERE project_id = ? AND (user_id = ? OR ? = ?)",
                (project_id, user.id, user.id, OWNER_ID),
            ).fetchone()

        if not proj:
            await query.edit_message_text("❌ Project nahi mila ya aapke paas access nahi hai.")
            return

        if action == "p_start":
            proc_item = ScriptProcess(
                project_id=proj["project_id"],
                user_id=proj["user_id"],
                display_name=proj["display_name"],
                entry_file=proj["entry_file"],
                folder=proj["folder_path"],
                log_path=proj["log_file"],
            )
            success, msg = engine.start_script(proc_item)
            res_text = "✅ Project Start Ho Gaya!" if success else f"❌ Failed: {msg}"
            await query.edit_message_text(
                f"{res_text}\n\nProject: <b>{esc(proj['display_name'])}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=project_action_keyboard(project_id, True if success else False),
            )

        elif action == "p_stop":
            success, msg = engine.stop_script(project_id)
            res_text = "🛑 Project Stop Ho Gaya!" if success else f"❌ Failed: {msg}"
            await query.edit_message_text(
                f"{res_text}\n\nProject: <b>{esc(proj['display_name'])}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=project_action_keyboard(project_id, False),
            )

        elif action == "p_restart":
            engine.stop_script(project_id)
            await asyncio.sleep(1)
            proc_item = ScriptProcess(
                project_id=proj["project_id"],
                user_id=proj["user_id"],
                display_name=proj["display_name"],
                entry_file=proj["entry_file"],
                folder=proj["folder_path"],
                log_path=proj["log_file"],
            )
            success, msg = engine.start_script(proc_item)
            res_text = "🔄 Project Restart Ho Gaya!" if success else f"❌ Restart Failed: {msg}"
            await query.edit_message_text(
                f"{res_text}\n\nProject: <b>{esc(proj['display_name'])}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=project_action_keyboard(project_id, True if success else False),
            )

        elif action == "p_logs":
            logs = engine.fetch_logs(proj["log_file"], lines_count=40)
            log_output = logs[-MAX_LOG_CHARS:] if len(logs) > MAX_LOG_CHARS else logs
            await query.edit_message_text(
                f"📜 <b>Live Logs: {esc(proj['display_name'])}</b>\n\n<code>{esc(log_output)}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=project_action_keyboard(project_id, bool(proj["is_running"])),
            )

        elif action == "p_delete":
            engine.stop_script(project_id)
            try:
                shutil.rmtree(proj["folder_path"], ignore_errors=True)
            except Exception:
                pass
            
            with db.get_connection() as conn:
                conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
                conn.commit()

            await query.edit_message_text(
                f"🗑 Project <b>{esc(proj['display_name'])}</b> successfully delete kar diya gaya hai.",
                parse_mode=ParseMode.HTML,
            )

async def list_user_projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Render list of active and hosted projects for current user."""
    user = update.effective_user
    if not user:
        return

    with db.get_connection() as conn:
        projects = conn.execute("SELECT * FROM projects WHERE user_id = ?", (user.id,)).fetchall()

    if not projects:
        msg_text = "📂 Aapka koi project hosted nahi hai. Telegram par `.py` ya `.zip` file bhejen!"
        if update.callback_query:
            await update.callback_query.edit_message_text(msg_text)
        else:
            await update.effective_message.reply_text(msg_text)
        return

    buttons = []
    for p in projects:
        status_icon = "🟢" if p["is_running"] else "🔴"
        buttons.append([
            InlineKeyboardButton(
                f"{status_icon} {p['display_name']} ({p['project_id']})",
                callback_data=f"p_logs:{p['project_id']}",
            )
        ])

    text = format_box(
        "Aapke Hosted Projects",
        [f"Total Projects: <code>{len(projects)}</code>", "", "Niche kisi project par click karke control karein:"]
    )

    markup = InlineKeyboardMarkup(buttons)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
# ═════════════════════════════════════════════════════════════════════════════
# ADMIN CENTER & MANAGEMENT COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

async def admin_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Render comprehensive admin options."""
    user = update.effective_user
    if not user or user.id != OWNER_ID:
        return

    with db.get_connection() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        active_projects = conn.execute("SELECT COUNT(*) FROM projects WHERE is_running = 1").fetchone()[0]

    text = format_box(
        "👑 ADMIN CENTER",
        [
            f"📊 <b>Total Users:</b> <code>{total_users}</code>",
            f"📂 <b>Total Projects:</b> <code>{total_projects}</code>",
            f"⚡ <b>Active Running:</b> <code>{active_projects}</code>",
            f"⏱ <b>Uptime:</b> <code>{get_system_uptime()}</code>",
            "",
            "<b>Admin Commands:</b>",
            "• <code>/addcredits USER_ID AMOUNT</code>",
            "• <code>/makepremium USER_ID</code>",
            "• <code>/ban USER_ID</code>",
            "• <code>/unban USER_ID</code>",
            "• <code>/broadcast MESSAGE</code>",
        ]
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

async def add_credits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to give credits to a specific user."""
    if update.effective_user.id != OWNER_ID:
        return
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: `/addcredits USER_ID AMOUNT`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        new_total = db.update_credits(target_id, amount)
        await update.effective_message.reply_text(f"✅ User <code>{target_id}</code> ke paas ab <code>{new_total}</code> credits hain.", parse_mode=ParseMode.HTML)
    except ValueError:
        await update.effective_message.reply_text("❌ Sahi parameters enter karein.")

async def make_premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Grant Premium status to user."""
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: `/makepremium USER_ID`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        target_id = int(context.args[0])
        with db.get_connection() as conn:
            conn.execute("UPDATE users SET is_premium = 1 WHERE user_id = ?", (target_id,))
            conn.commit()
        db.update_credits(target_id, PREMIUM_BONUS_CREDITS)
        await update.effective_message.reply_text(f"💎 User <code>{target_id}</code> ab Premium ban chuka hai!", parse_mode=ParseMode.HTML)
    except ValueError:
        await update.effective_message.reply_text("❌ Galat User ID.")

async def ban_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ban user from using the hosting platform."""
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: `/ban USER_ID`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        target_id = int(context.args[0])
        with db.get_connection() as conn:
            conn.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (target_id,))
            conn.commit()
        await update.effective_message.reply_text(f"🚫 User <code>{target_id}</code> ko ban kar diya gaya hai.", parse_mode=ParseMode.HTML)
    except ValueError:
        await update.effective_message.reply_text("❌ Galat User ID.")

# ═════════════════════════════════════════════════════════════════════════════
# WALLET & ACCOUNT STATS
# ═════════════════════════════════════════════════════════════════════════════

async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display user wallet details."""
    user = update.effective_user
    if not user:
        return
    
    user_data = db.get_user(user.id)
    credits = user_data["credits"] if user_data else 0

    text = format_box(
        "💳 USER WALLET",
        [
            f"👤 <b>Account:</b> {esc(user.first_name)}",
            f"💳 <b>Current Credits:</b> <code>{credits}</code>",
            f"⚡ <b>Cost Per Upload:</b> <code>{CREDIT_PER_UPLOAD} Credit</code>",
            "",
            "ℹ️ <i>Naye credits buy karne ke liye Admin se contact karein.</i>"
        ]
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

# ═════════════════════════════════════════════════════════════════════════════
# TEXT ROUTER HANDLER
# ═════════════════════════════════════════════════════════════════════════════

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle custom keyboard responses."""
    msg = update.effective_message
    if not msg or not msg.text:
        return

    text = msg.text.strip()
    user = update.effective_user
    if not user:
        return

    if text in ["🚀 ʜᴏsᴛ ᴘʀᴏᴊᴇᴄᴛ", "⚙️ ᴄᴏɴᴛʀᴏʟs"]:
        await msg.reply_text("📤 Apne bot ka <code>.py</code> file ya <code>.zip</code> archive is chat mein upload karein!", parse_mode=ParseMode.HTML)
    elif text in ["📂 ᴍʏ ᴘʀᴏᴊᴇᴄᴛs", "🧾 ʟɪᴠᴇ ʟᴏɢs"]:
        await list_user_projects(update, context)
    elif text == "💳 ᴡᴀʟʟᴇᴛ":
        await wallet_cmd(update, context)
    elif text == "📊 ᴀᴄᴄᴏᴜɴᴛ":
        await start_cmd(update, context)
    elif text == "👑 ᴀᴅᴍɪɴ ᴄᴇɴᴛᴇʀ":
        await admin_panel_cmd(update, context)
# ═════════════════════════════════════════════════════════════════════════════
# MAIN BOT INITIALIZATION ENGINE
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    """Start and configure RIZO X NB TECH Hype V10.7 Application."""
    logger.info("Initializing Bot Framework...")

    # Build Telegram Bot Application
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Core Command Handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("admin", admin_panel_cmd))
    app.add_handler(CommandHandler("addcredits", add_credits_cmd))
    app.add_handler(CommandHandler("makepremium", make_premium_cmd))
    app.add_handler(CommandHandler("ban", ban_user_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("wallet", wallet_cmd))

    # Document & Dynamic Upload Handlers
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    # Callback Query Router
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    logger.info(f"✨ {BRAND_NAME} Engine Online!")
    
    # Run Polling Loop
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
