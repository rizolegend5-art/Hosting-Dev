RIZO HOSTING BOT + CLONE BOT — RAILWAY DEPLOYMENT
=================================================

WHAT IS INCLUDED
----------------
- Original Hosting Bot source and original features are retained.
- Clone Bot wizard with token validation, owner ID, developer name, welcome
  text, profile-photo preview and confirmation.
- Clone bot registry in SQLite; clone tokens encrypted at rest.
- Main Telegram Admin Panel and web Admin Panel clone listing, counts,
  start and stop controls.
- Clone bots support /start, /help, /status, /setwelcome, /setname,
  /files and /getfile. Users can upload documents up to 10 MB to their
  own private clone-bot file area.
- Clone bot file uploads are stored, listed and downloadable. They are NOT
  executed by clone bots. Running arbitrary code from many unrelated users
  inside one shared Railway service is unsafe without a separate sandbox per
  user (container isolation, CPU/memory/process/network limits).
- The original host bot's existing file and script features remain in the
  main bot. Its existing channel logging behavior is retained. Clone uploads
  are not silently forwarded to a channel; add explicit disclosure/consent
  before enabling any clone-user channel forwarding.
- Admin web panel fails closed and stays disabled unless ADMIN_PASSWORD is set.

RAILWAY DEPLOYMENT
------------------
1. Push the contents of this folder to a GitHub repository.
2. Create a Railway project from that repository. Keep ONE running replica
   because Telegram long polling should not run in multiple replicas for the
   same bot token.
3. Set these Railway Variables:
     BOT_TOKEN                 = main bot token from BotFather
     OWNER_ID                  = your numeric Telegram user ID
     ADMIN_ID                  = your numeric Telegram admin ID
     ADMIN_PASSWORD            = long, unique web-panel password (required)
     CLONE_ENCRYPTION_KEY      = stable random secret (recommended; see below)
4. Optional variables used by the existing project:
     PORT                      = Railway normally supplies this automatically
     YOUR_USERNAME             = support username (existing source currently
                                 has a hard-coded default)
     UPDATE_CHANNEL            = update channel (existing source currently
                                 has a hard-coded default)
5. Generate a stable CLONE_ENCRYPTION_KEY locally with:
     python -c "import secrets; print(secrets.token_urlsafe(48))"
   Save it securely. Do not change it after clones have been registered, or
   their encrypted bot tokens cannot be decrypted after a redeploy.
6. Add a Railway Volume mounted at /app/inf for the SQLite database and at
   /app/upload_bots and /app/clone_data for uploaded project files and clone
   user files. If your service uses a different working directory, adjust the
   mount paths to match the deployed project directory.
7. Deploy. Railway uses railway.json / nixpacks.toml and starts `python bot.py`.
   The health endpoint is /health. The web Admin Panel is /admin.
8. Visit /admin over HTTPS and sign in using username `admin` and the
   ADMIN_PASSWORD value. Never leave ADMIN_PASSWORD empty.

PACKAGES / RUNTIME
------------------
- Python 3.11
- aiogram 3.13.1
- aiohttp 3.10.11
- psutil 6.1.1
- python-dotenv 1.0.1
- cryptography 44.0.0
- python-telegram-bot 21.10 (retained for compatibility with the existing
  project/deployed user projects)
- Node.js 20 is installed by Nixpacks for existing .js script support.

IMPORTANT HOSTING NOTES
-----------------------
- Railway ephemeral disk is lost on redeploy unless a Volume is mounted.
- Do not commit .env files, Telegram tokens, passwords or encryption keys.
- Revoke and replace any token that has been publicly exposed.
- Railway resource limits and restart behavior depend on your plan. A process
  started as a child script may be terminated on redeploy or service restart.
- The original host's uploaded script runner executes user-provided code. Only
  allow trusted users unless you move script execution into isolated workers.
- Each clone must be a bot token you control or are explicitly authorized to
  operate. Keep clone tokens private and use BotFather to revoke compromised
  tokens.
