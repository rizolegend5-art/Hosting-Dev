"""User side: deploy, manage, logs, stats, file manager, ENV, update code."""
import asyncio
import logging
import re
import time
import zipfile
from pathlib import Path

from telegram import Bot, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, Update
from telegram.constants import ChatAction
from telegram.ext import (CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler,
                          MessageHandler, filters)

import config
import database as db
import runner
from handlers.common import (HTML, edit, esc, fmt_uptime, is_admin, main_menu_kb, pre, rb,
                             send_welcome, show_menu, toast)

log = logging.getLogger(__name__)
D_TYPE, D_TOKEN, D_ZIP, U_ZIP, E_ADD, F_UPLOAD = range(6)
TMP = config.DATA_DIR / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
TEXT_EXT = {".py", ".js", ".json", ".txt", ".env", ".md", ".yaml", ".yml", ".ini", ".cfg", ".toml",
            ".html", ".css", ".sh", ".log", ".csv", ".ts"}


# ----------------------------------------------------------------- basics
HELP = (
    "❓ <b>Help</b>\n\n"
    "<b>Bot deploy karna</b>\n"
    "1. 🚀 Deploy New Bot dabao, Python ya Node.js chuno\n"
    "2. BotFather wala token bhejo\n"
    "3. Code ka <b>zip</b> bhejo (main.py / index.js zip ke root me ho)\n"
    "4. ▶️ Run dabao. Requirements khud install hongi.\n\n"
    "<b>Manage</b>\n"
    "• Start / Stop / Restart, Logs, Stats\n"
    "• 📁 File Manager: files dekho, download, delete, upload\n"
    "• 🔐 ENV Variables: API keys yahan daalo (token ki tarah safe)\n"
    "• 📝 Update Code: naya zip bhejo, bot khud restart hoga\n\n"
    "<b>Commands</b>\n"
    "/start - menu   /bots - mere bots   /myid - apni ID\n"
    "/ping - bot alive check   /cancel - chalta hua step cancel\n\n"
    "💡 Bot crash ho to auto-restart hota hai aur aapko message aata hai."
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_welcome(update.effective_chat, update.effective_user)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP, parse_mode=HTML)


async def cb_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await edit(q, HELP, Markup([[rb("Back", "menu", 6)]]))


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    role = "👑 Admin" if is_admin(u.id) else "👤 User"
    await update.message.reply_text(
        f"🆔 Aapki ID: <code>{u.id}</code>\nRole: {role}\n\n"
        "Admin banne ke liye ye ID Railway Variables me <code>ADMIN_IDS</code> (ya OWNER_ID) me daalo.",
        parse_mode=HTML)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = time.perf_counter()
    m = await update.message.reply_text("🏓 ...")
    ms = (time.perf_counter() - t) * 1000
    await m.edit_text(f"🏓 Pong! <b>{ms:.0f} ms</b>\n🤖 Hosted bots running: <b>{len(runner.RUN)}</b>",
                      parse_mode=HTML)


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await show_menu(q)


async def cb_mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    user = await db.get_user(uid)
    bots = await db.get_user_bots(uid)
    clones = await db.get_user_clones(uid)
    run = sum(1 for b in bots if runner.is_running("bot", b["bot_id"]))
    runc = sum(1 for c in clones if runner.is_running("clone", c["clone_id"]))
    await edit(q, (
        "📊 <b>Aapke Stats</b>\n\n"
        f"🤖 Hosted bots: <b>{len(bots)}</b> / {user['max_bots']} (running: {run})\n"
        f"🧬 Clone bots: <b>{len(clones)}</b> / {config.MAX_CLONE_BOTS_PER_USER} (running: {runc})\n"
        f"💾 RAM limit per bot: <b>{esc(user['ram_limit'])}</b>\n"
        f"⚙️ CPU limit: <b>{esc(user['cpu_limit'])}</b>\n"
        f"📅 Joined: {esc((user['join_date'] or '')[:10])}"), Markup([[rb("Back", "menu", 6)]]))


