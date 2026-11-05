"""Admin panel: users, bots, clones, approvals, broadcast, limits, server stats, backup."""
import asyncio
import logging
import sqlite3
import time
import zipfile

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, Update
from telegram.error import RetryAfter, TelegramError
from telegram.ext import (CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler,
                          MessageHandler, filters)

import config
import database as db
import runner
from handlers.common import HTML, edit, esc, fmt_uptime, is_admin, pre, rb, send_welcome, toast

log = logging.getLogger(__name__)
B_MSG, B_LIM = range(2)
PER_PAGE = 8


def panel_kb(pending=0):
    rows = [
        [rb("Users", "adm:users:0", 0), rb("Bots", "adm:bots:0", 1)],
        [rb("Clones", "adm:clones:0", 2), rb("Server Stats", "adm:stats", 3)],
        [rb("Broadcast", "adm:bc", 4), rb("Settings", "adm:set", 5)],
        [rb("Backup", "adm:backup", 6)],
    ]
    if pending:
        rows.insert(0, [rb(f"Pending Approvals ({pending})", "adm:pending", 0)])
    rows.append([rb("Menu", "menu", 6)])
    return Markup(rows)


async def _panel_text():
    users, bots, clones = await db.get_all_users(), await db.get_all_bots(), await db.get_all_clones()
    running = sum(1 for b in bots if runner.is_running("bot", b["bot_id"]))
    runc = sum(1 for c in clones if runner.is_running("clone", c["clone_id"]))
    pending = sum(1 for b in bots if not b["approved"])
    txt = (f"🔐 <b>Admin Panel</b>\n\n👥 Users: <b>{len(users)}</b>\n🤖 Bots: <b>{len(bots)}</b> (🟢 {running})\n"
           f"🧬 Clones: <b>{len(clones)}</b> (🟢 {runc})")
    return txt, pending


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text(
            f"❌ Aap admin nahi ho.\n🆔 Aapki ID: <code>{uid}</code>\n\n"
            "Agar aap owner ho to ye ID Railway Variables me <code>ADMIN_IDS</code> (ya OWNER_ID) me daalo "
            "aur redeploy karo.", parse_mode=HTML)
        return
    txt, pending = await _panel_text()
    await update.message.reply_text(txt, parse_mode=HTML, reply_markup=panel_kb(pending))


def _page(rows, page):
    pages = max(1, (len(rows) + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, pages - 1))
    return rows[page * PER_PAGE:(page + 1) * PER_PAGE], page, pages


def _nav(prefix, page, pages):
    nav = []
    if page > 0:
        nav.append(Btn("⬅️", callback_data=f"{prefix}:{page - 1}"))
    nav.append(Btn(f"{page + 1}/{pages}", callback_data="adm:noop"))
    if page < pages - 1:
        nav.append(Btn("➡️", callback_data=f"{prefix}:{page + 1}"))
    return nav


async def _notify_user(context, uid, text):
    try:
        await context.bot.send_message(uid, text, parse_mode=HTML)
    except TelegramError:
        pass


