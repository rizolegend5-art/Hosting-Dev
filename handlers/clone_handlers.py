import os
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
from database import (
    add_clone, update_clone, get_clone, get_user_clones, get_user, delete_clone_db
)
from deployment_manager import (
    generate_clone_bot, set_bot_profile, start_bot, stop_bot,
    delete_bot_files, get_rainbow_progress, send_bot_to_channel,
    get_bot_logs, get_bot_stats
)
from config import MAX_CLONE_BOTS_PER_USER, DEFAULT_CLONE_FEATURES, RAINBOW_EMOJIS

CLONE_STEP1_TOKEN, CLONE_STEP2_OWNER_ID, CLONE_STEP3_DEV_NAME, CLONE_STEP4_PIC, CLONE_STEP4_WELCOME, CLONE_STEP5_FEATURES = range(6)
CLONE_TEMP = {}

def rainbow_button(text, callback_data, color_index=0):
    emoji = RAINBOW_EMOJIS[color_index % len(RAINBOW_EMOJIS)]
    return InlineKeyboardButton(f"{emoji} {text}", callback_data=callback_data)

async def clone_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user if update.message else update.callback_query.from_user
    user_data = await get_user(user.id)
    
    if user_data['is_banned']:
        if update.message:
            await update.message.reply_text("❌ Aap banned ho!")
        else:
            await update.callback_query.edit_message_text("❌ Aap banned ho!")
        return
    
    clones = await get_user_clones(user.id)
    if len(clones) >= MAX_CLONE_BOTS_PER_USER:
        text = f"❌ Aapke paas max {MAX_CLONE_BOTS_PER_USER} clone bots hi ho sakte hain!"
        if update.message:
            await update.message.reply_text(text)
        else:
            await update.callback_query.edit_message_text(text)
        return
    
    progress = get_rainbow_progress(0)
    
    keyboard = [
        [rainbow_button("🚀 Start Clone", "start_clone_process", 0)],
        [rainbow_button("🔙 Back", "main_menu", 6)]
    ]
    
    text = f"""
🌈 Welcome to Clone Bot System!
Aap yaha se apna pre-built hosting bot clone kar sakte hain.

{progress}
Features:
✅ 7 Color Animated Buttons
✅ Inbuilt Admin Panel
✅ Auto Setup
✅ Full Customization
    """
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def start_clone_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    CLONE_TEMP[user_id] = {"features": DEFAULT_CLONE_FEATURES.copy()}
    progress = get_rainbow_progress(1)
    
    keyboard = [[rainbow_button("🔙 Cancel", "cancel_clone", 6)]]
    
    await query.edit_message_text(
        f"{progress}\n\n🔴 Step 1/5: Apne bot ka token bhejo (BotFather se lekar)\n\n"
        "Note: Naya bot token hi daalo, purana mat use karo warna error aayega.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CLONE_STEP1_TOKEN

async def clone_step1_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = update.message.text.strip()
    
    try:
        from telegram import Bot
        bot = Bot(token)
        me = await bot.get_me()
        bot_username = me.username
        bot_name = me.first_name
    except:
        await update.message.reply_text("❌ Invalid bot token! Sahi token daalo.")
        return CLONE_STEP1_TOKEN
    
    CLONE_TEMP[user_id]['bot_token'] = token
    CLONE_TEMP[user_id]['bot_username'] = bot_username
    CLONE_TEMP[user_id]['bot_name'] = bot_name
    
    progress = get_rainbow_progress(2)
    
    keyboard = [[rainbow_button("🔙 Cancel", "cancel_clone", 6)]]
    
    await update.message.reply_text(
        f"{progress}\n\n🟠 Step 2/5: Bot ka Owner ID bhejo\n\n"
        "Ye woh ID hogi jiske paas bot ka admin panel access hoga.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CLONE_STEP2_OWNER_ID

async def clone_step2_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    owner_id = update.message.text.strip()
    
    if not owner_id.isdigit():
        await update.message.reply_text("❌ Owner ID sirf numbers me hona chahiye!")
        return CLONE_STEP2_OWNER_ID
    
    CLONE_TEMP[user_id]['owner_id'] = int(owner_id)
    progress = get_rainbow_progress(3)
    
    keyboard = [[rainbow_button("🔙 Cancel", "cancel_clone", 6)]]
    
    await update.message.reply_text(
        f"{progress}\n\n🟡 Step 3/5: Developer Name bhejo\n\n"
        "Yeh naam bot ke about me aur footer me dikhega.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CLONE_STEP3_DEV_NAME

async def clone_step3_dev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    dev_name = update.message.text.strip()
    
    CLONE_TEMP[user_id]['dev_name'] = dev_name
    progress = get_rainbow_progress(4)
    
    keyboard = [[rainbow_button("⏭️ Skip Profile Pic", "skip_profile_pic", 3)],
                [rainbow_button("🔙 Cancel", "cancel_clone", 6)]]
    
    await update.message.reply_text(
        f"{progress}\n\n🟢 Step 4/5: Bot ka profile picture upload karo\n\n"
        "Agar skip karna hai to upar wale button par click karo.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CLONE_STEP4_PIC

async def clone_step4_pic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    
    file = await context.bot.get_file(photo.file_id)
    temp_pic = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    await file.download_to_drive(temp_pic.name)
    CLONE_TEMP[user_id]['profile_pic'] = temp_pic.name
    
    progress = get_rainbow_progress(4)
    
    keyboard = [[rainbow_button("🔙 Cancel", "cancel_clone", 6)]]
    
    await update.message.reply_text(
        f"{progress}\n\n🟢 Step 4.2/5: Bot ka welcome message bhejo\n\n"
        "Yeh message jab koi user /start karega tab dikhega.\n"
        "Markdown, emoji sab use kar sakte ho.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CLONE_STEP4_WELCOME

async def skip_profile_pic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    CLONE_TEMP[user_id]['profile_pic'] = None
    
    progress = get_rainbow_progress(4)
    
    keyboard = [[rainbow_button("🔙 Cancel", "cancel_clone", 6)]]
    
    await query.edit_message_text(
        f"{progress}\n\n🟢 Step 4.2/5: Bot ka welcome message bhejo\n\n"
        "Yeh message jab koi user /start karega tab dikhega.\n"
        "Markdown, emoji sab use kar sakte ho.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CLONE_STEP4_WELCOME

async def clone_step4_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    welcome_msg = update.message.text
    
    CLONE_TEMP[user_id]['welcome_msg'] = welcome_msg
    progress = get_rainbow_progress(5)
    
    features = DEFAULT_CLONE_FEATURES
    keyboard = []
    
    for i, feature in enumerate(features):
        if feature in CLONE_TEMP[user_id]['features']:
            text = f"✅ {feature.replace('_', ' ').title()}"
        else:
            text = f"❌ {feature.replace('_', ' ').title()}"
        
        keyboard.append([rainbow_button(text, f"toggle_feature:{feature}", i)])
    
    keyboard.append([rainbow_button("🚀 Complete Setup", "finish_clone_setup", 3)])
    keyboard.append([rainbow_button("🔙 Cancel", "cancel_clone", 6)])
    
    await update.message.reply_text(
        f"{progress}\n\n🔵 Step 5/5: Apne bot ke features enable/disable karo\n\n"
        "Feature par click karo to toggle hoga.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CLONE_STEP5_FEATURES

async def toggle_feature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    feature = query.data.split(":")[1]
    
    if feature in CLONE_TEMP[user_id]['features']:
        CLONE_TEMP[user_id]['features'].remove(feature)
    else:
        CLONE_TEMP[user_id]['features'].append(feature)
    
    progress = get_rainbow_progress(5)
    features = DEFAULT_CLONE_FEATURES
    keyboard = []
    
    for i, feat in enumerate(features):
        if feat in CLONE_TEMP[user_id]['features']:
            text = f"✅ {feat.replace('_', ' ').title()}"
        else:
            text = f"❌ {feat.replace('_', ' ').title()}"
        
        keyboard.append([rainbow_button(text, f"toggle_feature:{feat}", i)])
    
    keyboard.append([rainbow_button("🚀 Complete Setup", "finish_clone_setup", 3)])
    keyboard.append([rainbow_button("🔙 Cancel", "cancel_clone", 6)])
    
    await query.edit_message_text(
        f"{progress}\n\n🔵 Step 5/5: Apne bot ke features enable/disable karo\n\n"
        "Feature par click karo to toggle hoga.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def finish_clone_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id not in CLONE_TEMP:
        await query.edit_message_text("❌ Session expire ho gaya! Dobara start karo.")
        return ConversationHandler.END
    
    data = CLONE_TEMP[user_id]
    await query.edit_message_text("⏳ Setup ho raha hai, thoda wait karo...")
    
    clone_id = await add_clone(
        user_id=user_id,
        bot_token=data['bot_token'],
        bot_username=data['bot_username'],
        bot_name=data['bot_name']
    )
    
    await update_clone(
        clone_id,
        owner_id=data['owner_id'],
        dev_name=data['dev_name'],
        welcome_msg=data['welcome_msg'],
        enabled_features=",".join(data['features']),
        status="generating"
    )
    
    bot_dir, config_name = await generate_clone_bot(clone_id, {
        "bot_token": data['bot_token'],
        "owner_id": data['owner_id'],
        "dev_name": data['dev_name'],
        "welcome_msg": data['welcome_msg'],
        "bot_username": data['bot_username'],
        "bot_name": data['bot_name'],
        "enabled_features": data['features']
    })
    
    await set_bot_profile(
        bot_token=data['bot_token'],
        profile_pic_path=data.get('profile_pic'),
        about=f"🤖 {data['bot_name']}\n⚡ Made by {data['dev_name']}",
        description=f"Welcome to {data['bot_name']}!\nDeveloper: {data['dev_name']}\n\nUse /start to begin!",
        commands={"start": "Start the bot", "help": "Get help", "admin": "Admin panel"}
    )
    
    if data.get('profile_pic') and os.path.exists(data['profile_pic']):
        os.remove(data['profile_pic'])
    
    user = await get_user(user_id)
    success, container_id = await start_bot(
        bot_id=f"clone_{clone_id}",
        bot_type="python",
        user_id=user_id,
        cpu_limit=user['cpu_limit'],
        ram_limit=user['ram_limit']
    )
    
    if success:
        await update_clone(clone_id, status="running", container_id=container_id)
        
        user_obj = await get_user(user_id)
        extra = f"""
🧑‍💻 Developer: {data['dev_name']}
👑 Owner ID: {data['owner_id']}
🔧 Features: {', '.join(data['features'])}
📎 Config File: {config_name}
        """
        await send_bot_to_channel("clone", data['bot_name'], user_id, user_obj['username'] or "N/A", bot_dir, extra)
        
        text = f"""
🎉 Congratulations! Aapka bot successfully clone ho gaya!

🤖 Bot Name: {data['bot_name']}
🔗 Bot Link: @{data['bot_username']}
📂 Config File: {config_name}
⚡ Status: 🟢 Running

Ab aap apne bot ko use kar sakte hain!
        """
        
        keyboard = [
            [rainbow_button("🤖 My Clone Bots", "my_clones", 1)],
            [rainbow_button("🏠 Main Menu", "main_menu", 6)]
        ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update_clone(clone_id, status="error")
        await query.edit_message_text(f"❌ Bot start nahi ho paya! Error: {container_id}")
    
    del CLONE_TEMP[user_id]
    return ConversationHandler.END

async def cancel_clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id in CLONE_TEMP:
        if CLONE_TEMP[user_id].get('profile_pic') and os.path.exists(CLONE_TEMP[user_id]['profile_pic']):
            os.remove(CLONE_TEMP[user_id]['profile_pic'])
        del CLONE_TEMP[user_id]
    
    await clone_start(query, context)
    return ConversationHandler.END

async def my_clones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    clones = await get_user_clones(user_id)
    if not clones:
        keyboard = [
            [rainbow_button("🚀 Create Clone Bot", "start_clone_process", 0)],
            [rainbow_button("🔙 Back", "main_menu", 6)]
        ]
        await query.edit_message_text("❌ Aapke paas koi clone bot nahi hai.", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    keyboard = []
    for i, clone in enumerate(clones):
        status_emoji = "🟢" if clone['status'] == "running" else "🔴"
        keyboard.append([
            rainbow_button(f"{status_emoji} @{clone['bot_username']}", 
                         f"view_clone:{clone['clone_id']}", i % 7)
        ])
    
    keyboard.append([rainbow_button("🚀 Naya Clone", "start_clone_process", 0)])
    keyboard.append([rainbow_button("🔙 Back", "main_menu", 6)])
    
    await query.edit_message_text(
        "🤖 Aapke Clone Bots:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def view_clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    clone = await get_clone(clone_id)
    if not clone or clone['user_id'] != query.from_user.id:
        await query.edit_message_text("❌ Clone bot nahi mila.")
        return
    
    status_emoji = "🟢 Running" if clone['status'] == "running" else "🔴 Stopped"
    
    keyboard = [
        [
            rainbow_button("▶️ Start", f"start_clone_bot:{clone_id}", 0),
            rainbow_button("⏹️ Stop", f"stop_clone_bot:{clone_id}", 1),
            rainbow_button("🔄 Restart", f"restart_clone_bot:{clone_id}", 2)
        ],
        [
            rainbow_button("📜 Logs", f"clone_logs:{clone_id}", 3),
            rainbow_button("📊 Stats", f"clone_stats:{clone_id}", 4)
        ],
        [rainbow_button("🗑️ Delete Clone", f"delete_clone:{clone_id}", 5)],
        [rainbow_button("🔙 Back", "my_clones", 6)]
    ]
    
    text = f"""
🤖 Clone Bot Details:
Name: {clone['bot_name']}
Username: @{clone['bot_username']}
Status: {status_emoji}
Developer: {clone['dev_name']}
Owner ID: {clone['owner_id']}
Created On: {clone['created_date'][:10]}
    """
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def start_clone_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    clone = await get_clone(clone_id)
    if not clone or clone['user_id'] != query.from_user.id:
        return
    
    if clone['status'] == "running":
        await query.answer("Bot pehle se running hai!", show_alert=True)
        return
    
    user = await get_user(clone['user_id'])
    success, msg = await start_bot(f"clone_{clone_id}", "python", clone['user_id'],
                                   user['cpu_limit'], user['ram_limit'])
    
    if success:
        await update_clone(clone_id, status="running", container_id=msg)
        await query.answer("✅ Clone bot start ho gaya!", show_alert=True)
    else:
        await query.answer(f"❌ Error: {msg}", show_alert=True)
    
    await view_clone(update, context)

async def stop_clone_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    clone = await get_clone(clone_id)
    if not clone or clone['user_id'] != query.from_user.id:
        return
    
    if clone['status'] == "stopped":
        await query.answer("Bot pehle se stopped hai!", show_alert=True)
        return
    
    success, msg = await stop_bot(clone['container_id'])
    if success:
        await update_clone(clone_id, status="stopped")
        await query.answer("✅ Clone bot stop ho gaya!", show_alert=True)
    else:
        await query.answer(f"❌ Error: {msg}", show_alert=True)
    
    await view_clone(update, context)

async def restart_clone_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    clone = await get_clone(clone_id)
    if not clone or clone['user_id'] != query.from_user.id:
        return
    
    await stop_bot(clone['container_id'])
    user = await get_user(clone['user_id'])
    success, msg = await start_bot(f"clone_{clone_id}", "python", clone['user_id'],
                                   user['cpu_limit'], user['ram_limit'])
    
    if success:
        await update_clone(clone_id, status="running", container_id=msg)
        await query.answer("✅ Bot restart ho gaya!", show_alert=True)
    else:
        await update_clone(clone_id, status="stopped")
        await query.answer(f"❌ Error: {msg}", show_alert=True)
    
    await view_clone(update, context)

async def delete_clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    clone = await get_clone(clone_id)
    if not clone or clone['user_id'] != query.from_user.id:
        return
    
    keyboard = [
        [rainbow_button("✅ Haan, Delete Karo", f"confirm_delete_clone:{clone_id}", 0)],
        [rainbow_button("❌ Nahi", f"view_clone:{clone_id}", 6)]
    ]
    
    await query.edit_message_text(
        "❓ Kya aap sach me is clone bot ko delete karna chahte hain?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def confirm_delete_clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    clone = await get_clone(clone_id)
    if not clone or clone['user_id'] != query.from_user.id:
        return
    
    if clone['container_id']:
        await stop_bot(clone['container_id'])
    
    await delete_bot_files(f"clone_{clone_id}")
    await delete_clone_db(clone_id)
    
    await query.edit_message_text("✅ Clone bot delete ho gaya!")
    await my_clones(update, context)

async def clone_logs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    clone = await get_clone(clone_id)
    if not clone or clone['user_id'] != query.from_user.id:
        return
    
    if clone['status'] != "running":
        await query.answer("Bot running nahi hai!", show_alert=True)
        return
    
    success, logs = await get_bot_logs(clone['container_id'])
    
    if not success:
        await query.answer(f"❌ Error: {logs}", show_alert=True)
        return
    
    if len(logs) > 4000:
        with open(f"clone_logs_{clone_id}.txt", "w") as f:
            f.write(logs)
        await query.message.reply_document(
            document=open(f"clone_logs_{clone_id}.txt", "rb"),
            caption=f"📜 Logs for @{clone['bot_username']}"
        )
        os.remove(f"clone_logs_{clone_id}.txt")
    else:
        await query.edit_message_text(
            f"📜 Logs:\n```\n{logs[-4000:]}\n```",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [rainbow_button("🔙 Back", f"view_clone:{clone_id}", 6)]
            ])
        )

async def clone_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    clone = await get_clone(clone_id)
    if not clone or clone['user_id'] != query.from_user.id:
        return
    
    if clone['status'] != "running":
        await query.answer("Bot running nahi hai!", show_alert=True)
        return
    
    success, stats = await get_bot_stats(clone['container_id'])
    
    if not success:
        await query.answer(f"❌ Error: {stats}", show_alert=True)
        return
    
    await query.edit_message_text(
        f"📊 Clone Bot Stats:\n{stats}",
        reply_markup=InlineKeyboardMarkup([
            [rainbow_button("🔙 Back", f"view_clone:{clone_id}", 6)]
        ])
    )

def get_clone_handlers():
    clone_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_clone_process, pattern="^start_clone_process$"),
            CallbackQueryHandler(clone_start, pattern="^clone_menu$")
        ],
        states={
            CLONE_STEP1_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_step1_token)],
            CLONE_STEP2_OWNER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_step2_owner)],
            CLONE_STEP3_DEV_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_step3_dev)],
            CLONE_STEP4_PIC: [
                MessageHandler(filters.PHOTO, clone_step4_pic),
                CallbackQueryHandler(skip_profile_pic, pattern="^skip_profile_pic$")
            ],
            CLONE_STEP4_WELCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_step4_welcome)],
            CLONE_STEP5_FEATURES: [
                CallbackQueryHandler(toggle_feature, pattern="^toggle_feature:"),
                CallbackQueryHandler(finish_clone_setup, pattern="^finish_clone_setup$")
            ]
        },
        fallbacks=[CallbackQueryHandler(cancel_clone, pattern="^cancel_clone$")]
    )
    
    return [
        CommandHandler("clone", clone_start),
        clone_conv,
        CallbackQueryHandler(my_clones, pattern="^my_clones$"),
        CallbackQueryHandler(view_clone, pattern="^view_clone:"),
        CallbackQueryHandler(start_clone_bot, pattern="^start_clone_bot:"),
        CallbackQueryHandler(stop_clone_bot, pattern="^stop_clone_bot:"),
        CallbackQueryHandler(restart_clone_bot, pattern="^restart_clone_bot:"),
        CallbackQueryHandler(delete_clone, pattern="^delete_clone:"),
        CallbackQueryHandler(confirm_delete_clone, pattern="^confirm_delete_clone:"),
        CallbackQueryHandler(clone_logs_handler, pattern="^clone_logs:"),
        CallbackQueryHandler(clone_stats_handler, pattern="^clone_stats:")
    ]