# ----------------------------------------------------------------- bot list / view
def _status(b) -> str:
    if not b["approved"]:
        return "⏳ Approval pending"
    if runner.is_running("bot", b["bot_id"]):
        m = runner.RUN.get(runner.key_of("bot", b["bot_id"]))
        return f"🟢 Running ({fmt_uptime(time.time() - m.started_at)})"
    if b["status"] == "crashed":
        return "💥 Crashed"
    return "🔴 Stopped"


async def _render_bots(uid):
    bots = await db.get_user_bots(uid)
    if not bots:
        return ("🤖 Aapke paas abhi koi bot nahi hai.\n🚀 Deploy New Bot se shuru karo!",
                Markup([[rb("Deploy New Bot", "deploy", 0)], [rb("Back", "menu", 6)]]))
    rows = []
    for i, b in enumerate(bots):
        icon = "🟢" if runner.is_running("bot", b["bot_id"]) else ("⏳" if not b["approved"] else "🔴")
        rows.append([Btn(f"{icon} {b['bot_name']} ({b['bot_type']})", callback_data=f"b:view:{b['bot_id']}")])
    rows.append([rb("Deploy New Bot", "deploy", 0)])
    rows.append([rb("Back", "menu", 6)])
    return f"🤖 <b>Aapke Bots</b> ({len(bots)})", Markup(rows)


async def cb_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    text, kb = await _render_bots(q.from_user.id)
    await edit(q, text, kb)


async def cmd_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await _render_bots(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=HTML)


async def _owned(q, bot_id):
    row = await db.get_bot(bot_id)
    if not row or (row["user_id"] != q.from_user.id and not is_admin(q.from_user.id)):
        await toast(q, "❌ Bot nahi mila.", True)
        return None
    return row


async def _bot_view(q, b):
    user = await db.get_user(b["user_id"])
    bid = b["bot_id"]
    text = (f"🤖 <b>{esc(b['bot_name'])}</b>\n\n"
            f"🆔 ID: <code>{bid}</code>\n"
            f"📦 Type: {esc(b['bot_type']).upper()}\n"
            f"⚡ Status: {_status(b)}\n"
            f"💾 RAM limit: {esc(user['ram_limit'] if user else '-')}\n"
            f"📅 Deployed: {esc((b['deployed_date'] or '')[:10])}")
    kb = Markup([
        [rb("Start", f"b:start:{bid}", 3), rb("Stop", f"b:stop:{bid}", 0), rb("Restart", f"b:restart:{bid}", 1)],
        [rb("Logs", f"b:logs:{bid}", 4), rb("Stats", f"b:stats:{bid}", 5), rb("Files", f"b:files:{bid}", 2)],
        [rb("ENV Vars", f"b:env:{bid}", 6), rb("Update Code", f"upd:{bid}", 3)],
        [rb("Install Log", f"b:ilog:{bid}", 4), rb("Delete", f"b:del:{bid}", 0)],
        [rb("Back", "bots", 6)],
    ])
    await edit(q, text, kb)


async def _start_flow(q, b, restart=False):
    bid = b["bot_id"]
    if not b["approved"]:
        await toast(q, "⏳ Admin approval ka intezar hai.", True)
        return
    if not restart and runner.is_running("bot", bid):
        await toast(q, "Bot pehle se running hai!", True)
        return
    await toast(q, "⏳ Start ho raha hai...")
    await edit(q, f"⏳ <b>{esc(b['bot_name'])}</b>\nDependencies install + start ho raha hai, 10-60 sec lag sakte hain...")
    if restart:
        await runner.stop("bot", bid)
    ok, msg = await runner.start_bot_row(await db.get_bot(bid))
    if ok:
        await _bot_view(q, await db.get_bot(bid))
        return
    await edit(q, f"❌ <b>Bot start nahi hua</b>\n\n{pre(msg, 3000)}",
               Markup([[rb("Retry", f"b:start:{bid}", 3), rb("Logs", f"b:logs:{bid}", 4)],
                       [rb("Back", f"b:view:{bid}", 6)]]))


