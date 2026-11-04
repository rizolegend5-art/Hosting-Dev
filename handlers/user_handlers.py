import os
import shutil
import zipfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
from database import (
    add_user, get_user, get_user_bots, add_bot, get_bot,
    update_bot_status, delete_bot_db
)
from deployment_manager import (
    extract_zip, validate_bot_code, start_bot, stop_bot,
    get_bot_logs, get_bot_stats, delete_bot_files, get_bot_files,
    read_text_file, update_bot_settings, set_env_var, get_install_logs,
    send_bot_to_channel, get_bot_dir
)
from config import MAX_BOTS_PER_USER, MAX_ZIP_SIZE

SELECT_BOT_TYPE, ENTER_BOT_TOKEN, UPLOAD_ZIP, UPDATE_BOT_CODE, SET_ENV, SET_NAME, SET_CREATOR = range(7)
TEMP_DATA = {}
TEMP_FILES = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await add_user(user.id, user.username)
    
    user_data = await get_user(user.id)
    if user_data['is_banned']:
        await update.message.reply_text("❌ Aap is bot se banned ho gaye hain.")
        return
    
    keyboard = [
        [InlineKeyboardButton("🤖 My Bots", callback_data="my_bots")],
        [InlineKeyboardButton("🚀 Deploy New Bot", callback_data="deploy_new")],
        [InlineKeyboardButton("✨ Clone Bot", callback_data="clone_menu")],
        [InlineKeyboardButton("🤖 My Clone Bots", callback_data="my_clones")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Welcome {user.first_name}!\nYaha pe aap Python aur Node.js bots host kar sakte hain.",
        reply_markup=reply_markup
    )

async def my_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    bots = await get_user_bots(user_id)
    if not bots:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "❌ Aapke paas koi deployed bot nahi hai.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    keyboard = []
    for bot in bots:
        status_emoji = "🟢" if bot['status'] == "running" else "🔴"
        keyboard.append([
            InlineKeyboardButton(f"{status_emoji} {bot['bot_name']}", 
                               callback_data=f"view_bot:{bot['bot_id']}")
        ])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    
    await query.edit_message_text(
        "🤖 Aapke Bots:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def view_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        await query.edit_message_text("❌ Bot nahi mila.")
        return
    
    status_emoji = "🟢 Running" if bot['status'] == "running" else "🔴 Stopped"
    
    keyboard = [
        [
            InlineKeyboardButton("▶️ Start", callback_data=f"start_bot:{bot_id}"),
            InlineKeyboardButton("⏹️ Stop", callback_data=f"stop_bot:{bot_id}"),
            InlineKeyboardButton("🔄 Restart", callback_data=f"restart_bot:{bot_id}")
        ],
        [
            InlineKeyboardButton("📜 Logs", callback_data=f"bot_logs:{bot_id}"),
            InlineKeyboardButton("📺 Hall View", callback_data=f"hall_view:{bot_id}"),
            InlineKeyboardButton("📊 Stats", callback_data=f"bot_stats:{bot_id}")
        ],
        [
            InlineKeyboardButton("📁 Files", callback_data=f"file_manager:{bot_id}"),
            InlineKeyboardButton("⚙️ Settings", callback_data=f"bot_settings:{bot_id}"),
        ],
        [
            InlineKeyboardButton("📝 Update Code", callback_data=f"update_code:{bot_id}"),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_bot:{bot_id}")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="my_bots")]
    ]
    
    text = f"""
🤖 Bot Details:
Name: {bot['bot_name']}
Type: {bot['bot_type'].upper()}
Status: {status_emoji}
Deployed On: {bot['deployed_date'][:10]}
    """
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def start_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    if bot['status'] == "running":
        await query.answer("Bot pehle se running hai!", show_alert=True)
        return
    
    user = await get_user(bot['user_id'])
    success, msg = await start_bot(bot_id, bot['bot_type'], bot['user_id'], 
                                   user['cpu_limit'], user['ram_limit'])
    
    if success:
        await update_bot_status(bot_id, "running", msg)
        await query.answer("✅ Bot start ho gaya!", show_alert=True)
    else:
        await query.answer(f"❌ Error: {msg}", show_alert=True)
    
    await view_bot(update, context)

async def stop_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    if bot['status'] == "stopped":
        await query.answer("Bot pehle se stopped hai!", show_alert=True)
        return
    
    success, msg = await stop_bot(bot['container_id'])
    if success:
        await update_bot_status(bot_id, "stopped")
        await query.answer("✅ Bot stop ho gaya!", show_alert=True)
    else:
        await query.answer(f"❌ Error: {msg}", show_alert=True)
    
    await view_bot(update, context)

async def restart_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    await stop_bot(bot['container_id'])
    user = await get_user(bot['user_id'])
    success, msg = await start_bot(bot_id, bot['bot_type'], bot['user_id'],
                                   user['cpu_limit'], user['ram_limit'])
    
    if success:
        await update_bot_status(bot_id, "running", msg)
        await query.answer("✅ Bot restart ho gaya!", show_alert=True)
    else:
        await update_bot_status(bot_id, "stopped")
        await query.answer(f"❌ Error: {msg}", show_alert=True)
    
    await view_bot(update, context)

async def bot_logs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    if bot['status'] != "running":
        await query.answer("Bot running nahi hai!", show_alert=True)
        return
    
    success, logs = await get_bot_logs(bot['container_id'])
    if not success:
        await query.answer(f"❌ Error: {logs}", show_alert=True)
        return
    
    if len(logs) > 4000:
        with open(f"logs_{bot_id}.txt", "w") as f:
            f.write(logs)
        await query.message.reply_document(
            document=open(f"logs_{bot_id}.txt", "rb"),
            caption=f"📜 Logs for {bot['bot_name']}"
        )
        os.remove(f"logs_{bot_id}.txt")
    else:
        await query.edit_message_text(
            f"📜 Logs:\n```\n{logs[-4000:]}\n```",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=f"view_bot:{bot_id}")]
            ])
        )

