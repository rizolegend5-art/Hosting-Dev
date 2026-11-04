import aiosqlite
from config import DB_PATH
import datetime

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                is_banned INTEGER DEFAULT 0,
                max_bots INTEGER DEFAULT 5,
                cpu_limit TEXT DEFAULT "0.5",
                ram_limit TEXT DEFAULT "256m",
                join_date TEXT
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS bots (
                bot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                bot_name TEXT,
                bot_token TEXT,
                bot_type TEXT,
                status TEXT DEFAULT "stopped",
                container_id TEXT,
                deployed_date TEXT,
                last_start TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS clones (
                clone_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                bot_token TEXT,
                bot_username TEXT,
                bot_name TEXT,
                owner_id TEXT,
                dev_name TEXT,
                welcome_msg TEXT,
                enabled_features TEXT,
                status TEXT DEFAULT "setup",
                container_id TEXT,
                created_date TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS clone_templates (
                template_id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_name TEXT,
                is_default INTEGER DEFAULT 0,
                created_date TEXT
            )
        ''')
        
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                        ("deployment_approval", "0"))
        await db.commit()

# User Functions
async def add_user(user_id, username):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT OR IGNORE INTO users (user_id, username, join_date)
            VALUES (?, ?, ?)
        ''', (user_id, username, datetime.datetime.now().isoformat()))
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users")
        return await cursor.fetchall()

async def ban_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def unban_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        await db.commit()

async def update_user_limits(user_id, max_bots, cpu_limit, ram_limit):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            UPDATE users SET max_bots = ?, cpu_limit = ?, ram_limit = ?
            WHERE user_id = ?
        ''', (max_bots, cpu_limit, ram_limit, user_id))
        await db.commit()

# Bot Functions
async def add_bot(user_id, bot_name, bot_token, bot_type):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('''
            INSERT INTO bots (user_id, bot_name, bot_token, bot_type, deployed_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, bot_name, bot_token, bot_type, datetime.datetime.now().isoformat()))
        await db.commit()
        return cursor.lastrowid

async def get_user_bots(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM bots WHERE user_id = ?", (user_id,))
        return await cursor.fetchall()

async def get_all_bots():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM bots")
        return await cursor.fetchall()

async def get_bot(bot_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM bots WHERE bot_id = ?", (bot_id,))
        return await cursor.fetchone()

async def update_bot_status(bot_id, status, container_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        if container_id:
            await db.execute('''
                UPDATE bots SET status = ?, container_id = ?, last_start = ?
                WHERE bot_id = ?
            ''', (status, container_id, datetime.datetime.now().isoformat(), bot_id))
        else:
            await db.execute('''
                UPDATE bots SET status = ? WHERE bot_id = ?
            ''', (status, bot_id))
        await db.commit()

async def delete_bot_db(bot_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bots WHERE bot_id = ?", (bot_id,))
        await db.commit()

# Settings Functions
async def get_setting(key):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None

async def update_setting(key, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

# Clone Functions
async def add_clone(user_id, bot_token, bot_username, bot_name):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('''
            INSERT INTO clones (user_id, bot_token, bot_username, bot_name, created_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, bot_token, bot_username, bot_name, datetime.datetime.now().isoformat()))
        await db.commit()
        return cursor.lastrowid

async def update_clone(clone_id, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [clone_id]
        await db.execute(f"UPDATE clones SET {set_clause} WHERE clone_id = ?", values)
        await db.commit()

async def get_clone(clone_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM clones WHERE clone_id = ?", (clone_id,))
        return await cursor.fetchone()

async def get_user_clones(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM clones WHERE user_id = ?", (user_id,))
        return await cursor.fetchall()

async def get_all_clones():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM clones")
        return await cursor.fetchall()

async def delete_clone_db(clone_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM clones WHERE clone_id = ?", (clone_id,))
        await db.commit()