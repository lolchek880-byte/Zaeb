import asyncio
import logging
import os
from collections import defaultdict

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, BusinessConnection
from groq import AsyncGroq


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MODEL = "openai/gpt-oss-120b"

MAX_HISTORY_MESSAGES = 20

SYSTEM_PROMPT = """
Ты отвечаешь в Telegram от лица человека.

Общайся естественно и неформально.
Пиши коротко и живо, как в обычной переписке.
Не используй канцелярит и лишние вступления.

Не говори, что ты бот или ИИ, если собеседник прямо не спрашивает об этом.
Не придумывай личные факты, планы, встречи или договорённости.
Если информации не хватает — ответь нейтрально и продолжи разговор.

Не пиши слишком длинные сообщения без необходимости.
""".strip()


# =========================================================
# ПРОВЕРКА ПЕРЕМЕННЫХ
# =========================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "Не найдена переменная окружения TG_BOT_TOKEN"
    )

if not GROQ_API_KEY:
    raise RuntimeError(
        "Не найдена переменная окружения GROQ_API_KEY"
    )


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("business_bot")


# =========================================================
# TELEGRAM / GROQ
# =========================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

groq = AsyncGroq(
    api_key=GROQ_API_KEY
)


# =========================================================
# СОСТОЯНИЕ
# =========================================================

afk_enabled = True

# История отдельно для каждого Telegram-чата
history: dict[int, list[dict[str, str]]] = defaultdict(list)

# Запоминаем Business Connection
business_connections: dict[str, BusinessConnection] = {}


# =========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================

def who(message: Message) -> str:
    user = message.from_user

    if not user:
        return "unknown"

    username = (
        f"@{user.username}"
        if user.username
        else "(без username)"
    )

    return f"{username} id={user.id}"


def trim_history(chat_id: int):
    history[chat_id] = history[chat_id][-MAX_HISTORY_MESSAGES:]


# =========================================================
# /START
# =========================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    log.info(
        "CMD /start | %s",
        who(message)
    )

    await message.answer(
        "Привет!\n\n"
        "Подключи этого бота в:\n"
        "Настройки → Telegram Business → Чат-боты\n\n"
        "Команды:\n"
        "/away — включить автоответ\n"
        "/back — выключить автоответ\n"
        "/reset — очистить историю"
    )


# =========================================================
# /AWAY
# =========================================================

@dp.message(Command("away"))
async def cmd_away(message: Message):
    global afk_enabled

    afk_enabled = True

    log.info(
        "AFK ENABLED | %s",
        who(message)
    )

    await message.answer(
        "Автоответчик включён ✅"
    )


# =========================================================
# /BACK
# =========================================================

@dp.message(Command("back"))
async def cmd_back(message: Message):
    global afk_enabled

    afk_enabled = False

    log.info(
        "AFK DISABLED | %s",
        who(message)
    )

    await message.answer(
        "Автоответчик выключен ⛔"
    )


# =========================================================
# /RESET
# =========================================================

@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    history.clear()

    log.info(
        "HISTORY RESET | %s",
        who(message)
    )

    await message.answer(
        "История диалогов очищена."
    )


# =========================================================
# BUSINESS CONNECTION
# =========================================================

@dp.business_connection()
async def handle_business_connection(
    connection: BusinessConnection
):
    business_connections[connection.id] = connection

    user = connection.user

    username = (
        f"@{user.username}"
        if user and user.username
        else str(user.id if user else "?")
    )

    log.info(
        "BUSINESS CONNECTION | "
        "id=%s | "
        "user=%s | "
        "enabled=%s | "
        "can_reply=%s | "
        "rights=%s",
        connection.id,
        username,
        connection.is_enabled,
        connection.can_reply,
        connection.rights,
    )

    # Дополнительно получаем актуальное состояние
    try:
        actual = await bot.get_business_connection(
            business_connection_id=connection.id
        )

        business_connections[actual.id] = actual

        log.info(
            "BUSINESS CONNECTION CHECK | "
            "enabled=%s | can_reply=%s | rights=%s",
            actual.is_enabled,
            actual.can_reply,
            actual.rights,
        )

    except Exception:
        log.exception(
            "Не удалось получить состояние Business Connection"
        )


# =========================================================
# BUSINESS MESSAGE
# =========================================================