async def cb_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("❌ Sirf admin.", show_alert=True)
        return
    await q.answer()
    parts = q.data.split(":")
    act = parts[1]
    arg = int(parts[2]) if len(parts) > 2 and parts[2].lstrip("-").isdigit() else 0
    back = [rb("Panel", "adm:main", 6)]

    if act == "noop":
        return
    if act == "main":
        txt, pending = await _panel_text()
        await edit(q, txt, panel_kb(pending))

    # ---- users
    elif act == "users":
        users = list(await db.get_all_users())
        chunk, page, pages = _page(users, arg)
        rows = [[Btn(f"{'🚫' if u['is_banned'] else '✅'} {u['first_name'] or u['username'] or u['user_id']}",
                     callback_data=f"adm:u:{u['user_id']}")] for u in chunk]
        rows.append(_nav("adm:users", page, pages))
        rows.append(back)
        await edit(q, f"👥 <b>Users</b> ({len(users)})", Markup(rows))
    elif act == "u":
        if not await db.get_user(arg):
            await toast(q, "User nahi mila.", True)
            return
        await _show_user(q, arg)
    elif act in ("ban", "unban"):
        if act == "ban" and is_admin(arg):
            await toast(q, "Admin ko ban nahi kar sakte.", True)
            return
        await db.set_ban(arg, act == "ban")
        if act == "ban":
            for b in await db.get_user_bots(arg):
                await runner.stop("bot", b["bot_id"])
            for c in await db.get_user_clones(arg):
                await runner.stop("clone", c["clone_id"])
        await toast(q, "✅ Done")
        await _show_user(q, arg)
    elif act == "ub":
        bots = await db.get_user_bots(arg)
        rows = [[Btn(f"{'🟢' if runner.is_running('bot', b['bot_id']) else '🔴'} {b['bot_name']}", callback_data=f"adm:bv:{b['bot_id']}")] for b in bots]
        rows.append([rb("Back", f"adm:u:{arg}", 6)])
        await edit(q, f"🤖 User {arg} ke bots", Markup(rows))

    # ---- bots
    elif act == "bots":
        bots = list(await db.get_all_bots())
        chunk, page, pages = _page(bots, arg)
        rows = [[Btn(f"{'🟢' if runner.is_running('bot', b['bot_id']) else ('⏳' if not b['approved'] else '🔴')} #{b['bot_id']} {b['bot_name']}",
                     callback_data=f"adm:bv:{b['bot_id']}")] for b in chunk]
        rows.append(_nav("adm:bots", page, pages))
        rows.append(back)
        await edit(q, f"🤖 <b>All Bots</b> ({len(bots)})", Markup(rows))
    elif act == "bv":
        await _bot_view(q, arg)
    elif act in ("bstart", "bstop"):
        b = await db.get_bot(arg)
        if not b:
            return
        if act == "bstop":
            await runner.stop("bot", arg)
        else:
            await edit(q, "⏳ Start ho raha hai...")
            ok, msg = await runner.start_bot_row(b)
            if not ok:
                await edit(q, f"❌ Start fail:\n{pre(msg, 3000)}", Markup([[rb("Back", f"adm:bv:{arg}", 6)]]))
                return
        await _bot_view(q, arg)
    elif act == "blog":
        await edit(q, f"📜 <b>Logs #{arg}</b>\n{pre(runner.get_logs('bot', arg, 45))}",
                   Markup([[rb("Refresh", f"adm:blog:{arg}", 3)], [rb("Back", f"adm:bv:{arg}", 6)]]))
    elif act == "bdl":
        d = runner.dir_of("bot", arg)
        out = config.DATA_DIR / "tmp" / f"admin_dl_{arg}_{int(time.time())}.zip"
        out.parent.mkdir(exist_ok=True)
        await asyncio.to_thread(_zip_dir, d, out)
        if out.stat().st_size < 49_000_000:
            with open(out, "rb") as f:
                await q.message.reply_document(f, filename=f"bot_{arg}.zip")
        else:
            await toast(q, "Zip 50MB se bada hai.", True)
        out.unlink(missing_ok=True)
    elif act == "bdel":
        await edit(q, f"🗑 Bot #{arg} delete karna hai?", Markup([[rb("Haan", f"adm:bdely:{arg}", 0), rb("Nahi", f"adm:bv:{arg}", 3)]]))
    elif act == "bdely":
        b = await db.get_bot(arg)
        await runner.delete_files("bot", arg)
        await db.delete_bot_db(arg)
        if b:
            await _notify_user(context, b["user_id"], f"ℹ️ Admin ne aapka bot <b>{esc(b['bot_name'])}</b> delete kar diya.")
        await toast(q, "✅ Delete ho gaya.")
        await _list_bots(q)

    # ---- approvals
    elif act == "pending":
        rows = [[Btn(f"⏳ #{b['bot_id']} {b['bot_name']}", callback_data=f"adm:bv:{b['bot_id']}")]
                for b in await db.get_all_bots() if not b["approved"]]
        rows.append(back)
        await edit(q, "⏳ <b>Pending approvals</b>" + ("" if len(rows) > 1 else "\n\nKoi nahi."), Markup(rows))
    elif act in ("ap", "rj"):
        b = await db.get_bot(arg)
        if not b:
            await edit(q, "Ye request ab maujood nahi.", Markup([back]))
            return
        if act == "ap":
            await db.update_bot(arg, approved=1)
            await _notify_user(context, b["user_id"], f"✅ Aapka bot <b>{esc(b['bot_name'])}</b> approve ho gaya! My Bots se Run karo.")
            await edit(q, f"✅ Bot #{arg} approve kar diya.", Markup([back]))
        else:
            await runner.delete_files("bot", arg)
            await db.delete_bot_db(arg)
            await _notify_user(context, b["user_id"], f"❌ Aapka bot <b>{esc(b['bot_name'])}</b> reject ho gaya.")
            await edit(q, f"❌ Bot #{arg} reject + delete kar diya.", Markup([back]))

    # ---- clones
    elif act == "clones":
        clones = list(await db.get_all_clones())
        chunk, page, pages = _page(clones, arg)
        rows = [[Btn(f"{'🟢' if runner.is_running('clone', c['clone_id']) else '🔴'} @{c['bot_username']}", callback_data=f"adm:cv:{c['clone_id']}")] for c in chunk]
        rows.append(_nav("adm:clones", page, pages))
        rows.append(back)
        await edit(q, f"🧬 <b>All Clones</b> ({len(clones)})", Markup(rows))
    elif act == "cv":
        await _clone_view(q, arg)
    elif act in ("cstart", "cstop"):
        c = await db.get_clone(arg)
        if not c:
            return
        if act == "cstop":
            await runner.stop("clone", arg)
        else:
            await edit(q, "⏳ Start ho raha hai...")
            ok, msg = await runner.start_clone_row(c)
            if not ok:
                await edit(q, f"❌ Start fail:\n{pre(msg, 3000)}", Markup([[rb("Back", f"adm:cv:{arg}", 6)]]))
                return
        await _clone_view(q, arg)
    elif act == "clog":
        await edit(q, f"📜 <b>Clone #{arg} logs</b>\n{pre(runner.get_logs('clone', arg, 45))}",
                   Markup([[rb("Refresh", f"adm:clog:{arg}", 3)], [rb("Back", f"adm:cv:{arg}", 6)]]))
    elif act == "cdel":
        await edit(q, f"🗑 Clone #{arg} delete karna hai?", Markup([[rb("Haan", f"adm:cdely:{arg}", 0), rb("Nahi", f"adm:cv:{arg}", 3)]]))
    elif act == "cdely":
        await runner.delete_files("clone", arg)
        await db.delete_clone_db(arg)
        await toast(q, "✅ Delete ho gaya.")
        await _list_clones(q)

    # ---- stats / settings / backup
    elif act == "stats":
        s = await asyncio.to_thread(runner.server_stats)
        await edit(q, (f"🖥 <b>Server Stats</b>\n\n🧠 CPU: {s['cpu']:.0f}%\n💾 RAM: {s['ram']:.0f}% "
                       f"({s['ram_used']:.0f}/{s['ram_total']:.0f} MB)\n💽 Disk: {s['disk']:.0f}% ({s['disk_free']:.1f} GB free)\n"
                       f"🤖 Running processes: {s['running']}\n📂 Data dir: <code>{esc(config.DATA_DIR)}</code>"),
                   Markup([[rb("Refresh", "adm:stats", 3)], back]))
    elif act == "set":
        await _settings(q)
    elif act in ("tapp", "tmaint"):
        key = "deployment_approval" if act == "tapp" else "maintenance"
        cur = await db.get_setting(key, "0")
        await db.update_setting(key, "0" if cur == "1" else "1")
        await _settings(q)
    elif act == "backup":
        await edit(q, "⏳ Backup ban raha hai...")
        await _backup(q)


