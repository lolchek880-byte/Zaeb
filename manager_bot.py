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
# =========================================================

MANAGER_VERSION = "0.1.3 BETA"


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MODEL = "openai/gpt-oss-120b"

MAX_HISTORY_MESSAGES = 30

# Максимальное количество запомненных message_id
MAX_PROCESSED_MESSAGES = 10000


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
Ты ведёшь личную переписку в Telegram.

Твоя задача — поддерживать естественный, живой разговор.
Не отвечай как ассистент, консультант или справочник.

СТИЛЬ:
- Пиши естественно, как человек в обычном Telegram-чате.
- Не используй одинаковую структуру ответов.
- Не начинай постоянно с одинаковых слов.
- Не заканчивай каждый ответ вопросом.
- Иногда отвечай одной короткой фразой.
- Иногда используй 2–3 коротких предложения.
- Если уместно, шути, реагируй эмоционально или слегка подшучивай.
- Подстраивай длину ответа под сообщение собеседника.
- На короткое сообщение обычно отвечай коротко.
- На подробное сообщение можешь ответить подробнее.
- Не используй канцелярит.
- Не превращай обычную переписку в лекцию.

РАЗВИТИЕ ДИАЛОГА:
- Всегда учитывай последнее сообщение.
- Учитывай предыдущую переписку.
- Не задавай вопрос, на который уже был дан ответ.
- Не повторяй один и тот же вопрос другими словами.
- Не повторяй одну и ту же мысль.
- Не возвращайся к старой теме без причины.
- Если тема закончилась, можешь естественно сменить её.
- Иногда просто реагируй без вопроса.
- Не пытайся поддерживать разговор только вопросами.
- Если человек рассказывает историю, сначала реагируй на неё.
- Используй детали из предыдущих сообщений, когда это действительно уместно.

ЕСТЕСТВЕННОСТЬ:
- Не используй шаблонные фразы в каждом сообщении.
- Не начинай каждый ответ со слов "интересно", "понятно", "прикольно" и т.п.
- Не заканчивай каждый ответ словами "а ты?".
- Не задавай вопрос только ради продолжения диалога.
- Не используй одинаковые фразы несколько сообщений подряд.
- Не злоупотребляй эмодзи.
- Не ставь эмодзи в каждом сообщении.
- Разговорный стиль допустим.
- Не используй списки, если обычный текст подходит лучше.

ЛОГИКА:
- Сначала реагируй на конкретное сообщение человека.
- Затем учитывай контекст.
- Не придумывай факты о человеке.
- Не выдумывай встречи, события, планы или личную информацию.
- Если информации нет, не утверждай её как факт.
- Не повторяй пользователю его собственные слова без причины.

ГЛАВНОЕ:
Каждый ответ должен ощущаться как продолжение конкретной живой переписки,
а не как заранее подготовленный шаблон.

Форма ответа должна меняться от сообщения к сообщению.
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

# ---------------------------------------------------------
# ЗАЩИТА ОТ ДВОЙНОЙ ОБРАБОТКИ
# ---------------------------------------------------------
#
# Здесь храним:
# (business_connection_id, message_id)
#
# Если Telegram повторно передаст тот же message_id,
# бот второй раз отвечать не будет.
#

processed_messages: set[tuple[str, int]] = set()


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

    history[chat_id] = history[chat_id][
        -MAX_HISTORY_MESSAGES:
    ]


