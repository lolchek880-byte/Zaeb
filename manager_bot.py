import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from groq import AsyncGroq

# ==== НАСТРОЙКИ (переменные окружения Railway) ====
BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
MODEL = "openai/gpt-oss-120b"

# Опиши здесь свой стиль общения
SYSTEM_PROMPT = """
Ты отвечаешь в Telegram от лица человека, который сейчас не может ответить сам (АФК).
Пиши коротко, дружелюбно и в его обычном стиле — простыми словами, без канцелярита.
Если тебя спрашивают о чём-то, чего ты не знаешь (планы, договорённости, личные детали) —
не выдумывай, а честно скажи, что человек скоро ответит сам, когда будет на месте.
""".strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("business_bot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = AsyncGroq(api_key=GROQ_API_KEY)

# АФК-режим по умолчанию включён
afk_enabled = True
# История переписки по каждому диалогу (ключ — chat_id собеседника)
history: dict[int, list[dict]] = {}
MAX_HISTORY_MESSAGES = 20


def who(message: Message) -> str:
    u = message.from_user
    username = f"@{u.username}" if u and u.username else "(без юзернейма)"
    return f"{username} id={u.id if u else '?'}"


# ==== Обычные сообщения БОТУ напрямую — используем для управления режимом ====

@dp.message(CommandStart())
async def cmd_start(message: Message):
    log.info(f"CMD /start от {who(message)}")
    await message.answer(
        "Привет! Подключи меня в Настройки → Telegram Business → Чат-боты,\n"
        "и я буду отвечать в твоих личных чатах, пока тебя нет на месте.\n\n"
        "Управление (пиши мне сюда, в этот чат с ботом):\n"
        "/away — включить автоответ\n"
        "/back — выключить автоответ\n"
        "/reset — очистить историю диалогов"
    )


@dp.message(Command("away"))
async def cmd_away(message: Message):
    global afk_enabled
    afk_enabled = True
    log.info(f"АФК включён — команда от {who(message)}")
    await message.answer("Автоответчик включён ✅")


@dp.message(Command("back"))
async def cmd_back(message: Message):
    global afk_enabled
    afk_enabled = False
    log.info(f"АФК выключен — команда от {who(message)}")
    await message.answer("Автоответчик выключен ⛔")


@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    history.clear()
    log.info(f"История очищена — команда от {who(message)}")
    await message.answer("История диалогов очищена")


# ==== Сообщения в ЛИЧНЫХ ЧАТАХ через Business Mode ====

@dp.business_message()
async def handle_business_message(message: Message):
    business_connection_id = message.business_connection_id
    chat_id = message.chat.id
    text = message.text or ""

    log.info(f"IN  | {who(message)} (business chat_id={chat_id}): {text!r}")

    if not text:
        log.info("    -> пропущено: сообщение без текста")
        return

    if not afk_enabled:
        log.info("    -> проигнорировано: АФК выключен (напиши боту /away)")
        return

    chat_history = history.setdefault(chat_id, [])
    chat_history.append({"role": "user", "content": text})
    chat_history[:] = chat_history[-MAX_HISTORY_MESSAGES:]

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            max_tokens=1000,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *chat_history],
        )
        reply_text = (response.choices[0].message.content or "").strip()
    except Exception:
        log.exception("Ошибка при запросе к Groq API")
        reply_text = "Секунду, что-то пошло не так технически — напишу позже."

    chat_history.append({"role": "assistant", "content": reply_text})
    log.info(f"OUT | -> chat_id={chat_id}: {reply_text!r}")

    # Отправляем от имени бизнес-аккаунта — обязательно с business_connection_id
    await bot.send_message(
        chat_id=chat_id,
        text=reply_text,
        business_connection_id=business_connection_id,
    )


async def main():
    log.info("Бот запущен, ждём подключения Business Mode и личных сообщений...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