def _zip_dir(d, out):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in d.rglob("*"):
            rel = p.relative_to(d)
            if p.is_file() and not set(rel.parts) & {".deps", "node_modules", "__pycache__"}:
                z.write(p, rel)


async def _show_user(q, uid):
    u = await db.get_user(uid)
    bots = await db.get_user_bots(uid)
    kb = [[rb("Unban" if u["is_banned"] else "Ban", f"adm:{'unban' if u['is_banned'] else 'ban'}:{uid}", 3 if u["is_banned"] else 0)],
          [rb("Set Limits", f"adm:lim:{uid}", 4)], [rb(f"Bots ({len(bots)})", f"adm:ub:{uid}", 1)],
          [rb("Back", "adm:users:0", 6)]]
    await edit(q, (f"👤 <b>{esc(u['first_name'])}</b> @{esc(u['username'] or '-')}\n🆔 <code>{uid}</code>\n"
                    f"Status: {'🚫 Banned' if u['is_banned'] else '✅ Active'}\nMax bots: {u['max_bots']}\n"
                    f"CPU: {esc(u['cpu_limit'])}  RAM: {esc(u['ram_limit'])}\n🤖 Bots: {len(bots)}"), Markup(kb))


async def _bot_view(q, bid):
    b = await db.get_bot(bid)
    if not b:
        await edit(q, "Bot nahi mila.", Markup([[rb("Panel", "adm:main", 6)]]))
        return
    u = await db.get_user(b["user_id"])
    run = runner.is_running("bot", bid)
    kb = [[rb("Start", f"adm:bstart:{bid}", 3), rb("Stop", f"adm:bstop:{bid}", 0)],
          [rb("Logs", f"adm:blog:{bid}", 4), rb("Download", f"adm:bdl:{bid}", 5), rb("Delete", f"adm:bdel:{bid}", 0)]]
    if not b["approved"]:
        kb.insert(0, [rb("Approve", f"adm:ap:{bid}", 3), rb("Reject", f"adm:rj:{bid}", 0)])
    kb.append([rb("Back", "adm:bots:0", 6)])
    await edit(q, (f"🤖 <b>#{bid} {esc(b['bot_name'])}</b>\nType: {esc(b['bot_type'])}\n"
                   f"Status: {'🟢 Running' if run else '🔴 Stopped'}{'' if b['approved'] else ' (⏳ approval pending)'}\n"
                   f"Owner: {esc(u['first_name'] if u else '?')} (<code>{b['user_id']}</code>)\n"
                   f"Deployed: {esc((b['deployed_date'] or '')[:10])}"), Markup(kb))