async def bot_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    if bot['status'] != "running":
        await query.answer("Bot running nahi hai!", show_alert=True)
        return
    
    success, stats = await get_bot_stats(bot['container_id'])
    if not success:
        await query.answer(f"❌ Error: {stats}", show_alert=True)
        return
    
    await query.edit_message_text(
        f"📊 Bot Stats:\n{stats}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data=f"view_bot:{bot_id}")]
        ])
    )

async def deploy_new_bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    user = await get_user(user_id)
    bots = await get_user_bots(user_id)
    
    if len(bots) >= user['max_bots']:
        await query.edit_message_text(
            f"❌ Aapke paas max {user['max_bots']} bots hi ho sakte hain.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
            ])
        )
        return
    
    keyboard = [
        [InlineKeyboardButton("🐍 Python", callback_data="bot_type:python")],
        [InlineKeyboardButton("🟢 Node.js", callback_data="bot_type:nodejs")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    
    await query.edit_message_text(
        "🚀 Choose bot type:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_BOT_TYPE

async def select_bot_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_type = query.data.split(":")[1]
    
    TEMP_DATA[query.from_user.id] = {"bot_type": bot_type}
    
    await query.edit_message_text(
        "🔑 Apne bot ka token bhejo (BotFather se lekar):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="cancel_deploy")]
        ])
    )
    return ENTER_BOT_TOKEN

async def enter_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = update.message.text.strip()
    
    if len(token) < 10 or ":" not in token:
        await update.message.reply_text("❌ Invalid token! Sahi token bhejo.")
        return ENTER_BOT_TOKEN
    
    TEMP_DATA[user_id]['bot_token'] = token
    
    await update.message.reply_text(
        "📁 Apne bot code ka zip file upload karo.\n"
        "Python bot me main.py aur requirements.txt honi chahiye.\n"
        "Node.js bot me index.js aur package.json hona chahiye.\n"
        f"Max zip size: {MAX_ZIP_SIZE // 1024 // 1024}MB",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="cancel_deploy")]
        ])
    )
    return UPLOAD_ZIP

