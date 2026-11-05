"""SQLite (standard library). Har call alag thread me chalti hai, isliye bot block nahi hota."""
import asyncio
import datetime
import sqlite3

from config import DB_PATH, DEFAULT_CPU_LIMIT, DEFAULT_RAM_LIMIT, MAX_BOTS_PER_USER


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _connect():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=OFF")
    return c


def _run(sql, params=(), fetch=None):
    c = _connect()
    try:
        cur = c.execute(sql, params)
        c.commit()
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        return cur.lastrowid
    finally:
        c.close()


async def q(sql, params=(), fetch=None):
    return await asyncio.to_thread(_run, sql, params, fetch)


def _add_missing_columns(c, table, cols):
    have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
    for name, decl in cols.items():
        if name not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _init():
    c = _connect()
    try:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                is_banned INTEGER DEFAULT 0, max_bots INTEGER, cpu_limit TEXT,
                ram_limit TEXT, join_date TEXT);
            CREATE TABLE IF NOT EXISTS bots (
                bot_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                bot_name TEXT, bot_token TEXT, bot_type TEXT,
                status TEXT DEFAULT 'stopped', pid INTEGER, approved INTEGER DEFAULT 1,
                deployed_date TEXT, last_start TEXT);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS clones (
                clone_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                bot_token TEXT, bot_username TEXT, bot_name TEXT, owner_id TEXT,
                dev_name TEXT, welcome_msg TEXT, enabled_features TEXT,
                status TEXT DEFAULT 'stopped', pid INTEGER, created_date TEXT);
            """
        )
        # Purane database ko naye columns ke saath upgrade karo.
        _add_missing_columns(c, "users", {"first_name": "TEXT"})
        _add_missing_columns(c, "bots", {"pid": "INTEGER", "approved": "INTEGER DEFAULT 1",
                                         "last_start": "TEXT"})
        _add_missing_columns(c, "clones", {"pid": "INTEGER"})
        c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES ('deployment_approval','0')")
        c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES ('maintenance','0')")
        c.commit()
    finally:
        c.close()


async def init_db():
    await asyncio.to_thread(_init)


# ---------------- users ----------------
async def add_user(user_id, username, first_name=""):
    await q(
        "INSERT OR IGNORE INTO users (user_id,username,first_name,max_bots,cpu_limit,ram_limit,join_date)"
        " VALUES (?,?,?,?,?,?,?)",
        (user_id, username, first_name, MAX_BOTS_PER_USER, DEFAULT_CPU_LIMIT, DEFAULT_RAM_LIMIT, _now()),
    )
    await q("UPDATE users SET username=?, first_name=? WHERE user_id=?", (username, first_name, user_id))


async def get_user(user_id):
    return await q("SELECT * FROM users WHERE user_id=?", (user_id,), "one")


async def get_all_users():
    return await q("SELECT * FROM users ORDER BY join_date DESC", fetch="all")


async def set_ban(user_id, banned: bool):
    await q("UPDATE users SET is_banned=? WHERE user_id=?", (1 if banned else 0, user_id))


async def update_user_limits(user_id, max_bots, cpu_limit, ram_limit):
    await q("UPDATE users SET max_bots=?, cpu_limit=?, ram_limit=? WHERE user_id=?",
            (max_bots, cpu_limit, ram_limit, user_id))


# ---------------- bots ----------------
async def add_bot(user_id, bot_name, bot_token, bot_type, approved=1):
    return await q(
        "INSERT INTO bots (user_id,bot_name,bot_token,bot_type,approved,deployed_date) VALUES (?,?,?,?,?,?)",
        (user_id, bot_name, bot_token, bot_type, approved, _now()),
    )


async def get_user_bots(user_id):
    return await q("SELECT * FROM bots WHERE user_id=? ORDER BY bot_id", (user_id,), "all")


async def get_all_bots():
    return await q("SELECT * FROM bots ORDER BY bot_id DESC", fetch="all")


async def get_bot(bot_id):
    return await q("SELECT * FROM bots WHERE bot_id=?", (bot_id,), "one")


async def update_bot(bot_id, **kw):
    if not kw:
        return
    cols = ", ".join(f"{k}=?" for k in kw)
    await q(f"UPDATE bots SET {cols} WHERE bot_id=?", (*kw.values(), bot_id))


async def delete_bot_db(bot_id):
    await q("DELETE FROM bots WHERE bot_id=?", (bot_id,))


# ---------------- settings ----------------
async def get_setting(key, default=None):
    row = await q("SELECT value FROM settings WHERE key=?", (key,), "one")
    return row["value"] if row else default


async def update_setting(key, value):
    await q("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))


# ---------------- clones ----------------
async def add_clone(user_id, bot_token, bot_username, bot_name, owner_id, dev_name, welcome_msg, features):
    return await q(
        "INSERT INTO clones (user_id,bot_token,bot_username,bot_name,owner_id,dev_name,welcome_msg,"
        "enabled_features,status,created_date) VALUES (?,?,?,?,?,?,?,?,'stopped',?)",
        (user_id, bot_token, bot_username, bot_name, str(owner_id), dev_name, welcome_msg,
         ",".join(features), _now()),
    )


async def update_clone(clone_id, **kw):
    if not kw:
        return
    cols = ", ".join(f"{k}=?" for k in kw)
    await q(f"UPDATE clones SET {cols} WHERE clone_id=?", (*kw.values(), clone_id))


async def get_clone(clone_id):
    return await q("SELECT * FROM clones WHERE clone_id=?", (clone_id,), "one")


async def get_user_clones(user_id):
    return await q("SELECT * FROM clones WHERE user_id=? ORDER BY clone_id", (user_id,), "all")


async def get_all_clones():
    return await q("SELECT * FROM clones ORDER BY clone_id DESC", fetch="all")


async def delete_clone_db(clone_id):
    await q("DELETE FROM clones WHERE clone_id=?", (clone_id,))