async def cb_bot_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, action, sid = q.data.split(":")
    bid = int(sid)
    b = await _owned(q, bid)
    if not b:
        return
    await q.answer()
    if action == "view":
        await _bot_view(q, b)
    elif action == "start":
        await _start_flow(q, b)
    elif action == "restart":
        await _start_flow(q, b, restart=True)
    elif action == "stop":
        await runner.stop("bot", bid)
        await toast(q, "✅ Bot stop ho gaya.")
        await _bot_view(q, await db.get_bot(bid))
    elif action == "logs":
        logs = runner.get_logs("bot", bid, 45)
        await edit(q, f"📜 <b>Logs — {esc(b['bot_name'])}</b>\n{pre(logs)}", Markup([
            [rb("Refresh", f"b:logs:{bid}", 3), rb("Download", f"b:dlog:{bid}", 4)],
            [rb("Back", f"b:view:{bid}", 6)]]))
    elif action == "dlog":
        p = runner.log_path("bot", bid)
        if p.is_file() and p.stat().st_size:
            with open(p, "rb") as f:
                await q.message.reply_document(f, filename=f"{b['bot_name']}_logs.txt", caption="📜 Full logs")
        else:
            await toast(q, "Abhi koi log nahi hai.", True)
    elif action == "ilog":
        t = runner.tail_text(runner.install_log_path("bot", bid), 40) or "Koi install activity nahi (deps cached/none)."
        await edit(q, f"📦 <b>Install Log</b>\n{pre(t)}", Markup([[rb("Back", f"b:view:{bid}", 6)]]))
    elif action == "stats":
        s = await runner.stats_async("bot", bid)
        if not s:
            await toast(q, "Bot running nahi hai.", True)
            return
        await edit(q, (f"📊 <b>Stats — {esc(b['bot_name'])}</b>\n\n"
                       f"🆔 PID: <code>{s['pid']}</code>\n⏱ Uptime: {fmt_uptime(s['uptime'])}\n"
                       f"🧠 CPU: {s['cpu']:.1f}%\n💾 RAM: {s['ram_mb']:.1f} MB / {s['limit_mb']} MB\n"
                       f"🔁 Auto-restarts: {s['restarts']}\n🧵 Processes: {s['procs']}"),
                   Markup([[rb("Refresh", f"b:stats:{bid}", 3)], [rb("Back", f"b:view:{bid}", 6)]]))
    elif action == "del":
        await edit(q, f"🗑 <b>{esc(b['bot_name'])}</b> ko permanently delete karna hai? Files aur logs sab ud jayenge.",
                   Markup([[rb("Haan, Delete", f"b:delyes:{bid}", 0)], [rb("Nahi", f"b:view:{bid}", 3)]]))
    elif action == "delyes":
        await runner.delete_files("bot", bid)
        await db.delete_bot_db(bid)
        await toast(q, "✅ Delete ho gaya.")
        text, kb = await _render_bots(q.from_user.id)
        await edit(q, text, kb)
    elif action == "files":
        context.user_data["fm"] = {"bot": bid, "cwd": "", "items": [], "file": None}
        await _fm_list(q, context)
    elif action == "env":
        await _env_menu(q, bid)


# ----------------------------------------------------------------- file manager
def _fm_root(bid) -> Path:
    return runner.dir_of("bot", bid).resolve()


def _fm_safe(bid, rel) -> Path | None:
    root = _fm_root(bid)
    p = (root / rel).resolve()
    return p if (p == root or root in p.parents) else None


async def _fm_list(q, context):
    fm = context.user_data.get("fm")
    if not fm:
        await toast(q, "Session expire ho gaya, dobara Files kholo.", True)
        return
    d = _fm_safe(fm["bot"], fm["cwd"])
    if not d or not d.is_dir():
        fm["cwd"] = ""
        d = _fm_root(fm["bot"])
    fm["items"] = runner.list_files(_fm_root(fm["bot"]), fm["cwd"])[:40]
    fm["file"] = None
    rows = []
    for i, (name, is_dir, size) in enumerate(fm["items"]):
        label = f"📁 {name}/" if is_dir else f"📄 {name} ({runner.human(size)})"
        rows.append([Btn(label[:60], callback_data=f"fm:i:{i}")])
    nav = [rb("Upload", "fm:upl", 3)]
    if fm["cwd"]:
        nav.insert(0, rb("Up", "fm:up", 4))
    rows.append(nav)
    rows.append([rb("Back", f"b:view:{fm['bot']}", 6)])
    where = "/" + fm["cwd"] if fm["cwd"] else "/"
    await edit(q, f"📁 <b>File Manager</b>\n<code>{esc(where)}</code>  ({len(fm['items'])} items)", Markup(rows))