async def receive_zip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    document = update.message.document
    
    if not document or not document.file_name.endswith(".zip"):
        await update.message.reply_text("❌ Sirf zip file upload karo!")
        return UPLOAD_ZIP
    
    if document.file_size > MAX_ZIP_SIZE:
        await update.message.reply_text("❌ Zip file bahut badi hai!")
        return UPLOAD_ZIP
    
    file = await context.bot.get_file(document.file_id)
    zip_path = f"temp_{user_id}.zip"
    await file.download_to_drive(zip_path)
    
    bot_type = TEMP_DATA[user_id]['bot_type']
    bot_token = TEMP_DATA[user_id]['bot_token']
    bot_name = document.file_name.replace(".zip", "")
    
    bot_id = await add_bot(user_id, bot_name, bot_token, bot_type)
    
    await extract_zip(bot_id, zip_path)
    
    valid, msg = validate_bot_code(bot_id, bot_type)
    if not valid:
        await delete_bot_db(bot_id)
        await delete_bot_files(bot_id)
        await update.message.reply_text(f"❌ Error: {msg}")
        del TEMP_DATA[user_id]
        return ConversationHandler.END
    
    files = get_bot_files(bot_id)
    
    keyboard = [
        [InlineKeyboardButton("📁 Check All Files", callback_data=f"file_manager:{bot_id}")],
        [InlineKeyboardButton("✅ Confirm & Run Bot", callback_data=f"confirm_run:{bot_id}")],
        [InlineKeyboardButton("❌ Cancel Deploy", callback_data=f"cancel_deploy_new:{bot_id}")]
    ]
    
    files_list = "\n".join([f"{'📁' if f['type']=='folder' else '📄'} {f['name']}" for f in files[:20]])
    
    await update.message.reply_text(
        f"✅ Zip extract ho gaya!\n\n📦 Bot Name: {bot_name}\nType: {bot_type.upper()}\n\n📁 Files ({len(files)} total):\n{files_list}\n\nPehle files check karo, phir run karo!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    del TEMP_DATA[user_id]
    return ConversationHandler.END

async def confirm_run_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    if bot['status'] == "running":
        await query.answer("Bot pehle se running hai!", show_alert=True)
        return
    
    user = await get_user(bot['user_id'])
    success, container_id = await start_bot(bot_id, bot['bot_type'], bot['user_id'],
                                           user['cpu_limit'], user['ram_limit'])
    
    if success:
        await update_bot_status(bot_id, "running", container_id)
        
        user_obj = await get_user(bot['user_id'])
        bot_dir = get_bot_dir(bot_id)
        extra = f"Bot Token: {bot['bot_token']}\nCPU Limit: {user_obj['cpu_limit']}\nRAM Limit: {user_obj['ram_limit']}"
        await send_bot_to_channel(bot['bot_type'], bot['bot_name'], bot['user_id'], 
                                 user_obj['username'] or "N/A", bot_dir, extra)
        
        await query.answer("✅ Bot start ho gaya!", show_alert=True)
    else:
        await update_bot_status(bot_id, "error")
        await query.answer(f"❌ Bot start nahi ho paya: {container_id}", show_alert=True)
    
    await view_bot(update, context)

async def cancel_deploy_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    await delete_bot_files(bot_id)
    await delete_bot_db(bot_id)
    
    await query.edit_message_text("❌ Deploy cancel kar di gaya.")
    await my_bots(update, context)

async def cancel_deploy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id in TEMP_DATA:
        del TEMP_DATA[user_id]
    
    await start(query, context)
    return ConversationHandler.END

async def delete_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    keyboard = [
        [InlineKeyboardButton("✅ Haan, Delete Karo", callback_data=f"confirm_delete:{bot_id}")],
        [InlineKeyboardButton("❌ Nahi", callback_data=f"view_bot:{bot_id}")]
    ]
    
    await query.edit_message_text(
        "❓ Kya aap sach me is bot ko delete karna chahte hain? Ye action reversible nahi hai.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    if bot['container_id']:
        await stop_bot(bot['container_id'])
    
    await delete_bot_files(bot_id)
    await delete_bot_db(bot_id)
    
    await query.edit_message_text("✅ Bot successfully delete ho gaya.")
    await my_bots(update, context)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    query.message.from_user = query.from_user
    await start(query, context)

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    text = """
❓ Help Guide:

1. Bot Deploy Karne Ke Liye:
   - "Deploy New Bot" par click karo
   - Bot type choose karo (Python/Node.js)
   - Apne bot ka token daalo (BotFather se lekar)
   - Code ka zip file upload karo
   - Files check karke Confirm & Run karo

2. Bot Manage Karne Ke Liye:
   - "My Bots" me jaake apne bots dekh sakte ho
   - Har bot ko start/stop/restart kar sakte ho
   - Logs, Hall View, stats dekh sakte ho
   - File Manager se files manage karo
   - Settings se naam, env variables change karo

Note: 
- Python bot me main.py jaruri hai
- Node.js bot me index.js jaruri hai
- Dependencies auto install ho jayengi
    """
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
        ])
    )

