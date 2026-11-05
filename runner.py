"""Real process manager: user bots aur clone bots ko subprocess ke taur par chalata hai.

Railway par Docker nahi hota, isliye pehle har cheez "error" deti thi. Ab:
  * zip safe tareeke se extract hoti hai (zip-slip se bachav),
  * requirements.txt / package.json automatic install hote hain (cache ke saath),
  * bot alag process me chalta hai, logs file me jaate hain,
  * crash ho to auto-restart (10 min me max 5 baar), RAM limit enforce hoti hai,
  * Railway redeploy ke baad jo bots 'running' the wo khud wapas start ho jaate hain.
"""
import asyncio
import hashlib
import logging
import os
import re
import shutil
import signal
import sys
import time
import zipfile
from pathlib import Path

import psutil

import config
import database as db

log = logging.getLogger("runner")

PY_ENTRIES = ["main.py", "bot.py", "app.py", "index.py", "run.py"]
JS_ENTRIES = ["index.js", "bot.js", "main.js", "app.js", "server.js"]
KEEP_ON_UPDATE = {".env", ".deps", "node_modules", "clone.db", "clone.db-wal", "clone.db-shm",
                  "welcome.jpg", "data"}
SAFE_ENV = ["PATH", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR", "VIRTUAL_ENV"]
SAFE_PREFIX = ("MISE_", "NIX_", "LD_")
STARTUP_WAIT = 5
MAX_CRASHES = 5

RUN = {}            # key -> Managed
SHUTTING_DOWN = False
NOTIFY = None       # async callable(user_id, text) -- main.py set karta hai


class Managed:
    def __init__(self, kind, id_, user_id, name):
        self.kind, self.id, self.user_id, self.name = kind, id_, user_id, name
        self.proc = None
        self.task = None
        self.stopping = False
        self.started_at = 0.0
        self.crashes = []
        self.total_restarts = 0
        self.limit_mb = 0
        self.env = {}
        self.cmd = []
        self.dir = None
        self.log = None


def key_of(kind, id_):
    return f"{kind}_{id_}"


def dir_of(kind, id_) -> Path:
    return config.USER_BOTS_DIR / key_of(kind, id_)


def log_path(kind, id_) -> Path:
    return config.LOGS_DIR / f"{key_of(kind, id_)}.log"


def install_log_path(kind, id_) -> Path:
    return config.LOGS_DIR / f"{key_of(kind, id_)}.install.log"


def parse_ram_mb(value) -> int:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kKmMgG])?[bB]?\s*", str(value or ""))
    if not m:
        return 256
    n, unit = float(m.group(1)), (m.group(2) or "m").lower()
    return max(32, int(n * {"k": 1 / 1024, "m": 1, "g": 1024}[unit]))


def is_running(kind, id_) -> bool:
    m = RUN.get(key_of(kind, id_))
    return bool(m and m.proc and m.proc.returncode is None)


# ------------------------------------------------------------------ zip / files
def _flatten(dest: Path):
    skip = {".env", ".deps", "node_modules", "clone.db"}
    items = [p for p in dest.iterdir() if p.name not in skip]
    if len(items) == 1 and items[0].is_dir() and items[0].name not in skip:
        tmp = dest / ".flat_tmp"
        items[0].rename(tmp)
        for child in tmp.iterdir():
            target = dest / child.name
            if target.exists():
                shutil.rmtree(target) if target.is_dir() else target.unlink()
            shutil.move(str(child), str(target))
        tmp.rmdir()


def safe_extract(zip_path, dest: Path, wipe_old=False):
    """Zip ko dest me extract karo. ValueError deta hai agar zip unsafe/bahut bada ho."""
    dest.mkdir(parents=True, exist_ok=True)
    if wipe_old:
        for p in dest.iterdir():
            if p.name in KEEP_ON_UPDATE:
                continue
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise ValueError("Ye valid zip file nahi hai.")
    with z:
        infos = z.infolist()
        if len(infos) > 5000:
            raise ValueError("Zip me bahut zyada files hain (max 5000).")
        if sum(i.file_size for i in infos) > config.MAX_UNZIPPED_SIZE:
            raise ValueError("Zip extract hone par bahut bada ho jayega.")
        root = dest.resolve()
        for i in infos:
            name = i.filename
            if name.startswith("__MACOSX/") or name.endswith(".DS_Store"):
                continue
            target = (dest / name).resolve()
            if target != root and root not in target.parents:
                raise ValueError("Zip me unsafe path mila, reject kar diya.")
            if i.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    _flatten(dest)


