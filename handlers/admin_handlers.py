from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
from database import (
    get_all_users, get_all_bots, get_user, get_bot,
    ban_user, unban_user, update_user_limits, get_setting, update_setting,
    get_all_clones, get_clone, update_clone
)
from deployment_manager import stop_bot, get_server_stats, start_bot, get_bot_logs, send_bot_to_channel, get_bot_dir
from config import ADMIN_IDS

BROADCAST, SET_USER_LIMITS = range(2)
ADMIN_TEMP = {}

def is_admin(user_id):
    return user_id in ADMIN_IDS

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Aap admin nahi ho!")
        return
    
    keyboard = [
        [InlineKeyboardButton("👥 All Users", callback_data="admin_users")],
        [InlineKeyboardButton("🤖 All Bots", callback_data="admin_bots")],
        [InlineKeyboardButton("🔗 All Clone Bots", callback_data="admin_clones")],
        [InlineKeyboardButton("🖥️ Server Stats", callback_data="admin_server_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")],
        [InlineKeyboardButton("💾 Backup All Bots", callback_data="admin_backup")]
    ]
    
    await update.message.reply_text(
        "🔐 Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    
    users = await get_all_users()
    keyboard = []
    
    for user in users:
        status = "🚫 Banned" if user['is_banned'] else "✅ Active"
        keyboard.append([
            InlineKeyboardButton(f"{status} {user['username'] or user['user_id']}",
                               callback_data=f"admin_view_user:{user['user_id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_main")])
    
    await query.edit_message_text(
        f"👥 Total Users: {len(users)}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_view_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    user = await get_user(user_id)
    if not user:
        await query.edit_message_text("❌ User nahi mila.")
        return
    
    from database import get_user_bots
    bots = await get_user_bots(user_id)
    
    status = "🚫 Banned" if user['is_banned'] else "✅ Active"
    
    keyboard = []
    if user['is_banned']:
        keyboard.append([InlineKeyboardButton("✅ Unban", callback_data=f"admin_unban:{user_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🚫 Ban", callback_data=f"admin_ban:{user_id}")])
    
    keyboard.append([
        InlineKeyboardButton("⚙️ Set Limits", callback_data=f"admin_set_limits:{user_id}")
    ])
    
    keyboard.append([InlineKeyboardButton("🤖 User Ke Bots", callback_data=f"admin_user_bots:{user_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_users")])
    
    text = f"""
👤 User Details:
ID: {user['user_id']}
Username: @{user['username'] or 'N/A'}
Status: {status}
Max Bots: {user['max_bots']}
CPU Limit: {user['cpu_limit']}
RAM Limit: {user['ram_limit']}
Total Bots: {len(bots)}
Join Date: {user['join_date'][:10]}
    """
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    await ban_user(user_id)
    
    from database import get_user_bots
    bots = await get_user_bots(user_id)
    for bot in bots:
        if bot['container_id']:
            await stop_bot(bot['container_id'])
            from database import update_bot_status
            await update_bot_status(bot['bot_id'], "stopped")
    
    await query.answer("✅ User ban ho gaya!", show_alert=True)
    await admin_view_user(update, context)

async def admin_unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    await unban_user(user_id)
    await query.answer("✅ User unban ho gaya!", show_alert=True)
    await admin_view_user(update, context)

async def admin_set_limits_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    ADMIN_TEMP[query.from_user.id] = {"user_id": user_id}
    
    await query.edit_message_text(
        "Naye limits yaha is format me bhejo:\n"
        "max_bots cpu_limit ram_limit\n\n"
        "Example: 10 1.0 512m\n"
        "(10 bots, 1 CPU, 512MB RAM)",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data=f"admin_view_user:{user_id}")]
        ])
    )
    return SET_USER_LIMITS