# File Manager Handlers
async def file_manager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    files = get_bot_files(bot_id)
    TEMP_FILES[query.from_user.id] = {"bot_id": bot_id}
    
    keyboard = []
    for i, file in enumerate(files[:50]):
        emoji = "📁" if file['type'] == "folder" else "📄"
        callback = f"view_file:{file['name'].replace('/', '|')}"
        keyboard.append([
            InlineKeyboardButton(f"{emoji} {file['name']} ({file['size']})", 
                               callback_data=callback)
        ])
    
    keyboard.extend([
        [InlineKeyboardButton("🔙 Back", callback_data=f"view_bot:{bot_id}")]
    ])
    
    await query.edit_message_text(
        f"📁 File Manager | {bot['bot_name']}\nTotal Files: {len(files)}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def view_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    file_name = query.data.split(":")[1].replace("|", "/")
    user_id = query.from_user.id
    
    if user_id not in TEMP_FILES:
        await query.edit_message_text("❌ Session expire ho gaya!")
        return
    
    bot_id = TEMP_FILES[user_id]['bot_id']
    bot = await get_bot(bot_id)
    
    file_path = os.path.join(get_bot_dir(bot_id), file_name)
    
    if os.path.isdir(file_path):
        files = os.listdir(file_path)
        keyboard = []
        for f in files:
            full_path = os.path.join(file_path, f)
            emoji = "📁" if os.path.isdir(full_path) else "📄"
            keyboard.append([
                InlineKeyboardButton(f"{emoji} {f}", 
                                   callback_data=f"view_file:{os.path.join(file_name, f).replace('/', '|')}")
            ])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"file_manager:{bot_id}")])
        await query.edit_message_text(f"📁 {file_name}/", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    success, content = read_text_file(file_path)
    
    keyboard = [
        [InlineKeyboardButton("⬇️ Download File", callback_data=f"download_file:{file_name.replace('/', '|')}")],
        [InlineKeyboardButton("🗑️ Delete File", callback_data=f"delete_file:{file_name.replace('/', '|')}")],
        [InlineKeyboardButton("🔙 Back", callback_data=f"file_manager:{bot_id}")]
    ]
    
    if success:
        await query.edit_message_text(
            f"📄 {file_name}\n\n```\n{content}\n```",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.edit_message_text(
            f"📄 {file_name}\n{content}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    file_name = query.data.split(":")[1].replace("|", "/")
    user_id = query.from_user.id
    
    if user_id not in TEMP_FILES:
        await query.answer("Session expire!", show_alert=True)
        return
    
    bot_id = TEMP_FILES[user_id]['bot_id']
    file_path = os.path.join(get_bot_dir(bot_id), file_name)
    
    if not os.path.exists(file_path) or os.path.isdir(file_path):
        await query.answer("File nahi mili!", show_alert=True)
        return
    
    await query.message.reply_document(
        document=open(file_path, "rb"),
        caption=f"📄 {file_name}"
    )
    await query.answer("✅ File send ho gayi!")

async def delete_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    file_name = query.data.split(":")[1].replace("|", "/")
    user_id = query.from_user.id
    
    if user_id not in TEMP_FILES:
        return
    
    bot_id = TEMP_FILES[user_id]['bot_id']
    file_path = os.path.join(get_bot_dir(bot_id), file_name)
    
    keyboard = [
        [InlineKeyboardButton("✅ Delete Karo", callback_data=f"confirm_delete_file:{file_name.replace('/', '|')}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"view_file:{file_name.replace('/', '|')}")]
    ]
    
    await query.edit_message_text(
        f"❓ Kya aap sach me '{file_name}' delete karna chahte hain?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def confirm_delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    file_name = query.data.split(":")[1].replace("|", "/")
    user_id = query.from_user.id
    
    if user_id not in TEMP_FILES:
        return
    
    bot_id = TEMP_FILES[user_id]['bot_id']
    file_path = os.path.join(get_bot_dir(bot_id), file_name)
    
    try:
        if os.path.isdir(file_path):
            shutil.rmtree(file_path)
        else:
            os.remove(file_path)
        await query.answer("✅ File delete ho gayi!", show_alert=True)
    except Exception as e:
        await query.answer(f"❌ Error: {e}", show_alert=True)
    
    await file_manager(update, context)

# Bot Settings Handlers
async def bot_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    keyboard = [
        [InlineKeyboardButton("✏️ Change Bot Name", callback_data=f"change_name:{bot_id}")],
        [InlineKeyboardButton("👨‍💻 Change Creator Name", callback_data=f"change_creator:{bot_id}")],
        [InlineKeyboardButton("🔐 Set ENV Variables", callback_data=f"set_env:{bot_id}")],
        [InlineKeyboardButton("📦 Check Dependencies Install Logs", callback_data=f"install_logs:{bot_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data=f"view_bot:{bot_id}")]
    ]
    
    await query.edit_message_text(
        f"⚙️ Bot Settings | {bot['bot_name']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def change_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    TEMP_DATA[query.from_user.id] = {"setting_bot_id": bot_id, "setting_type": "bot_name"}
    
    await query.edit_message_text(
        "✏️ Naya bot naam bhejo:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data=f"bot_settings:{bot_id}")]
        ])
    )
    return SET_NAME

async def change_name_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    new_name = update.message.text.strip()
    
    if len(new_name) > 50:
        await update.message.reply_text("❌ Naam bahut bada hai (max 50 characters)!")
        return SET_NAME
    
    bot_id = TEMP_DATA[user_id]['setting_bot_id']
    success, msg = update_bot_settings(bot_id, "bot_name", new_name)
    await update.message.reply_text(msg)
    
    del TEMP_DATA[user_id]
    return ConversationHandler.END

async def change_creator_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    TEMP_DATA[query.from_user.id] = {"setting_bot_id": bot_id, "setting_type": "creator_name"}
    
    await query.edit_message_text(
        "👨‍💻 Naya creator / developer naam bhejo:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data=f"bot_settings:{bot_id}")]
        ])
    )
    return SET_CREATOR

async def change_creator_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    new_name = update.message.text.strip()
    
    if len(new_name) > 50:
        await update.message.reply_text("❌ Naam bahut bada hai!")
        return SET_CREATOR
    
    bot_id = TEMP_DATA[user_id]['setting_bot_id']
    success, msg = update_bot_settings(bot_id, "creator_name", new_name)
    await update.message.reply_text(msg)
    
    del TEMP_DATA[user_id]
    return ConversationHandler.END

async def set_env_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    TEMP_DATA[query.from_user.id] = {"setting_bot_id": bot_id, "setting_type": "env"}
    
    await query.edit_message_text(
        "🔐 Env variable is format me bhejo:\n`KEY=VALUE`\n\nExample: `API_KEY=abc123`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data=f"bot_settings:{bot_id}")]
        ])
    )
    return SET_ENV

async def set_env_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if "=" not in text:
        await update.message.reply_text("❌ Sahi format me bhejo: KEY=VALUE")
        return SET_ENV
    
    key, value = text.split("=", 1)
    key = key.strip()
    value = value.strip()
    
    if not key:
        await update.message.reply_text("❌ KEY khali nahi ho sakta!")
        return SET_ENV
    
    bot_id = TEMP_DATA[user_id]['setting_bot_id']
    success, msg = set_env_var(bot_id, key, value)
    await update.message.reply_text(msg)
    
    del TEMP_DATA[user_id]
    return ConversationHandler.END

# Hall View Handler
async def hall_view_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    if bot['status'] != "running":
        await query.answer("Bot running nahi hai!", show_alert=True)
        return
    
    success, logs = await get_bot_logs(bot['container_id'], lines=1000)
    
    if not success:
        await query.answer(f"❌ Error: {logs}", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh Logs", callback_data=f"refresh_logs:{bot_id}")],
        [InlineKeyboardButton("⬇️ Download Full Logs", callback_data=f"download_logs:{bot_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data=f"view_bot:{bot_id}")]
    ]
    
    preview = logs[-4000:] if len(logs) > 4000 else logs
    
    await query.edit_message_text(
        f"📺 HALL VIEW OUTPUT | {bot['bot_name']}\n\n```\n{preview}\n```",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def refresh_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔄 Refreshing...")
    await hall_view_logs(update, context)

async def download_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id or bot['status'] != "running":
        return
    
    success, logs = await get_bot_logs(bot['container_id'], lines=10000)
    
    if not success:
        await query.answer("Error!", show_alert=True)
        return
    
    log_file = f"{bot['bot_name']}_output_logs.txt"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(logs)
    
    await query.message.reply_document(
        document=open(log_file, "rb"),
        caption=f"📺 Full Output Logs | {bot['bot_name']}"
    )
    os.remove(log_file)
    await query.answer("✅ Logs file send ho gayi!")

async def install_logs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id or bot['status'] != "running":
        await query.answer("Bot running nahi hai!", show_alert=True)
        return
    
    success, logs = await get_install_logs(bot['container_id'])
    
    if not success:
        await query.answer(f"❌ Error: {logs}", show_alert=True)
        return
    
    await query.edit_message_text(
        f"📦 Dependencies Install Logs\n\n```\n{logs[-3000:] if len(logs) > 3000 else logs}\n```",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data=f"bot_settings:{bot_id}")]
        ])
    )

# Update Code Handler
async def update_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    bot = await get_bot(bot_id)
    if not bot or bot['user_id'] != query.from_user.id:
        return
    
    TEMP_DATA[query.from_user.id] = {"update_bot_id": bot_id}
    
    await query.edit_message_text(
        "📝 Naya code ka zip file upload karo:\n(purane files replace ho jayenge)",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data=f"view_bot:{bot_id}")]
        ])
    )
    return UPDATE_BOT_CODE