async def _clone_view(q, cid):
    c = await db.get_clone(cid)
    if not c:
        await edit(q, "Clone nahi mila.", Markup([[rb("Panel", "adm:main", 6)]]))
        return
    run = runner.is_running("clone", cid)
    await edit(q, (f"🧬 <b>#{cid} @{esc(c['bot_username'])}</b>\nStatus: {'🟢 Running' if run else '🔴 Stopped'}\n"
                   f"Creator: <code>{c['user_id']}</code>  Owner: <code>{esc(c['owner_id'])}</code>\nDev: {esc(c['dev_name'])}"),
               Markup([[rb("Start", f"adm:cstart:{cid}", 3), rb("Stop", f"adm:cstop:{cid}", 0)],
                       [rb("Logs", f"adm:clog:{cid}", 4), rb("Delete", f"adm:cdel:{cid}", 0)],
                       [rb("Back", "adm:clones:0", 6)]]))


async def _list_bots(q):
    bots = list(await db.get_all_bots())
    chunk, page, pages = _page(bots, 0)
    rows = [[Btn(f"#{b['bot_id']} {b['bot_name']}", callback_data=f"adm:bv:{b['bot_id']}")] for b in chunk]
    rows.append([rb("Panel", "adm:main", 6)])
    await edit(q, f"🤖 <b>All Bots</b> ({len(bots)})", Markup(rows))