async def cb_fm_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    fm = context.user_data.get("fm")
    if not fm:
        await toast(q, "Session expire ho gaya, dobara Files kholo.", True)
        return
    b = await _owned(q, fm["bot"])
    if not b:
        return
    parts = q.data.split(":")
    action = parts[1]
    if action == "up":
        fm["cwd"] = str(Path(fm["cwd"]).parent) if Path(fm["cwd"]).parent != Path(".") else ""
        await _fm_list(q, context)
    elif action == "back":
        await _fm_list(q, context)
    elif action == "i":
        idx = int(parts[2])
        if idx >= len(fm["items"]):
            await _fm_list(q, context)
            return
        name, is_dir, size = fm["items"][idx]
        rel = str(Path(fm["cwd"]) / name) if fm["cwd"] else name
        if is_dir:
            fm["cwd"] = rel
            await _fm_list(q, context)
            return
        fm["file"] = rel
        p = _fm_safe(fm["bot"], rel)
        body = ""
        if p and p.suffix.lower() in TEXT_EXT and size < 300_000:
            body = pre(p.read_text(encoding="utf-8", errors="replace")[:2800].replace("\x00", ""), 2800)
        else:
            body = "ℹ️ Preview available nahi (binary ya bahut bada). Download karo."
        await edit(q, f"📄 <b>{esc(rel)}</b> ({runner.human(size)})\n{body}", Markup([
            [rb("Download", "fm:dl", 3), rb("Delete", "fm:rm", 0)], [rb("Back", "fm:back", 6)]]))
    elif action == "dl":
        p = _fm_safe(fm["bot"], fm["file"] or "")
        if p and p.is_file():
            with open(p, "rb") as f:
                await q.message.reply_document(f, filename=p.name)
        else:
            await toast(q, "File nahi mili.", True)
    elif action == "rm":
        await edit(q, f"🗑 <code>{esc(fm['file'])}</code> delete karni hai?", Markup([
            [rb("Haan", "fm:rmy", 0), rb("Nahi", "fm:back", 3)]]))
    elif action == "rmy":
        p = _fm_safe(fm["bot"], fm["file"] or "")
        if p and p.is_file():
            p.unlink()
            await toast(q, "✅ Delete ho gayi.")
        await _fm_list(q, context)


async def fm_upload_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    fm = context.user_data.get("fm")
    if not fm or not await _owned(q, fm["bot"]):
        return ConversationHandler.END
    await edit(q, f"📤 Jo file upload karni hai wo <b>document</b> ki tarah bhejo.\n"
                  f"Save hogi: <code>/{esc(fm['cwd'])}</code>\nMax {config.MAX_ZIP_SIZE // 1048576} MB.",
               Markup([[rb("Cancel", "fm:back", 0)]]))
    return F_UPLOAD


async def fm_upload_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fm = context.user_data.get("fm")
    doc = update.message.document
    if not fm or not doc:
        await update.message.reply_text("❌ Document bhejo.")
        return F_UPLOAD
    if doc.file_size and doc.file_size > config.MAX_ZIP_SIZE:
        await update.message.reply_text("❌ File bahut badi hai.")
        return F_UPLOAD
    name = re.sub(r"[^\w.\- ]", "_", Path(doc.file_name or "file.bin").name)[:100] or "file.bin"
    dest_dir = _fm_safe(fm["bot"], fm["cwd"])
    if not dest_dir or not dest_dir.is_dir():
        await update.message.reply_text("❌ Folder nahi mila.")
        return ConversationHandler.END
    f = await context.bot.get_file(doc.file_id)
    await f.download_to_drive(dest_dir / name)
    await update.message.reply_text(f"✅ <code>{esc(name)}</code> upload ho gayi.\nRestart karo taaki changes apply hon.",
                                    parse_mode=HTML, reply_markup=Markup([
                                        [rb("Files", f"b:files:{fm['bot']}", 2), rb("Restart", f"b:restart:{fm['bot']}", 1)]]))
    return ConversationHandler.END


