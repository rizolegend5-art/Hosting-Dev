"""Clone Bot wizard + management (host bot ke andar, real running clone processes)."""
import logging
import re
import shutil
import time

from telegram import Bot, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, Update
from telegram.ext import (CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler,
                          MessageHandler, filters)

import config
import database as db
import runner
from handlers.common import HTML, edit, esc, fmt_uptime, is_admin, pre, rb, send_welcome, show_menu, toast

log = logging.getLogger(__name__)
C_TOKEN, C_OWNER, C_DEV, C_PIC, C_WELCOME, C_FEATURES = range(6)
TOTAL = 6
DEFAULT_WELCOME = "Welcome {user}! 🎉\nMain ek smart bot hoon. Neeche ke buttons se shuru karo."


def progress(step):
    filled = int(step / TOTAL * 7)
    bar = "".join(config.RAINBOW_EMOJIS[i] if i < filled else "⚪" for i in range(7))
    return f"{bar} {step}/{TOTAL}"


def cancel_row():
    return [rb("Cancel", "cclose", 0)]


# ----------------------------------------------------------------- intro
async def cb_clone_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await edit(q, (
        "🧬 <b>Clone Bot System</b>\n\nApna khud ka branded bot banao, bas token do:\n\n"
        "✅ Welcome message + <b>photo</b>\n✅ Owner admin panel (broadcast, ban/unban, stats)\n"
        "✅ File share, auto-reply\n✅ 24/7 hosted, auto-restart\n\n"
        "Setup me 1-2 minute lagte hain."),
        Markup([[rb("Start Clone", "cgo", 0)], [rb("My Clones", "my_clones", 3)], [rb("Back", "menu", 6)]]))


# ----------------------------------------------------------------- wizard
async def clone_go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    n = len(await db.get_user_clones(uid))
    if n >= config.MAX_CLONE_BOTS_PER_USER and not is_admin(uid):
        await edit(q, f"❌ Aap max <b>{config.MAX_CLONE_BOTS_PER_USER}</b> clone bots bana sakte ho.",
                   Markup([[rb("My Clones", "my_clones", 3), rb("Back", "menu", 6)]]))
        return ConversationHandler.END
    context.user_data["clone"] = {"features": list(config.DEFAULT_CLONE_FEATURES)}
    await edit(q, f"{progress(1)}\n\n🔴 <b>Step 1:</b> Naye bot ka <b>token</b> bhejo (@BotFather se).\n"
                  "Naya bot banao ya aisa token do jo kahin aur use nahi ho raha.\nMessage verify ke baad delete ho jayega.",
               Markup([cancel_row()]))
    return C_TOKEN


async def c_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = (update.message.text or "").strip()
    chat = update.effective_chat
    try:
        await update.message.delete()
    except Exception:
        pass
    if not re.fullmatch(r"\d{6,}:[\w-]{30,}", token):
        await chat.send_message("❌ Token ka format galat hai. Poora token bhejo.")
        return C_TOKEN
    if token == config.BOT_TOKEN:
        await chat.send_message("❌ Ye is hosting bot ka apna token hai. Naya bot banao.")
        return C_TOKEN
    used = [r["bot_token"] for r in await db.get_all_bots()] + [r["bot_token"] for r in await db.get_all_clones()]
    if token in used:
        await chat.send_message("❌ Ye token pehle se host/clone ho chuka hai.")
        return C_TOKEN
    wait = await chat.send_message("⏳ Token verify ho raha hai...")
    try:
        async with Bot(token) as b:
            me = await b.get_me()
    except Exception:
        await wait.edit_text("❌ Token verify nahi hua. Sahi/active token bhejo.")
        return C_TOKEN
    c = context.user_data["clone"]
    c.update(token=token, username=me.username, name=me.first_name)
    await wait.edit_text(
        f"✅ Verified: <b>@{esc(me.username)}</b>\n\n{progress(2)}\n\n🟠 <b>Step 2:</b> Owner ka <b>numeric Telegram ID</b> bhejo "
        "(jo is bot ka admin hoga). Apni ID jaanne ke liye /myid.", parse_mode=HTML,
        reply_markup=Markup([[rb("Main hi owner hoon", "cown", 3)], cancel_row()]))
    return C_OWNER