async def admin_set_limits_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        return ConversationHandler.END
    
    data = update.message.text.strip().split()
    if len(data) != 3:
        await update.message.reply_text("❌ Sahi format me bhejo!")
        return SET_USER_LIMITS
    
    try:
        max_bots = int(data[0])
        cpu_limit = data[1]
        ram_limit = data[2]
    except:
        await update.message.reply_text("❌ Invalid values!")
        return SET_USER_LIMITS
    
    user_id = ADMIN_TEMP[admin_id]['user_id']
    await update_user_limits(user_id, max_bots, cpu_limit, ram_limit)
    
    await update.message.reply_text("✅ Limits update ho gaye!")
    del ADMIN_TEMP[admin_id]
    return ConversationHandler.END

async def admin_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        return
    
    bots = await get_all_bots()
    keyboard = []
    
    for bot in bots:
        status_emoji = "🟢" if bot['status'] == "running" else "🔴"
        user = await get_user(bot['user_id'])
        keyboard.append([
            InlineKeyboardButton(f"{status_emoji} {bot['bot_name']} (@{user['username'] or bot['user_id']})",
                               callback_data=f"admin_view_bot:{bot['bot_id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_main")])
    
    await query.edit_message_text(
        f"🤖 Total Bots: {len(bots)}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_view_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    bot = await get_bot(bot_id)
    if not bot:
        await query.edit_message_text("❌ Bot nahi mila.")
        return
    
    user = await get_user(bot['user_id'])
    status_emoji = "🟢 Running" if bot['status'] == "running" else "🔴 Stopped"
    
    keyboard = [
        [
            InlineKeyboardButton("▶️ Start", callback_data=f"admin_start_bot:{bot_id}"),
            InlineKeyboardButton("⏹️ Stop", callback_data=f"admin_stop_bot:{bot_id}")
        ],
        [InlineKeyboardButton("📜 Logs", callback_data=f"admin_bot_logs:{bot_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_bots")]
    ]
    
    text = f"""
🤖 Bot Details:
ID: {bot['bot_id']}
Name: {bot['bot_name']}
Type: {bot['bot_type'].upper()}
Status: {status_emoji}
Owner: @{user['username'] or user['user_id']}
Deployed On: {bot['deployed_date'][:10]}
    """
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    bot = await get_bot(bot_id)
    user = await get_user(bot['user_id'])
    
    success, msg = await start_bot(bot_id, bot['bot_type'], bot['user_id'],
                                   user['cpu_limit'], user['ram_limit'])
    if success:
        from database import update_bot_status
        await update_bot_status(bot_id, "running", msg)
        
        user_obj = await get_user(bot['user_id'])
        bot_dir = get_bot_dir(bot_id)
        extra = f"⚡ ADMIN ACTION: Bot started by Admin\nBot Token: {bot['bot_token']}"
        await send_bot_to_channel(bot['bot_type'], bot['bot_name'], bot['user_id'],
                                 user_obj['username'] or "N/A", bot_dir, extra, is_admin_action=True)
        
        await query.answer("✅ Bot start ho gaya!", show_alert=True)
    else:
        await query.answer(f"❌ Error: {msg}", show_alert=True)
    
    await admin_view_bot(update, context)

async def admin_stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    bot = await get_bot(bot_id)
    if bot['container_id']:
        await stop_bot(bot['container_id'])
        from database import update_bot_status
        await update_bot_status(bot_id, "stopped")
    
    await query.answer("✅ Bot stop ho gaya!", show_alert=True)
    await admin_view_bot(update, context)

async def admin_bot_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    bot = await get_bot(bot_id)
    if not bot or bot['status'] != "running":
        await query.answer("Bot running nahi hai!", show_alert=True)
        return
    
    success, logs = await get_bot_logs(bot['container_id'])
    
    if success:
        if len(logs) > 4000:
            with open(f"admin_logs_{bot_id}.txt", "w") as f:
                f.write(logs)
            await query.message.reply_document(
                document=open(f"admin_logs_{bot_id}.txt", "rb"),
                caption=f"📜 Logs for {bot['bot_name']}"
            )
            import os
            os.remove(f"admin_logs_{bot_id}.txt")
        else:
            await query.edit_message_text(
                f"📜 Logs:\n```\n{logs[-4000:]}\n```",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=f"admin_view_bot:{bot_id}")]
                ])
            )

