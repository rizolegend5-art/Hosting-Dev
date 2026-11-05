import asyncio
import logging

from telegram import BotCommand, Update
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationBuilder, ContextTypes, TypeHandler

try:  # local run ke liye .env, Railway par zaroorat nahi
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import config  # noqa: E402  (dotenv ke baad import hona chahiye)
import database as db  # noqa: E402
import runner  # noqa: E402
from handlers.admin_handlers import get_admin_handlers  # noqa: E402
from handlers.clone_handlers import get_clone_handlers  # noqa: E402
from handlers.common import gate  # noqa: E402
from handlers.user_handlers import get_user_handlers  # noqa: E402

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("main")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Update handler failed", exc_info=context.error)
    if isinstance(update, Update):
        try:
            if update.callback_query:
                await update.callback_query.answer("❌ Kuch gadbad hui, dobara try karo.", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text("❌ Kuch gadbad hui. Dobara try karo ya /start dabao.")
        except TelegramError:
            pass


async def _background_start(app: Application):
    await runner.restore_all()
    running = len(runner.RUN)
    log.info("Hosting bot ready. %d hosted bot(s) running.", running)
    for aid in config.ADMIN_IDS:
        try:
            await app.bot.send_message(aid, f"🟢 Hosting bot online.\n🤖 Running bots/clones: {running}\n"
                                            f"💾 Data dir: {config.DATA_DIR}")
        except TelegramError:
            log.info("Admin %s ko startup message nahi gaya (unhone bot /start nahi kiya?)", aid)


async def post_init(app: Application) -> None:
    await db.init_db()

    async def notify(user_id, text):
        await app.bot.send_message(user_id, text)

    runner.NOTIFY = notify
    me = await app.bot.get_me()
    log.info("Logged in as @%s | admins: %s | data: %s", me.username, config.ADMIN_IDS or "NONE", config.DATA_DIR)
    if not config.ADMIN_IDS:
        log.warning("Koi ADMIN ID set nahi! Railway Variables me ADMIN_IDS (ya OWNER_ID) daalo.")
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "Menu kholo"), BotCommand("bots", "Mere bots"),
            BotCommand("help", "Help"), BotCommand("myid", "Meri Telegram ID"),
            BotCommand("ping", "Bot alive check"), BotCommand("cancel", "Step cancel"),
        ])
    except TelegramError:
        log.warning("set_my_commands fail", exc_info=True)
    app.bot_data["bg"] = asyncio.create_task(_background_start(app))


async def post_shutdown(app: Application) -> None:
    await runner.shutdown_all()


def main() -> None:
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing hai. Railway Variables me BOT_TOKEN set karo.")

    app = (ApplicationBuilder().token(config.BOT_TOKEN)
           .concurrent_updates(True)      # lamba install/start ek user ka, baaqi sab ko block na kare
           .post_init(post_init).post_shutdown(post_shutdown).build())

    app.add_handler(TypeHandler(Update, gate), group=-1)
    for h in get_admin_handlers() + get_user_handlers() + get_clone_handlers():
        app.add_handler(h)
    app.add_error_handler(error_handler)

    log.info("Bot is starting")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
