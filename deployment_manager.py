import docker
import os
import shutil
import zipfile
import datetime
from telegram import Bot
from config import (
    USER_BOTS_DIR, DOCKER_PYTHON_IMAGE, DOCKER_NODEJS_IMAGE,
    DEFAULT_CPU_LIMIT, DEFAULT_RAM_LIMIT, BOT_TOKEN, BOT_FILES_CHANNEL,
    CLONE_TEMPLATE_DIR, RAINBOW_EMOJIS
)
import psutil


class _LazyDockerClient:
    """Docker se connection import ke waqt nahi, pehli baar use hone par banta hai.

    Railway par Docker daemon hota hi nahi, isliye pehle docker.from_env()
    import par chalta tha aur poora bot crash ho jata tha. Ab bot start hota
    hai, aur sirf Docker wale features clear error message dete hain.
    """

    def __init__(self):
        self._client = None

    def _connect(self):
        if self._client is None:
            try:
                self._client = docker.from_env()
            except Exception as e:
                raise RuntimeError(
                    "Docker is server par available nahi hai (Railway par Docker "
                    "daemon nahi hota). User bots hosting ke liye Docker wala "
                    "VPS/server chahiye."
                ) from e
        return self._client

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._connect(), name)


client = _LazyDockerClient()


def get_bot_dir(bot_id):
    return os.path.join(USER_BOTS_DIR, str(bot_id))