# ----------------------------------------------------------------- ENV
def _mask(v):
    return (v[:2] + "•••" + v[-1:]) if len(v) > 6 else "•••"


async def _env_menu(q, bid):
    env = runner.read_env_file(runner.dir_of("bot", bid))
    keys = sorted(env)[:20]
    lines = "\n".join(f"• <code>{esc(k)}</code> = {esc(_mask(env[k]))}" for k in keys) or "Abhi koi variable nahi."
    rows = [[rb("Add / Update", f"envadd:{bid}", 3)]]
    for i, k in enumerate(keys):
        rows.append([Btn(f"🗑 {k}", callback_data=f"env:d:{bid}:{i}")])
    rows.append([rb("Restart (apply)", f"b:restart:{bid}", 1)])
    rows.append([rb("Back", f"b:view:{bid}", 6)])
    await edit(q, f"🔐 <b>ENV Variables</b>\nBot ko ye environment variables milte hain (BOT_TOKEN automatic hai).\n\n{lines}",
               Markup(rows))


async def cb_env_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, action, sid, sidx = q.data.split(":")
    b = await _owned(q, int(sid))
    if not b:
        return
    await q.answer()
    d = runner.dir_of("bot", b["bot_id"])
    env = runner.read_env_file(d)
    keys = sorted(env)[:20]
    idx = int(sidx)
    if action == "d" and idx < len(keys):
        env.pop(keys[idx], None)
        runner.write_env_file(d, env)
        await toast(q, "✅ Hata diya. Restart karo.")
    await _env_menu(q, b["bot_id"])


async def env_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    bid = int(q.data.split(":")[1])
    if not await _owned(q, bid):
        return ConversationHandler.END
    await q.answer()
    context.user_data["env_bot"] = bid
    await edit(q, "🔐 Variable is format me bhejo (ek ya zyada lines):\n<code>API_KEY=abc123\nDB_URL=xyz</code>\n\n"
                  "Aapka message security ke liye delete kar diya jayega.",
               Markup([[rb("Cancel", f"b:env:{bid}", 0)]]))
    return E_ADD