@dp.business_message()
async def handle_business_message(message: Message):

    business_connection_id = message.business_connection_id
    chat_id = message.chat.id
    text = (message.text or "").strip()

    log.info(
        "BUSINESS MESSAGE | "
        "chat_id=%s | "
        "connection=%s | "
        "from=%s | "
        "text=%r",
        chat_id,
        business_connection_id,
        who(message),
        text,
    )

    # -----------------------------------------------------
    # Проверка Business Connection ID
    # -----------------------------------------------------

    if not business_connection_id:
        log.error(
            "ОШИБКА: у Business Message отсутствует "
            "business_connection_id"
        )
        return

    # -----------------------------------------------------
    # Только текстовые сообщения
    # -----------------------------------------------------

    if not text:
        log.info(
            "Пропуск: сообщение не содержит текста"
        )
        return

    # -----------------------------------------------------
    # AFK
    # -----------------------------------------------------

    if not afk_enabled:
        log.info(
            "Пропуск: AFK выключен"
        )
        return

    # -----------------------------------------------------
    # Проверяем Business Connection
    # -----------------------------------------------------

    connection = business_connections.get(
        business_connection_id
    )

    if connection is None:
        try:
            connection = await bot.get_business_connection(
                business_connection_id=business_connection_id
            )

            business_connections[
                business_connection_id
            ] = connection

        except Exception:
            log.exception(
                "Не удалось получить Business Connection"
            )
            return

    if not connection.is_enabled:
        log.error(
            "Business Connection выключен"
        )
        return

    if connection.can_reply is False:
        log.error(
            "Business Connection не имеет права отвечать"
        )
        return

    # =====================================================
    # ИСТОРИЯ
    # =====================================================

    chat_history = history[chat_id]

    chat_history.append({
        "role": "user",
        "content": text,
    })

    trim_history(chat_id)

    # =====================================================
    # GROQ
    # =====================================================

    try:
        log.info(
            "GROQ REQUEST | chat_id=%s",
            chat_id
        )

        response = await groq.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                *chat_history,
            ],
            max_tokens=500,
            temperature=0.8,
        )

        reply_text = (
            response.choices[0].message.content or ""
        ).strip()

        if not reply_text:
            log.error(
                "Groq вернул пустой ответ"
            )

            reply_text = (
                "Секунду, сейчас не получилось ответить."
            )

    except Exception:
        log.exception(
            "ОШИБКА GROQ API"
        )

        reply_text = (
            "Секунду, что-то пошло не так. "
            "Попробуй написать ещё раз."
        )

    # =====================================================
    # СОХРАНЯЕМ ОТВЕТ
    # =====================================================

    chat_history.append({
        "role": "assistant",
        "content": reply_text,
    })

    trim_history(chat_id)

    log.info(
        "GROQ RESPONSE | chat_id=%s | text=%r",
        chat_id,
        reply_text,
    )

    # =====================================================
    # ОТПРАВКА ОТ ИМЕНИ BUSINESS-АККАУНТА
    # =====================================================

    try:
        log.info(
            "TELEGRAM SEND | "
            "chat_id=%s | "
            "connection=%s",
            chat_id,
            business_connection_id,
        )

        sent = await bot.send_message(
            chat_id=chat_id,
            text=reply_text,
            business_connection_id=business_connection_id,
        )

        log.info(
            "TELEGRAM SEND OK | "
            "message_id=%s | "
            "chat_id=%s",
            sent.message_id,
            chat_id,
        )

    except Exception:
        log.exception(
            "ОШИБКА ОТПРАВКИ TELEGRAM"
        )


# =========================================================
# ЗАПУСК
# =========================================================

async def main():

    log.info(
        "========================================"
    )

    log.info(
        "Business AI Bot запускается..."
    )

    log.info(
        "Model: %s",
        MODEL
    )

    log.info(
        "AFK: %s",
        afk_enabled
    )

    # Проверяем токен Telegram
    try:
        me = await bot.get_me()

        log.info(
            "Telegram bot: @%s | id=%s",
            me.username,
            me.id,
        )

    except Exception:
        log.exception(
            "Не удалось подключиться к Telegram"
        )
        return

    log.info(
        "Бот успешно запущен."
    )

    log.info(
        "========================================"
    )

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    finally:
        await bot.session.close()


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())