def replace_code(zip_path, dest: Path, bot_type: str):
    """Naya zip pehle temp me extract+validate, phir purani files (env/deps chhod kar) replace."""
    tmp = dest.with_name(dest.name + "_new")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        safe_extract(zip_path, tmp)
        ok, msg = validate_code(tmp, bot_type)
        if not ok:
            return False, msg
        for p in dest.iterdir():
            if p.name in KEEP_ON_UPDATE:
                continue
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        for p in tmp.iterdir():
            if p.name in {".env", "clone.db"}:
                continue
            target = dest / p.name
            if target.exists():
                shutil.rmtree(target, ignore_errors=True) if target.is_dir() else target.unlink()
            shutil.move(str(p), str(target))
        return True, msg
    except ValueError as e:
        return False, str(e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def detect_entry(d: Path, bot_type: str):
    for name in (JS_ENTRIES if bot_type == "nodejs" else PY_ENTRIES):
        if (d / name).is_file():
            return name
    return None


def validate_code(d: Path, bot_type: str):
    entry = detect_entry(d, bot_type)
    if entry:
        if bot_type == "python" and not (d / "requirements.txt").exists():
            (d / "requirements.txt").write_text("")
        if bot_type == "nodejs" and not (d / "package.json").exists():
            (d / "package.json").write_text('{"dependencies": {}}')
        return True, entry
    want = "index.js" if bot_type == "nodejs" else "main.py"
    return False, f"{want} zip ke root me nahi mili. Zip me files seedhi daalo (folder ke andar nahi)."


def list_files(d: Path, sub=""):
    """(name, is_dir, size) list; sirf ek level."""
    base = (d / sub).resolve()
    root = d.resolve()
    if base != root and root not in base.parents:
        return []
    out = []
    hidden = {".deps", "node_modules", "__pycache__", ".npm"}
    for p in sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if p.name in hidden:
            continue
        out.append((p.name, p.is_dir(), 0 if p.is_dir() else p.stat().st_size))
    return out


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def read_env_file(d: Path) -> dict:
    out = {}
    p = d / ".env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def write_env_file(d: Path, env: dict):
    (d / ".env").write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")


# ------------------------------------------------------------------ dependencies
_PIP_MODE = None


async def _exec_logged(cmd, cwd, env, logfile, timeout):
    with open(logfile, "ab", buffering=0) as lf:
        lf.write(f"\n$ {' '.join(cmd)}\n".encode())
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(cwd), env=env, stdout=lf, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL)
        try:
            return await asyncio.wait_for(proc.wait(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            lf.write(b"\n[TIMEOUT] install bahut der le raha tha, rok diya.\n")
            return -1


async def _pip_install_cmd(target: Path, req: Path, env):
    """Railpack/uv environment me 'python -m pip' na ho to fallback use karo."""
    global _PIP_MODE
    if _PIP_MODE is None:
        p = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "--version", env=env,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        if await p.wait() == 0:
            _PIP_MODE = "pip"
        elif shutil.which("uv"):
            _PIP_MODE = "uv"
        else:
            p = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "ensurepip", "--default-pip", env=env,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            _PIP_MODE = "pip" if await p.wait() == 0 else "none"
    if _PIP_MODE == "pip":
        return [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
                "--target", str(target), "-r", str(req)]
    if _PIP_MODE == "uv":
        return ["uv", "pip", "install", "--python", sys.executable, "--target", str(target), "-r", str(req)]
    return None


def _significant(text: str) -> bool:
    return any(l.strip() and not l.strip().startswith("#") for l in text.splitlines())


async def install_deps(kind, id_, d: Path, bot_type, env):
    ilog = install_log_path(kind, id_)
    ilog.write_text("")
    if bot_type == "python":
        req = d / "requirements.txt"
        if not req.is_file() or not _significant(req.read_text(errors="replace")):
            return True, "no deps"
        h = hashlib.sha256(req.read_bytes()).hexdigest()
        marker = d / ".deps" / ".req_hash"
        if marker.is_file() and marker.read_text().strip() == h:
            return True, "deps cached"
        cmd = await _pip_install_cmd(d / ".deps", req, env)
        if not cmd:
            return False, "Server par pip available nahi hai."
        (d / ".deps").mkdir(exist_ok=True)
        rc = await _exec_logged(cmd, d, env, ilog, 900)
        if rc != 0:
            return False, "requirements install fail:\n" + tail_text(ilog, 12)
        marker.write_text(h)
        return True, "deps installed"
    # nodejs
    pkg = d / "package.json"
    if not pkg.is_file():
        return True, "no deps"
    if not shutil.which("npm"):
        return False, "Node.js/npm is server par installed nahi hai (railpack.json me node daalo)."
    h = hashlib.sha256(pkg.read_bytes() + (d / "package-lock.json").read_bytes()
                       if (d / "package-lock.json").is_file() else pkg.read_bytes()).hexdigest()
    marker = d / "node_modules" / ".pkg_hash"
    if marker.is_file() and marker.read_text().strip() == h:
        return True, "deps cached"
    env = dict(env, npm_config_cache=str(config.DATA_DIR / ".npm-cache"))
    rc = await _exec_logged(["npm", "install", "--omit=dev", "--no-audit", "--no-fund", "--loglevel=error"],
                            d, env, ilog, 900)
    if rc != 0:
        return False, "npm install fail:\n" + tail_text(ilog, 12)
    (d / "node_modules").mkdir(exist_ok=True)
    marker.write_text(h)
    return True, "deps installed"


# ------------------------------------------------------------------ logs
def tail_text(path: Path, lines=40, max_bytes=200_000) -> str:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            data = f.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    return "\n".join(data.splitlines()[-lines:])


def get_logs(kind, id_, lines=60) -> str:
    return tail_text(log_path(kind, id_), lines) or "(abhi tak koi log nahi)"


# ------------------------------------------------------------------ process control
def _build_env(d: Path, token, bot_type, extra, user_env):
    env = {k: os.environ[k] for k in SAFE_ENV if k in os.environ}
    env.update({k: v for k, v in os.environ.items() if k.startswith(SAFE_PREFIX)})
    env.update({
        "HOME": str(d), "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": f"{d / '.deps'}{os.pathsep}{d}", "NODE_ENV": "production",
        "BOT_TOKEN": token or "", "TOKEN": token or "", "TELEGRAM_BOT_TOKEN": token or "",
    })
    env.update(extra or {})
    env.update(user_env)
    return env


async def _set_status(m: Managed, status):
    pid = m.proc.pid if (m.proc and status == "running") else None
    try:
        if m.kind == "bot":
            await db.update_bot(m.id, status=status, pid=pid)
        else:
            await db.update_clone(m.id, status=status, pid=pid)
    except Exception:
        log.exception("status update failed")


async def _notify(m: Managed, text):
    if NOTIFY and m.user_id:
        try:
            await NOTIFY(m.user_id, text)
        except Exception:
            log.debug("notify failed", exc_info=True)


async def _spawn(m: Managed):
    try:
        if m.log.exists() and m.log.stat().st_size > 5_000_000:
            m.log.write_text("")
    except OSError:
        pass
    with open(m.log, "ab", buffering=0) as lf:
        lf.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} START {m.cmd[-1]} =====\n".encode())
        m.proc = await asyncio.create_subprocess_exec(
            *m.cmd, cwd=str(m.dir), env=m.env, stdout=lf, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, start_new_session=True)
    m.started_at = time.time()


def _tree_rss_mb(pid):
    try:
        p = psutil.Process(pid)
        procs = [p] + p.children(recursive=True)
        return sum(x.memory_info().rss for x in procs if x.is_running()) / 1048576
    except (psutil.Error, ProcessLookupError):
        return 0.0


async def _kill(m: Managed, grace=6):
    p = m.proc
    if not p or p.returncode is not None:
        return
    try:
        os.killpg(p.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        p.terminate()
    try:
        await asyncio.wait_for(p.wait(), grace)
    except asyncio.TimeoutError:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            p.kill()
        await p.wait()


async def _wait_exit(m: Managed):
    """Process khatam hone tak wait; saath me RAM limit check."""
    while True:
        try:
            return await asyncio.wait_for(m.proc.wait(), 5)
        except asyncio.TimeoutError:
            if m.limit_mb and _tree_rss_mb(m.proc.pid) > m.limit_mb:
                with open(m.log, "ab") as lf:
                    lf.write(f"\n[HOST] RAM limit ({m.limit_mb} MB) cross hui, bot band kar diya.\n".encode())
                m.stopping = True
                await _kill(m)
                await _notify(m, f"⚠️ {m.name}: RAM limit ({m.limit_mb} MB) cross ho gayi, bot band kar diya gaya. "
                                 "Code optimize karo ya admin se limit badhwao.")
                return -9


async def _supervise(m: Managed):
    k = key_of(m.kind, m.id)
    try:
        while True:
            rc = await _wait_exit(m)
            if m.stopping or SHUTTING_DOWN:
                break
            if rc == 0:
                await _set_status(m, "stopped")
                await _notify(m, f"ℹ️ {m.name}: script khatam ho gayi (exit 0). Dobara chalane ke liye Start dabao.")
                break
            now = time.time()
            m.crashes = [t for t in m.crashes if now - t < 600] + [now]
            if len(m.crashes) > MAX_CRASHES:
                await _set_status(m, "crashed")
                await _notify(m, f"❌ {m.name} baar baar crash ho raha hai (exit {rc}). Auto-restart band. "
                                 "Logs dekho aur code theek karke Start karo.")
                break
            delay = min(3 * len(m.crashes), 20)
            await _notify(m, f"⚠️ {m.name} crash hua (exit {rc}). {delay}s me auto-restart "
                             f"({len(m.crashes)}/{MAX_CRASHES})...")
            await asyncio.sleep(delay)
            if m.stopping or SHUTTING_DOWN:
                break
            m.total_restarts += 1
            await _spawn(m)
            await _set_status(m, "running")
    except asyncio.CancelledError:
        pass
    finally:
        if RUN.get(k) is m and not SHUTTING_DOWN:
            if m.proc and m.proc.returncode is None:
                await _kill(m)
            RUN.pop(k, None)
        if m.stopping and not SHUTTING_DOWN:
            await _set_status(m, "stopped")


def sync_clone_template(d: Path):
    """Har start par clone ko latest template code do; user ka welcome.jpg/.db na chhedo."""
    shutil.copy2(config.CLONE_TEMPLATE_DIR / "main.py", d / "main.py")
    if not (d / "welcome.jpg").exists() and config.WELCOME_IMAGE.exists():
        shutil.copy2(config.WELCOME_IMAGE, d / "welcome.jpg")


async def start(kind, id_, *, token, bot_type, user_id, name, ram, extra_env=None):
    """(ok, message). Fail hone par message me asli error hota hai."""
    k = key_of(kind, id_)
    if is_running(kind, id_):
        return True, "Pehle se running hai."
    d = dir_of(kind, id_)
    if not d.is_dir():
        return False, "Bot ki files nahi mili. Code dobara upload karo."
    if kind == "clone":
        sync_clone_template(d)
    entry = detect_entry(d, bot_type)
    if not entry:
        return False, ("index.js" if bot_type == "nodejs" else "main.py") + " nahi mili."
    if bot_type == "nodejs" and not shutil.which("node"):
        return False, "Node.js is server par installed nahi hai."

    m = Managed(kind, id_, user_id, name)
    m.dir, m.log = d, log_path(kind, id_)
    m.limit_mb = parse_ram_mb(ram)
    m.env = _build_env(d, token, bot_type, extra_env, read_env_file(d))
    inner = ["node", entry] if bot_type == "nodejs" else [sys.executable, "-u", entry]
    wrapper = 'ulimit -c 0 2>/dev/null; ulimit -f 409600 2>/dev/null; exec "$@"'
    m.cmd = ["sh", "-c", wrapper, "sh"] + inner
    RUN[k] = m

    ok, msg = await install_deps(kind, id_, d, bot_type, m.env)
    if not ok:
        RUN.pop(k, None)
        return False, msg
    await _spawn(m)
    try:
        rc = await asyncio.wait_for(m.proc.wait(), STARTUP_WAIT)
    except asyncio.TimeoutError:
        rc = None
    if rc is not None:
        RUN.pop(k, None)
        await _set_status(m, "stopped")
        err = tail_text(m.log, 14)
        return False, (f"Bot start hote hi band ho gaya (exit {rc}).\n\n{err}" if rc
                       else "Script chali aur turant khatam ho gayi (koi polling/loop nahi mila).\n\n" + err)
    await _set_status(m, "running")
    await db.update_bot(id_, last_start=time.strftime("%Y-%m-%dT%H:%M:%S")) if kind == "bot" else None
    m.task = asyncio.create_task(_supervise(m))
    return True, "Bot chal raha hai."


async def stop(kind, id_):
    k = key_of(kind, id_)
    m = RUN.get(k)
    if m:
        m.stopping = True
        await _kill(m)
        if m.task:
            try:
                await asyncio.wait_for(m.task, 5)
            except Exception:
                pass
        RUN.pop(k, None)
    if kind == "bot":
        await db.update_bot(id_, status="stopped", pid=None)
    else:
        await db.update_clone(id_, status="stopped", pid=None)
    return True


async def delete_files(kind, id_):
    await stop(kind, id_)
    shutil.rmtree(dir_of(kind, id_), ignore_errors=True)
    for p in (log_path(kind, id_), install_log_path(kind, id_)):
        p.unlink(missing_ok=True)


def stats(kind, id_):
    m = RUN.get(key_of(kind, id_))
    if not m or not m.proc or m.proc.returncode is not None:
        return None
    try:
        p = psutil.Process(m.proc.pid)
        procs = [p] + p.children(recursive=True)
        for x in procs:
            x.cpu_percent(None)
        time.sleep(0.4)  # chhota sa sample window
        cpu = sum(x.cpu_percent(None) for x in procs)
        rss = sum(x.memory_info().rss for x in procs) / 1048576
    except psutil.Error:
        return None
    return {"pid": m.proc.pid, "cpu": cpu, "ram_mb": rss, "limit_mb": m.limit_mb,
            "uptime": int(time.time() - m.started_at), "restarts": m.total_restarts,
            "procs": len(procs)}


async def stats_async(kind, id_):
    return await asyncio.to_thread(stats, kind, id_)


def server_stats() -> dict:
    vm = psutil.virtual_memory()
    du = psutil.disk_usage(str(config.DATA_DIR))
    return {"cpu": psutil.cpu_percent(interval=0.5), "ram": vm.percent,
            "ram_used": vm.used / 1048576, "ram_total": vm.total / 1048576,
            "disk": du.percent, "disk_free": du.free / 1073741824,
            "running": sum(1 for m in RUN.values() if m.proc and m.proc.returncode is None)}


# ------------------------------------------------------------------ rows -> start
async def start_bot_row(row):
    user = await db.get_user(row["user_id"])
    return await start("bot", row["bot_id"], token=row["bot_token"], bot_type=row["bot_type"],
                       user_id=row["user_id"], name=row["bot_name"],
                       ram=(user["ram_limit"] if user else config.DEFAULT_RAM_LIMIT))


async def start_clone_row(row):
    user = await db.get_user(row["user_id"])
    extra = {
        "CLONE_ID": str(row["clone_id"]), "CLONE_TOKEN": row["bot_token"],
        "CLONE_OWNER_ID": str(row["owner_id"]), "CLONE_DEV_NAME": row["dev_name"] or "",
        "CLONE_USERNAME": row["bot_username"] or "", "CLONE_NAME": row["bot_name"] or "",
        "CLONE_WELCOME": row["welcome_msg"] or "", "CLONE_FEATURES": row["enabled_features"] or "",
        "CLONE_HOST_USERNAME": config.SUPPORT_USERNAME,
    }
    return await start("clone", row["clone_id"], token=row["bot_token"], bot_type="python",
                       user_id=row["user_id"], name="@" + (row["bot_username"] or str(row["clone_id"])),
                       ram=(user["ram_limit"] if user else config.DEFAULT_RAM_LIMIT), extra_env=extra)


async def restore_all():
    """Redeploy/restart ke baad jo 'running' the unhe wapas chalao."""
    sem = asyncio.Semaphore(2)

    async def one(kind, row):
        async with sem:
            try:
                ok, msg = await (start_bot_row(row) if kind == "bot" else start_clone_row(row))
                log.info("restore %s %s -> %s", kind, row[0], "OK" if ok else msg.splitlines()[0])
                if not ok:
                    await _mark(kind, row, "stopped")
            except Exception:
                log.exception("restore failed %s %s", kind, row[0])

    async def _mark(kind, row, status):
        (await db.update_bot(row["bot_id"], status=status)) if kind == "bot" else \
            (await db.update_clone(row["clone_id"], status=status))

    jobs = []
    for r in await db.get_all_bots():
        if r["status"] == "running" and r["approved"]:
            jobs.append(one("bot", r))
    for r in await db.get_all_clones():
        if r["status"] == "running":
            jobs.append(one("clone", r))
    if jobs:
        log.info("Restoring %d bot(s)...", len(jobs))
        await asyncio.gather(*jobs)


async def shutdown_all():
    """Host band ho raha hai: processes rokho par DB status 'running' rehne do (restore ke liye)."""
    global SHUTTING_DOWN
    SHUTTING_DOWN = True
    await asyncio.gather(*[_kill(m, 4) for m in list(RUN.values())], return_exceptions=True)
