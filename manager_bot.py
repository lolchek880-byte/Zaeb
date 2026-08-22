import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from groq import AsyncGroq

# ==== НАСТРОЙКИ (берутся из переменных окружения Railway) ====
BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
MODEL = "openai/gpt-oss-120b"  # актуальная флагманская модель Groq

# Опиши здесь свой стиль общения — как ты обычно пишешь, что можно отвечать
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
log = logging.getLogger("manager_bot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = AsyncGroq(api_key=GROQ_API_KEY)

# Состояние АФК-режима на чат: True — бот отвечает, False — молчит
afk_mode: dict[int, bool] = {}
# История переписки по каждому чату
history: dict[int, list[dict]] = {}
MAX_HISTORY_MESSAGES = 20


def who(message: Message) -> str:
    u = message.from_user
    username = f"@{u.username}" if u and u.username else "(без юзернейма)"
    return f"{username} id={u.id if u else '?'} chat_id={message.chat.id}"


@dp.message(CommandStart())
async def cmd_start(message: Message):
    log.info(f"CMD /start от {who(message)}")
    afk_mode[message.chat.id] = False
    await message.answer(
        "Привет! Я включаюсь, когда тебя нет на месте.\n\n"
        "/away — включить автоответчик\n"
        "/back — выключить (буду молчать)\n"
        "/reset — очистить историю диалога"
    )


@dp.message(Command("away"))
async def cmd_away(message: Message):
    afk_mode[message.chat.id] = True
    log.info(f"CMD /away от {who(message)} — АФК включён для chat_id={message.chat.id}")
    await message.answer("Ок, включил автоответ. Отвечаю за тебя, пока ты не вернёшься 👋")


@dp.message(Command("back"))
async def cmd_back(message: Message):
    afk_mode[message.chat.id] = False
    log.info(f"CMD /back от {who(message)} — АФК выключен для chat_id={message.chat.id}")
    await message.answer("Выключил автоответ, дальше сам 🙂")


@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    history[message.chat.id] = []
    log.info(f"CMD /reset от {who(message)}")
    await message.answer("История диалога очищена.")


@dp.message()
async def handle_message(message: Message):
    chat_id = message.chat.id
    text = message.text or ""

    log.info(f"IN  | {who(message)}: {text!r}")

    if not text:
        log.info("    -> пропущено: сообщение без текста (стикер/фото/голос и т.п.)")
        return

    # Отвечаем только если для этого чата включён АФК-режим
    if not afk_mode.get(chat_id, False):
        log.info(f"    -> проигнорировано: АФК выключен для chat_id={chat_id} (нужно /away)")
        return

    chat_history = history.setdefault(chat_id, [])
    chat_history.append({"role": "user", "content": text})
    chat_history[:] = chat_history[-MAX_HISTORY_MESSAGES:]

    await bot.send_chat_action(chat_id, "typing")

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
    await message.answer(reply_text)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
