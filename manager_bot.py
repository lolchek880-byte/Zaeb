import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    BusinessConnection,
)
from groq import AsyncGroq


# =========================================================
# MANAGER
# =========================================================

MANAGER_VERSION = "0.3.1"

# Если эта модель недоступна в твоём Groq-аккаунте,
# укажи доступную модель через переменную GROQ_MODEL в Railway.
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

TIMEZONE = ZoneInfo("Europe/Moscow")

MAX_HISTORY_MESSAGES = 40
MAX_REPLY_TOKENS = 2500
MAX_RETRIES = 2


# =========================================================
# ENV
# =========================================================

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL")
OWNER_ID_ENV = os.getenv("OWNER_ID")


if not BOT_TOKEN:
    raise RuntimeError("Не найдена переменная TG_BOT_TOKEN")

if not GROQ_API_KEY:
    raise RuntimeError("Не найдена переменная GROQ_API_KEY")

if not REQUIRED_CHANNEL:
    raise RuntimeError("Не найдена переменная REQUIRED_CHANNEL")


# =========================================================
# DATA
# =========================================================

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATA_FILE = DATA_DIR / "manager_data.json"


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("manager")


# =========================================================
# TELEGRAM / GROQ
# =========================================================

bot = Bot(token=BOT_TOKEN)

dp = Dispatcher(storage=MemoryStorage())

groq = AsyncGroq(api_key=GROQ_API_KEY)


# =========================================================
# DEFAULT DATA
# =========================================================

DEFAULT_DATA = {
    "owner_id": None,

    "profile": {
        "name": "",
        "age": "",
        "city": "",
        "work": "",
        "education": "",
        "interests": "",
        "about": "",
        "extra": "",
    },

    "schedule": [],

    "facts": [],

    "questions": [],

    "settings": {
        "style": "естественный, живой, разговорный",
        "default_length": "short",
        "emoji_level": "normal",
    },

    "contacts": {},

    "history": {},

    "business_connections": {},
}


# =========================================================
# LOAD / SAVE
# ВАЖНО: save_data объявлена ДО load_data.
# =========================================================

