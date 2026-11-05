"""Clone bot (host bot ke andar alag process me chalta hai).

Config environment se aata hai (CLONE_*). Data isi folder ki clone.db me rehta hai.
Features: welcome + photo, file share, auto reply, broadcast, ban/unban, stats, owner panel.
"""
import asyncio
import html
import logging
import os
import sqlite3
import time
from pathlib import Path

from telegram import (BotCommand, BotCommandScopeChat, InlineKeyboardButton as Btn,
                      InlineKeyboardMarkup as Markup, Update)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, TypeHandler, filters)

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("clone")
logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = os.environ["CLONE_TOKEN"]
OWNER = int(os.environ.get("CLONE_OWNER_ID", "0") or 0)
DEV = os.environ.get("CLONE_DEV_NAME", "Developer")
USERNAME = os.environ.get("CLONE_USERNAME", "")
BOT_NAME = os.environ.get("CLONE_NAME", "Bot")
WELCOME_ENV = os.environ.get("CLONE_WELCOME", "") or "Welcome {user}! 🎉 Bot ready hai."
HOST_SUPPORT = os.environ.get("CLONE_HOST_USERNAME", "")
FEATURES = {f for f in os.environ.get("CLONE_FEATURES", "").split(",") if f}
BASE = Path(__file__).resolve().parent
DB = BASE / "clone.db"
PHOTO = BASE / "welcome.jpg"
STARTED = time.time()
COLORS = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🟤"]
HTML = ParseMode.HTML


def sql(q, p=(), fetch=None):
    c = sqlite3.connect(DB, timeout=30)
    try:
        c.row_factory = sqlite3.Row
        cur = c.execute(q, p)
        c.commit()
        return cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else cur.lastrowid
    finally:
        c.close()


