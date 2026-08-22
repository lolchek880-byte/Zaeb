import asyncio
import logging
import os
import random
from collections import defaultdict

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, BusinessConnection
from groq import AsyncGroq


# =========================================================
# MANAGER VERSION
# При обновлении меняй только это значение
# =========================================================

MANAGER_VERSION = "0.1.0"


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# GPT-OSS 120B — мощная модель Groq
MODEL = "openai/gpt-oss-120b"

MAX_HISTORY_MESSAGES = 30


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
Ты ведёшь личную переписку в Telegram.

Твоя главная задача — поддерживать естественный, живой разговор.
Не отвечай как ассистент, консультант или справочник.

СТИЛЬ:
- Пиши естественно, как человек в обычном Telegram-чате.
- Не делай каждый ответ одинаковой структуры.
- Не начинай постоянно с одинаковых слов.
- Не заканчивай каждый ответ вопросом.
- Иногда отвечай одной короткой фразой.
- Иногда используй 2–3 коротких предложения.
- Если уместно, можешь пошутить, отреагировать эмоционально или слегка подколоть собеседника.
- Не превращай обычный разговор в длинное объяснение.
- Подстраивай длину ответа под длину сообщения собеседника.
- Если человек пишет коротко — обычно отвечай коротко.
- Если человек подробно рассказывает что-то — можешь ответить подробнее.

РАЗВИТИЕ ДИАЛОГА:
- Следи за тем, что уже обсуждалось.
- Не задавай вопрос, на который собеседник уже отвечал.
- Не повторяй один и тот же вопрос другими словами.
- Не возвращайся без причины к старой теме.
- Если тема закончилась, можешь естественно предложить новую.
- Иногда просто реагируй на сообщение без вопроса.
- Не пытайся постоянно поддерживать разговор вопросами.
- Если собеседник рассказывает историю, сначала реагируй на неё, а не сразу задавай новый вопрос.
- Используй детали из предыдущих сообщений, когда это действительно уместно.

ЕСТЕСТВЕННОСТЬ:
- Не используй шаблонные фразы вроде:
  "Интересно!"
  "Расскажи подробнее"
  "А что ты думаешь?"
  в каждом ответе.
- Не повторяй одну и ту же мысль.
- Не используй одинаковые конструкции несколько сообщений подряд.
- Не пиши слишком правильным или официальным языком.
- Допускается разговорный стиль.
- Не злоупотребляй эмодзи.
- Не ставь эмодзи в каждый ответ.
- Не используй списки, если обычный текст подходит лучше.

ЛОГИКА:
- Сначала учитывай последнее сообщение.
- Затем учитывай контекст предыдущей переписки.
- Не придумывай факты о человеке.
- Не выдумывай встречи, события, планы, знакомства или личную информацию.
- Если конкретной информации нет, не утверждай её как факт.
- Не повторяй пользователю то, что он только что сказал, без причины.

ВАЖНО:
Твои ответы должны ощущаться как продолжение реальной переписки,
а не как последовательность заранее подготовленных ответов.

Каждый новый ответ должен быть сформирован с учётом конкретного сообщения
и текущего контекста разговора.
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

log = logging.getLogger("business_manager")


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

history: dict[int, list[dict[str, str]]] = defaultdict(list)

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
# START
# =========================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):

    log.info(
        "CMD /start | %s",
        who(message)
    )

    await message.answer(
        f"🍀 Manager {MANAGER_VERSION}\n\n"
        "Я подключён к Telegram Business.\n\n"
        "Команды:\n"
        "/away — включить автоответ\n"
        "/back — выключить автоответ\n"
        "/reset — очистить историю диалогов\n\n"
        "Статус: "
        + ("автоответ включён ✅" if afk_enabled else "автоответ выключен ⛔")
    )


# =========================================================
# AWAY
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
        f"Manager {MANAGER_VERSION}: автоответ включён ✅"
    )


# =========================================================
# BACK
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
        f"Manager {MANAGER_VERSION}: автоответ выключен ⛔"
    )


# =========================================================
# RESET
# =========================================================

@dp.message(Command("reset"))
async def cmd_reset(message: Message):

    history.clear()

    log.info(
        "HISTORY RESET | %s",
        who(message)
    )

    await message.answer(
        "История всех диалогов очищена."
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

    try:

        actual = await bot.get_business_connection(
            business_connection_id=connection.id
        )

        business_connections[actual.id] = actual

        log.info(
            "BUSINESS CONNECTION CHECK | "
            "enabled=%s | "
            "can_reply=%s | "
            "rights=%s",
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
    # Проверка connection
    # -----------------------------------------------------

    if not business_connection_id:

        log.error(
            "Business Message без business_connection_id"
        )

        return

    # -----------------------------------------------------
    # Только текст
    # -----------------------------------------------------

    if not text:

        log.info(
            "Пропуск: нет текста"
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
    # Business Connection
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
            "У Business Connection нет права отвечать"
        )

        return

    # -----------------------------------------------------
    # Не отвечаем владельцу аккаунта
    # -----------------------------------------------------

    owner_id = (
        connection.user.id
        if connection.user
        else None
    )

    if (
        message.from_user
        and owner_id
        and message.from_user.id == owner_id
    ):

        log.info(
            "Пропуск: сообщение владельца аккаунта"
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
    # ДОПОЛНИТЕЛЬНАЯ ИНСТРУКЦИЯ ДЛЯ ВАРИАТИВНОСТИ
    # =====================================================

    variation_instruction = random.choice([
        "Ответь естественно и коротко. Не заканчивай ответ вопросом без необходимости.",
        "Сконцентрируйся на последнем сообщении. Не повторяй предыдущие формулировки.",
        "Ответь так, как продолжился бы обычный живой чат. Можно просто отреагировать без вопроса.",
        "Не используй шаблонный ответ. Выбери естественную реакцию именно на это сообщение.",
        "Не повторяй уже использованные вопросы или фразы. Развивай разговор только если это уместно.",
        "Сделай ответ немного непредсказуемым по форме, но естественным по смыслу.",
    ])

    # =====================================================
    # GROQ
    # =====================================================

    try:

        log.info(
            "GROQ REQUEST | chat_id=%s | model=%s",
            chat_id,
            MODEL,
        )

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            *chat_history,
            {
                "role": "system",
                "content": variation_instruction,
            },
        ]

        response = await groq.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=400,
            temperature=1.0,
            reasoning_effort="low",
        )

        reply_text = (
            response.choices[0].message.content or ""
        ).strip()

        if not reply_text:

            log.error(
                "Groq вернул пустой ответ"
            )

            reply_text = (
                "Секунду, что-то зависло 😅"
            )

    except Exception:

        log.exception(
            "ОШИБКА GROQ API"
        )

        reply_text = (
            "Секунду, что-то пошло не так 😅"
        )

    # =====================================================
    # СОХРАНЕНИЕ ОТВЕТА
    # =====================================================

    chat_history.append({
        "role": "assistant",
        "content": reply_text,
    })

    trim_history(chat_id)

    log.info(
        "GROQ RESPONSE | "
        "chat_id=%s | "
        "text=%r",
        chat_id,
        reply_text,
    )

    # =====================================================
    # ОТПРАВКА
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
        "MANAGER %s STARTING",
        MANAGER_VERSION,
    )

    log.info(
        "MODEL: %s",
        MODEL,
    )

    log.info(
        "AFK: %s",
        afk_enabled,
    )

    # -----------------------------------------------------
    # Проверка Telegram
    # -----------------------------------------------------

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
        "Manager %s успешно запущен.",
        MANAGER_VERSION,
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