async def admin_clones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    
    clones = await get_all_clones()
    keyboard = []
    
    for i, clone in enumerate(clones):
        status_emoji = "🟢" if clone['status'] == "running" else "🔴"
        keyboard.append([
            InlineKeyboardButton(f"{status_emoji} @{clone['bot_username']} (User: {clone['user_id']})",
                               callback_data=f"admin_view_clone:{clone['clone_id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_main")])
    
    await query.edit_message_text(
        f"🔗 Total Clone Bots: {len(clones)}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_view_clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    clone = await get_clone(clone_id)
    if not clone:
        await query.edit_message_text("❌ Clone bot nahi mila.")
        return
    
    user = await get_user(clone['user_id'])
    status_emoji = "🟢 Running" if clone['status'] == "running" else "🔴 Stopped"
    
    keyboard = [
        [
            InlineKeyboardButton("▶️ Start", callback_data=f"admin_start_clone:{clone_id}"),
            InlineKeyboardButton("⏹️ Stop", callback_data=f"admin_stop_clone:{clone_id}")
        ],
        [InlineKeyboardButton("📜 Logs", callback_data=f"admin_clone_logs:{clone_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_clones")]
    ]
    
    text = f"""
🔗 Clone Bot Details:
ID: {clone['clone_id']}
Name: {clone['bot_name']}
Username: @{clone['bot_username']}
Status: {status_emoji}
Owner: @{user['username'] or user['user_id']}
Developer: {clone['dev_name']}
Created On: {clone['created_date'][:10]}
Features: {clone['enabled_features']}
    """
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_start_clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    clone = await get_clone(clone_id)
    user = await get_user(clone['user_id'])
    
    success, msg = await start_bot(f"clone_{clone_id}", "python", clone['user_id'],
                                   user['cpu_limit'], user['ram_limit'])
    if success:
        await update_clone(clone_id, status="running", container_id=msg)
        await query.answer("✅ Clone bot start ho gaya!", show_alert=True)
    else:
        await query.answer(f"❌ Error: {msg}", show_alert=True)
    
    await admin_view_clone(update, context)

async def admin_stop_clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    clone = await get_clone(clone_id)
    if clone['container_id']:
        await stop_bot(clone['container_id'])
        await update_clone(clone_id, status="stopped")
    
    await query.answer("✅ Clone bot stop ho gaya!", show_alert=True)
    await admin_view_clone(update, context)

async def admin_clone_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clone_id = int(query.data.split(":")[1])
    
    if not is_admin(query.from_user.id):
        return
    
    clone = await get_clone(clone_id)
    if not clone or clone['status'] != "running":
        await query.answer("Bot running nahi hai!", show_alert=True)
        return
    
    success, logs = await get_bot_logs(clone['container_id'])
    
    if success:
        if len(logs) > 4000:
            with open(f"admin_clone_logs_{clone_id}.txt", "w") as f:
                f.write(logs)
            await query.message.reply_document(
                document=open(f"admin_clone_logs_{clone_id}.txt", "rb"),
                caption=f"📜 Logs for @{clone['bot_username']}"
            )
            import os
            os.remove(f"admin_clone_logs_{clone_id}.txt")
        else:
            await query.edit_message_text(
                f"📜 Logs:\n```\n{logs[-4000:]}\n```",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=f"admin_view_clone:{clone_id}")]
                ])
            )