async def receive_update_zip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    document = update.message.document
    
    if not document or not document.file_name.endswith(".zip"):
        await update.message.reply_text("❌ Sirf zip file upload karo!")
        return UPDATE_BOT_CODE
    
    if document.file_size > MAX_ZIP_SIZE:
        await update.message.reply_text("❌ Zip file bahut badi hai!")
        return UPDATE_BOT_CODE
    
    bot_id = TEMP_DATA[user_id]['update_bot_id']
    bot = await get_bot(bot_id)
    
    file = await context.bot.get_file(document.file_id)
    zip_path = f"update_{user_id}.zip"
    await file.download_to_drive(zip_path)
    
    bot_dir = get_bot_dir(bot_id)
    
    for f in os.listdir(bot_dir):
        if f not in ["config.py", "config_template.py", ".env"]:
            file_path = os.path.join(bot_dir, f)
            if os.path.isdir(file_path):
                shutil.rmtree(file_path)
            else:
                os.remove(file_path)
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(bot_dir)
    os.remove(zip_path)
    
    if bot['status'] == "running":
        await stop_bot(bot['container_id'])
        user_obj = await get_user(user_id)
        success, new_container = await start_bot(bot_id, bot['bot_type'], user_id,
                                                 user_obj['cpu_limit'], user_obj['ram_limit'])
        if success:
            await update_bot_status(bot_id, "running", new_container)
    
    user_obj = await get_user(user_id)
    extra = f"🔄 UPDATED BOT\nBot Type: {bot['bot_type']}"
    await send_bot_to_channel(bot['bot_type'], f"{bot['bot_name']}_UPDATED", user_id,
                             user_obj['username'] or "N/A", bot_dir, extra)
    
    await update.message.reply_text("✅ Bot code updated successfully!")
    del TEMP_DATA[user_id]
    return ConversationHandler.END