def init():
    c = sqlite3.connect(DB)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, username TEXT,
            banned INTEGER DEFAULT 0, joined TEXT);
        CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, file_id TEXT,
            kind TEXT, added TEXT);
        CREATE TABLE IF NOT EXISTS replies(keyword TEXT PRIMARY KEY, reply TEXT);
    """)
    c.commit()
    c.close()


def getset(k, default=None):
    r = sql("SELECT v FROM settings WHERE k=?", (k,), "one")
    return r["v"] if r else default


def setset(k, v):
    sql("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, v))


def e(x):
    return html.escape(str(x or ""))


def has(f):
    return f in FEATURES


def rb(text, data, i=0):
    return Btn(f"{COLORS[i % 7]} {text}", callback_data=data)


def is_owner(uid):
    return uid == OWNER


async def say(target, text, **kw):
    """HTML try karo; owner ke text me galat tag ho to plain text bhej do."""
    try:
        return await target(text, parse_mode=HTML, **kw)
    except BadRequest as ex:
        if "parse" in str(ex).lower() or "entit" in str(ex).lower():
            return await target(text, **kw)
        raise


def menu_kb(uid):
    rows = []
    r = []
    if has("file_share"):
        r.append(rb("File Share", "m:files", 0))
    if has("auto_reply"):
        r.append(rb("Auto Reply", "m:replies", 1))
    if r:
        rows.append(r)
    r = []
    if has("stats"):
        r.append(rb("Bot Stats", "m:stats", 2))
    r.append(rb("Help", "m:help", 3))
    rows.append(r)
    rows.append([rb("Developer", "m:dev", 4)])
    if is_owner(uid) and has("admin_panel"):
        rows.append([rb("Owner Panel", "m:admin", 6)])
    return Markup(rows)


def welcome_text(user):
    t = getset("welcome") or WELCOME_ENV
    return t.replace("{user}", user.first_name or "friend").replace("{bot}", BOT_NAME)


# ------------------------------------------------------------------ gate
async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u or u.is_bot:
        return
    name = u.first_name or ""
    sql("INSERT OR IGNORE INTO users(id,name,username,joined) VALUES(?,?,?,?)",
        (u.id, name, u.username, time.strftime("%Y-%m-%d %H:%M:%S")))
    sql("UPDATE users SET name=?, username=? WHERE id=?", (name, u.username, u.id))
    if has("ban_system") and not is_owner(u.id):
        r = sql("SELECT banned FROM users WHERE id=?", (u.id,), "one")
        if r and r["banned"]:
            if update.effective_message and update.effective_chat.type == "private":
                await update.effective_message.reply_text("🚫 Aap is bot se banned ho.")
            raise ApplicationHandlerStop


# ------------------------------------------------------------------ user side
async def send_start(chat, user):
    kb = menu_kb(user.id)
    if not has("welcome_message"):
        await chat.send_message(f"👋 Hi {user.first_name}! Neeche se option chuno.", reply_markup=kb)
        return
    text = welcome_text(user)
    fid = getset("photo")
    src = fid or (open(PHOTO, "rb") if PHOTO.is_file() else None)
    if src:
        try:
            short = len(text) <= 1000
            msg = await chat.send_photo(src, caption=text if short else None,
                                        parse_mode=HTML if short else None,
                                        reply_markup=kb if short else None)
            if not fid:
                setset("photo", msg.photo[-1].file_id)
            if not short:
                await say(lambda t, **k: chat.send_message(t, **k), text, reply_markup=kb)
            return
        except BadRequest as ex:
            if "parse" in str(ex).lower() or "entit" in str(ex).lower():
                await chat.send_photo(fid or open(PHOTO, "rb"), caption=text[:1000], reply_markup=kb)
                return
            log.warning("photo fail: %s", ex)
            setset("photo", "")
        except TelegramError as ex:
            log.warning("photo fail: %s", ex)
        finally:
            if hasattr(src, "close"):
                src.close()
    await say(lambda t, **k: chat.send_message(t, **k), text, reply_markup=kb)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_start(update.effective_chat, update.effective_user)


HELP_TXT = ("<b>Commands</b>\n/start - menu\n/help - help\n/about - developer info\n/id - aapki ID\n")
OWNER_HELP = (
    "\n<b>Owner commands</b>\n"
    "/admin - owner panel\n/setwelcome TEXT - welcome text ({user} = naam)\n"
    "/setpic - kisi photo ko reply karke welcome photo set\n/resetpic - default photo\n"
    "/broadcast - kisi message ko reply karke sab users ko bhejo (ya /broadcast TEXT)\n"
    "/ban ID, /unban ID\n/addfile NAME - kisi document/photo/video ko reply karke\n/delfile ID\n"
    "/addreply keyword | jawab\n/delreply keyword\n/users - user count")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = HELP_TXT + (OWNER_HELP if is_owner(update.effective_user.id) else "")
    await update.message.reply_text(txt, parse_mode=HTML)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 <code>{update.effective_user.id}</code>", parse_mode=HTML)


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(dev_text(), parse_mode=HTML)


def dev_text():
    t = f"👨‍💻 <b>Developer:</b> {e(DEV)}\n🤖 <b>Bot:</b> @{e(USERNAME)}"
    if HOST_SUPPORT:
        t += f"\n💬 Hosting support: @{e(HOST_SUPPORT)}"
    return t


def stats_text():
    total = sql("SELECT COUNT(*) c FROM users", fetch="one")["c"]
    banned = sql("SELECT COUNT(*) c FROM users WHERE banned=1", fetch="one")["c"]
    day = sql("SELECT COUNT(*) c FROM users WHERE joined >= datetime('now','-1 day','localtime')", fetch="one")["c"]
    up = int(time.time() - STARTED)
    return (f"📊 <b>Bot Stats</b>\n\n👥 Total users: <b>{total}</b>\n🆕 Last 24h: <b>{day}</b>\n"
            f"🚫 Banned: <b>{banned}</b>\n⏱ Uptime: {up // 3600}h {up % 3600 // 60}m")


async def edit(q, text, kb=None):
    try:
        await q.edit_message_text(text, parse_mode=HTML, reply_markup=kb, disable_web_page_preview=True)
    except BadRequest as ex:
        if "not modified" in str(ex).lower():
            return
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.chat.send_message(text, parse_mode=HTML, reply_markup=kb)


def back(i=6):
    return [rb("Back", "m:home", i)]


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    action = q.data.split(":", 1)[1]
    uid = q.from_user.id
    await q.answer()
    if action == "home":
        try:
            await q.message.delete()
        except Exception:
            pass
        await send_start(q.message.chat, q.from_user)
    elif action == "help":
        await edit(q, HELP_TXT + (OWNER_HELP if is_owner(uid) else ""), Markup([back()]))
    elif action == "dev":
        await edit(q, dev_text(), Markup([back()]))
    elif action == "stats" and has("stats"):
        await edit(q, stats_text(), Markup([back()]))
    elif action == "files" and has("file_share"):
        files = sql("SELECT id,title FROM files ORDER BY id DESC LIMIT 40", fetch="all")
        if not files:
            await edit(q, "📁 Abhi koi file share nahi hui.", Markup([back()]))
            return
        rows = [[rb(f["title"][:40], f"f:{f['id']}", i)] for i, f in enumerate(files)]
        rows.append(back())
        await edit(q, "📁 <b>Files</b>\nFile par click karo, mil jayegi:", Markup(rows))
    elif action == "replies" and has("auto_reply"):
        rep = sql("SELECT keyword FROM replies ORDER BY keyword", fetch="all")
        txt = ("💬 <b>Auto Reply</b>\nYe words likhoge to bot khud jawab dega:\n\n" +
               "\n".join(f"• <code>{e(r['keyword'])}</code>" for r in rep)) if rep else "💬 Abhi koi auto-reply set nahi."
        await edit(q, txt, Markup([back()]))
    elif action == "admin" and is_owner(uid) and has("admin_panel"):
        await edit(q, admin_text(), admin_kb())


async def cb_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not has("file_share"):
        await q.answer()
        return
    f = sql("SELECT * FROM files WHERE id=?", (int(q.data.split(":")[1]),), "one")
    if not f:
        await q.answer("File nahi mili.", show_alert=True)
        return
    await q.answer("📤 Bhej raha hoon...")
    send = {"photo": q.message.chat.send_photo, "video": q.message.chat.send_video,
            "audio": q.message.chat.send_audio}.get(f["kind"], q.message.chat.send_document)
    await send(f["file_id"], caption=f["title"][:900])


async def auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has("auto_reply") or not update.message or not update.message.text:
        return
    text = update.message.text.lower()
    for r in sql("SELECT keyword,reply FROM replies", fetch="all"):
        if r["keyword"] in text:
            await say(update.message.reply_text, r["reply"].replace("{user}", update.effective_user.first_name or ""))
            return


# ------------------------------------------------------------------ owner side
def admin_text():
    return (f"🔐 <b>Owner Panel</b> — {e(BOT_NAME)}\n\n" + stats_text() +
            "\n\nNeeche ke buttons se manage karo. Poori command list: /help")


def admin_kb():
    rows = []
    if has("broadcast"):
        rows.append([rb("Broadcast", "a:bc", 0)])
    if has("ban_system"):
        rows.append([rb("Banned Users", "a:bans", 1)])
    if has("file_share"):
        rows.append([rb("Manage Files", "a:files", 2)])
    if has("auto_reply"):
        rows.append([rb("Manage Replies", "a:reps", 3)])
    rows.append([rb("Welcome Setup", "a:wel", 4), rb("Users", "a:users", 5)])
    rows.append(back())
    return Markup(rows)


def owner_only(fn):
    async def wrap(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_owner(update.effective_user.id):
            return
        return await fn(update, context)
    return wrap


async def cb_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_owner(q.from_user.id):
        await q.answer("Sirf owner.", show_alert=True)
        return
    await q.answer()
    await do_admin(q, context, q.data.split(":", 1)[1])


async def do_admin(q, context, a):
    home = [rb("Panel", "m:admin", 6)]
    if a == "bc":
        await edit(q, "📢 <b>Broadcast</b>\n\nKisi bhi message (text/photo/video) ko <b>reply</b> karke <code>/broadcast</code> bhejo, "
                      "wo sab users ko chala jayega.\nYa seedha: <code>/broadcast Hello sabko</code>", Markup([home]))
    elif a == "bans":
        rows = sql("SELECT id,name FROM users WHERE banned=1 LIMIT 30", fetch="all")
        kb = [[rb(f"Unban {r['name'] or r['id']}", f"a:unban:{r['id']}", 3)] for r in rows] + [home]
        await edit(q, "🚫 <b>Banned users</b>\nBan: <code>/ban USER_ID</code>" + ("" if rows else "\n\nKoi banned nahi."), Markup(kb))
    elif a.startswith("unban:"):
        sql("UPDATE users SET banned=0 WHERE id=?", (int(a.split(":")[1]),))
        await do_admin(q, context, "bans")
    elif a == "files":
        rows = sql("SELECT id,title FROM files ORDER BY id DESC LIMIT 30", fetch="all")
        kb = [[rb(f"🗑 #{r['id']} {r['title'][:30]}", f"a:delf:{r['id']}", 0)] for r in rows] + [home]
        await edit(q, "📁 <b>Files</b>\nNayi file: kisi document/photo/video ko reply karke <code>/addfile NAAM</code>" +
                   ("" if rows else "\n\nAbhi koi file nahi."), Markup(kb))
    elif a.startswith("delf:"):
        sql("DELETE FROM files WHERE id=?", (int(a.split(":")[1]),))
        await do_admin(q, context, "files")
    elif a == "reps":
        rows = sql("SELECT keyword FROM replies ORDER BY keyword LIMIT 30", fetch="all")
        kb = [[rb(f"🗑 {r['keyword'][:30]}", f"a:delr:{i}", 0)] for i, r in enumerate(rows)] + [home]
        context.bot_data["rep_keys"] = [r["keyword"] for r in rows]
        await edit(q, "💬 <b>Auto replies</b>\nNaya: <code>/addreply hello | Namaste {user}!</code>" +
                   ("" if rows else "\n\nAbhi koi reply nahi."), Markup(kb))
    elif a.startswith("delr:"):
        keys = context.bot_data.get("rep_keys", [])
        i = int(a.split(":")[1])
        if i < len(keys):
            sql("DELETE FROM replies WHERE keyword=?", (keys[i],))
        await do_admin(q, context, "reps")
    elif a == "wel":
        await edit(q, "🖼 <b>Welcome Setup</b>\n\n"
                      "Text: <code>/setwelcome Welcome {user}! 🎉</code>\n"
                      "Photo: koi photo bhejo, us par reply karke <code>/setpic</code>\n"
                      "Default photo: <code>/resetpic</code>\n\n/start bhej kar preview dekho.", Markup([home]))
    elif a == "users":
        rows = sql("SELECT name,username,joined FROM users ORDER BY joined DESC LIMIT 10", fetch="all")
        lines = "\n".join(f"• {e(r['name'])} {('@' + e(r['username'])) if r['username'] else ''}" for r in rows)
        await edit(q, f"👥 <b>Latest users</b>\n\n{lines or 'Koi nahi'}\n\n" + stats_text(), Markup([home]))


@owner_only
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has("admin_panel"):
        await update.message.reply_text("Owner panel is bot me disabled hai.")
        return
    await update.message.reply_text(admin_text(), parse_mode=HTML, reply_markup=admin_kb())


@owner_only
async def cmd_setwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Usage: /setwelcome Welcome {user}! 🎉")
        return
    setset("welcome", text[:3000])
    await update.message.reply_text("✅ Welcome text update ho gaya. /start se dekho.")


@owner_only
async def cmd_setpic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("Kisi photo ko reply karke /setpic bhejo.")
        return
    setset("photo", r.photo[-1].file_id)
    await update.message.reply_text("✅ Welcome photo set ho gayi. /start se dekho.")


@owner_only
async def cmd_resetpic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    setset("photo", "")
    await update.message.reply_text("✅ Default photo wapas laga di.")


@owner_only
async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(stats_text(), parse_mode=HTML)


@owner_only
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has("ban_system"):
        return
    ban = update.message.text.split()[0].lstrip("/").split("@")[0] == "ban"
    arg = update.message.text.partition(" ")[2].strip()
    if not arg.isdigit():
        await update.message.reply_text(f"Usage: /{'ban' if ban else 'unban'} USER_ID")
        return
    uid = int(arg)
    if uid == OWNER:
        await update.message.reply_text("Apne aap ko ban nahi kar sakte 🙂")
        return
    sql("INSERT OR IGNORE INTO users(id,name,joined) VALUES(?,?,?)", (uid, "", time.strftime("%Y-%m-%d %H:%M:%S")))
    sql("UPDATE users SET banned=? WHERE id=?", (1 if ban else 0, uid))
    await update.message.reply_text(f"✅ {uid} {'ban' if ban else 'unban'} ho gaya.")


@owner_only
async def cmd_addfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has("file_share"):
        return
    r = update.message.reply_to_message
    if not r:
        await update.message.reply_text("Document/photo/video ko reply karke /addfile NAAM bhejo.")
        return
    if r.document:
        kind, fid, default = "document", r.document.file_id, r.document.file_name
    elif r.photo:
        kind, fid, default = "photo", r.photo[-1].file_id, "Photo"
    elif r.video:
        kind, fid, default = "video", r.video.file_id, "Video"
    elif r.audio:
        kind, fid, default = "audio", r.audio.file_id, r.audio.file_name or "Audio"
    else:
        await update.message.reply_text("Ye type support nahi (document/photo/video/audio chalega).")
        return
    title = update.message.text.partition(" ")[2].strip() or default or "File"
    fid_row = sql("INSERT INTO files(title,file_id,kind,added) VALUES(?,?,?,?)",
                  (title[:60], fid, kind, time.strftime("%Y-%m-%d")))
    await update.message.reply_text(f"✅ File add hui (#{fid_row}): {title}")


@owner_only
async def cmd_delfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = update.message.text.partition(" ")[2].strip()
    if not arg.isdigit():
        await update.message.reply_text("Usage: /delfile ID (ID Owner Panel > Manage Files me hai)")
        return
    sql("DELETE FROM files WHERE id=?", (int(arg),))
    await update.message.reply_text("✅ Hata di.")


@owner_only
async def cmd_addreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has("auto_reply"):
        return
    arg = update.message.text.partition(" ")[2]
    if "|" not in arg:
        await update.message.reply_text("Usage: /addreply keyword | jawab")
        return
    k, v = (x.strip() for x in arg.split("|", 1))
    if not k or not v:
        await update.message.reply_text("Keyword aur jawab dono chahiye.")
        return
    sql("INSERT OR REPLACE INTO replies(keyword,reply) VALUES(?,?)", (k.lower()[:60], v[:3000]))
    await update.message.reply_text(f"✅ Auto-reply set: '{k}'")


@owner_only
async def cmd_delreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    k = update.message.text.partition(" ")[2].strip().lower()
    sql("DELETE FROM replies WHERE keyword=?", (k,))
    await update.message.reply_text("✅ Hata diya.")


@owner_only
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has("broadcast"):
        return
    m = update.message
    src = m.reply_to_message
    text = m.text.partition(" ")[2].strip()
    if not src and not text:
        await m.reply_text("Kisi message ko reply karke /broadcast bhejo, ya /broadcast TEXT likho.")
        return
    users = [r["id"] for r in sql("SELECT id FROM users WHERE banned=0", fetch="all")]
    status = await m.reply_text(f"📢 Broadcast shuru: {len(users)} users...")
    ok = fail = 0
    for i, uid in enumerate(users, 1):
        try:
            if src:
                await context.bot.copy_message(uid, src.chat_id, src.message_id)
            else:
                await context.bot.send_message(uid, text)
            ok += 1
        except RetryAfter as ex:
            await asyncio.sleep(ex.retry_after + 1)
            try:
                await (context.bot.copy_message(uid, src.chat_id, src.message_id) if src
                       else context.bot.send_message(uid, text))
                ok += 1
            except TelegramError:
                fail += 1
        except (Forbidden, BadRequest, TelegramError):
            fail += 1
        if i % 25 == 0:
            await asyncio.sleep(1)
            try:
                await status.edit_text(f"📢 {i}/{len(users)} ... ✅ {ok} ❌ {fail}")
            except TelegramError:
                pass
    await status.edit_text(f"✅ Broadcast khatam.\n📨 Delivered: {ok}\n❌ Failed (blocked/deleted): {fail}")


async def on_error(update, context):
    log.error("handler error", exc_info=context.error)


async def post_init(app: Application):
    me = await app.bot.get_me()
    log.info("Clone @%s started (owner %s, features: %s)", me.username, OWNER, ",".join(sorted(FEATURES)))
    pub = [BotCommand("start", "Menu"), BotCommand("help", "Help"), BotCommand("about", "Developer"),
           BotCommand("id", "Meri ID")]
    try:
        await app.bot.set_my_commands(pub)
        if OWNER:
            await app.bot.set_my_commands(pub + [BotCommand("admin", "Owner panel"),
                                                 BotCommand("broadcast", "Sab ko message"),
                                                 BotCommand("setwelcome", "Welcome text"),
                                                 BotCommand("setpic", "Welcome photo")],
                                          scope=BotCommandScopeChat(OWNER))
    except TelegramError:
        log.warning("set_my_commands failed", exc_info=True)


def main():
    init()
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(TypeHandler(Update, gate), group=-1)
    for name, fn in [("start", cmd_start), ("help", cmd_help), ("id", cmd_id), ("about", cmd_about),
                     ("admin", cmd_admin), ("setwelcome", cmd_setwelcome), ("setpic", cmd_setpic),
                     ("resetpic", cmd_resetpic), ("users", cmd_users), ("ban", cmd_ban), ("unban", cmd_ban),
                     ("addfile", cmd_addfile), ("delfile", cmd_delfile), ("addreply", cmd_addreply),
                     ("delreply", cmd_delreply), ("broadcast", cmd_broadcast)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(cb_menu, pattern=r"^m:"))
    app.add_handler(CallbackQueryHandler(cb_admin, pattern=r"^a:"))
    app.add_handler(CallbackQueryHandler(cb_file, pattern=r"^f:\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, auto_reply))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