async def _list_clones(q):
    clones = list(await db.get_all_clones())
    chunk, page, pages = _page(clones, 0)
    rows = [[Btn(f"#{c['clone_id']} @{c['bot_username']}", callback_data=f"adm:cv:{c['clone_id']}")] for c in chunk]
    rows.append([rb("Panel", "adm:main", 6)])
    await edit(q, f"🧬 <b>All Clones</b> ({len(clones)})", Markup(rows))


async def _settings(q):
    app = await db.get_setting("deployment_approval", "0") == "1"
    mt = await db.get_setting("maintenance", "0") == "1"
    await edit(q, ("⚙️ <b>Settings</b>\n\n"
                   f"• Deploy approval: <b>{'ON' if app else 'OFF'}</b> (ON = naye bots admin approve karega)\n"
                   f"• Maintenance: <b>{'ON' if mt else 'OFF'}</b> (ON = sirf admin use kar sakta hai)"),
               Markup([[rb(f"Approval: {'ON → OFF' if app else 'OFF → ON'}", "adm:tapp", 3)],
                       [rb(f"Maintenance: {'ON → OFF' if mt else 'OFF → ON'}", "adm:tmaint", 1)],
                       [rb("Panel", "adm:main", 6)]]))


def _backup_db(path):
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()


async def _backup(q):
    tmp = config.DATA_DIR / "tmp"
    tmp.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dbcopy = tmp / f"bot_{stamp}.db"
    out = tmp / f"backup_{stamp}.zip"
    await asyncio.to_thread(_backup_db, str(dbcopy))

    def build():
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(dbcopy, "bot.db")
            for p in config.USER_BOTS_DIR.rglob("*"):
                rel = p.relative_to(config.USER_BOTS_DIR)
                if p.is_file() and not set(rel.parts) & {".deps", "node_modules", "__pycache__"}:
                    z.write(p, f"user_bots/{rel}")
    try:
        await asyncio.to_thread(build)
        if out.stat().st_size < 49_000_000:
            with open(out, "rb") as f:
                await q.message.reply_document(f, filename=out.name, caption="💾 Full backup (DB + bot files). Tokens isme hain, safe rakho!")
        else:
            with open(dbcopy, "rb") as f:
                await q.message.reply_document(f, filename=dbcopy.name, caption="💾 Zip 50MB se bada tha, sirf database bheja.")
        await edit(q, "✅ Backup bhej diya.", Markup([[rb("Panel", "adm:main", 6)]]))
    finally:
        out.unlink(missing_ok=True)
        dbcopy.unlink(missing_ok=True)


# ----------------------------------------------------------------- broadcast
async def bc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Sirf admin.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    await edit(q, "📢 <b>Broadcast</b>\nJo message sab users ko bhejna hai wo bhejo (text, photo, video, file - sab chalega).",
               Markup([[rb("Cancel", "adm:main", 0)]]))
    return B_MSG


async def bc_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    users = [u["user_id"] for u in await db.get_all_users() if not u["is_banned"]]
    status = await msg.reply_text(f"📢 {len(users)} users ko bhej raha hoon...")
    ok = fail = 0
    for i, uid in enumerate(users, 1):
        try:
            await context.bot.copy_message(uid, msg.chat_id, msg.message_id)
            ok += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await context.bot.copy_message(uid, msg.chat_id, msg.message_id)
                ok += 1
            except TelegramError:
                fail += 1
        except TelegramError:
            fail += 1
        if i % 20 == 0:
            await asyncio.sleep(1)
        if i % 50 == 0:
            try:
                await status.edit_text(f"📢 {i}/{len(users)} ... ✅ {ok} ❌ {fail}")
            except TelegramError:
                pass
    await status.edit_text(f"✅ Broadcast complete\n📨 Delivered: {ok}\n❌ Failed: {fail}",
                           reply_markup=Markup([[rb("Panel", "adm:main", 6)]]))
    return ConversationHandler.END


# ----------------------------------------------------------------- limits
async def lim_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Sirf admin.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    uid = int(q.data.split(":")[2])
    context.user_data["lim_uid"] = uid
    await edit(q, "⚙️ Naye limits bhejo: <code>max_bots cpu ram</code>\nExample: <code>10 1.0 512m</code>",
               Markup([[rb("Cancel", f"adm:u:{uid}", 0)]]))
    return B_LIM