def save_data(data: dict[str, Any] | None = None) -> None:
    global DATA

    if data is None:
        data = DATA

    temp_file = DATA_FILE.with_suffix(".tmp")

    try:
        with open(
            temp_file,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        temp_file.replace(DATA_FILE)

    except Exception:
        log.exception("Ошибка сохранения данных")


def deep_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def load_data() -> dict[str, Any]:

    if not DATA_FILE.exists():

        data = deep_copy(DEFAULT_DATA)

        if OWNER_ID_ENV:
            try:
                data["owner_id"] = int(OWNER_ID_ENV)
            except ValueError:
                log.error("OWNER_ID должен быть числом")

        # save_data уже существует к этому моменту.
        # Передаём data напрямую, поэтому DATA пока не нужен.
        save_data(data)

        return data

    try:
        with open(
            DATA_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

    except Exception:
        log.exception(
            "Не удалось прочитать manager_data.json"
        )
        data = deep_copy(DEFAULT_DATA)

    # Добавляем новые разделы при обновлении версии.
    for key, default_value in DEFAULT_DATA.items():
        if key not in data:
            data[key] = deep_copy(default_value)

    # Гарантируем вложенные разделы.
    for key, default_value in DEFAULT_DATA["profile"].items():
        data.setdefault("profile", {}).setdefault(key, default_value)

    for key, default_value in DEFAULT_DATA["settings"].items():
        data.setdefault("settings", {}).setdefault(key, default_value)

    data.setdefault("schedule", [])
    data.setdefault("facts", [])
    data.setdefault("questions", [])
    data.setdefault("contacts", {})
    data.setdefault("history", {})
    data.setdefault("business_connections", {})

    if not data.get("owner_id") and OWNER_ID_ENV:
        try:
            data["owner_id"] = int(OWNER_ID_ENV)
        except ValueError:
            log.error("OWNER_ID должен быть числом")

    save_data(data)

    return data


DATA = load_data()


# =========================================================
# OWNER
# =========================================================

def get_owner_id() -> int | None:

    owner_id = DATA.get("owner_id")

    if owner_id:
        try:
            return int(owner_id)
        except (TypeError, ValueError):
            return None

    if OWNER_ID_ENV:
        try:
            return int(OWNER_ID_ENV)
        except ValueError:
            return None

    return None


def is_owner(user_id: int | None) -> bool:
    owner_id = get_owner_id()
    return bool(
        user_id
        and owner_id
        and user_id == owner_id
    )


# =========================================================
# TIME
# =========================================================

def moscow_now() -> datetime:
    return datetime.now(TIMEZONE)


def moscow_time_string() -> str:
    return moscow_now().strftime("%d.%m.%Y %H:%M")


def get_schedule_context() -> str:

    now = moscow_now()

    current_minutes = now.hour * 60 + now.minute

    active = []

    for item in DATA.get("schedule", []):

        try:
            start_h, start_m = map(
                int,
                item["start"].split(":"),
            )

            end_h, end_m = map(
                int,
                item["end"].split(":"),
            )

            start = start_h * 60 + start_m
            end = end_h * 60 + end_m

            if start <= end:
                inside = start <= current_minutes <= end
            else:
                inside = (
                    current_minutes >= start
                    or current_minutes <= end
                )

            if inside:
                active.append(item)

        except Exception:
            continue

    if not active:
        return "Сейчас нет активного события в расписании владельца."

    lines = []

    for item in active:
        lines.append(
            f"- {item['name']} ({item['start']}–{item['end']})"
        )

    return (
        "Сейчас по расписанию владельца:\n"
        + "\n".join(lines)
    )


# =========================================================
# SUBSCRIPTION
# Подписка проверяется ТОЛЬКО в самом Manager.
# Business-сообщения здесь не блокируются подпиской.
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
            "Ошибка проверки подписки: user_id=%s",
            user_id,
        )
        return False


def subscription_keyboard() -> InlineKeyboardMarkup:

    channel_url = (
        f"https://t.me/"
        f"{REQUIRED_CHANNEL.lstrip('@')}"
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


async def require_subscription(message: Message) -> bool:

    user = message.from_user

    if not user:
        return False

    if await is_subscribed(user.id):
        return True

    await message.answer(
        "🔒 <b>Доступ ограничен</b>\n\n"
        "Чтобы пользоваться Manager, сначала "
        "подпишись на наш канал.\n\n"
        "После подписки нажми "
        "«Проверить подписку».",
        parse_mode="HTML",
        reply_markup=subscription_keyboard(),
    )

    return False


# =========================================================
# FSM
# =========================================================

class SetupStates(StatesGroup):
    profile_field = State()

    fact_text = State()

    schedule_name = State()
    schedule_start = State()
    schedule_end = State()

    question_text = State()

    style_text = State()


# =========================================================
# MENUS
# =========================================================

def main_menu() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Мой профиль",
                    callback_data="menu_profile",
                ),
                InlineKeyboardButton(
                    text="🕐 Расписание",
                    callback_data="menu_schedule",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📦 Информация",
                    callback_data="menu_facts",
                ),
                InlineKeyboardButton(
                    text="📋 Анкета",
                    callback_data="menu_questions",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎭 Стиль общения",
                    callback_data="menu_style",
                ),
                InlineKeyboardButton(
                    text="🧠 Память",
                    callback_data="menu_memory",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статус",
                    callback_data="menu_status",
                ),
            ],
        ]
    )


def back_menu() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu_main",
                )
            ]
        ]
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):

    user = message.from_user

    if not user:
        return

    # Если OWNER_ID не задан, первый /start становится владельцем.
    if get_owner_id() is None:

        DATA["owner_id"] = user.id

        save_data()

        log.info(
            "OWNER SET: %s",
            user.id,
        )

    # Подписка действует только внутри Manager.
    if not await require_subscription(message):
        return

    await message.answer(
        f"🍀 <b>Manager {MANAGER_VERSION}</b>\n\n"
        "Добро пожаловать в панель управления.\n\n"
        "Здесь можно настроить:\n"
        "👤 профиль и биографию\n"
        "🕐 расписание по МСК\n"
        "📦 товары, проекты и другую информацию\n"
        "📋 сведения, которые нужно узнавать у собеседников\n"
        "🎭 стиль общения\n"
        "🧠 память о собеседниках\n\n"
        "Business-чат работает отдельно: "
        "проверка подписки там не выполняется.\n\n"
        f"🕐 МСК: <code>{moscow_time_string()}</code>",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


# =========================================================
# SUBSCRIPTION CALLBACK
# =========================================================

@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):

    user = callback.from_user

    if await is_subscribed(user.id):

        await callback.answer(
            "Подписка подтверждена ✅",
            show_alert=True,
        )

        if callback.message:
            await callback.message.edit_text(
                f"🍀 <b>Manager {MANAGER_VERSION}</b>\n\n"
                "Подписка подтверждена ✅\n\n"
                "Теперь можно пользоваться Manager.",
                parse_mode="HTML",
                reply_markup=main_menu(),
            )

    else:

        await callback.answer(
            "Подписка пока не найдена.",
            show_alert=True,
        )


