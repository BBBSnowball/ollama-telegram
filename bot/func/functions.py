import logging
import os
import aiohttp
import json
from aiogram import types
from asyncio import Lock
from functools import wraps
from dotenv import load_dotenv
# --- Environment
load_dotenv()
# --- Environment Checker
token = os.getenv("TOKEN")
allowed_ids = list(map(int, os.getenv("USER_IDS", "").split(",")))
admin_ids = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
no_stream_ids = list(map(int, os.getenv("NO_STREAM_USER_IDS", "").split(",")))
ollama_base_url = os.getenv("OLLAMA_BASE_URL")
ollama_port = os.getenv("OLLAMA_PORT", "11434")
log_level_str = os.getenv("LOG_LEVEL", "INFO")

# --- Other
log_levels = list(logging._levelToName.values())
# ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'NOTSET']

# Set default level to be INFO
if log_level_str not in log_levels:
    log_level = logging.DEBUG
else:
    log_level = logging.getLevelName(log_level_str)

logging.basicConfig(level=log_level)


# Ollama API
# Model List
async def model_list():
    async with aiohttp.ClientSession() as session:
        url = f"http://{ollama_base_url}:{ollama_port}/api/tags"
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data["models"]
            else:
                return []
async def generate(payload: dict, modelname: str, prompt: str):
    # try:
    async with aiohttp.ClientSession() as session:
        logging.info("generate: " + repr(payload))
        url = f"http://{ollama_base_url}:{ollama_port}/api/chat"

        # Stream from API
        async with session.post(url, json=payload) as response:
            async for chunk in response.content:
                if chunk:
                    decoded_chunk = chunk.decode()
                    if decoded_chunk.strip():
                        yield json.loads(decoded_chunk)


# Aiogram functions & wraps
def perms_allowed(func):
    @wraps(func)
    async def wrapper(message: types.Message = None, query: types.CallbackQuery = None):
        user_id = message.from_user.id if message else query.from_user.id
        if user_id in admin_ids or user_id in allowed_ids:
            if message:
                return await func(message)
            elif query:
                return await func(query=query)
        else:
            logging.info("access denied for {query.from_user.full_name} ({query.from_user.id})")
            if message:
                if message and message.chat.type in ["supergroup", "group"]:
                    return
                await message.answer("Access Denied")
            elif query:
                if message and message.chat.type in ["supergroup", "group"]:
                    return
                await query.answer("Access Denied")

    return wrapper


def perms_admins(func):
    @wraps(func)
    async def wrapper(message: types.Message = None, query: types.CallbackQuery = None):
        user_id = message.from_user.id if message else query.from_user.id
        if user_id in admin_ids:
            if message:
                return await func(message)
            elif query:
                return await func(query=query)
        else:
            if message:
                if message and message.chat.type in ["supergroup", "group"]:
                    return
                await message.answer("Access Denied")
                logging.info(
                    f"[MSG] {message.from_user.first_name} {message.from_user.last_name}({message.from_user.id}) is not allowed to use this bot."
                )
            elif query:
                if message and message.chat.type in ["supergroup", "group"]:
                    return
                await query.answer("Access Denied")
                logging.info(
                    f"[QUERY] {message.from_user.first_name} {message.from_user.last_name}({message.from_user.id}) is not allowed to use this bot."
                )

    return wrapper


def md_autofixer(text: str) -> str:
    # In MarkdownV2, these characters must be escaped: _ * [ ] ( ) ~ ` > # + - = | { } . !
    escape_chars = r"_[]()~>#+-=|{}.!"
    # Use a backslash to escape special characters
    return "".join("\\" + char if char in escape_chars else char for char in text)


# Context-Related
class contextLock:
    lock = Lock()

    async def __aenter__(self):
        await self.lock.acquire()

    async def __aexit__(self, exc_type, exc_value, exc_traceback):
        self.lock.release()