async def extract_zip(bot_id, zip_path):
    bot_dir = get_bot_dir(bot_id)
    os.makedirs(bot_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(bot_dir)
    os.remove(zip_path)
    return True


def validate_bot_code(bot_id, bot_type):
    bot_dir = get_bot_dir(bot_id)
    files = os.listdir(bot_dir)
    if bot_type == "python":
        if "main.py" not in files:
            return False, "main.py file nahi mil rahi"
        if "requirements.txt" not in files:
            with open(os.path.join(bot_dir, "requirements.txt"), "w") as f:
                f.write("")
        return True, "Valid"
    elif bot_type == "nodejs":
        if "index.js" not in files:
            return False, "index.js file nahi mil rahi"
        if "package.json" not in files:
            with open(os.path.join(bot_dir, "package.json"), "w") as f:
                f.write('{"dependencies": {}}')
        return True, "Valid"
    return False, "Invalid bot type"


async def start_bot(bot_id, bot_type, user_id, cpu_limit=None, ram_limit=None):
    bot_dir = get_bot_dir(bot_id)
    cpu_limit = cpu_limit or DEFAULT_CPU_LIMIT
    ram_limit = ram_limit or DEFAULT_RAM_LIMIT
    try:
        try:
            old_container = client.containers.get(f"bot_{bot_id}_{user_id}")
            old_container.remove(force=True)
        except docker.errors.NotFound:
            pass
        if bot_type == "python":
            command = "bash -c 'pip install -r requirements.txt && python main.py'"
            image = DOCKER_PYTHON_IMAGE
        else:
            command = "sh -c 'npm install && node index.js'"
            image = DOCKER_NODEJS_IMAGE
        container = client.containers.run(
            image,
            command=command,
            name=f"bot_{bot_id}_{user_id}",
            volumes={bot_dir: {'bind': '/app', 'mode': 'rw'}},
            working_dir="/app",
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            cpu_quota=int(float(cpu_limit) * 100000),
            mem_limit=ram_limit,
            network_mode="bridge",
            read_only=False,
            security_opt=["no-new-privileges:true"]
        )
        return True, container.id
    except Exception as e:
        return False, str(e)


async def stop_bot(container_id):
    try:
        container = client.containers.get(container_id)
        container.stop(timeout=10)
        container.remove(force=True)
        return True, "Bot stopped successfully"
    except Exception as e:
        return False, str(e)


async def get_bot_logs(container_id, lines=100):
    try:
        container = client.containers.get(container_id)
        logs = container.logs(tail=lines).decode('utf-8')
        return True, logs if logs else "Koi logs nahi hai"
    except Exception as e:
        return False, str(e)


async def get_bot_stats(container_id):
    try:
        container = client.containers.get(container_id)
        stats = container.stats(stream=False)
        cpu_usage = stats['cpu_stats']['cpu_usage']['total_usage'] / 1000000000
        ram_usage = stats['memory_stats']['usage'] / 1024 / 1024
        return True, f"CPU: {round(cpu_usage, 2)}s\nRAM: {round(ram_usage, 2)} MB"
    except Exception as e:
        return False, str(e)


async def delete_bot_files(bot_id):
    bot_dir = get_bot_dir(bot_id)
    if os.path.exists(bot_dir):
        shutil.rmtree(bot_dir)
    return True


def get_server_stats():
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    try:
        running = len(client.containers.list())
    except Exception:
        running = "N/A (Docker available nahi)"
    return f"""
🖥️ Server Stats:
CPU Usage: {cpu}%
RAM Usage: {ram}%
Disk Usage: {disk}%
Total Bots Running: {running}
"""


# Channel Send Function
async def send_bot_to_channel(bot_type, bot_name, user_id, username, bot_dir, extra_details="", is_admin_action=False):
    try:
        zip_path = f"{bot_name}_full.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(bot_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, bot_dir)
                    zipf.write(file_path, arcname)
        details_path = f"{bot_name}_details.txt"
        with open(details_path, "w", encoding="utf-8") as f:
            f.write(f"🤖 Bot Name: {bot_name}\n")
            f.write(f"📦 Bot Type: {bot_type.upper()}\n")
            f.write(f"👤 User ID: {user_id}\n")
            f.write(f"👤 Username: @{username}\n")
            f.write(f"📅 Deploy Date: {datetime.datetime.now().strftime('%d %B %Y, %H:%M')}\n")
            f.write(f"⚡ Action: {'Admin Deployed' if is_admin_action else 'User Deployed'}\n")
            if extra_details:
                f.write(f"\n📝 Extra Details:\n{extra_details}\n")
        bot = Bot(BOT_TOKEN)
        caption = f"""
📦 NEW BOT HOSTED ON PLATFORM
🤖 Bot Name: {bot_name}
📦 Type: {bot_type.upper()}
👤 User: @{username} (ID: {user_id})
⚡ Action: {'Admin Deploy' if is_admin_action else 'Self Deploy'}
📅 Date: {datetime.datetime.now().strftime("%d %B %Y, %H:%M")}
"""
        with open(zip_path, "rb") as f:
            msg = await bot.send_document(
                chat_id=BOT_FILES_CHANNEL,
                document=f,
                caption=caption,
                parse_mode="Markdown"
            )
        with open(details_path, "rb") as f:
            await bot.send_document(
                chat_id=BOT_FILES_CHANNEL,
                document=f,
                reply_to_message_id=msg.message_id
            )
        os.remove(zip_path)
        os.remove(details_path)
        return True
    except Exception as e:
        print(f"Channel send error: {e}")
        return False


# Clone Bot Generator
async def generate_clone_bot(clone_id, bot_data):
    bot_dir = get_bot_dir(f"clone_{clone_id}")
    os.makedirs(bot_dir, exist_ok=True)
    shutil.copytree(CLONE_TEMPLATE_DIR, bot_dir, dirs_exist_ok=True)
    config_name = f"{bot_data['bot_name'].lower().replace(' ', '_')}_config.py"
    old_config = os.path.join(bot_dir, "config_template.py")
    new_config = os.path.join(bot_dir, config_name)
    if os.path.exists(old_config):
        os.rename(old_config, new_config)
    config_path = os.path.join(bot_dir, config_name)
    with open(config_path, "r", encoding="utf-8") as f:
        config_content = f.read()
    replacements = {
        "{{BOT_TOKEN}}": bot_data['bot_token'],
        "{{OWNER_ID}}": str(bot_data['owner_id']),
        "{{DEV_NAME}}": bot_data['dev_name'],
        "{{WELCOME_MSG}}": bot_data['welcome_msg'],
        "{{BOT_USERNAME}}": bot_data['bot_username'],
        "{{ENABLED_FEATURES}}": str(bot_data['enabled_features']),
        "{{CONFIG_FILENAME}}": config_name
    }
    for placeholder, value in replacements.items():
        config_content = config_content.replace(placeholder, value)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config_content)
    main_path = os.path.join(bot_dir, "main.py")
    if os.path.exists(main_path):
        with open(main_path, "r", encoding="utf-8") as f:
            main_content = f.read()
        main_content = main_content.replace("import config", f"import {config_name.replace('.py', '')} as config", 1)
        with open(main_path, "w", encoding="utf-8") as f:
            f.write(main_content)
    return bot_dir, config_name


