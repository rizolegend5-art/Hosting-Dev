RIZO HOSTING BOT (Railway ready)  —  real hosting + real clone bots
====================================================================

KYA BADLA (purani problems ka fix)
----------------------------------
1. ADMIN pehchaan: ab OWNER_ID, ADMIN_ID, ADMIN_IDS sab chalte hain (comma/space se multiple).
   Agar phir bhi "Aap admin nahi ho" aaye to bot aapki asli ID dikha deta hai (/myid ya /admin).
2. Docker hata diya (Railway par Docker hota hi nahi). Ab bots real subprocess me chalte hain:
   zip safe extract -> requirements.txt / package.json auto install -> bot live.
   Start fail ho to asli error message dikhta hai (logs me bhi).
3. Clone bot ab real hai: alag process me chalta hai, aur poora working bot hai
   (welcome + PHOTO, file share, auto-reply, broadcast, ban/unban, stats, owner panel).
4. /start par welcome ke saath PICTURE aati hai (assets/welcome.jpg). Admin badal sakta hai:
   kisi photo ko reply karke /setwelcomepic
5. Crash par auto-restart (10 min me max 5), user ko message, RAM limit enforce,
   Railway redeploy ke baad running bots khud wapas start.
6. Naye features: File Manager (view/download/delete/upload), ENV variables menu, Update Code,
   Install logs, Stats, Admin: users/bots/clones, approvals, maintenance mode, broadcast,
   limits, backup, server stats, /ban /unban /stats /myid /ping.

RAILWAY SETUP
-------------
Variables:
  BOT_TOKEN     = main hosting bot ka token
  ADMIN_IDS     = aapki numeric Telegram ID (multiple: 111,222)   [OWNER_ID bhi chalega]
Optional:
  BOT_FILES_CHANNEL = channel ID (code backup, token ke bina)  | YOUR_USERNAME | UPDATE_CHANNEL
  MAX_BOTS_PER_USER (5) | MAX_CLONE_BOTS_PER_USER (3) | DEFAULT_RAM_LIMIT (256m) | MAX_ZIP_SIZE (bytes)

Volume (ZAROORI): Railway -> service -> Volumes -> mount path  /data
  (bots, database, logs yahin save hote hain; bina volume ke redeploy par sab ud jata hai)

Deploy: is folder ko GitHub repo me push karo. Purani Procfile aur nixpacks.toml delete hain,
sirf railway.json + railpack.json use hoti hain. Replica = 1 rakho.

NOTES
-----
- Hosted bots isi server par process ki tarah chalte hain (container isolation nahi). Un par RAM limit,
  alag folder, aur host ke secrets (BOT_TOKEN, ADMIN_IDS) unse chhupe rehte hain, lekin unknown logon
  ka code chalana risky hai. Public karne se pehle "Deploy approval" ON rakho (Admin > Settings).
- CPU limit sirf informational hai; RAM limit enforce hoti hai.
- Node.js bots ke liye railpack.json me node 20 already hai.
- Token/ENV wale messages bot khud delete kar deta hai.
