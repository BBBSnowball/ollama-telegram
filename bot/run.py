from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters.command import Command, CommandStart
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from func.functions import *
# Other
import asyncio
import traceback
import io
import base64
import time
bot = Bot(token=token)
dp = Dispatcher()
builder = InlineKeyboardBuilder()
builder.row(
    types.InlineKeyboardButton(text="ℹ️ About", callback_data="info"),
    types.InlineKeyboardButton(text="⚙️ Select Model", callback_data="modelmanager"),
    types.InlineKeyboardButton(text="↺ Reset Chat", callback_data="reset"),
)

commands = [
    types.BotCommand(command="start", description="Start"),
    types.BotCommand(command="reset", description="Reset Chat"),
    types.BotCommand(command="history", description="Look through messages"),
]

# Context variables for OllamaAPI
ACTIVE_CHATS = {}
ACTIVE_CHATS_LOCK = contextLock()
ACTIVE_MODELS = {}
modelname = os.getenv("INITMODEL")
mention = None

# Telegram group types
CHAT_TYPE_GROUP = "group"
CHAT_TYPE_SUPERGROUP = "supergroup"

def is_mentioned_in_group_or_supergroup(message):
    text = message.text or message.caption or ""
    return (message.chat.type in [CHAT_TYPE_GROUP, CHAT_TYPE_SUPERGROUP]
            and text.find(mention) >= 0)

async def get_bot_info():
    global mention
    if mention is None:
        get = await bot.get_me()
        mention = (f"@{get.username}")
    return mention


# /start command
@dp.message(CommandStart())
@perms_allowed
async def command_start_handler(message: Message) -> None:
    start_message = f"Welcome, <b>{message.from_user.full_name}</b>!"
    await message.answer(
        start_message,
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
    )

@dp.callback_query(lambda query: query.data == "start")
@perms_allowed
async def query_start_handler(query: types.CallbackQuery) -> None:
    start_message = f"Welcome, <b>{query.from_user.full_name}</b>!"
    await query.message.edit_text(
        start_message,
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
    )

async def handle_reset(message: Message, from_user, extra_text="") -> None:
    logging.info(f"/reset by user id {from_user.id}")
    if from_user.id in ACTIVE_CHATS:
        async with ACTIVE_CHATS_LOCK:
            ACTIVE_CHATS.pop(from_user.id)
        logging.info(f"Chat has been reset for {from_user.first_name}")
    # always reply even if this was a no-op
    await bot.send_message(
        chat_id=message.chat.id,
        text="Chat has been reset."+extra_text,
    )

# /reset command, wipes context (history)
@dp.message(Command("reset"))
@perms_allowed
async def command_reset_handler(message: Message) -> None:
    await handle_reset(message, message.from_user)

@dp.callback_query(lambda query: query.data == "reset")
@perms_allowed
async def query_reset_handler(query: types.CallbackQuery) -> None:
    await handle_reset(query.message, query.from_user)