# Bot Profile Set
async def set_bot_profile(bot_token, profile_pic_path=None, about="", description="", commands=None):
    try:
        bot = Bot(bot_token)
        if profile_pic_path and os.path.exists(profile_pic_path):
            with open(profile_pic_path, "rb") as f:
                await bot.set_my_avatar(photo=f)
        if about:
            await bot.set_my_short_description(short_description=about)
        if description:
            await bot.set_my_description(description=description)
        if commands:
            from telegram import BotCommand
            await bot.set_my_commands(commands=[BotCommand(cmd, desc) for cmd, desc in commands.items()])
        return True
    except Exception as e:
        print(f"Profile set error: {e}")
        return False


# 7 Color Progress Bar
def get_rainbow_progress(current_step, total_steps=5):
    progress = []
    for i in range(7):
        step_ratio = current_step / total_steps
        fill_up_to = int(step_ratio * 7)
        if i < fill_up_to:
            progress.append(RAINBOW_EMOJIS[i])
        else:
            progress.append("⚪")
    return "".join(progress) + f" {current_step}/{total_steps}"


# File Manager Functions
def get_bot_files(bot_id):
    bot_dir = get_bot_dir(bot_id)
    files_list = []
    if not os.path.exists(bot_dir):
        return []
    for root, dirs, files in os.walk(bot_dir):
        rel_root = os.path.relpath(root, bot_dir)
        if rel_root == ".":
            rel_root = ""
        for d in dirs:
            files_list.append({
                "name": os.path.join(rel_root, d),
                "type": "folder",
                "size": "Folder"
            })
        for f in files:
            file_path = os.path.join(root, f)
            size = os.path.getsize(file_path)
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{round(size/1024, 2)} KB"
            else:
                size_str = f"{round(size/(1024*1024), 2)} MB"
            files_list.append({
                "name": os.path.join(rel_root, f),
                "type": "file",
                "size": size_str,
                "path": file_path
            })
    return sorted(files_list, key=lambda x: (x["type"] == "folder", x["name"]))


def read_text_file(file_path, max_chars=4000):
    allowed_extensions = [".py", ".js", ".json", ".txt", ".env", ".md", ".yaml", ".yml", ".ini", ".cfg"]
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in allowed_extensions:
        return False, "❌ Is file ko preview nahi kar sakte (text file nahi hai)"
    if not os.path.exists(file_path):
        return False, "❌ File nahi mili"
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n... (file bahut bada hai, poora download karo)"
        return True, content
    except Exception as e:
        return False, f"❌ Error: {str(e)}"


def update_bot_settings(bot_id, setting_type, new_value):
    bot_dir = get_bot_dir(bot_id)
    config_files = [f for f in os.listdir(bot_dir) if f.endswith("_config.py") or f == "config.py" or f == "config_template.py"]
    if not config_files:
        return False, "Config file nahi mili"
    config_path = os.path.join(bot_dir, config_files[0])
    try:
        import re
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        if setting_type == "bot_name":
            if "BOT_NAME" in content:
                content = re.sub(r'BOT_NAME\s*=\s*["\'].*?["\']', f'BOT_NAME = "{new_value}"', content)
            else:
                content += f'\nBOT_NAME = "{new_value}"'
        elif setting_type == "creator_name":
            if "DEV_NAME" in content:
                content = re.sub(r'DEV_NAME\s*=\s*["\'].*?["\']', f'DEV_NAME = "{new_value}"', content)
            elif "CREATOR_NAME" in content:
                content = re.sub(r'CREATOR_NAME\s*=\s*["\'].*?["\']', f'CREATOR_NAME = "{new_value}"', content)
            else:
                content += f'\nDEV_NAME = "{new_value}"'
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True, "✅ Settings update ho gaye! Changes ke liye bot restart karo."
    except Exception as e:
        return False, f"❌ Error: {str(e)}"


def set_env_var(bot_id, key, value):
    bot_dir = get_bot_dir(bot_id)
    env_path = os.path.join(bot_dir, ".env")
    try:
        env_vars = {}
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip()
        env_vars[key] = value
        with open(env_path, "w", encoding="utf-8") as f:
            for k, v in env_vars.items():
                f.write(f"{k}={v}\n")
        return True, "✅ Env variable add ho gaya! Bot restart karo changes ke liye."
    except Exception as e:
        return False, f"❌ Error: {str(e)}"


async def get_install_logs(container_id):
    try:
        container = client.containers.get(container_id)
        logs = container.logs(tail=500).decode('utf-8')
        install_lines = [line for line in logs.split("\n") if any(
            word in line.lower() for word in ["install", "download", "requirement", "package", "npm", "pip"]
        )]
        if not install_lines:
            return True, "✅ Sab dependencies pehle se installed hain!"
        return True, "\n".join(install_lines[-100:])
    except Exception as e:
        return False, str(e)