async def env_add_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bid = context.user_data.get("env_bot")
    b = await db.get_bot(bid) if bid else None
    uid = update.effective_user.id
    if not b or (b["user_id"] != uid and not is_admin(uid)):
        return ConversationHandler.END
    d = runner.dir_of("bot", bid)
    env = runner.read_env_file(d)
    added, bad = [], []
    for line in (update.message.text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                env[k] = v.strip().strip("'\"")
                added.append(k)
                continue
        bad.append(line[:30])
    try:
        await update.message.delete()
    except Exception:
        pass
    if not added:
        await update.effective_chat.send_message("❌ Sahi format: KEY=VALUE. Dobara bhejo.")
        return E_ADD
    runner.write_env_file(d, env)
    txt = "✅ Save hua: " + ", ".join(f"<code>{esc(k)}</code>" for k in added)
    if bad:
        txt += f"\n⚠️ Skip: {esc(', '.join(bad))}"
    await update.effective_chat.send_message(txt + "\nBot restart karo.", parse_mode=HTML, reply_markup=Markup([
        [rb("Restart", f"b:restart:{bid}", 1), rb("ENV", f"b:env:{bid}", 3)]]))
    return ConversationHandler.END


# ----------------------------------------------------------------- deploy flow
async def _download_zip(context, doc, prefix) -> Path:
    TMP.mkdir(parents=True, exist_ok=True)
    path = TMP / f"{prefix}_{int(time.time() * 1000)}.zip"
    f = await context.bot.get_file(doc.file_id)
    await f.download_to_drive(path)
    return path


async def deploy_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    user = await db.get_user(uid)
    bots = await db.get_user_bots(uid)
    if len(bots) >= user["max_bots"] and not is_admin(uid):
        await edit(q, f"❌ Aap max <b>{user['max_bots']}</b> bots hi host kar sakte ho.",
                   Markup([[rb("My Bots", "bots", 1), rb("Back", "menu", 6)]]))
        return ConversationHandler.END
    context.user_data["deploy"] = {}
    await edit(q, "🚀 <b>Deploy New Bot</b>\nBot ka type chuno:", Markup([
        [rb("Python", "dt:python", 3), rb("Node.js", "dt:nodejs", 4)], [rb("Cancel", "cancel", 0)]]))
    return D_TYPE


async def deploy_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["deploy"] = {"type": q.data.split(":")[1]}
    await edit(q, "🔑 Apne bot ka <b>token</b> bhejo (@BotFather se).\n"
                  "Message verify hote hi delete kar diya jayega.", Markup([[rb("Cancel", "cancel", 0)]]))
    return D_TOKEN


async def deploy_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = (update.message.text or "").strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    chat = update.effective_chat
    if not re.fullmatch(r"\d{6,}:[\w-]{30,}", token):
        await chat.send_message("❌ Token ka format galat hai. BotFather wala poora token bhejo.")
        return D_TOKEN
    if token == config.BOT_TOKEN:
        await chat.send_message("❌ Ye is hosting bot ka apna token hai. Apne bot ka token do.")
        return D_TOKEN
    for row in await db.get_all_bots():
        if row["bot_token"] == token:
            await chat.send_message("❌ Ye token pehle se host ho raha hai. Pehle purana bot delete karo.")
            return D_TOKEN
    wait = await chat.send_message("⏳ Token verify ho raha hai...")
    try:
        async with Bot(token) as b:
            me = await b.get_me()
    except Exception:
        await wait.edit_text("❌ Token verify nahi hua. Sahi/active token bhejo (revoke to nahi hua?).")
        return D_TOKEN
    context.user_data["deploy"].update(token=token, username=me.username)
    note = "\nℹ️ Moderation ke liye code ki copy admin channel me jaati hai (token nahi)." if config.BOT_FILES_CHANNEL else ""
    t = context.user_data["deploy"]["type"]
    need = "main.py (+ requirements.txt)" if t == "python" else "index.js (+ package.json)"
    await wait.edit_text(
        f"✅ Token OK: <b>@{esc(me.username)}</b>\n\n📁 Ab code ka <b>zip</b> bhejo.\nZip ke <b>root</b> me {need} ho.\n"
        f"Max size: {config.MAX_ZIP_SIZE // 1048576} MB{note}", parse_mode=HTML,
        reply_markup=Markup([[rb("Cancel", "cancel", 0)]]))
    return D_ZIP


async def _archive(context, row, user):
    """Optional: admin channel me code ka backup (token/.env ke bina)."""
    if not config.BOT_FILES_CHANNEL:
        return
    d = runner.dir_of("bot", row["bot_id"])
    out = TMP / f"arch_{row['bot_id']}_{int(time.time())}.zip"

    def build():
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in d.rglob("*"):
                rel = p.relative_to(d)
                if p.is_file() and not set(rel.parts) & {".deps", "node_modules", "__pycache__", ".env"}:
                    z.write(p, rel)
    try:
        await asyncio.to_thread(build)
        if out.stat().st_size < 49_000_000:
            cap = (f"📦 <b>{esc(row['bot_name'])}</b> ({esc(row['bot_type'])})\n"
                   f"👤 {esc(user.first_name)} (<code>{user.id}</code>) @{esc(user.username or '-')}\n🆔 bot #{row['bot_id']}")
            with open(out, "rb") as f:
                await context.bot.send_document(config.BOT_FILES_CHANNEL, f, caption=cap, parse_mode=HTML)
    except Exception:
        log.warning("channel archive fail", exc_info=True)
    finally:
        out.unlink(missing_ok=True)


async def deploy_zip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    data = context.user_data.get("deploy") or {}
    if not data.get("token"):
        await update.message.reply_text("Session expire ho gaya. /start karke dobara try karo.")
        return ConversationHandler.END
    if not doc or not (doc.file_name or "").lower().endswith(".zip"):
        await update.message.reply_text("❌ Sirf .zip file bhejo.")
        return D_ZIP
    if doc.file_size and doc.file_size > config.MAX_ZIP_SIZE:
        await update.message.reply_text(f"❌ Zip bahut badi hai (max {config.MAX_ZIP_SIZE // 1048576} MB).")
        return D_ZIP
    uid = update.effective_user.id
    await update.effective_chat.send_chat_action(ChatAction.UPLOAD_DOCUMENT)
    status = await update.message.reply_text("⏳ Zip download + extract ho rahi hai...")
    path = await _download_zip(context, doc, f"dep{uid}")
    need_approval = (await db.get_setting("deployment_approval", "0")) == "1" and not is_admin(uid)
    bid = await db.add_bot(uid, "@" + data["username"], data["token"], data["type"], 0 if need_approval else 1)
    d = runner.dir_of("bot", bid)
    try:
        await asyncio.to_thread(runner.safe_extract, path, d)
        ok, msg = runner.validate_code(d, data["type"])
    except ValueError as e:
        ok, msg = False, str(e)
    finally:
        path.unlink(missing_ok=True)
    if not ok:
        await runner.delete_files("bot", bid)
        await db.delete_bot_db(bid)
        await status.edit_text(f"❌ {msg}\n\nZip theek karke dobara bhejo ya /start se shuru karo.")
        return D_ZIP
    files = runner.list_files(d)
    listing = "\n".join(f"{'📁' if is_dir else '📄'} {n}" for n, is_dir, _ in files[:15])
    kb = [[rb("Run Bot", f"b:start:{bid}", 3)], [rb("Files", f"b:files:{bid}", 2), rb("Menu", "menu", 6)]]
    extra = ""
    if need_approval:
        extra = "\n\n⏳ Admin approval zaroori hai. Approve hote hi Run kar sakoge."
        for aid in config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    aid, f"🆕 <b>Approval request</b>\nUser: {esc(update.effective_user.first_name)} "
                         f"(<code>{uid}</code>)\nBot: @{esc(data['username'])} ({data['type']}) #{bid}",
                    parse_mode=HTML, reply_markup=Markup([[rb("Approve", f"adm:ap:{bid}", 3),
                                                           rb("Reject", f"adm:rj:{bid}", 0)]]))
            except Exception:
                pass
    await status.edit_text(
        f"✅ <b>Zip ready!</b> (entry: <code>{esc(msg)}</code>)\n\n📁 Files:\n{esc(listing)}{extra}",
        parse_mode=HTML, reply_markup=Markup(kb))
    context.user_data.pop("deploy", None)
    asyncio.create_task(_archive(context, await db.get_bot(bid), update.effective_user))
    return ConversationHandler.END


