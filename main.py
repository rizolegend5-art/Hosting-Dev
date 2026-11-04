import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes
from config import BOT_TOKEN
from database import init_db
from handlers.user_handlers import get_user_handlers
from handlers.admin_handlers import get_admin_handlers
from handlers.clone_handlers import get_clone_handlers

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    try:
        await update.effective_message.reply_text("❌ Koi error aa gaya. Please try again.")
    except:
        pass

async def main():
    await init_db()
    print("✅ Database initialized")
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    for handler in get_user_handlers():
        application.add_handler(handler)
    
    for handler in get_admin_handlers():
        application.add_handler(handler)
    
    for handler in get_clone_handlers():
        application.add_handler(handler)
    
    application.add_error_handler(error_handler)
    
    print("✅ Bot started successfully")
    print(f"Bot link: https://t.me/{(await application.bot.get_me()).username}")
    
    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())