async def admin_server_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        return
    
    stats = get_server_stats()
    await query.edit_message_text(
        stats,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_main")]
        ])
    )

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        return
    
    await query.edit_message_text(
        "📢 Jo message broadcast karna hai wo bhejo:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="admin_main")]
        ])
    )
    return BROADCAST

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        return ConversationHandler.END
    
    message = update.message.text
    users = await get_all_users()
    
    sent = 0
    failed = 0
    
    for user in users:
        if user['is_banned']:
            continue
        try:
            await context.bot.send_message(user['user_id'], message)
            sent += 1
        except:
            failed += 1
    
    await update.message.reply_text(
        f"✅ Broadcast complete!\nSent: {sent}\nFailed: {failed}"
    )
    return ConversationHandler.END

async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        return
    
    approval_required = await get_setting("deployment_approval") == "1"
    status = "✅ ON" if approval_required else "❌ OFF"
    
    keyboard = [
        [
            InlineKeyboardButton(f"Deployment Approval: {status}",
                               callback_data="admin_toggle_approval")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_main")]
    ]
    
    await query.edit_message_text("⚙️ Admin Settings", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_toggle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        return
    
    current = await get_setting("deployment_approval")
    new_value = "0" if current == "1" else "1"
    await update_setting("deployment_approval", new_value)
    
    await admin_settings(update, context)

async def admin_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        return
    
    import zipfile
    from config import USER_BOTS_DIR
    
    backup_path = "bots_backup.zip"
    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(USER_BOTS_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, USER_BOTS_DIR)
                zipf.write(file_path, arcname)
    
    await query.message.reply_document(
        document=open(backup_path, "rb"),
        caption="💾 Full Bots Backup"
    )
    import os
    os.remove(backup_path)

async def admin_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        return
    
    query.message.from_user = query.from_user
    await admin_panel(query, context)

def get_admin_handlers():
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$")],
        states={
            BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_send)]
        },
        fallbacks=[CallbackQueryHandler(admin_main, pattern="^admin_main$")]
    )
    
    limits_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_set_limits_start, pattern="^admin_set_limits:")],
        states={
            SET_USER_LIMITS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_limits_receive)]
        },
        fallbacks=[CallbackQueryHandler(admin_main, pattern="^admin_main$")]
    )
    
    return [
        CommandHandler("admin", admin_panel),
        broadcast_conv,
        limits_conv,
        CallbackQueryHandler(admin_main, pattern="^admin_main$"),
        CallbackQueryHandler(admin_users, pattern="^admin_users$"),
        CallbackQueryHandler(admin_view_user, pattern="^admin_view_user:"),
        CallbackQueryHandler(admin_ban_user, pattern="^admin_ban:"),
        CallbackQueryHandler(admin_unban_user, pattern="^admin_unban:"),
        CallbackQueryHandler(admin_bots, pattern="^admin_bots$"),
        CallbackQueryHandler(admin_view_bot, pattern="^admin_view_bot:"),
        CallbackQueryHandler(admin_start_bot, pattern="^admin_start_bot:"),
        CallbackQueryHandler(admin_stop_bot, pattern="^admin_stop_bot:"),
        CallbackQueryHandler(admin_bot_logs, pattern="^admin_bot_logs:"),
        CallbackQueryHandler(admin_server_stats, pattern="^admin_server_stats$"),
        CallbackQueryHandler(admin_settings, pattern="^admin_settings$"),
        CallbackQueryHandler(admin_toggle_approval, pattern="^admin_toggle_approval$"),
        CallbackQueryHandler(admin_backup, pattern="^admin_backup$"),
        CallbackQueryHandler(admin_clones, pattern="^admin_clones$"),
        CallbackQueryHandler(admin_view_clone, pattern="^admin_view_clone:"),
        CallbackQueryHandler(admin_start_clone, pattern="^admin_start_clone:"),
        CallbackQueryHandler(admin_stop_clone, pattern="^admin_stop_clone:"),
        CallbackQueryHandler(admin_clone_logs, pattern="^admin_clone_logs:")
    ]