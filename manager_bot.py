import asyncio
import logging
import os
import random
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    BusinessConnection,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from groq import AsyncGroq


# =========================================================
# MANAGER VERSION
# =========================================================

MANAGER_VERSION = "0.2.2"


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Например:
# REQUIRED_CHANNEL=@my_channel
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL")

MODEL = "openai/gpt-oss-120b"

MAX_HISTORY_MESSAGES = 30


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

if not REQUIRED_CHANNEL:
    raise RuntimeError(
        "Не найдена переменная окружения REQUIRED_CHANNEL"
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
# ВРЕМЯ МОСКВЫ
# =========================================================

def get_moscow_time() -> str:
    now = datetime.now(
        ZoneInfo("Europe/Moscow")
    )

    return now.strftime(
        "%d.%m.%Y %H:%M:%S"
    )


# =========================================================
# WHO
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


# =========================================================
# HISTORY
# =========================================================

def trim_history(chat_id: int):
    history[chat_id] = history[chat_id][
        -MAX_HISTORY_MESSAGES:
    ]


# =========================================================
# ПРОВЕРКА ПОДПИСКИ
# =========================================================

async def is_subscribed(user_id: int) -> bool:

    try:

        member = await bot.get_chat_member(
            chat_id=REQUIRED_CHANNEL,
            user_id=user_id,
        )

        if member.status in (
            "creator",
            "administrator",
            "member",
        ):
            return True

        if member.status == "restricted":
            return bool(
                getattr(
                    member,
                    "is_member",
                    False,
                )
            )

        return False

    except Exception:

        log.exception(
            "Ошибка проверки подписки | user_id=%s",
            user_id,
        )

        return False


# =========================================================
# КЛАВИАТУРА ПОДПИСКИ
# =========================================================

def subscription_keyboard() -> InlineKeyboardMarkup:

    channel_url = (
        f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Подписаться",
                    url=channel_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Проверить подписку",
                    callback_data="check_subscription",
                )
            ],
        ]
    )


# =========================================================
# СООБЩЕНИЕ О ПОДПИСКЕ
# =========================================================

async def send_subscription_required(
    message: Message,
):

    await message.answer(
        "🔒 <b>Доступ ограничен</b>\n\n"
        "Чтобы пользоваться Manager, необходимо "
        "подписаться на наш Telegram-канал.\n\n"
        "1. Нажми «📢 Подписаться».\n"
        "2. Подпишись на канал.\n"
        "3. Вернись сюда и нажми "
        "«✅ Проверить подписку».",
        reply_markup=subscription_keyboard(),
        parse_mode="HTML",
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):

    log.info(
        "CMD /start | %s",
        who(message),
    )

    user = message.from_user

    if not user:

        await message.answer(
            "Не удалось определить пользователя."
        )

        return

    subscribed = await is_subscribed(
        user.id
    )

    connected_count = len(
        business_connections
    )

    enabled_connections = sum(
        1
        for connection in business_connections.values()
        if connection.is_enabled
    )

    if subscribed:

        subscription_status = (
            "Подписка: ✅ подтверждена"
        )

    else:

        subscription_status = (
            "Подписка: ❌ не подтверждена"
        )

    if enabled_connections > 0:

        business_status = (
            "Business Mode: 🟢 подключён"
        )

    else:

        business_status = (
            "Business Mode: 🔴 не подключён"
        )

    await message.answer(
        f"🍀 <b>Manager {MANAGER_VERSION}</b>\n\n"
        "AI-менеджер для Telegram Business.\n\n"
        "━━━━━━━━━━━━━━\n"
        f"{subscription_status}\n"
        f"{business_status}\n"
        f"Подключений: {connected_count}\n"
        "━━━━━━━━━━━━━━\n\n"
        "<b>Как начать:</b>\n"
        "1️⃣ Подпишись на канал.\n"
        "2️⃣ Подключи Manager в "
        "Настройки → Telegram Business → Чат-боты.\n"
        "3️⃣ Разреши боту отвечать на сообщения.\n"
        "4️⃣ После этого Manager сможет автоматически "
        "отвечать в твоих Business-чатах.\n\n"
        "<b>Команды:</b>\n"
        "/away — включить автоответ\n"
        "/back — выключить автоответ\n"
        "/reset — очистить историю диалогов\n\n"
        f"🕐 МСК: <code>{get_moscow_time()}</code>",
        parse_mode="HTML",
        reply_markup=(
            None
            if subscribed
            else subscription_keyboard()
        ),
    )


# =========================================================
# ПРОВЕРКА ПОДПИСКИ КНОПКОЙ
# =========================================================