# =========================================================
# MAIN MENU CALLBACK
# =========================================================

@dp.callback_query(F.data == "menu_main")
async def menu_main(callback: CallbackQuery):

    if not await is_subscribed(callback.from_user.id):
        await callback.answer(
            "Сначала подпишись на канал.",
            show_alert=True,
        )
        return

    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            f"🍀 <b>Manager {MANAGER_VERSION}</b>\n\n"
            "⚙️ <b>Панель управления</b>\n\n"
            "Выбери раздел:",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )


# =========================================================
# PROFILE
# =========================================================

def profile_text() -> str:

    p = DATA["profile"]

    return (
        "👤 <b>Мой профиль</b>\n\n"
        f"Имя: {p.get('name') or '—'}\n"
        f"Возраст: {p.get('age') or '—'}\n"
        f"Город: {p.get('city') or '—'}\n"
        f"Работа: {p.get('work') or '—'}\n"
        f"Учёба: {p.get('education') or '—'}\n"
        f"Интересы: {p.get('interests') or '—'}\n"
        f"О себе: {p.get('about') or '—'}\n"
        f"Дополнительно: {p.get('extra') or '—'}"
    )


def profile_menu() -> InlineKeyboardMarkup:

    fields = [
        ("Имя", "name"),
        ("Возраст", "age"),
        ("Город", "city"),
        ("Работа", "work"),
        ("Учёба", "education"),
        ("Интересы", "interests"),
        ("О себе", "about"),
        ("Дополнительно", "extra"),
    ]

    buttons = []

    for title, key in fields:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"✏️ {title}",
                    callback_data=f"profile_edit:{key}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="menu_main",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(F.data == "menu_profile")
async def menu_profile(callback: CallbackQuery):

    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            profile_text(),
            parse_mode="HTML",
            reply_markup=profile_menu(),
        )


@dp.callback_query(F.data.startswith("profile_edit:"))
async def profile_edit(
    callback: CallbackQuery,
    state: FSMContext,
):

    field = callback.data.split(":", 1)[1]

    await state.update_data(profile_field=field)
    await state.set_state(SetupStates.profile_field)

    names = {
        "name": "имя",
        "age": "возраст",
        "city": "город",
        "work": "работу",
        "education": "учёбу",
        "interests": "интересы",
        "about": "информацию о себе",
        "extra": "дополнительную информацию",
    }

    await callback.answer()

    if callback.message:
        await callback.message.answer(
            f"✏️ Напиши {names.get(field, field)}.\n\n"
            "Можно отправить несколько слов или "
            "подробное описание."
        )


@dp.message(SetupStates.profile_field)
async def profile_save(
    message: Message,
    state: FSMContext,
):

    data = await state.get_data()

    field = data.get("profile_field")

    if field in DATA["profile"]:
        DATA["profile"][field] = (
            message.text or ""
        ).strip()

        save_data()

    await state.clear()

    await message.answer(
        "✅ Сохранено.",
        reply_markup=profile_menu(),
    )


# =========================================================
# FACTS
# =========================================================

def facts_text() -> str:

    facts = DATA.get("facts", [])

    if not facts:
        return (
            "📦 <b>Информация</b>\n\n"
            "Пока ничего не добавлено."
        )

    lines = [f"• {fact}" for fact in facts]

    return (
        "📦 <b>Информация</b>\n\n"
        + "\n".join(lines)
    )


def facts_menu() -> InlineKeyboardMarkup:

    buttons = [
        [
            InlineKeyboardButton(
                text="➕ Добавить",
                callback_data="fact_add",
            )
        ]
    ]

    for index, fact in enumerate(DATA.get("facts", [])):
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 {fact[:35]}",
                    callback_data=f"fact_delete:{index}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="menu_main",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(F.data == "menu_facts")
async def menu_facts(callback: CallbackQuery):

    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            facts_text(),
            parse_mode="HTML",
            reply_markup=facts_menu(),
        )