# /history command | Displays dialogs between LLM and USER
@dp.message(Command("history"))
@perms_allowed
async def command_get_context_handler(message: Message) -> None:
    if message.from_user.id in ACTIVE_CHATS:
        messages = ACTIVE_CHATS.get(message.chat.id)["messages"]
        context = ""
        for msg in messages:
            context += f"*{msg['role'].capitalize()}*: {msg['content']}\n"
        await bot.send_message(
            chat_id=message.chat.id,
            text=context,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await bot.send_message(
            chat_id=message.chat.id,
            text="No chat history available for this user",
        )


@dp.callback_query(lambda query: query.data == "modelmanager")
async def modelmanager_callback_handler(query: types.CallbackQuery):
    models = await model_list()
    modelmanager_builder = InlineKeyboardBuilder()
    for model in models:
        modelname = model["name"]
        modelfamilies = ""
        if model["details"]["families"]:
            modelicon = {"llama": "🦙", "clip": "📷"}
            try:
                modelfamilies = "".join([modelicon[family] for family in model['details']['families']])
            except KeyError as e:
                # Use a default value when the key is not found
                modelfamilies = f"✨"
        # Add a button for each model
        modelmanager_builder.row(
            types.InlineKeyboardButton(
                text=f"{modelname} {modelfamilies}", callback_data=f"model_{modelname}"
            )
        )
    modelmanager_builder.row(
        types.InlineKeyboardButton(
            text=f"↺ reset chat", callback_data=f"reset"
        )
    )
    modelmanager_builder.row(
        types.InlineKeyboardButton(
            text=f"← back", callback_data=f"start"
        )
    )
    await query.message.edit_text(
        f"{len(models)} models available.\n🦙 = Regular\n🦙📷 = Multimodal", reply_markup=modelmanager_builder.as_markup()
    )


@dp.callback_query(lambda query: query.data.startswith("model_"))
async def model_callback_handler(query: types.CallbackQuery):
    global ACTIVE_MODELS
    global ACTIVE_CHATS_LOCK
    modelname = query.data.split("model_")[1]
    async with ACTIVE_CHATS_LOCK:
        ACTIVE_MODELS[query.from_user.id] = modelname
    await query.answer(f"Chosen model: {modelname}")
    # reset chat so new model will be used
    await handle_reset(query.message, query.from_user, extra_text=f" Model is {modelname}.")


@dp.callback_query(lambda query: query.data == "info")
#@perms_admins
@perms_allowed
async def info_callback_handler(query: types.CallbackQuery):
    dotenv_model = os.getenv("INITMODEL")
    await bot.send_message(
        chat_id=query.message.chat.id,
        text=f"<b>About Models</b>\nCurrent model: <code>{ACTIVE_MODELS.get(query.from_user.id, modelname)}</code>\nDefault model: <code>{dotenv_model}</code>\nThis project is under <a href='https://github.com/ruecat/ollama-telegram/blob/main/LICENSE'>MIT License.</a>\n<a href='https://github.com/ruecat/ollama-telegram'>Source Code</a>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

class Updater(object):
    def __init__(self, bot, chat_id, reply_to_message_id):
        self.bot = bot
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id
        self.sent_message = None
        self.last_sent_text = None
        self.last_update_time = 0

    async def update(self, text, done, try_markdown=False):
        kwargs = {
            "chat_id": self.chat_id,
            "text": text,
        }
        if try_markdown:
            kwargs["parse_mode"] = ParseMode.MARKDOWN_V2

        try:
            if not self.sent_message:
                self.sent_message = await bot.send_message(
                    reply_to_message_id=self.reply_to_message_id,
                    disable_notification=not done,
                    **kwargs
                )
            elif text == self.last_sent_text:
                return
            elif not done and (time.time() - self.last_update_time < 3 or (len(text) > 500 and time.time() - self.last_update_time < 10)):
                # hold off to avoid rate limiting
                # https://telegra.ph/So-your-bot-is-rate-limited-01-26
                logging.info("skip update because last one was %.1f sec ago" % (time.time() - self.last_update_time))
                return
            else:
                await bot.edit_message_text(
                    message_id=self.sent_message.message_id,
                    **kwargs
                )
            self.last_sent_text = text
            self.last_update_time = time.time()
        except TelegramRetryAfter as e:
            #FIXME Do something more useful for done=True.
            self.last_update_time = time.time() + e.retry_after
        except TelegramBadRequest as e:
            if try_markdown:
                # try as plain text
                return self.update(text, done, try_markdown=False)
            else:
                raise

# React on message | LLM will respond on user's message or mention in groups
@dp.message()
@perms_allowed
async def handle_message(message: types.Message):
    await get_bot_info()
    if message.chat.type == "private":
        await ollama_request(message)
    elif is_mentioned_in_group_or_supergroup(message):
        await ollama_request(message, remove_mention=mention)

...
async def ollama_request(message: types.Message, remove_mention=None):
    try:
        await bot.send_chat_action(message.chat.id, "typing")
        prompt = message.text or message.caption
        if remove_mention:
            prompt = prompt.replace(remove_mention, "").strip()
        image_base64 = ''
        if message.content_type == 'photo':
            image_buffer = io.BytesIO()
            await bot.download(
                message.photo[-1],
                destination=image_buffer
            )
            image_base64 = base64.b64encode(image_buffer.getvalue()).decode('utf-8')
        full_response = ""
        updater = Updater(bot, chat_id=message.chat.id, reply_to_message_id=message.message_id)
        sent_message = None
        last_sent_text = None

        async with ACTIVE_CHATS_LOCK:
            # Add prompt to active chats object
            if ACTIVE_CHATS.get(message.from_user.id) is None:
                ACTIVE_CHATS[message.from_user.id] = {
                    "model": ACTIVE_MODELS.get(message.from_user.id, modelname),
                    "messages": [{"role": "user", "content": prompt, "images": ([image_base64] if image_base64 else [])}],
                    "stream": True,
                }
            else:
                ACTIVE_CHATS[message.from_user.id]["messages"].append(
                    {"role": "user", "content": prompt, "images": ([image_base64] if image_base64 else [])}
                )
        logging.info(
            f"[Request]: Processing '{prompt}' for {message.from_user.first_name} {message.from_user.last_name} ({message.from_user.id})"
        )
        payload = ACTIVE_CHATS.get(message.from_user.id)
        async for response_data in generate(payload, prompt):
            msg = response_data.get("message")
            if msg is None:
                logging.info("no msg")
                continue
            chunk = msg.get("content", "")
            full_response += chunk
            full_response_stripped = full_response.strip()

            # avoid Bad Request: message text is empty
            if full_response_stripped == "":
                continue

            if ("." in chunk or "\n" in chunk or "!" in chunk or "?" in chunk or "," in chunk) and len(full_response_stripped) >= 30:
                if message.from_user.id in no_stream_ids:
                    # user prefers no streaming
                    pass
                else:
                    await updater.update(full_response_stripped, done=False)

            if response_data.get("done"):
                end_text = f"Current Model: `{payload['model']}`**\n**Generated in {response_data.get('total_duration') / 1e9:.2f}s"
                if updater.sent_message:
                    # update existing message with final text
                    await updater.update(text=md_autofixer(full_response_stripped),
                        done=True,
                        try_markdown=True)

                    # send end text as seperate message with notification
                    await bot.send_message(
                        chat_id=message.chat.id,
                        reply_to_message_id=message.message_id,
                        text=md_autofixer(end_text),
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )
                else:
                    # send message with notification
                    await updater.update(text=md_autofixer(full_response_stripped + "\n\n" + end_text),
                        done=True,
                        try_markdown=True)

                async with ACTIVE_CHATS_LOCK:
                    if ACTIVE_CHATS.get(message.from_user.id) is not None:
                        # Add response to active chats object
                        ACTIVE_CHATS[message.from_user.id]["messages"].append(
                            {"role": "assistant", "content": full_response_stripped}
                        )
                        logging.info(
                            f"[Response]: '{full_response_stripped}' for {message.from_user.first_name} {message.from_user.last_name}"
                        )
                    else:
                        await bot.send_message(
                            chat_id=message.chat.id, text="Chat was reset"
                        )

                break
    except Exception as e:
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"""Error occurred\n```\n{traceback.format_exc()}\n```""",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


async def main():
    await bot.set_my_commands(commands)
    await dp.start_polling(bot, skip_update=True)


if __name__ == "__main__":
    asyncio.run(main())