async def lim_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = (update.message.text or "").split()
    uid = context.user_data.get("lim_uid")
    try:
        assert len(parts) == 3 and uid
        max_bots, cpu, ram = int(parts[0]), str(float(parts[1])), parts[2].lower()
        assert 0 <= max_bots <= 100 and runner.parse_ram_mb(ram) >= 32
    except (AssertionError, ValueError):
        await update.message.reply_text("❌ Format: max_bots cpu ram — jaise 10 1.0 512m")
        return B_LIM
    await db.update_user_limits(uid, max_bots, cpu, ram)
    await update.message.reply_text("✅ Limits update ho gaye.", reply_markup=Markup([[rb("User", f"adm:u:{uid}", 3)]]))
    return ConversationHandler.END


async def adm_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("adm:u:"):
        await _show_user(q, int(q.data.split(":")[2]))
    else:
        txt, pending = await _panel_text()
        await edit(q, txt, panel_kb(pending))
    return ConversationHandler.END


async def adm_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancel.")
    return ConversationHandler.END


# ----------------------------------------------------------------- commands
async def _cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    ban = update.message.text.split()[0].lstrip("/").split("@")[0] == "ban"
    arg = update.message.text.partition(" ")[2].strip()
    if not arg.isdigit():
        await update.message.reply_text(f"Usage: /{'ban' if ban else 'unban'} USER_ID")
        return
    uid = int(arg)
    if ban and is_admin(uid):
        await update.message.reply_text("Admin ko ban nahi kar sakte.")
        return
    if not await db.get_user(uid):
        await update.message.reply_text("User database me nahi hai (usne bot start nahi kiya).")
        return
    await db.set_ban(uid, ban)
    if ban:
        for b in await db.get_user_bots(uid):
            await runner.stop("bot", b["bot_id"])
    await update.message.reply_text(f"✅ {uid} {'ban' if ban else 'unban'} ho gaya.")


async def cmd_setwelcomepic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    r = update.message.reply_to_message
    if r and r.photo:
        await db.update_setting("welcome_photo", r.photo[-1].file_id)
        await update.message.reply_text("✅ Welcome photo set. /start se dekho.")
    elif update.message.text.strip().endswith("reset"):
        await db.update_setting("welcome_photo", "")
        await update.message.reply_text("✅ Default photo wapas.")
    else:
        await update.message.reply_text("Kisi photo ko reply karke /setwelcomepic bhejo. (Default ke liye: /setwelcomepic reset)")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    s = await asyncio.to_thread(runner.server_stats)
    txt, _ = await _panel_text()
    await update.message.reply_text(f"{txt}\n\n🧠 CPU {s['cpu']:.0f}% | 💾 RAM {s['ram']:.0f}% | 💽 Disk {s['disk']:.0f}%",
                                    parse_mode=HTML)


def get_admin_handlers():
    bc = ConversationHandler(
        entry_points=[CallbackQueryHandler(bc_start, pattern=r"^adm:bc$"),
                      CallbackQueryHandler(lim_start, pattern=r"^adm:lim:\d+$")],
        states={B_MSG: [MessageHandler(~filters.COMMAND, bc_send)],
                B_LIM: [MessageHandler(filters.TEXT & ~filters.COMMAND, lim_receive)]},
        fallbacks=[CommandHandler("cancel", adm_cancel_cmd),
                   CallbackQueryHandler(adm_cancel_cb, pattern=r"^adm:(main|u:\d+)$")],
        allow_reentry=True,
    )
    return [
        CommandHandler("admin", cmd_admin),
        CommandHandler("ban", _cmd_ban),
        CommandHandler("unban", _cmd_ban),
        CommandHandler("setwelcomepic", cmd_setwelcomepic),
        CommandHandler("stats", cmd_stats),
        bc,
        CallbackQueryHandler(cb_admin, pattern=r"^adm:"),
    ]