def check_duplicate_message(
    business_connection_id: str | None,
    message_id: int | None,
) -> bool:

    """
    Возвращает True, если сообщение уже обрабатывалось.
    """

    if not business_connection_id:
        return False

    if not message_id:
        return False

    message_key = (
        business_connection_id,
        message_id,
    )

    if message_key in processed_messages:

        log.warning(
            "DUPLICATE MESSAGE SKIPPED | "
            "connection=%s | message_id=%s",
            business_connection_id,
            message_id,
        )

        return True

    processed_messages.add(
        message_key
    )

    # Защита от бесконечного роста памяти
    if len(processed_messages) > MAX_PROCESSED_MESSAGES:

        log.info(
            "Очищаем список обработанных сообщений"
        )

        processed_messages.clear()

        # Сразу добавляем текущее сообщение обратно
        processed_messages.add(
            message_key
        )

    return False


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):

    log.info(
        "CMD /start | %s",
        who(message)
    )

    status = (
        "автоответ включён ✅"
        if afk_enabled
        else "автоответ выключен ⛔"
    )

    await message.answer(
        f"🍀 Manager {MANAGER_VERSION}\n\n"
        "Я подключён к Telegram Business.\n\n"
        "Команды:\n"
        "/away — включить автоответ\n"
        "/back — выключить автоответ\n"
        "/reset — очистить историю диалогов\n\n"
        f"Статус: {status}"
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

    business_connections[
        connection.id
    ] = connection

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

        business_connections[
            actual.id
        ] = actual

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

    business_connection_id = (
        message.business_connection_id
    )

    chat_id = message.chat.id

    message_id = message.message_id

    text = (
        message.text or ""
    ).strip()

    # =====================================================
    # ЗАЩИТА ОТ ДВОЙНОГО ОТВЕТА
    # =====================================================

    if check_duplicate_message(
        business_connection_id,
        message_id,
    ):

        return

    # =====================================================
    # LOG
    # =====================================================

    log.info(
        "BUSINESS MESSAGE | "
        "chat_id=%s | "
        "message_id=%s | "
        "connection=%s | "
        "from=%s | "
        "text=%r",
        chat_id,
        message_id,
        business_connection_id,
        who(message),
        text,
    )

    # =====================================================
    # ПРОВЕРКА BUSINESS CONNECTION ID
    # =====================================================

    if not business_connection_id:

        log.error(
            "Business Message без business_connection_id"
        )

        return

    # =====================================================
    # ТОЛЬКО ТЕКСТОВЫЕ СООБЩЕНИЯ
    # =====================================================

    if not text:

        log.info(
            "Пропуск: сообщение без текста"
        )

        return

    # =====================================================
    # AFK
    # =====================================================

    if not afk_enabled:

        log.info(
            "Пропуск: AFK выключен"
        )

        return

    # =====================================================
    # BUSINESS CONNECTION
    # =====================================================

    connection = (
        business_connections.get(
            business_connection_id
        )
    )

    if connection is None:

        try:

            connection = (
                await bot.get_business_connection(
                    business_connection_id=(
                        business_connection_id
                    )
                )
            )

            business_connections[
                business_connection_id
            ] = connection

        except Exception:

            log.exception(
                "Не удалось получить Business Connection"
            )

            return

    # =====================================================
    # ПРОВЕРКА CONNECTION
    # =====================================================

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

    # =====================================================
    # НЕ ОТВЕЧАЕМ ВЛАДЕЛЬЦУ BUSINESS-АККАУНТА
    # =====================================================

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
    # ВАРИАТИВНОСТЬ
    # =====================================================

    variation_instruction = random.choice([

        (
            "Ответь естественно и коротко. "
            "Не заканчивай ответ вопросом без необходимости."
        ),

        (
            "Сконцентрируйся на последнем сообщении. "
            "Не повторяй предыдущие формулировки."
        ),

        (
            "Ответь как в обычном живом чате. "
            "Можно просто отреагировать без вопроса."
        ),

        (
            "Не используй шаблонный ответ. "
            "Сформируй реакцию именно на это сообщение."
        ),

        (
            "Не повторяй уже использованные вопросы "
            "или фразы."
        ),

        (
            "Сделай ответ естественным "
            "и немного непредсказуемым по форме."
        ),

        (
            "Если вопрос не нужен для продолжения разговора — "
            "не задавай его."
        ),

        (
            "Сначала отреагируй на смысл сообщения, "
            "а уже потом решай, нужен ли вопрос."
        ),

    ])

    # =====================================================
    # GROQ
    # =====================================================

    try:

        log.info(
            "GROQ REQUEST | "
            "chat_id=%s | "
            "message_id=%s | "
            "model=%s",
            chat_id,
            message_id,
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

        response = (
            await groq.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=400,
                temperature=1.0,
            )
        )

        reply_text = (
            response.choices[0]
            .message
            .content or ""
        ).strip()

        if not reply_text:

            log.error(
                "Groq вернул пустой ответ"
            )

            reply_text = (
                "Секунду, что-то зависло 😅"
            )

    except Exception as error:

        log.exception(
            "ОШИБКА GROQ API: %s",
            error,
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
        "message_id=%s | "
        "text=%r",
        chat_id,
        message_id,
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
            business_connection_id=(
                business_connection_id
            ),
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

    # =====================================================
    # ПРОВЕРКА TELEGRAM
    # =====================================================

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
            allowed_updates=(
                dp.resolve_used_update_types()
            ),
        )

    finally:

        await bot.session.close()


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    asyncio.run(main())