async def _ask_dev(chat_send, uid, owner_id, context):
    context.user_data["clone"]["owner_id"] = owner_id
    await chat_send(f"{progress(3)}\n\n🟡 <b>Step 3:</b> <b>Developer name</b> bhejo (welcome/about me dikhega).",
                    parse_mode=HTML, reply_markup=Markup([cancel_row()]))


async def c_owner_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _ask_dev(lambda t, **k: edit(q, t, k.get("reply_markup")), q.from_user.id, q.from_user.id, context)
    return C_DEV


async def c_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = (update.message.text or "").strip()
    if not v.isdigit() or len(v) < 5:
        await update.message.reply_text("❌ Owner ID sirf numbers me honi chahiye (jaise 123456789).")
        return C_OWNER
    await _ask_dev(update.message.reply_text, update.effective_user.id, int(v), context)
    return C_DEV


async def c_dev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = (update.message.text or "").strip()
    if not v or len(v) > 50:
        await update.message.reply_text("❌ Naam 1-50 characters ka ho.")
        return C_DEV
    context.user_data["clone"]["dev"] = v
    await update.message.reply_text(
        f"{progress(4)}\n\n🟢 <b>Step 4:</b> <b>Welcome photo</b> bhejo (photo ki tarah). Ye /start par welcome ke saath aayegi.\n"
        "Skip karoge to default banner lagega.", parse_mode=HTML,
        reply_markup=Markup([[rb("Skip (default photo)", "cskip", 3)], cancel_row()]))
    return C_PIC


async def _ask_welcome(send):
    await send(f"{progress(5)}\n\n🔵 <b>Step 5:</b> <b>Welcome message</b> bhejo.\n"
               "<code>{user}</code> likhoge to user ka naam aa jayega.", parse_mode=HTML,
               reply_markup=Markup([[rb("Default use karo", "cdef", 3)], cancel_row()]))


async def c_pic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_obj = None
    if msg.photo:
        file_obj = await context.bot.get_file(msg.photo[-1].file_id)
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        file_obj = await context.bot.get_file(msg.document.file_id)
    if not file_obj:
        await msg.reply_text("❌ Photo bhejo, ya Skip dabao.")
        return C_PIC
    path = config.DATA_DIR / "tmp" / f"clone_pic_{update.effective_user.id}_{int(time.time())}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    await file_obj.download_to_drive(path)
    context.user_data["clone"]["pic"] = str(path)
    await _ask_welcome(msg.reply_text)
    return C_WELCOME


async def c_skip_pic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await _ask_welcome(lambda t, **k: edit(q, t, k.get("reply_markup")))
    return C_WELCOME


def _features_kb(c):
    rows = []
    for i, f in enumerate(config.DEFAULT_CLONE_FEATURES):
        on = f in c["features"]
        rows.append([rb(f"{'✅' if on else '❌'} {config.FEATURE_LABELS[f]}", f"cf:{f}", i)])
    rows.append([rb("Create Clone", "cmake", 3)])
    rows.append(cancel_row())
    return Markup(rows)


async def _show_features(q_or_msg, c, is_cb):
    text = f"{progress(6)}\n\n🟣 <b>Step 6:</b> Features chuno (click = on/off).\nTheek ho to <b>Create Clone</b> dabao."
    if is_cb:
        await edit(q_or_msg, text, _features_kb(c))
    else:
        await q_or_msg.reply_text(text, parse_mode=HTML, reply_markup=_features_kb(c))


async def c_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c = context.user_data["clone"]
    c["welcome"] = (update.message.text or "").strip()[:3000] or DEFAULT_WELCOME
    await _show_features(update.message, c, False)
    return C_FEATURES


async def c_default_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    c = context.user_data["clone"]
    c["welcome"] = DEFAULT_WELCOME
    await _show_features(q, c, True)
    return C_FEATURES


