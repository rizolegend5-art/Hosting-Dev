RIZO X NB TECH HOSTING BOT — ENHANCED BUILD

Railway setup:
1. Upload bot.py and requirements.txt to your GitHub repository.
2. Set Railway Variables:
   BOT_TOKEN = a NEW Telegram bot token (revoke the exposed old token first)
   OWNER_ID = your numeric Telegram user ID
3. Start Command: python bot.py
4. Redeploy and inspect Deploy Logs.

Added commands:
User: /start, /help, /status, /myprojects, /wallet
Owner: /admin, /approve USER_ID, /users, /stats, /addcredits USER_ID AMOUNT,
       /setcredits USER_ID AMOUNT, /makepremium USER_ID, /premiumoff USER_ID,
       /ban USER_ID, /unban USER_ID, /broadcast MESSAGE

Also includes safer ZIP path validation and user/project analytics.
Important: this platform executes uploaded scripts. Only use it with trusted code and isolate workloads before offering public multi-user hosting. Railway may terminate child processes or limit long-running workloads; verify actual deployment logs.
