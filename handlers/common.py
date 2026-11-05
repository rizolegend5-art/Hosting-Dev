"""Shared helpers: HTML escape, safe edit, welcome photo, main menu, ban/maintenance gate."""
import html
import logging

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ApplicationHandlerStop, ContextTypes

import config
import database as db

log = logging.getLogger(__name__)
HTML = ParseMode.HTML


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def is_admin(uid) -> bool:
    return uid in config.ADMIN_IDS


def rb(text, data, i=0):
    return Btn(f"{config.RAINBOW_EMOJIS[i % 7]} {text}", callback_data=data)


def pre(text, limit=3300) -> str:
    text = (text or "")[-limit:]
    return f"<pre>{esc(text)}</pre>"


def fmt_uptime(sec) -> str:
    d, r = divmod(int(sec), 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return (f"{d}d " if d else "") + (f"{h}h " if h else "") + (f"{m}m " if m else "") + f"{s}s"


async def edit(q, text, kb=None):
    """Callback ka message edit karo. Photo wale (welcome) message par edit nahi hota, tab naya bhejo."""
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode=HTML, disable_web_page_preview=True)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.chat.send_message(text, reply_markup=kb, parse_mode=HTML,
                                          disable_web_page_preview=True)


async def toast(q, text, alert=False):
    try:
        await q.answer(text[:190], show_alert=alert)
    except Exception:
        pass


def main_menu_kb(uid):
    rows = [
        [rb("Deploy New Bot", "deploy", 0), rb("My Bots", "bots", 1)],
        [rb("Clone Bot", "clone_menu", 2), rb("My Clones", "my_clones", 3)],
        [rb("My Stats", "mystats", 4), rb("Help", "help", 5)],
    ]
    links = []
    if config.SUPPORT_USERNAME:
        links.append(Btn("💬 Support", url=f"https://t.me/{config.SUPPORT_USERNAME}"))
    if config.UPDATE_CHANNEL:
        ch = config.UPDATE_CHANNEL.lstrip("@")
        if not ch.startswith("http"):
            ch = f"https://t.me/{ch}"
        links.append(Btn("📢 Updates", url=ch))
    if links:
        rows.append(links)
    if is_admin(uid):
        rows.append([rb("Admin Panel", "adm:main", 6)])
    return Markup(rows)


def welcome_text(user) -> str:
    return (
        f"👋 <b>Welcome, {esc(user.first_name)}!</b>\n\n"
        "🚀 Yahan aap <b>Python</b> aur <b>Node.js</b> bots 24/7 host kar sakte ho.\n\n"
        "✅ Zip upload → dependencies auto install → bot live\n"
        "✅ Logs, stats, file manager, ENV variables, auto-restart\n"
        "✅ Clone Bot: apna branded bot ek minute me\n\n"
        "Neeche se option chuno 👇"
    )


async def send_welcome(chat, user):
    """Welcome message PICTURE ke saath. Admin /setwelcomepic se photo badal sakta hai."""
    caption = welcome_text(user)
    kb = main_menu_kb(user.id)
    file_id = await db.get_setting("welcome_photo")
    try:
        if file_id:
            await chat.send_photo(file_id, caption=caption, parse_mode=HTML, reply_markup=kb)
            return
        if config.WELCOME_IMAGE.is_file():
            with open(config.WELCOME_IMAGE, "rb") as f:
                msg = await chat.send_photo(f, caption=caption, parse_mode=HTML, reply_markup=kb)
            await db.update_setting("welcome_photo", msg.photo[-1].file_id)
            return
    except Exception:
        log.warning("welcome photo bhejna fail hua, text bhej raha hoon", exc_info=True)
        await db.update_setting("welcome_photo", "")
    await chat.send_message(caption, parse_mode=HTML, reply_markup=kb)


async def show_menu(q):
    """Callback se main menu dikhao (photo ke saath)."""
    try:
        await q.message.delete()
    except Exception:
        pass
    await send_welcome(q.message.chat, q.from_user)


async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Har update se pehle: user register, ban check, maintenance check."""
    u = update.effective_user
    if not u or u.is_bot:
        return
    seen = context.bot_data.setdefault("seen", {})
    sig = (u.username, u.first_name)
    if seen.get(u.id) != sig:
        await db.add_user(u.id, u.username, u.first_name)
        seen[u.id] = sig
    if is_admin(u.id):
        return
    row = await db.get_user(u.id)
    msg = None
    if row and row["is_banned"]:
        msg = "🚫 Aap is bot se banned ho."
    elif await db.get_setting("maintenance", "0") == "1":
        msg = "🛠 Bot maintenance me hai, thodi der baad try karo."
    if msg:
        if update.callback_query:
            await toast(update.callback_query, msg, True)
        elif update.effective_message:
            await update.effective_message.reply_text(msg)
        raise ApplicationHandlerStop
