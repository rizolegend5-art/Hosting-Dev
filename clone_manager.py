"""Opt-in Telegram bot cloning manager for RIZO HostBot.

Clones run isolated aiogram dispatchers and provide a branded welcome/help/status
experience plus owner profile customization. They do not inherit arbitrary uploaded
script execution or the host bot's private admin capabilities.
"""
import asyncio
import base64
import hashlib
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

class CloneManager:
    def __init__(self, db_path: Path, master_token: str, admin_ids: set, data_dir: Path | None = None):
        self.db_path = str(db_path)
        self.data_dir = Path(data_dir or Path(db_path).parent / 'clone_data')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key = base64.urlsafe_b64encode(hashlib.sha256(master_token.encode()).digest())
        self.cipher = Fernet(key)
        self.admin_ids = admin_ids
        self.sessions = {}
        self.instances = {}
        self.tasks = {}
        self._init_db()

    def _db(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._db() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS cloned_bots (
                bot_id INTEGER PRIMARY KEY, username TEXT NOT NULL, owner_id INTEGER NOT NULL,
                token_enc TEXT NOT NULL, developer TEXT NOT NULL DEFAULT '',
                welcome TEXT NOT NULL DEFAULT '', photo_file_id TEXT,
                status TEXT NOT NULL DEFAULT 'stopped', created_at TEXT NOT NULL)''')

    def rows(self):
        with self._db() as c:
            return c.execute('SELECT bot_id,username,owner_id,developer,welcome,photo_file_id,status,created_at FROM cloned_bots ORDER BY created_at DESC').fetchall()

    def count(self):
        with self._db() as c:
            return c.execute('SELECT COUNT(*) FROM cloned_bots').fetchone()[0]

    def get(self, bot_id):
        with self._db() as c:
            row = c.execute('SELECT bot_id,username,owner_id,token_enc,developer,welcome,photo_file_id,status FROM cloned_bots WHERE bot_id=?',(bot_id,)).fetchone()
        if not row: return None
        try: token = self.cipher.decrypt(row[3].encode()).decode()
        except (InvalidToken, ValueError): return None
        return {'bot_id':row[0],'username':row[1],'owner_id':row[2],'token':token,'developer':row[4], 'welcome':row[5], 'photo':row[6], 'status':row[7]}

    async def begin(self, message):
        self.sessions[message.from_user.id] = {'step':'token'}
        await message.answer('🤖 <b>Clone Bot Setup — Step 1/6</b>\nApne Telegram bot ka token bhejein. Token private rakhein.',parse_mode='HTML')

    async def handle_setup_message(self, message):
        uid = message.from_user.id
        s = self.sessions.get(uid)
        if not s: return False
        value = (message.text or '').strip()
        if s['step']=='token':
            try:
                candidate = Bot(value)
                me = await candidate.get_me()
                s.update(token=value, bot_id=me.id, username=me.username, bot_name=me.first_name, step='owner')
                await candidate.session.close()
                await message.answer('✅ Token verified.\n\n<b>Step 2/6:</b> Clone bot ka owner Telegram numeric ID bhejein.',parse_mode='HTML')
            except Exception:
                await message.answer('❌ Token verify nahi hua. BotFather se valid token bhejein.')
            return True
        if s['step']=='owner':
            if not value.isdigit():
                await message.answer('Numeric Telegram Owner ID bhejein.'); return True
            s['owner_id']=int(value); s['step']='developer'
            await message.answer('<b>Step 3/6:</b> Developer name bhejein jo welcome message mein dikhaya jayega.',parse_mode='HTML'); return True
        if s['step']=='developer':
            if not value or len(value)>64:
                await message.answer('Developer name 1–64 characters ka hona chahiye.'); return True
            s['developer']=value; s['step']='welcome'
            # Step 4: show the selected bot's current Telegram profile photo when available.
            try:
                preview_bot=Bot(s['token'])
                photos=await preview_bot.get_user_profile_photos(s['bot_id'],limit=1)
                if photos.total_count:
                    file=await preview_bot.get_file(photos.photos[0][-1].file_id)
                    raw=await preview_bot.download_file(file.file_path)
                    from io import BytesIO
                    await message.answer_photo(types.BufferedInputFile(raw.read() if hasattr(raw,'read') else raw,filename='clone-profile.jpg'),caption='🖼 Step 4/6: Ye aapke bot ki current profile picture hai.')
                else:
                    await message.answer('🖼 Step 4/6: Is bot par profile photo set nahi hai.')
                await preview_bot.session.close()
            except Exception:
                await message.answer('🖼 Step 4/6: Bot profile photo preview available nahi hui; setup continue karein.')
            await message.answer('<b>Step 5/6:</b> Welcome message bhejein. Default ke liye /default bhejein.',parse_mode='HTML'); return True
        if s['step']=='welcome':
            s['welcome'] = 'Welcome! Your bot is ready.' if value=='/default' else value[:3000]
            s['step']='confirm'
            kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Confirm & Start',callback_data='clone_confirm'),InlineKeyboardButton(text='❌ Cancel',callback_data='clone_cancel')]])
            await message.answer(f"<b>Step 6/6 — Clone Preview</b>\nBot: @{s['username']}\nOwner ID: <code>{s['owner_id']}</code>\nDeveloper: {s['developer']}\n\n{s['welcome']}",reply_markup=kb,parse_mode='HTML')
            return True
        return True

    async def confirm(self, callback, master_bot):
        uid=callback.from_user.id; s=self.sessions.get(uid)
        if not s or s.get('step')!='confirm':
            await callback.answer('Setup expired.',show_alert=True); return
        token=s['token']; bot_id=s['bot_id']
        try:
            enc=self.cipher.encrypt(token.encode()).decode()
            with self._db() as c:
                c.execute('INSERT OR REPLACE INTO cloned_bots(bot_id,username,owner_id,token_enc,developer,welcome,status,created_at) VALUES(?,?,?,?,?,?,?,?)',
                    (bot_id,s['username'],s['owner_id'],enc,s['developer'],s['welcome'],'starting',datetime.utcnow().isoformat()))
            self.sessions.pop(uid,None)
            await self.start(bot_id)
            await callback.message.edit_text(f"✅ Clone bot @{s['username']} start ho gaya.",parse_mode='HTML')
        except Exception as e:
            log.exception('Clone start failed')
            await callback.message.edit_text(f'❌ Bot start nahi hua: {str(e)[:250]}')
        await callback.answer()

    async def start(self, bot_id):
        if bot_id in self.tasks and not self.tasks[bot_id].done(): return
        cfg=self.get(bot_id)
        if not cfg: raise RuntimeError('Clone record/token unavailable')
        b=Bot(cfg['token']); dp=Dispatcher()
        owner=cfg['owner_id']
        async def start_cmd(m):
            from html import escape
            text=f"{escape(cfg['welcome'])}\n\n👨‍💻 Developer: {escape(cfg['developer'])}\n🤖 @{escape(cfg['username'])}\n\nCommands: /help /status /files"
            if cfg['photo']:
                await m.answer_photo(cfg['photo'],caption=text[:1024])
            else: await m.answer(text,parse_mode='HTML')
        async def help_cmd(m):
            await m.answer('Commands:\n/start — Welcome\n/help — Help\n/status — Bot status\n/files — List your uploads\n/getfile NAME — Download a file\n\nSend a document to upload (10 MB max).\nOwner: /setwelcome TEXT, /setname NAME.\nFor safety, uploaded scripts are stored only; they are not executed by clone bots.')
        async def status_cmd(m): await m.answer('🟢 Clone bot is running.')
        async def setwelcome(m):
            if m.from_user.id!=owner: return
            text=m.text.partition(' ')[2].strip()
            if not text: await m.answer('Usage: /setwelcome Your new welcome'); return
            cfg['welcome']=text[:3000]
            with self._db() as c: c.execute('UPDATE cloned_bots SET welcome=? WHERE bot_id=?',(cfg['welcome'],bot_id))
            await m.answer('✅ Welcome message updated.')
        async def setname(m):
            if m.from_user.id!=owner: return
            name=m.text.partition(' ')[2].strip()
            if not name: await m.answer('Usage: /setname New Bot Name'); return
            try:
                await b.set_my_name(name[:64]); await m.answer('✅ Bot name updated.')
            except Exception as e: await m.answer(f'❌ {str(e)[:200]}')
        async def photo(m):
            if m.from_user.id!=owner or not m.photo: return
            fid=m.photo[-1].file_id; cfg['photo']=fid
            with self._db() as c: c.execute('UPDATE cloned_bots SET photo_file_id=? WHERE bot_id=?',(fid,bot_id))
            await m.answer('✅ Welcome photo updated.')
        async def files_cmd(m):
            folder = self.data_dir / str(bot_id) / str(m.from_user.id)
            folder.mkdir(parents=True, exist_ok=True)
            files = sorted(x.name for x in folder.iterdir() if x.is_file())
            await m.answer('📁 Your files:\n' + ('\n'.join(f'• {x}' for x in files) if files else 'No files uploaded yet.'))

        async def upload_file(m):
            doc = m.document
            if not doc:
                return
            if doc.file_size and doc.file_size > 10 * 1024 * 1024:
                await m.answer('❌ Maximum file size is 10 MB.')
                return
            name = Path(doc.file_name or f'{doc.file_unique_id}.bin').name
            if not re.fullmatch(r'[A-Za-z0-9_. -]{1,120}', name) or name in {'.', '..'}:
                await m.answer('❌ Invalid filename.')
                return
            folder = self.data_dir / str(bot_id) / str(m.from_user.id)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / name
            stream = await b.download(doc.file_id)
            target.write_bytes(stream.read())
            await m.answer(f'✅ Saved <code>{name}</code>. Use /files to list files or /getfile filename to download.', parse_mode='HTML')

        async def getfile_cmd(m):
            name = m.text.partition(' ')[2].strip()
            if not name or Path(name).name != name:
                await m.answer('Usage: /getfile filename')
                return
            target = self.data_dir / str(bot_id) / str(m.from_user.id) / name
            if not target.is_file():
                await m.answer('❌ File not found. Use /files.')
                return
            await m.answer_document(FSInputFile(target))

        async def owner_photo(m):
            if m.from_user.id != owner or not m.photo:
                return
            fid = m.photo[-1].file_id
            cfg['photo'] = fid
            with self._db() as c:
                c.execute('UPDATE cloned_bots SET photo_file_id=? WHERE bot_id=?', (fid, bot_id))
            await m.answer('✅ Welcome photo updated. Send /start to preview it.')

        dp.message.register(start_cmd,Command('start'))
        dp.message.register(help_cmd,Command('help'))
        dp.message.register(status_cmd,Command('status'))
        dp.message.register(setwelcome,Command('setwelcome'))
        dp.message.register(setname,Command('setname'))
        dp.message.register(files_cmd,Command('files'))
        dp.message.register(getfile_cmd,Command('getfile'))
        dp.message.register(upload_file,F.document)
        dp.message.register(owner_photo,F.photo)
        async def runner():
            with self._db() as c: c.execute("UPDATE cloned_bots SET status='running' WHERE bot_id=?",(bot_id,))
            try: await dp.start_polling(b)
            finally:
                with self._db() as c: c.execute("UPDATE cloned_bots SET status='stopped' WHERE bot_id=?",(bot_id,))
                await b.session.close()
        self.instances[bot_id]=(b,dp)
        self.tasks[bot_id]=asyncio.create_task(runner())

    async def stop(self, bot_id):
        task=self.tasks.get(int(bot_id))
        if task and not task.done():
            inst=self.instances.get(int(bot_id))
            if inst:
                try: await inst[0].session.close()
                except Exception: pass
            task.cancel()
            try: await task
            except (asyncio.CancelledError,Exception): pass
        with self._db() as c: c.execute("UPDATE cloned_bots SET status='stopped' WHERE bot_id=?",(int(bot_id),))
        return True

    async def restore(self):
        for row in self.rows():
            try: await self.start(row[0])
            except Exception: log.exception('Could not restore clone %s',row[0])