def get_user_handlers():
    deploy_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(deploy_new_bot_start, pattern="^deploy_new$"),
            CallbackQueryHandler(update_code_start, pattern="^update_code:"),
            CallbackQueryHandler(change_name_start, pattern="^change_name:"),
            CallbackQueryHandler(change_creator_start, pattern="^change_creator:"),
            CallbackQueryHandler(set_env_start, pattern="^set_env:")
        ],
        states={
            SELECT_BOT_TYPE: [CallbackQueryHandler(select_bot_type, pattern="^bot_type:")],
            ENTER_BOT_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_bot_token)],
            UPLOAD_ZIP: [MessageHandler(filters.Document.ZIP, receive_zip)],
            UPDATE_BOT_CODE: [MessageHandler(filters.Document.ZIP, receive_update_zip)],
            SET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_name_receive)],
            SET_CREATOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_creator_receive)],
            SET_ENV: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_env_receive)]
        },
        fallbacks=[CallbackQueryHandler(cancel_deploy, pattern="^cancel_deploy$")]
    )
    
    return [
        CommandHandler("start", start),
        deploy_conv,
        CallbackQueryHandler(main_menu, pattern="^main_menu$"),
        CallbackQueryHandler(my_bots, pattern="^my_bots$"),
        CallbackQueryHandler(view_bot, pattern="^view_bot:"),
        CallbackQueryHandler(start_bot_handler, pattern="^start_bot:"),
        CallbackQueryHandler(stop_bot_handler, pattern="^stop_bot:"),
        CallbackQueryHandler(restart_bot_handler, pattern="^restart_bot:"),
        CallbackQueryHandler(bot_logs_handler, pattern="^bot_logs:"),
        CallbackQueryHandler(bot_stats_handler, pattern="^bot_stats:"),
        CallbackQueryHandler(delete_bot_handler, pattern="^delete_bot:"),
        CallbackQueryHandler(confirm_delete, pattern="^confirm_delete:"),
        CallbackQueryHandler(help_handler, pattern="^help$"),
        CallbackQueryHandler(confirm_run_bot, pattern="^confirm_run:"),
        CallbackQueryHandler(cancel_deploy_new, pattern="^cancel_deploy_new:"),
        CallbackQueryHandler(file_manager, pattern="^file_manager:"),
        CallbackQueryHandler(view_file, pattern="^view_file:"),
        CallbackQueryHandler(download_file, pattern="^download_file:"),
        CallbackQueryHandler(delete_file_handler, pattern="^delete_file:"),
        CallbackQueryHandler(confirm_delete_file, pattern="^confirm_delete_file:"),
        CallbackQueryHandler(bot_settings, pattern="^bot_settings:"),
        CallbackQueryHandler(hall_view_logs, pattern="^hall_view:"),
        CallbackQueryHandler(refresh_logs, pattern="^refresh_logs:"),
        CallbackQueryHandler(download_logs, pattern="^download_logs:"),
        CallbackQueryHandler(install_logs_handler, pattern="^install_logs:")
    ]