# ----------------------------------------------------------------- update code
async def upd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    bid = int(q.data.split(":")[1])
    if not await _owned(q, bid):
        return ConversationHandler.END
    await q.answer()
    context.user_data["upd_bot"] = bid
    await edit(q, "📝 Naye code ka <b>zip</b> bhejo.\nPurani files replace hongi (ENV aur installed deps bachenge). "
                  "Agar bot running hai to khud restart hoga.", Markup([[rb("Cancel", f"b:view:{bid}", 0)]]))
    return U_ZIP


async def upd_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    bid = context.user_data.get("upd_bot")
    b = await db.get_bot(bid) if bid else None
    uid = update.effective_user.id
    if not b or (b["user_id"] != uid and not is_admin(uid)):
        return ConversationHandler.END
    if not doc or not (doc.file_name or "").lower().endswith(".zip"):
        await update.message.reply_text("❌ Sirf .zip file bhejo.")
        return U_ZIP
    if doc.file_size and doc.file_size > config.MAX_ZIP_SIZE:
        await update.message.reply_text("❌ Zip bahut badi hai.")
        return U_ZIP
    status = await update.message.reply_text("⏳ Code update ho raha hai...")
    path = await _download_zip(context, doc, f"upd{uid}")
    was_running = runner.is_running("bot", bid)
    if was_running:
        await runner.stop("bot", bid)
    try:
        ok, msg = await asyncio.to_thread(runner.replace_code, path, runner.dir_of("bot", bid), b["bot_type"])
    finally:
        path.unlink(missing_ok=True)
    if not ok:
        await status.edit_text(f"❌ Update fail: {msg}\nPurana code same hai.")
        if was_running:
            await runner.start_bot_row(await db.get_bot(bid))
        return ConversationHandler.END
    text = "✅ Code update ho gaya."
    if was_running:
        await status.edit_text(text + " Bot restart ho raha hai...")
        ok2, m2 = await runner.start_bot_row(await db.get_bot(bid))
        text += " Bot " + ("🟢 chal raha hai." if ok2 else f"start nahi hua:\n{m2[-600:]}")
        await status.edit_text(text[:3900])
    else:
        await status.edit_text(text + " Run karne ke liye Start dabao.", reply_markup=Markup([[rb("Open Bot", f"b:view:{bid}", 3)]]))
    context.user_data.pop("upd_bot", None)
    asyncio.create_task(_archive(context, await db.get_bot(bid), update.effective_user))
    return ConversationHandler.END