@dp.callback_query(F.data == "fact_add")
async def fact_add(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.set_state(SetupStates.fact_text)

    await callback.answer()

    if callback.message:
        await callback.message.answer(
            "📦 Напиши информацию, которую Manager "
            "должен знать.\n\n"
            "Например:\n"
            "«Monster Viking Berry — редкая банка "
            "из моей коллекции»\n\n"
            "Можно написать большой текст."
        )


@dp.message(SetupStates.fact_text)
async def fact_save(
    message: Message,
    state: FSMContext,
):

    text = (message.text or "").strip()

    if text:
        DATA["facts"].append(text)
        save_data()

    await state.clear()

    await message.answer(
        "✅ Информация сохранена.",
        reply_markup=facts_menu(),
    )


@dp.callback_query(F.data.startswith("fact_delete:"))
async def fact_delete(callback: CallbackQuery):

    try:
        index = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка")
        return

    facts = DATA.get("facts", [])

    if 0 <= index < len(facts):
        facts.pop(index)
        save_data()

    await callback.answer("Удалено")

    if callback.message:
        await callback.message.edit_text(
            facts_text(),
            parse_mode="HTML",
            reply_markup=facts_menu(),
        )


# =========================================================
# SCHEDULE
# =========================================================

def schedule_text() -> str:

    schedule = DATA.get("schedule", [])

    if not schedule:
        return (
            "🕐 <b>Расписание</b>\n\n"
            "Пока расписание пустое.\n\n"
            "Все времена указываются по МСК."
        )

    lines = []

    for item in schedule:
        lines.append(
            f"• <b>{item['name']}</b> — "
            f"{item['start']}–{item['end']}"
        )

    return (
        "🕐 <b>Расписание</b>\n\n"
        + "\n".join(lines)
        + "\n\nВремя: МСК (UTC+3)"
    )


def schedule_menu() -> InlineKeyboardMarkup:

    buttons = [
        [
            InlineKeyboardButton(
                text="➕ Добавить событие",
                callback_data="schedule_add",
            )
        ]
    ]

    for index, item in enumerate(DATA.get("schedule", [])):
        buttons.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"🗑 {item['name']} "
                        f"{item['start']}–{item['end']}"
                    ),
                    callback_data=f"schedule_delete:{index}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="menu_main",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(F.data == "menu_schedule")
async def menu_schedule(callback: CallbackQuery):

    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            schedule_text(),
            parse_mode="HTML",
            reply_markup=schedule_menu(),
        )


@dp.callback_query(F.data == "schedule_add")
async def schedule_add(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.set_state(SetupStates.schedule_name)

    await callback.answer()

    if callback.message:
        await callback.message.answer(
            "🕐 Название события?\n\n"
            "Например: работа, сон, спорт, "
            "учёба, свободное время."
        )


@dp.message(SetupStates.schedule_name)
async def schedule_name(
    message: Message,
    state: FSMContext,
):

    name = (message.text or "").strip()

    if not name:
        await message.answer("Напиши название события.")
        return

    await state.update_data(schedule_name=name)

    await state.set_state(SetupStates.schedule_start)

    await message.answer(
        "Теперь напиши время начала.\n\n"
        "Например: <code>18:00</code>",
        parse_mode="HTML",
    )


@dp.message(SetupStates.schedule_start)
async def schedule_start(
    message: Message,
    state: FSMContext,
):

    text = (message.text or "").strip()

    try:
        datetime.strptime(text, "%H:%M")
    except ValueError:
        await message.answer(
            "❌ Неверный формат.\n"
            "Используй, например: 18:00"
        )
        return

    await state.update_data(schedule_start=text)

    await state.set_state(SetupStates.schedule_end)

    await message.answer(
        "Теперь время окончания.\n\n"
        "Например: <code>23:00</code>",
        parse_mode="HTML",
    )


@dp.message(SetupStates.schedule_end)
async def schedule_end(
    message: Message,
    state: FSMContext,
):

    text = (message.text or "").strip()

    try:
        datetime.strptime(text, "%H:%M")
    except ValueError:
        await message.answer(
            "❌ Неверный формат.\n"
            "Используй, например: 23:00"
        )
        return

    data = await state.get_data()

    DATA["schedule"].append(
        {
            "name": data.get("schedule_name", "Событие"),
            "start": data.get("schedule_start", "00:00"),
            "end": text,
        }
    )

    save_data()

    await state.clear()

    await message.answer(
        "✅ Событие добавлено.",
        reply_markup=schedule_menu(),
    )


@dp.callback_query(F.data.startswith("schedule_delete:"))
async def schedule_delete(callback: CallbackQuery):

    try:
        index = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка")
        return

    schedule = DATA.get("schedule", [])

    if 0 <= index < len(schedule):
        schedule.pop(index)
        save_data()

    await callback.answer("Удалено")

    if callback.message:
        await callback.message.edit_text(
            schedule_text(),
            parse_mode="HTML",
            reply_markup=schedule_menu(),
        )


# =========================================================
# QUESTIONS
# =========================================================

def questions_text() -> str:

    questions = DATA.get("questions", [])

    if not questions:
        return (
            "📋 <b>Что узнавать</b>\n\n"
            "Список пуст.\n\n"
            "Добавь сведения, которые Manager "
            "должен естественно узнавать в разговоре."
        )

    lines = [f"• {q}" for q in questions]

    return (
        "📋 <b>Что узнавать у собеседника</b>\n\n"
        + "\n".join(lines)
    )


def questions_menu() -> InlineKeyboardMarkup:

    buttons = [
        [
            InlineKeyboardButton(
                text="➕ Добавить пункт",
                callback_data="question_add",
            )
        ]
    ]

    for index, question in enumerate(DATA.get("questions", [])):
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 {question[:35]}",
                    callback_data=f"question_delete:{index}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="menu_main",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(F.data == "menu_questions")
async def menu_questions(callback: CallbackQuery):

    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            questions_text(),
            parse_mode="HTML",
            reply_markup=questions_menu(),
        )