@dp.callback_query(
    lambda callback: callback.data == "check_subscription"
)
async def check_subscription(callback):

    user = callback.from_user

    if not user:

        await callback.answer(
            "Не удалось определить пользователя.",
            show_alert=True,
        )

        return

    subscribed = await is_subscribed(
        user.id
    )

    if subscribed:

        await callback.answer(
            "Подписка подтверждена! ✅",
            show_alert=True,
        )

        if callback.message:

            try:

                await callback.message.edit_text(
                    f"✅ <b>Подписка подтверждена!</b>\n\n"
                    f"🍀 Manager {MANAGER_VERSION}\n\n"
                    "Теперь Manager доступен.\n\n"
                    "Подключи его в:\n"
                    "Настройки → Telegram Business → Чат-боты",
                    parse_mode="HTML",
                )

            except Exception:

                log.exception(
                    "Не удалось изменить сообщение проверки подписки"
                )

    else:

        await callback.answer(
            "Подписка не найдена. Сначала подпишись на канал.",
            show_alert=True,
        )


# =========================================================
# AWAY
# =========================================================

@dp.message(Command("away"))
async def cmd_away(message: Message):

    global afk_enabled

    user = message.from_user

    if not user:
        return

    if not await is_subscribed(
        user.id
    ):

        await send_subscription_required(
            message
        )

        return

    afk_enabled = True

    log.info(
        "AFK ENABLED | %s",
        who(message),
    )

    await message.answer(
        f"🍀 Manager {MANAGER_VERSION}\n"
        "Автоответчик включён ✅"
    )


# =========================================================
# BACK
# =========================================================

@dp.message(Command("back"))
async def cmd_back(message: Message):

    global afk_enabled

    user = message.from_user

    if not user:
        return

    if not await is_subscribed(
        user.id
    ):

        await send_subscription_required(
            message
        )

        return

    afk_enabled = False

    log.info(
        "AFK DISABLED | %s",
        who(message),
    )

    await message.answer(
        f"🍀 Manager {MANAGER_VERSION}\n"
        "Автоответчик выключен ⛔"
    )


# =========================================================
# RESET
# =========================================================

@dp.message(Command("reset"))
async def cmd_reset(message: Message):

    user = message.from_user

    if not user:
        return

    if not await is_subscribed(
        user.id
    ):

        await send_subscription_required(
            message
        )

        return

    history.clear()

    log.info(
        "HISTORY RESET | %s",
        who(message),
    )

    await message.answer(
        "История всех диалогов очищена. 🧹"
    )


# =========================================================
# BUSINESS CONNECTION
# =========================================================

@dp.business_connection()
async def handle_business_connection(
    connection: BusinessConnection,
):

    business_connections[
        connection.id
    ] = connection

    user = connection.user

    username = (
        f"@{user.username}"
        if user and user.username
        else str(
            user.id
            if user
            else "?"
        )
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
async def handle_business_message(
    message: Message,
):

    business_connection_id = (
        message.business_connection_id
    )

    chat_id = message.chat.id

    text = (
        message.text or ""
    ).strip()

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
    # CONNECTION
    # -----------------------------------------------------

    if not business_connection_id:

        log.error(
            "Business Message без business_connection_id"
        )

        return

    # -----------------------------------------------------
    # ТОЛЬКО ТЕКСТ
    # -----------------------------------------------------

    if not text:

        log.info(
            "Пропуск: сообщение без текста"
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
    # BUSINESS CONNECTION
    # -----------------------------------------------------

    connection = business_connections.get(
        business_connection_id
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
    # ВЛАДЕЛЕЦ АККАУНТА
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
    # ВАЖНО:
    # ЗДЕСЬ НЕТ ПРОВЕРКИ ПОДПИСКИ.
    #
    # Business-чаты работают независимо от подписки.
    # =====================================================

    # =====================================================
    # HISTORY
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
        "Ответь естественно и коротко. Не заканчивай ответ вопросом без необходимости.",
        "Сконцентрируйся на последнем сообщении. Не повторяй предыдущие формулировки.",
        "Ответь как в обычном живом чате. Можно просто отреагировать без вопроса.",
        "Не используй шаблонный ответ. Сформируй реакцию именно на это сообщение.",
        "Не повторяй уже использованные вопросы или фразы.",
        "Сделай ответ естественным и немного непредсказуемым по форме.",
        "Если вопрос не нужен для продолжения разговора — не задавай его.",
        "Сначала отреагируй на смысл сообщения, а уже потом решай, нужен ли вопрос.",
    ])

    # =====================================================
    # АКТУАЛЬНОЕ ВРЕМЯ МОСКВЫ
    # =====================================================

    moscow_time = get_moscow_time()

    time_context = (
        f"Текущее время по Москве (МСК, UTC+3): "
        f"{moscow_time}.\n"
        "Если собеседник спрашивает текущее время, "
        "ориентируйся именно на это значение. "
        "Не придумывай другое время."
    )

    # =====================================================
    # GROQ
    # =====================================================

    try:

        log.info(
            "GROQ REQUEST | "
            "chat_id=%s | "
            "model=%s | "
            "moscow_time=%s",
            chat_id,
            MODEL,
            moscow_time,
        )

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "system",
                "content": time_context,
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
            .message.content or ""
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
    # СОХРАНЕНИЕ
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
    # TELEGRAM SEND
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

    log.info(
        "REQUIRED CHANNEL: %s",
        REQUIRED_CHANNEL,
    )

    # -----------------------------------------------------
    # ПРОВЕРЯЕМ TELEGRAM
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