async def c_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    c = context.user_data.get("clone")
    if not c:
        await q.answer("Session expire.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    f = q.data.split(":")[1]
    if f in c["features"]:
        c["features"].remove(f)
    elif f in config.DEFAULT_CLONE_FEATURES:
        c["features"].append(f)
    await _show_features(q, c, True)
    return C_FEATURES


async def c_make(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    c = context.user_data.get("clone")
    if not c or "welcome" not in c:
        await q.answer("Session expire ho gaya, dobara shuru karo.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    uid = q.from_user.id
    await edit(q, "⏳ Clone ban raha hai, bot start ho raha hai...")
    feats = [f for f in config.DEFAULT_CLONE_FEATURES if f in c["features"]]
    cid = await db.add_clone(uid, c["token"], c["username"], c["name"], c["owner_id"], c["dev"], c["welcome"], feats)
    d = runner.dir_of("clone", cid)
    d.mkdir(parents=True, exist_ok=True)
    if c.get("pic"):
        shutil.move(c["pic"], d / "welcome.jpg")
    try:
        async with Bot(c["token"]) as b:
            await b.set_my_short_description(f"Made by {c['dev']}"[:120])
            await b.set_my_description(f"{c['name']} — developer: {c['dev']}. /start dabao!"[:500])
    except Exception:
        log.info("bot description set nahi hua", exc_info=True)
    ok, msg = await runner.start_clone_row(await db.get_clone(cid))
    context.user_data.pop("clone", None)
    if ok:
        await edit(q, (f"🎉 <b>Clone ready!</b>\n\n🤖 @{esc(c['username'])}\n👑 Owner ID: <code>{c['owner_id']}</code>\n"
                       f"👨‍💻 Developer: {esc(c['dev'])}\n⚡ Status: 🟢 Running\n\n"
                       f"Ab bot ko open karke /start dabao. Owner (<code>{c['owner_id']}</code>) ko bot me "
                       "<b>Owner Panel</b> milega."),
                   Markup([[Btn("🤖 Open Bot", url=f"https://t.me/{c['username']}")],
                           [rb("My Clones", "my_clones", 3), rb("Menu", "menu", 6)]]))
    else:
        await edit(q, f"⚠️ Clone save ho gaya par start nahi hua:\n{pre(msg, 2500)}",
                   Markup([[rb("Retry", f"c:start:{cid}", 3)], [rb("My Clones", "my_clones", 3)]]))
    return ConversationHandler.END


async def c_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _drop_pic(context)
    context.user_data.pop("clone", None)
    await show_menu(q)
    return ConversationHandler.END


async def c_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _drop_pic(context)
    context.user_data.pop("clone", None)
    await send_welcome(update.effective_chat, update.effective_user)
    return ConversationHandler.END


def _drop_pic(context):
    p = (context.user_data.get("clone") or {}).get("pic")
    if p:
        try:
            import os
            os.remove(p)
        except OSError:
            pass


# ----------------------------------------------------------------- manage
async def _render_clones(uid):
    clones = await db.get_user_clones(uid)
    if not clones:
        return "🧬 Aapke paas koi clone bot nahi hai.", Markup([[rb("Create Clone", "cgo", 0)], [rb("Back", "menu", 6)]])
    rows = []
    for i, c in enumerate(clones):
        icon = "🟢" if runner.is_running("clone", c["clone_id"]) else "🔴"
        rows.append([rb(f"{icon} @{c['bot_username']}", f"c:view:{c['clone_id']}", i)])
    rows.append([rb("New Clone", "cgo", 0)])
    rows.append([rb("Back", "menu", 6)])
    return f"🧬 <b>Aapke Clone Bots</b> ({len(clones)})", Markup(rows)


async def cb_my_clones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    text, kb = await _render_clones(q.from_user.id)
    await edit(q, text, kb)


async def _owned(q, cid):
    row = await db.get_clone(cid)
    if not row or (row["user_id"] != q.from_user.id and not is_admin(q.from_user.id)):
        await toast(q, "❌ Clone nahi mila.", True)
        return None
    return row


async def _view(q, c):
    cid = c["clone_id"]
    run = runner.is_running("clone", cid)
    feats = ", ".join(config.FEATURE_LABELS.get(f, f) for f in (c["enabled_features"] or "").split(",") if f)
    text = (f"🧬 <b>@{esc(c['bot_username'])}</b>\n\n⚡ Status: {'🟢 Running' if run else '🔴 Stopped'}\n"
            f"👨‍💻 Developer: {esc(c['dev_name'])}\n👑 Owner ID: <code>{esc(c['owner_id'])}</code>\n"
            f"🔧 Features: {esc(feats)}\n📅 Created: {esc((c['created_date'] or '')[:10])}")
    await edit(q, text, Markup([
        [rb("Start", f"c:start:{cid}", 3), rb("Stop", f"c:stop:{cid}", 0), rb("Restart", f"c:restart:{cid}", 1)],
        [rb("Logs", f"c:logs:{cid}", 4), rb("Stats", f"c:stats:{cid}", 5)],
        [Btn("🤖 Open Bot", url=f"https://t.me/{c['bot_username']}")],
        [rb("Delete", f"c:del:{cid}", 0), rb("Back", "my_clones", 6)],
    ]))


async def cb_clone_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, action, sid = q.data.split(":")
    cid = int(sid)
    c = await _owned(q, cid)
    if not c:
        return
    await q.answer()
    if action == "view":
        await _view(q, c)
    elif action in ("start", "restart"):
        if action == "start" and runner.is_running("clone", cid):
            await toast(q, "Pehle se running hai!", True)
            return
        await edit(q, f"⏳ @{esc(c['bot_username'])} start ho raha hai...")
        if action == "restart":
            await runner.stop("clone", cid)
        ok, msg = await runner.start_clone_row(await db.get_clone(cid))
        if ok:
            await _view(q, await db.get_clone(cid))
        else:
            await edit(q, f"❌ Start nahi hua:\n{pre(msg, 3000)}",
                       Markup([[rb("Retry", f"c:start:{cid}", 3), rb("Logs", f"c:logs:{cid}", 4)],
                               [rb("Back", f"c:view:{cid}", 6)]]))
    elif action == "stop":
        await runner.stop("clone", cid)
        await toast(q, "✅ Stop ho gaya.")
        await _view(q, await db.get_clone(cid))
    elif action == "logs":
        await edit(q, f"📜 <b>Logs — @{esc(c['bot_username'])}</b>\n{pre(runner.get_logs('clone', cid, 40))}",
                   Markup([[rb("Refresh", f"c:logs:{cid}", 3)], [rb("Back", f"c:view:{cid}", 6)]]))
    elif action == "stats":
        s = await runner.stats_async("clone", cid)
        if not s:
            await toast(q, "Clone running nahi hai.", True)
            return
        await edit(q, (f"📊 <b>Stats — @{esc(c['bot_username'])}</b>\n\n⏱ Uptime: {fmt_uptime(s['uptime'])}\n"
                       f"🧠 CPU: {s['cpu']:.1f}%\n💾 RAM: {s['ram_mb']:.1f} MB / {s['limit_mb']} MB\n"
                       f"🔁 Auto-restarts: {s['restarts']}"),
                   Markup([[rb("Refresh", f"c:stats:{cid}", 3)], [rb("Back", f"c:view:{cid}", 6)]]))
    elif action == "del":
        await edit(q, f"🗑 @{esc(c['bot_username'])} permanently delete karna hai? Uska saara data (users, files) ud jayega.",
                   Markup([[rb("Haan, Delete", f"c:delyes:{cid}", 0)], [rb("Nahi", f"c:view:{cid}", 3)]]))
    elif action == "delyes":
        await runner.delete_files("clone", cid)
        await db.delete_clone_db(cid)
        await toast(q, "✅ Delete ho gaya.")
        text, kb = await _render_clones(q.from_user.id)
        await edit(q, text, kb)


def get_clone_handlers():
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(clone_go, pattern=r"^cgo$")],
        states={
            C_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, c_token)],
            C_OWNER: [CallbackQueryHandler(c_owner_btn, pattern=r"^cown$"),
                      MessageHandler(filters.TEXT & ~filters.COMMAND, c_owner)],
            C_DEV: [MessageHandler(filters.TEXT & ~filters.COMMAND, c_dev)],
            C_PIC: [CallbackQueryHandler(c_skip_pic, pattern=r"^cskip$"),
                    MessageHandler(filters.PHOTO | filters.Document.IMAGE, c_pic)],
            C_WELCOME: [CallbackQueryHandler(c_default_welcome, pattern=r"^cdef$"),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, c_welcome)],
            C_FEATURES: [CallbackQueryHandler(c_toggle, pattern=r"^cf:\w+$"),
                         CallbackQueryHandler(c_make, pattern=r"^cmake$")],
        },
        fallbacks=[CommandHandler("cancel", c_cancel_cmd), CommandHandler("start", c_cancel_cmd),
                   CallbackQueryHandler(c_cancel_cb)],
        allow_reentry=True,
    )
    return [
        conv,
        CallbackQueryHandler(cb_clone_menu, pattern=r"^clone_menu$"),
        CallbackQueryHandler(cb_my_clones, pattern=r"^my_clones$"),
        CallbackQueryHandler(cb_clone_router, pattern=r"^c:\w+:\d+$"),
        CallbackQueryHandler(c_cancel_cb, pattern=r"^cclose$"),
    ]