@dp.callback_query(F.data == "question_add")
async def question_add(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.set_state(SetupStates.question_text)

    await callback.answer()

    if callback.message:
        await callback.message.answer(
            "📋 Что Manager должен узнать?\n\n"
            "Например:\n"
            "• возраст\n"
            "• город\n"
            "• работа\n"
            "• интересы\n"
            "• как зовут\n\n"
            "Можно написать свой пункт."
        )


@dp.message(SetupStates.question_text)
async def question_save(
    message: Message,
    state: FSMContext,
):

    text = (message.text or "").strip()

    if text:
        DATA["questions"].append(text)
        save_data()

    await state.clear()

    await message.answer(
        "✅ Пункт анкеты сохранён.",
        reply_markup=questions_menu(),
    )


@dp.callback_query(F.data.startswith("question_delete:"))
async def question_delete(callback: CallbackQuery):

    try:
        index = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка")
        return

    questions = DATA.get("questions", [])

    if 0 <= index < len(questions):
        questions.pop(index)
        save_data()

    await callback.answer("Удалено")

    if callback.message:
        await callback.message.edit_text(
            questions_text(),
            parse_mode="HTML",
            reply_markup=questions_menu(),
        )


# =========================================================
# STYLE
# =========================================================

def style_text() -> str:

    settings = DATA["settings"]

    return (
        "🎭 <b>Стиль общения</b>\n\n"
        f"Стиль: {settings.get('style', '—')}\n"
        f"Длина: {settings.get('default_length', 'short')}\n"
        f"Эмодзи: {settings.get('emoji_level', 'normal')}"
    )


def style_menu() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить стиль",
                    callback_data="style_edit",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📏 Короткие",
                    callback_data="length_short",
                ),
                InlineKeyboardButton(
                    text="📏 Средние",
                    callback_data="length_medium",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📏 Свободная длина",
                    callback_data="length_auto",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🙂 Эмодзи",
                    callback_data="emoji_normal",
                ),
                InlineKeyboardButton(
                    text="🚫 Мало",
                    callback_data="emoji_low",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="menu_main",
                )
            ],
        ]
    )


@dp.callback_query(F.data == "menu_style")
async def menu_style(callback: CallbackQuery):

    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            style_text(),
            parse_mode="HTML",
            reply_markup=style_menu(),
        )


@dp.callback_query(F.data == "style_edit")
async def style_edit(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.set_state(SetupStates.style_text)

    await callback.answer()

    if callback.message:
        await callback.message.answer(
            "🎭 Опиши желаемый стиль.\n\n"
            "Например:\n"
            "«Пиши максимально естественно, немного "
            "с юмором, без официоза, иногда используй "
            "сленг, но не перебарщивай.»"
        )


@dp.message(SetupStates.style_text)
async def style_save(
    message: Message,
    state: FSMContext,
):

    text = (message.text or "").strip()

    if text:
        DATA["settings"]["style"] = text
        save_data()

    await state.clear()

    await message.answer(
        "✅ Стиль сохранён.",
        reply_markup=style_menu(),
    )


@dp.callback_query(F.data.startswith("length_"))
async def set_length(callback: CallbackQuery):

    value = callback.data.replace("length_", "")

    values = {
        "short": "short",
        "medium": "medium",
        "auto": "auto",
    }

    DATA["settings"]["default_length"] = values.get(
        value,
        "short",
    )

    save_data()

    await callback.answer("Настройка сохранена")

    if callback.message:
        await callback.message.edit_text(
            style_text(),
            parse_mode="HTML",
            reply_markup=style_menu(),
        )


@dp.callback_query(F.data.startswith("emoji_"))
async def set_emoji(callback: CallbackQuery):

    value = callback.data.replace("emoji_", "")

    DATA["settings"]["emoji_level"] = value

    save_data()

    await callback.answer("Настройка сохранена")

    if callback.message:
        await callback.message.edit_text(
            style_text(),
            parse_mode="HTML",
            reply_markup=style_menu(),
        )


# =========================================================
# MEMORY
# =========================================================

@dp.callback_query(F.data == "menu_memory")
async def menu_memory(callback: CallbackQuery):

    contacts = DATA.get("contacts", {})

    if not contacts:
        text = (
            "🧠 <b>Память</b>\n\n"
            "Пока Manager ничего не сохранил "
            "о собеседниках."
        )
    else:
        lines = []

        for chat_id, contact in contacts.items():
            name = (
                contact.get("name")
                or f"Chat {chat_id}"
            )

            lines.append(f"• {name}")

        text = (
            "🧠 <b>Память</b>\n\n"
            + "\n".join(lines)
        )

    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=back_menu(),
        )