# ----------------------------------------------------------------- cancel
async def conv_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    for k in ("deploy", "upd_bot", "env_bot"):
        context.user_data.pop(k, None)
    await show_menu(q)
    return ConversationHandler.END


async def conv_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for k in ("deploy", "upd_bot", "env_bot"):
        context.user_data.pop(k, None)
    await update.message.reply_text("❌ Cancel kar diya.", reply_markup=main_menu_kb(update.effective_user.id))
    return ConversationHandler.END


async def conv_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for k in ("deploy", "upd_bot", "env_bot"):
        context.user_data.pop(k, None)
    await send_welcome(update.effective_chat, update.effective_user)
    return ConversationHandler.END


async def conv_leave_to_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Flow ke beech me koi bot-button dabe to flow band karo aur wahi action chalao."""
    if update.callback_query.data == "bots":
        await cb_bots(update, context)
    else:
        await cb_bot_router(update, context)
    return ConversationHandler.END


async def conv_fm_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _fm_list(q, context)
    return ConversationHandler.END


def get_user_handlers():
    zipf = filters.Document.ALL
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(deploy_start, pattern=r"^deploy$"),
            CallbackQueryHandler(upd_start, pattern=r"^upd:\d+$"),
            CallbackQueryHandler(env_add_start, pattern=r"^envadd:\d+$"),
            CallbackQueryHandler(fm_upload_start, pattern=r"^fm:upl$"),
        ],
        states={
            D_TYPE: [CallbackQueryHandler(deploy_type, pattern=r"^dt:(python|nodejs)$")],
            D_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, deploy_token)],
            D_ZIP: [MessageHandler(zipf, deploy_zip)],
            U_ZIP: [MessageHandler(zipf, upd_receive)],
            E_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, env_add_receive)],
            F_UPLOAD: [MessageHandler(zipf, fm_upload_receive)],
        },
        fallbacks=[
            CommandHandler("cancel", conv_cancel_cmd),
            CommandHandler("start", conv_start),
            CallbackQueryHandler(conv_fm_back, pattern=r"^fm:back$"),
            CallbackQueryHandler(conv_leave_to_router, pattern=r"^(b:\w+:\d+|bots)$"),
            CallbackQueryHandler(conv_cancel_cb),
        ],
        allow_reentry=True,
    )
    return [
        CommandHandler("start", cmd_start),
        CommandHandler("help", cmd_help),
        CommandHandler("myid", cmd_myid),
        CommandHandler("ping", cmd_ping),
        CommandHandler("bots", cmd_bots),
        conv,
        CallbackQueryHandler(cb_menu, pattern=r"^menu$"),
        CallbackQueryHandler(cb_help, pattern=r"^help$"),
        CallbackQueryHandler(cb_mystats, pattern=r"^mystats$"),
        CallbackQueryHandler(cb_bots, pattern=r"^bots$"),
        CallbackQueryHandler(cb_bot_router, pattern=r"^b:\w+:\d+$"),
        CallbackQueryHandler(cb_fm_router, pattern=r"^fm:"),
        CallbackQueryHandler(cb_env_router, pattern=r"^env:\w:\d+:\d+$"),
    ]
