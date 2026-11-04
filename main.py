import asyncio
import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes

from config import BOT_TOKEN
from database import init_db
from handlers.user_handlers import get_user_handlers
from handlers.admin_handlers import get_admin_handlers
from handlers.clone_handlers import get_clone_handlers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Telegram update handler failed", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ Koi error aa gaya. Please dobara try karo."
            )
        except Exception:
            logger.exception("Could not send error reply")


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN missing hai. Railway Variables mein BOT_TOKEN set karo."
        )

    # Initialize SQLite before python-telegram-bot starts its own event loop.
    asyncio.run(init_db())
    logger.info("Database initialized")

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    for handler in get_user_handlers():
        application.add_handler(handler)
    for handler in get_admin_handlers():
        application.add_handler(handler)
    for handler in get_clone_handlers():
        application.add_handler(handler)

    application.add_error_handler(error_handler)
    logger.info("Bot is starting")
    # run_polling() manages the event loop itself; do not await it.
    application.run_polling( drop_pending_updates=True )


if __name__ == "__main__":
    main()