# =========================================================
# STATUS
# =========================================================

@dp.callback_query(F.data == "menu_status")
async def menu_status(callback: CallbackQuery):

    connections = DATA.get(
        "business_connections",
        {},
    )

    enabled = sum(
        1
        for connection in connections.values()
        if connection.get("enabled")
    )

    owner = get_owner_id()

    text = (
        f"📊 <b>Manager {MANAGER_VERSION}</b>\n\n"
        f"🤖 Model: <code>{MODEL}</code>\n"
        f"🟢 Business connections: {enabled}\n"
        f"👤 Owner ID: <code>{owner or '—'}</code>\n"
        f"🕐 МСК: <code>{moscow_time_string()}</code>\n"
        f"💾 Data: <code>{DATA_FILE}</code>\n"
        f"🧠 Диалогов: {len(DATA.get('history', {}))}"
    )

    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=back_menu(),
        )


# =========================================================
# BUSINESS CONNECTION
# ВАЖНО: здесь НЕТ проверки подписки.
# =========================================================

@dp.business_connection()
async def handle_business_connection(
    connection: BusinessConnection,
):

    log.info(
        "BUSINESS CONNECTION | "
        "id=%s | user=%s | enabled=%s | can_reply=%s",
        connection.id,
        connection.user.id if connection.user else "?",
        connection.is_enabled,
        connection.can_reply,
    )

    DATA.setdefault("business_connections", {})

    DATA["business_connections"][connection.id] = {
        "user_id": (
            connection.user.id
            if connection.user
            else None
        ),
        "enabled": connection.is_enabled,
        "can_reply": connection.can_reply,
    }

    save_data()


# =========================================================
# BUSINESS MESSAGE
# =========================================================

@dp.business_message()
async def handle_business_message(message: Message):

    connection_id = message.business_connection_id
    chat_id = message.chat.id
    text = (message.text or "").strip()

    if not connection_id:
        return

    if not text:
        return

    log.info(
        "BUSINESS MESSAGE | chat=%s | text=%r",
        chat_id,
        text,
    )

    # -----------------------------------------------------
    # Получаем актуальный Business Connection.
    # -----------------------------------------------------

    try:
        connection = await bot.get_business_connection(
            business_connection_id=connection_id,
        )

    except Exception:
        log.exception(
            "Не удалось получить Business Connection"
        )
        return

    if not connection.is_enabled:
        return

    if connection.can_reply is False:
        return

    # -----------------------------------------------------
    # Не отвечаем владельцу самому себе.
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
        return

    # -----------------------------------------------------
    # История.
    # -----------------------------------------------------

    history = DATA.setdefault("history", {})

    chat_key = str(chat_id)

    chat_history = history.setdefault(
        chat_key,
        [],
    )

    chat_history.append(
        {
            "role": "user",
            "content": text,
        }
    )

    chat_history[:] = chat_history[
        -MAX_HISTORY_MESSAGES:
    ]

    # -----------------------------------------------------
    # Контакт.
    # -----------------------------------------------------

    contacts = DATA.setdefault("contacts", {})

    contact = contacts.setdefault(
        chat_key,
        {
            "name": "",
            "username": "",
            "facts": {},
            "reported_questions": [],
        },
    )

    if message.from_user:

        if message.from_user.username:
            contact["username"] = (
                "@"
                + message.from_user.username
            )

        if (
            not contact["name"]
            and message.from_user.full_name
        ):
            contact["name"] = (
                message.from_user.full_name
            )

    # -----------------------------------------------------
    # Профиль владельца.
    # -----------------------------------------------------

    profile = DATA["profile"]

    profile_lines = []

    profile_labels = {
        "name": "Имя",
        "age": "Возраст",
        "city": "Город",
        "work": "Работа",
        "education": "Учёба",
        "interests": "Интересы",
        "about": "О себе",
        "extra": "Дополнительно",
    }

    for key, value in profile.items():
        if value:
            profile_lines.append(
                f"{profile_labels.get(key, key)}: {value}"
            )

    profile_context = (
        "\n".join(profile_lines)
        if profile_lines
        else "Профиль пока не заполнен."
    )

    # -----------------------------------------------------
    # Информация / товары / проекты.
    # -----------------------------------------------------

    facts = DATA.get("facts", [])

    facts_context = (
        "\n".join(
            f"- {fact}"
            for fact in facts
        )
        if facts
        else "Дополнительной информации нет."
    )

    # -----------------------------------------------------
    # Что узнать.
    # -----------------------------------------------------

    questions = DATA.get("questions", [])

    questions_context = (
        "\n".join(
            f"- {question}"
            for question in questions
        )
        if questions
        else "Специальных сведений собирать не нужно."
    )

    # -----------------------------------------------------
    # Уже известные сведения.
    # -----------------------------------------------------

    known_facts = contact.get("facts", {})

    known_context = (
        "\n".join(
            f"- {key}: {value}"
            for key, value in known_facts.items()
        )
        if known_facts
        else "Пока ничего дополнительного не известно."
    )

    # -----------------------------------------------------
    # Время.
    # -----------------------------------------------------

    current_time = moscow_time_string()
    schedule_context = get_schedule_context()

    # -----------------------------------------------------
    # Длина ответа.
    # -----------------------------------------------------

    length = DATA["settings"].get(
        "default_length",
        "short",
    )

    if length == "short":
        length_instruction = (
            "Обычно отвечай коротко и естественно."
        )
    elif length == "medium":
        length_instruction = (
            "Обычно отвечай примерно 2–5 предложениями."
        )
    else:
        length_instruction = (
            "Длину ответа выбирай естественно."
        )

    # Если человек сам просит большой ответ.
    long_request_words = [
        "подробнее",
        "подробно",
        "распиши",
        "распиши подробнее",
        "большой ответ",
        "длинный ответ",
        "расскажи подробно",
        "объясни подробно",
        "развернуто",
        "развёрнуто",
        "максимально подробно",
        "можешь расписать",
        "можешь объяснить подробнее",
    ]

    text_lower = text.lower()

    wants_long = any(
        phrase in text_lower
        for phrase in long_request_words
    )

    if wants_long:
        length_instruction = (
            "Собеседник явно попросил подробный ответ. "
            "Можно отвечать значительно длиннее обычного "
            "и раскрыть тему полностью."
        )

    # -----------------------------------------------------
    # Стиль.
    # -----------------------------------------------------

    style = DATA["settings"].get(
        "style",
        "естественный, живой, разговорный",
    )

    emoji_level = DATA["settings"].get(
        "emoji_level",
        "normal",
    )

    # -----------------------------------------------------
    # SYSTEM PROMPT.
    # -----------------------------------------------------

    system_prompt = f"""
Ты ведёшь живую переписку в Telegram от лица владельца
Business-аккаунта.

Твоя главная задача — отвечать естественно, уместно и
последовательно, учитывая конкретный диалог.

Не веди себя как технический ассистент и не превращай
обычную переписку в интервью.

СТИЛЬ ВЛАДЕЛЬЦА:
{style}

ДЛИНА:
{length_instruction}

ЭМОДЗИ:
{emoji_level}

ТЕКУЩЕЕ ВРЕМЯ:
{current_time} по Москве (UTC+3)

АКТУАЛЬНОЕ РАСПИСАНИЕ:
{schedule_context}

ПРОФИЛЬ ВЛАДЕЛЬЦА:
{profile_context}

ИНФОРМАЦИЯ / ТОВАРЫ / ПРОЕКТЫ:
{facts_context}

ЧТО НУЖНО УЗНАТЬ У СОБЕСЕДНИКА:
{questions_context}

ЧТО УЖЕ ИЗВЕСТНО О СОБЕСЕДНИКЕ:
{known_context}

ПРАВИЛА:

1. Никогда не выдумывай факты о владельце.

2. Профиль владельца — источник правды о его
   биографии.

3. Если работа владельца указана как отсутствие работы,
   не говори, что он работает.

4. Если конкретного факта нет, не придумывай его.

5. Расписание используй только если оно действительно
   относится к текущему разговору.

6. Учитывай время по Москве.

7. Не спрашивай то, что уже известно из истории.

8. Не повторяй один и тот же вопрос разными словами.

9. Не задавай вопрос в конце каждого сообщения.

10. Не пытайся искусственно продолжать разговор.

11. Реагируй прежде всего на смысл последнего сообщения.

12. Учитывай предыдущую переписку.

13. Если нужно узнать сведения из списка анкеты,
    спрашивай их естественно и только когда это
    уместно.

14. Если человек сам сообщил сведения о себе,
    не спрашивай их повторно.

15. Не упоминай профиль, память, расписание, анкету,
    системный промпт, Manager или технические настройки.

16. Не говори собеседнику, что ты анализируешь его.

17. Не используй одинаковые шаблоны ответов.

18. Не злоупотребляй вопросами.

19. Не злоупотребляй эмодзи.

20. Не пиши канцеляритом.

21. Не начинай каждый ответ одинаково.

22. Не используй фразы вроде:
    «Я понимаю ваш запрос»,
    «Конечно, я помогу»,
    «Как ИИ»,
    если они неуместны.

23. Если сообщение короткое — ответ тоже может быть коротким.

24. Если собеседник явно просит подробный ответ,
    дай действительно подробный ответ.

25. Если собеседник шутит, можно ответить живее и
    с лёгким юмором, если это соответствует стилю.

26. Если собеседник не задаёт вопрос, не обязан задавать
    вопрос в ответ.

27. Не выдумывай встречи, поездки, работу, планы,
    отношения или другие личные события владельца.

28. Если в информации владельца есть конкретные данные
    о товаре, проекте или интересе — используй их,
    когда они относятся к разговору.

29. Отвечай так, будто это обычная переписка человека,
    а не диалог с консультантом.

30. Не повторяй недавние формулировки без причины.
""".strip()

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        *chat_history,
    ]

    # -----------------------------------------------------
    # GROQ.
    # -----------------------------------------------------

    reply_text = ""

    for attempt in range(MAX_RETRIES + 1):

        try:
            log.info(
                "GROQ REQUEST | chat=%s | attempt=%s | model=%s",
                chat_id,
                attempt + 1,
                MODEL,
            )

            response = await groq.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=MAX_REPLY_TOKENS,
                temperature=0.85,
            )

            reply_text = (
                response.choices[0]
                .message.content
                or ""
            ).strip()

            if reply_text:
                break

        except Exception:
            log.exception(
                "Groq request failed | attempt=%s",
                attempt + 1,
            )

            if attempt < MAX_RETRIES:
                await asyncio.sleep(1.0)

    # -----------------------------------------------------
    # Если Groq не ответил:
    # ничего технического человеку не отправляем.
    # -----------------------------------------------------

    if not reply_text:
        log.error(
            "Groq не вернул ответ после всех попыток. "
            "Пользователю ничего не отправляем."
        )
        return

    # -----------------------------------------------------
    # История.
    # -----------------------------------------------------

    chat_history.append(
        {
            "role": "assistant",
            "content": reply_text,
        }
    )

    chat_history[:] = chat_history[
        -MAX_HISTORY_MESSAGES:
    ]

    # -----------------------------------------------------
    # Сохранение.
    # -----------------------------------------------------

    save_data()

    # -----------------------------------------------------
    # Отправка от Business-аккаунта.
    # -----------------------------------------------------

    try:

        await bot.send_message(
            chat_id=chat_id,
            text=reply_text,
            business_connection_id=connection_id,
        )

        log.info(
            "BUSINESS REPLY SENT | chat=%s",
            chat_id,
        )

    except Exception:
        log.exception(
            "Telegram send error"
        )


# =========================================================
# STARTUP
# =========================================================

async def main():

    log.info("========================================")
    log.info(
        "🍀 MANAGER %s STARTING",
        MANAGER_VERSION,
    )
    log.info("MODEL: %s", MODEL)
    log.info("DATA FILE: %s", DATA_FILE)

    try:
        me = await bot.get_me()

        log.info(
            "BOT: @%s | id=%s",
            me.username,
            me.id,
        )

    except Exception:
        log.exception(
            "Telegram connection failed"
        )
        return

    owner = get_owner_id()

    if owner:
        log.info("OWNER ID: %s", owner)
    else:
        log.warning(
            "OWNER_ID не установлен. "
            "Первый /start станет владельцем."
        )

    log.info(
        "Manager %s started.",
        MANAGER_VERSION,
    )

    log.info("========================================")

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
