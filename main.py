import asyncio
import html
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

# ================= КОНФИГУРАЦИЯ (ПОД DEPLOYKA / ХОСТИНГ) =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")

raw_admins = os.getenv("ADMIN_IDS", "123456789,987654321")
ADMIN_IDS = [int(x.strip()) for x in raw_admins.split(",") if x.strip().isdigit()]

if os.path.exists("/data") or os.access("/", os.W_OK):
    os.makedirs("/data", exist_ok=True)
    DB_PATH = "/data/bot_database.db"
else:
    DB_PATH = "bot_database.db"

POST_INTERVAL_SECONDS = 15 * 60  # Каждые 15 минут пост
AUTO_CLOSE_SECONDS = 20 * 60     # Автозакрытие поста через 20 минут
TZ_MSK = timezone(timedelta(hours=3))  # Московское время (UTC+3)
# =========================================================================

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)


def now_msk() -> datetime:
    return datetime.now(TZ_MSK)


def fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ_MSK).strftime("%d.%m %H:%M")


# ================= СПИСОК ВСЕХ НАСТРАИВАЕМЫХ КНОПОК =================
BUTTON_KEYS = [
    "btn_get_access",
    "btn_post_task",
    "btn_profile",
    "btn_close_task",
    "btn_p_2gis",
    "btn_p_yamaps",
    "btn_p_gmaps",
    "btn_p_yabrowser",
    "btn_p_other",
    "btn_confirm_post",
    "btn_cancel",
    "btn_support",
    "btn_take_task",
    "btn_back"
]

SETTING_LABELS = {
    "channel_id": "📢 ID канала (напр. -100123456789 или @channel)",
    "access_contact": "👤 Юзернейм для выдачи доступа (@elenesing)",
    "support_contact": "🛟 Юзернейм поддержки (@help_freecash)",
    "template_new_task": "📋 Шаблон НОВОГО задания в канале ({platform}, {cena}, {opisanie})",
    "template_closed_task": "⛔ Шаблон ЗАКРЫТОГО задания в канале",
    "text_no_access": "❌ Текст «У вас нету доступа»",
    "text_main_menu": "🏠 Текст главного меню (/start)",
    "text_choose_platform": "📌 Текст выбора платформы",
    "text_enter_custom_platform": "✍️ Текст запроса своей платформы",
    "text_enter_price": "💰 Текст запроса цены",
    "text_enter_desc": "📝 Текст запроса описания",
    "text_preview": "👀 Текст предпросмотра ({preview})",
    "btn_get_access": "Кнопка: Получить доступ",
    "btn_post_task": "Кнопка: Выложить / Занять пост",
    "btn_profile": "Кнопка: Профиль",
    "btn_close_task": "Кнопка: Закрыть задание",
    "btn_p_2gis": "Кнопка: 2ГИС",
    "btn_p_yamaps": "Кнопка: Яндекс карты",
    "btn_p_gmaps": "Кнопка: Гугл карты",
    "btn_p_yabrowser": "Кнопка: Яндекс Браузер",
    "btn_p_other": "Кнопка: Другое...",
    "btn_confirm_post": "Кнопка: Подтвердить",
    "btn_cancel": "Кнопка: Отменить",
    "btn_support": "Кнопка в канале: Поддержка",
    "btn_take_task": "Кнопка в канале: Взять задание",
    "btn_back": "Кнопка: Назад"
}


# ================= БАЗА ДАННЫХ =================
def get_conn():
    return sqlite3.connect("/data/bot_database.db" if DB_PATH.startswith("/data") else DB_PATH)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            sub_until INTEGER DEFAULT 0,
            posted_count INTEGER DEFAULT 0,
            closed_count INTEGER DEFAULT 0,
            last_post_time INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            author_username TEXT,
            channel_id TEXT,
            message_id INTEGER DEFAULT 0,
            platform TEXT,
            price TEXT,
            description TEXT,
            status TEXT DEFAULT 'open',
            scheduled_time INTEGER DEFAULT 0,
            published_at INTEGER DEFAULT 0
        )
    """)

    cur.execute("PRAGMA table_info(tasks)")
    cols = [c[1] for c in cur.fetchall()]
    if "scheduled_time" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN scheduled_time INTEGER DEFAULT 0")
    if "author_username" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN author_username TEXT DEFAULT ''")
    if "published_at" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN published_at INTEGER DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    default_settings = {
        "channel_id": "",
        "access_contact": "elenesing",
        "support_contact": "help_freecash",
        "btn_color": "",
        "btn_style": "",  # Нативный цвет кнопок Bot API (primary, success, danger)

        "text_no_access": "❌ <b>У вас нету доступа.</b>\nЧтобы получить доступ, напишите: @elenesing",
        "text_main_menu": "👋 <b>Добро пожаловать в панель управления заданиями!</b>\nВыберите нужное действие ниже:",
        "text_choose_platform": "📌 <b>Выберите платформу для задания:</b>",
        "text_enter_custom_platform": "✍️ <b>Введите название платформы:</b>",
        "text_enter_price": "💰 <b>Введите цену в рублях (₽):</b>",
        "text_enter_desc": "📝 <b>Введите описание задания:</b>",
        "text_preview": "👀 <b>Предпросмотр вашего задания:</b>\n\n{preview}\n\nПодтвердите действие:",
        "template_new_task": (
            "🔥 <b>Новое задание!</b>\n"
            "<b>EASY CASH</b>\n"
            "Платформа: <b>{platform}</b>\n"
            "Цена: <b>{cena} ₽</b>\n"
            "Описание:\n<blockquote>{opisanie}</blockquote>"
        ),
        "template_closed_task": (
            "⛔ <b>Это задание уже закрыто.</b>\n\n"
            "Следующее предложение появится по расписанию. "
            "Включите уведомления канала, чтобы ничего не пропустить."
        ),

        "btn_get_access": "🔑 Получить доступ",
        "btn_post_task": "📤 Выложить / Занять пост",
        "btn_profile": "👤 Профиль",
        "btn_close_task": "🔒 Закрыть задание",
        "btn_p_2gis": "2ГИС",
        "btn_p_yamaps": "Яндекс карты",
        "btn_p_gmaps": "Гугл карты",
        "btn_p_yabrowser": "Яндекс Браузер",
        "btn_p_other": "Другое...",
        "btn_confirm_post": "✅ Подтвердить",
        "btn_cancel": "❌ Отменить",
        "btn_support": "🛟 Поддержка",
        "btn_take_task": "⚡️ Взять задание",
        "btn_back": "🔙 Назад"
    }

    # Создаем слоты под Premium Emoji ID для каждой кнопки
    for b_key in BUTTON_KEYS:
        default_settings[f"emoji_{b_key}"] = ""

    for k, v in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()


def get_setting(key: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else ""


def set_setting(key: str, value: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def register_or_update_user(user_id: int, username: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username or "Без_юзернейма"))
    else:
        if username:
            cur.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
    conn.commit()
    conn.close()


def get_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, sub_until, posted_count, closed_count, last_post_time FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def has_access(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    user = get_user(user_id)
    if not user:
        return False
    return user[2] > int(time.time())


# ================= КОНСТРУКТОР КНОПОК С ПОДДЕРЖКОЙ PREMIUM EMOJI И ЦВЕТА =================
def make_btn(
    text: str,
    callback_data: str | None = None,
    url: str | None = None,
    custom_emoji_id: str | None = None,
    style: str | None = None
) -> dict:
    """Формирует raw-словарь кнопки для Telegram Bot API с поддержкой icon_custom_emoji_id и style."""
    btn = {"text": text}
    if callback_data is not None:
        btn["callback_data"] = callback_data
    if url is not None:
        btn["url"] = url
    if custom_emoji_id:
        btn["icon_custom_emoji_id"] = str(custom_emoji_id)
    if style in ("primary", "success", "danger"):
        btn["style"] = style
    return btn


def make_cfg_btn(key: str, callback_data: str | None = None, url: str | None = None) -> dict:
    """Создает настраиваемую кнопку из БД вместе с привязанным к ней Premium Emoji и цветом."""
    color_prefix = get_setting("btn_color")
    raw_text = get_setting(key)
    label = f"{color_prefix} {raw_text}".strip() if color_prefix else raw_text
    emoji_id = get_setting(f"emoji_{key}").strip()
    btn_style = get_setting("btn_style").strip()
    return make_btn(
        text=label,
        callback_data=callback_data,
        url=url,
        custom_emoji_id=emoji_id if emoji_id else None,
        style=btn_style if btn_style else None
    )


def make_kb(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def extract_custom_emoji_id(message: Message) -> str | None:
    """Извлекает ID премиум-эмодзи из entities сообщения или из текста."""
    if message.entities:
        for ent in message.entities:
            if ent.type == "custom_emoji" and getattr(ent, "custom_emoji_id", None):
                return str(ent.custom_emoji_id)
    if message.html_text:
        m = re.search(r'emoji-id=["\']?(\d+)["\']?', message.html_text)
        if m:
            return m.group(1)
    if message.text and message.text.strip().isdigit() and len(message.text.strip()) >= 15:
        return message.text.strip()
    return None


# ================= ЛОГИКА ИНТЕРВАЛА 15 МИНУТ МЕЖДУ ПОСТАМИ =================
def get_active_slots() -> list[int]:
    conn = get_conn()
    cur = conn.cursor()
    cutoff = int(time.time()) - POST_INTERVAL_SECONDS
    cur.execute(
        "SELECT scheduled_time FROM tasks WHERE status IN ('scheduled', 'open', 'closed') AND scheduled_time > ? ORDER BY scheduled_time ASC",
        (cutoff,)
    )
    slots = [r[0] for r in cur.fetchall() if r[0]]
    conn.close()
    return sorted(slots)


def check_slot_conflict(target_ts: int) -> int | None:
    for s in get_active_slots():
        if abs(target_ts - s) < POST_INTERVAL_SECONDS:
            return s
    return None


def find_nearest_available_time(from_ts: int) -> int:
    candidate = max(from_ts, int(time.time()))
    slots = get_active_slots()
    while True:
        conflict = False
        for s in slots:
            if abs(candidate - s) < POST_INTERVAL_SECONDS:
                candidate = s + POST_INTERVAL_SECONDS
                conflict = True
                break
        if not conflict:
            return candidate


def parse_user_time(text: str) -> int | None:
    text = text.strip()
    now = now_msk()
    try:
        t = datetime.strptime(text, "%H:%M").time()
        dt = datetime.combine(now.date(), t, tzinfo=TZ_MSK)
        if dt <= now:
            dt += timedelta(days=1)
        return int(dt.timestamp())
    except ValueError:
        pass

    try:
        dt_naive = datetime.strptime(text, "%d.%m %H:%M")
        dt = dt_naive.replace(year=now.year, tzinfo=TZ_MSK)
        if dt < now - timedelta(days=30):
            dt = dt.replace(year=now.year + 1)
        return int(dt.timestamp())
    except ValueError:
        return None


# ================= FSM СОСТОЯНИЯ =================
class CreateTaskSG(StatesGroup):
    choose_time = State()
    custom_time = State()
    platform_custom = State()
    price = State()
    description = State()
    confirm = State()


class AdminSG(StatesGroup):
    give_sub_user = State()
    give_sub_days = State()
    revoke_sub_user = State()
    edit_setting_value = State()
    edit_btn_emoji = State()


# ================= КЛАВИАТУРЫ =================
def kb_no_access() -> dict:
    contact = get_setting("access_contact").lstrip("@")
    return make_kb([
        [make_cfg_btn("btn_get_access", url=f"https://t.me/{contact}")]
    ])


def kb_main_menu(user_id: int) -> dict:
    rows = [
        [make_cfg_btn("btn_post_task", callback_data="menu_post_task")],
        [
            make_cfg_btn("btn_profile", callback_data="menu_profile"),
            make_cfg_btn("btn_close_task", callback_data="menu_close_task")
        ]
    ]
    if user_id in ADMIN_IDS:
        rows.append([make_btn("⚙️ Админ-панель", callback_data="admin_main")])
    return make_kb(rows)


def kb_platforms() -> dict:
    return make_kb([
        [
            make_cfg_btn("btn_p_2gis", callback_data="plat_p_2gis"),
            make_cfg_btn("btn_p_yamaps", callback_data="plat_p_yamaps")
        ],
        [
            make_cfg_btn("btn_p_gmaps", callback_data="plat_p_gmaps"),
            make_cfg_btn("btn_p_yabrowser", callback_data="plat_p_yabrowser")
        ],
        [make_cfg_btn("btn_p_other", callback_data="plat_other")],
        [make_cfg_btn("btn_cancel", callback_data="cancel_action")]
    ])


def kb_confirm_task() -> dict:
    return make_kb([
        [make_cfg_btn("btn_confirm_post", callback_data="task_publish")],
        [make_cfg_btn("btn_cancel", callback_data="cancel_action")]
    ])


def kb_channel_active_task(author_username: str) -> dict:
    support = get_setting("support_contact").lstrip("@")
    author = author_username.lstrip("@")
    return make_kb([
        [
            make_cfg_btn("btn_take_task", url=f"https://t.me/{author}"),
            make_cfg_btn("btn_support", url=f"https://t.me/{support}")
        ]
    ])


def kb_channel_closed_task() -> dict:
    support = get_setting("support_contact").lstrip("@")
    return make_kb([
        [make_cfg_btn("btn_support", url=f"https://t.me/{support}")]
    ])


def kb_back_to_menu() -> dict:
    return make_kb([
        [make_cfg_btn("btn_back", callback_data="back_to_main")]
    ])


# ================= ПОЛЬЗОВАТЕЛЬСКИЕ ХЕНДЛЕРЫ =================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    register_or_update_user(message.from_user.id, message.from_user.username)

    if not has_access(message.from_user.id):
        await message.answer(get_setting("text_no_access"), reply_markup=kb_no_access())
        return

    await message.answer(get_setting("text_main_menu"), reply_markup=kb_main_menu(message.from_user.id))


@router.callback_query(F.data == "back_to_main")
@router.callback_query(F.data == "cancel_action")
async def cb_back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    if not has_access(call.from_user.id):
        await call.message.edit_text(get_setting("text_no_access"), reply_markup=kb_no_access())
        return
    await call.message.edit_text(get_setting("text_main_menu"), reply_markup=kb_main_menu(call.from_user.id))


# --- ПРОФИЛЬ ---
@router.callback_query(F.data == "menu_profile")
async def cb_profile(call: CallbackQuery):
    if not has_access(call.from_user.id):
        return await call.message.edit_text(get_setting("text_no_access"), reply_markup=kb_no_access())

    user = get_user(call.from_user.id)
    _, username, sub_until, posted, closed, _ = user

    if call.from_user.id in ADMIN_IDS and sub_until < int(time.time()):
        sub_str = "♾ Безлимитно (Администратор)"
    else:
        sub_str = fmt_ts(sub_until) + " МСК"

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'scheduled'", (call.from_user.id,))
    sched_count = cur.fetchone()[0]
    conn.close()

    text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🆔 ID: <code>{call.from_user.id}</code>\n"
        f"⏳ Подписка активна до: <b>{sub_str}</b>\n\n"
        f"📤 Выложено заданий: <b>{posted}</b>\n"
        f"📅 В очереди на публикацию: <b>{sched_count}</b>\n"
        f"🔒 Закрыто заданий: <b>{closed}</b>"
    )
    await call.message.edit_text(text, reply_markup=kb_back_to_menu())


# --- ШАГ 1: ВЫБОР ВРЕМЕНИ ИЛИ БРОНИРОВАНИЕ СЛОТА (КАЖДЫЕ 15 МИНУТ) ---
@router.callback_query(F.data == "menu_post_task")
async def cb_post_task(call: CallbackQuery, state: FSMContext):
    if not has_access(call.from_user.id):
        return await call.message.edit_text(get_setting("text_no_access"), reply_markup=kb_no_access())

    if not call.from_user.username:
        return await call.answer("⚠️ Установите @username в настройках Telegram, чтобы исполнители могли вам написать!", show_alert=True)

    channel_id = get_setting("channel_id")
    if not channel_id:
        return await call.answer("⚠️ Канал для публикаций еще не настроен администратором!", show_alert=True)

    await state.clear()
    await state.set_state(CreateTaskSG.choose_time)

    now = int(time.time())
    nearest_ts = find_nearest_available_time(now)
    nearest_str = fmt_ts(nearest_ts)

    rows = []
    if nearest_ts <= now + 5:
        text = (
            f"🕒 <b>Выбор времени публикации (МСК)</b>\n"
            f"Сейчас на канале свободно! Вы можете выложить задание прямо сейчас или занять пост на другое время.\n\n"
            f"ℹ️ <i>Интервал между постами в канале — <b>15 минут</b>. Каждое задание автоматически закрывается через <b>20 минут</b> после выхода.</i>"
        )
        rows.append([make_btn("⚡ Выложить прямо сейчас", callback_data="slot_now")])
    else:
        wait_min = max(1, (nearest_ts - now + 59) // 60)
        text = (
            f"⏳ <b>Сейчас действует интервал 15 минут после предыдущего задания!</b>\n\n"
            f"Ближайшее свободное время для публикации: <b>{nearest_str} МСК</b> (через ~{wait_min} мин).\n"
            f"Вы можете занять это ближайшее окно или ввести своё время:"
        )
        rows.append([make_btn(f"✅ Занять ближайшее ({nearest_str} МСК)", callback_data=f"slot_ts_{nearest_ts}")])

    rows.append([make_btn("📅 Занять пост на своё время", callback_data="slot_custom")])
    rows.append([make_cfg_btn("btn_cancel", callback_data="cancel_action")])

    await call.message.edit_text(text, reply_markup=make_kb(rows))


@router.callback_query(F.data == "slot_now")
async def cb_slot_now(call: CallbackQuery, state: FSMContext):
    now = int(time.time())
    nearest = find_nearest_available_time(now)
    if nearest > now + 5:
        nearest_str = fmt_ts(nearest)
        kb = make_kb([
            [make_btn(f"✅ Занять ближайшее ({nearest_str} МСК)", callback_data=f"slot_ts_{nearest}")],
            [make_btn("📅 Ввести другое время", callback_data="slot_custom")],
            [make_cfg_btn("btn_cancel", callback_data="cancel_action")]
        ])
        return await call.message.edit_text(
            f"⚠️ Только что выложили другое задание! Ближайшее свободное время: <b>{nearest_str} МСК</b>.",
            reply_markup=kb
        )

    await state.update_data(scheduled_time=0)
    await call.message.edit_text(get_setting("text_choose_platform"), reply_markup=kb_platforms())


@router.callback_query(F.data.startswith("slot_ts_"))
async def cb_slot_ts(call: CallbackQuery, state: FSMContext):
    ts = int(call.data.replace("slot_ts_", ""))
    now = int(time.time())
    if ts < now:
        ts = now

    conflict = check_slot_conflict(ts)
    if conflict is not None:
        nearest = find_nearest_available_time(ts)
        nearest_str = fmt_ts(nearest)
        kb = make_kb([
            [make_btn(f"✅ Выбрать {nearest_str} МСК", callback_data=f"slot_ts_{nearest}")],
            [make_btn("📅 Ввести другое время", callback_data="slot_custom")],
            [make_cfg_btn("btn_cancel", callback_data="cancel_action")]
        ])
        return await call.message.edit_text(
            f"⚠️ Это время уже заняли! Ближайшее свободное окно: <b>{nearest_str} МСК</b>.",
            reply_markup=kb
        )

    await state.update_data(scheduled_time=ts)
    await call.message.edit_text(
        f"🕒 Выбрано время публикации: <b>{fmt_ts(ts)} МСК</b>\n\n" + get_setting("text_choose_platform"),
        reply_markup=kb_platforms()
    )


@router.callback_query(F.data == "slot_custom")
async def cb_slot_custom(call: CallbackQuery, state: FSMContext):
    await state.set_state(CreateTaskSG.custom_time)
    now_str = now_msk().strftime("%H:%M")

    slots = [s for s in get_active_slots() if s > int(time.time()) - POST_INTERVAL_SECONDS]
    busy_info = ""
    if slots:
        formatted_slots = ", ".join([datetime.fromtimestamp(s, TZ_MSK).strftime("%H:%M") for s in slots[:8]])
        busy_info = f"\n📌 <b>Уже занятые посты:</b> {formatted_slots} МСК (интервал ±15 мин от них недоступен).\n"

    text = (
        f"⌚ <b>Введите желаемое время публикации по МСК</b> (сейчас {now_str} МСК).\n"
        f"{busy_info}\n"
        f"Формат ввода: <code>ЧЧ:ММ</code> (например, <code>16:45</code>) или с датой <code>ДД.ММ ЧЧ:ММ</code> (например, <code>15.11 12:00</code>):"
    )
    await call.message.edit_text(text, reply_markup=kb_back_to_menu())


@router.message(CreateTaskSG.custom_time)
async def msg_custom_time(message: Message, state: FSMContext):
    if not has_access(message.from_user.id):
        return await message.answer(get_setting("text_no_access"), reply_markup=kb_no_access())

    ts = parse_user_time(message.text)
    if ts is None:
        return await message.answer(
            "❌ Неверный формат времени!\nВведите время в формате <code>15:30</code> или <code>15.11 15:30</code>:",
            reply_markup=kb_back_to_menu()
        )

    now = int(time.time())
    if ts < now - 60:
        return await message.answer("❌ Нельзя выбрать время в прошлом! Введите корректное время:", reply_markup=kb_back_to_menu())

    conflict = check_slot_conflict(ts)
    if conflict is not None:
        nearest = find_nearest_available_time(ts)
        nearest_str = fmt_ts(nearest)
        conflict_str = fmt_ts(conflict)
        kb = make_kb([
            [make_btn(f"✅ Выбрать ближайшее ({nearest_str} МСК)", callback_data=f"slot_ts_{nearest}")],
            [make_cfg_btn("btn_cancel", callback_data="cancel_action")]
        ])
        return await message.answer(
            f"⛔ <b>Это время занять нельзя!</b>\n"
            f"На <b>{conflict_str} МСК</b> уже стоит другой пост (минимальный интервал между постами — 15 минут).\n\n"
            f"💡 Ближайшее доступное время: <b>{nearest_str} МСК</b>.\n"
            f"Нажмите кнопку ниже, чтобы выбрать его, или отправьте другое время текстом:",
            reply_markup=kb
        )

    await state.update_data(scheduled_time=ts)
    await message.answer(
        f"✅ Время <b>{fmt_ts(ts)} МСК</b> свободно и выбрано!\n\n" + get_setting("text_choose_platform"),
        reply_markup=kb_platforms()
    )


# --- ШАГ 2: ПЛАТФОРМА, ЦЕНА И ОПИСАНИЕ ---
@router.callback_query(F.data.startswith("plat_"))
async def cb_choose_platform(call: CallbackQuery, state: FSMContext):
    if not has_access(call.from_user.id):
        return await call.message.edit_text(get_setting("text_no_access"), reply_markup=kb_no_access())

    code = call.data.replace("plat_", "")
    if code == "other":
        await state.set_state(CreateTaskSG.platform_custom)
        await call.message.edit_text(get_setting("text_enter_custom_platform"), reply_markup=kb_back_to_menu())
    else:
        platform_name = get_setting(f"btn_{code}")
        await state.update_data(platform=platform_name)
        await state.set_state(CreateTaskSG.price)
        await call.message.edit_text(get_setting("text_enter_price"), reply_markup=kb_back_to_menu())


@router.message(CreateTaskSG.platform_custom)
async def msg_custom_platform(message: Message, state: FSMContext):
    if not has_access(message.from_user.id):
        return await message.answer(get_setting("text_no_access"), reply_markup=kb_no_access())

    await state.update_data(platform=html.escape(message.text.strip()))
    await state.set_state(CreateTaskSG.price)
    await message.answer(get_setting("text_enter_price"), reply_markup=kb_back_to_menu())


@router.message(CreateTaskSG.price)
async def msg_enter_price(message: Message, state: FSMContext):
    if not has_access(message.from_user.id):
        return await message.answer(get_setting("text_no_access"), reply_markup=kb_no_access())

    price_clean = html.escape(message.text.replace("₽", "").strip())
    await state.update_data(price=price_clean)
    await state.set_state(CreateTaskSG.description)
    await message.answer(get_setting("text_enter_desc"), reply_markup=kb_back_to_menu())


def render_task_template(platform: str, price: str, desc_html: str) -> str:
    tpl = get_setting("template_new_task")
    if "<blockquote>" not in tpl and "{opisanie}" in tpl:
        opisanie_formatted = f"<blockquote>{desc_html}</blockquote>"
    else:
        opisanie_formatted = desc_html

    return (
        tpl.replace("{platform}", platform)
           .replace("{cena}", price)
           .replace("{opisanie}", opisanie_formatted)
    )


@router.message(CreateTaskSG.description)
async def msg_enter_desc(message: Message, state: FSMContext):
    if not has_access(message.from_user.id):
        return await message.answer(get_setting("text_no_access"), reply_markup=kb_no_access())

    desc_html = message.html_text.strip()
    await state.update_data(description=desc_html)
    data = await state.get_data()

    sched_ts = data.get("scheduled_time", 0)
    time_banner = (
        "⚡ <b>Время выхода:</b> Прямо сейчас (автозакрытие через 20 мин)\n\n"
        if sched_ts == 0
        else f"📅 <b>Запланировано на:</b> {fmt_ts(sched_ts)} МСК (автозакрытие через 20 мин после выхода)\n\n"
    )

    preview_post = render_task_template(data["platform"], data["price"], desc_html)
    preview_wrapper = time_banner + get_setting("text_preview").replace("{preview}", preview_post)

    await state.set_state(CreateTaskSG.confirm)
    await message.answer(preview_wrapper, reply_markup=kb_confirm_task())


# --- ШАГ 3: ПУБЛИКАЦИЯ ИЛИ ПОСТАНОВКА В ОЧЕРЕДЬ ---
@router.callback_query(CreateTaskSG.confirm, F.data == "task_publish")
async def cb_task_publish(call: CallbackQuery, state: FSMContext):
    if not has_access(call.from_user.id):
        return await call.message.edit_text(get_setting("text_no_access"), reply_markup=kb_no_access())

    data = await state.get_data()
    sched_ts = data.get("scheduled_time", 0)
    now = int(time.time())
    target_ts = now if sched_ts == 0 else sched_ts

    conflict = check_slot_conflict(target_ts)
    if conflict is not None:
        nearest = find_nearest_available_time(target_ts)
        await state.update_data(scheduled_time=nearest)
        kb = make_kb([
            [make_btn(f"✅ Занять {fmt_ts(nearest)} МСК", callback_data="task_publish")],
            [make_cfg_btn("btn_cancel", callback_data="cancel_action")]
        ])
        return await call.message.edit_text(
            f"⚠️ Пока вы заполняли анкету, это время заняли!\n"
            f"Ближайшее свободное окно: <b>{fmt_ts(nearest)} МСК</b>. Нажмите кнопку ниже, чтобы забронировать его:",
            reply_markup=kb
        )

    channel_id = get_setting("channel_id")

    if target_ts <= now + 5:
        post_text = render_task_template(data["platform"], data["price"], data["description"])
        try:
            sent_msg = await bot.send_message(
                chat_id=channel_id,
                text=post_text,
                reply_markup=kb_channel_active_task(call.from_user.username)
            )
        except Exception as e:
            return await call.answer(f"❌ Ошибка отправки в канал: {e}", show_alert=True)

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tasks (user_id, author_username, channel_id, message_id, platform, price, description, status, scheduled_time, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
            (call.from_user.id, call.from_user.username, channel_id, sent_msg.message_id, data["platform"], data["price"], data["description"], now, now)
        )
        cur.execute(
            "UPDATE users SET posted_count = posted_count + 1, last_post_time = ? WHERE user_id = ?",
            (now, call.from_user.id)
        )
        conn.commit()
        conn.close()

        await state.clear()
        await call.message.edit_text(
            "✅ <b>Ваше задание опубликовано в канале!</b>\n"
            "⏱ Оно автоматически закроется через <b>20 минут</b> (или вы можете закрыть его раньше вручную).",
            reply_markup=kb_main_menu(call.from_user.id)
        )
    else:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tasks (user_id, author_username, channel_id, message_id, platform, price, description, status, scheduled_time, published_at) "
            "VALUES (?, ?, ?, 0, ?, ?, ?, 'scheduled', ?, 0)",
            (call.from_user.id, call.from_user.username, channel_id, data["platform"], data["price"], data["description"], target_ts)
        )
        conn.commit()
        conn.close()

        await state.clear()
        await call.message.edit_text(
            f"📅 <b>Пост успешно занят на {fmt_ts(target_ts)} МСК!</b>\n"
            f"Бот автоматически опубликует ваше задание в указанное время и закроет его через 20 минут после выхода.",
            reply_markup=kb_main_menu(call.from_user.id)
        )


# --- ФОНОВЫЙ ПЛАНИРОВЩИК: АВТОПУБЛИКАЦИЯ (КАЖДЫЕ 15 МИН) + АВТОЗАКРЫТИЕ (ЧЕРЕЗ 20 МИН) ---
async def scheduled_posts_worker():
    while True:
        try:
            now = int(time.time())
            conn = get_conn()
            cur = conn.cursor()

            cur.execute(
                "SELECT task_id, user_id, author_username, channel_id, platform, price, description, scheduled_time "
                "FROM tasks WHERE status = 'scheduled' AND scheduled_time <= ? ORDER BY scheduled_time ASC",
                (now,)
            )
            due_tasks = cur.fetchall()

            for t_id, u_id, uname, ch_id, plat, price, desc, sched_ts in due_tasks:
                target_channel = ch_id or get_setting("channel_id")
                post_text = render_task_template(plat, price, desc)
                try:
                    sent = await bot.send_message(
                        chat_id=target_channel,
                        text=post_text,
                        reply_markup=kb_channel_active_task(uname or "username")
                    )
                    cur.execute(
                        "UPDATE tasks SET status = 'open', message_id = ?, channel_id = ?, published_at = ? WHERE task_id = ?",
                        (sent.message_id, target_channel, now, t_id)
                    )
                    cur.execute(
                        "UPDATE users SET posted_count = posted_count + 1, last_post_time = ? WHERE user_id = ?",
                        (now, u_id)
                    )
                    conn.commit()
                    try:
                        await bot.send_message(
                            u_id,
                            f"✅ <b>Ваше запланированное задание ({plat} — {price}₽) опубликовано в канале!</b>\n"
                            f"⏱ Оно автоматически закроется через 20 минут."
                        )
                    except Exception:
                        pass
                except Exception as e:
                    print(f"Ошибка автопубликации задачи #{t_id}: {e}")
                    cur.execute("UPDATE tasks SET status = 'failed' WHERE task_id = ?", (t_id,))
                    conn.commit()

            close_cutoff = now - AUTO_CLOSE_SECONDS
            cur.execute(
                "SELECT task_id, user_id, channel_id, message_id, platform, price "
                "FROM tasks WHERE status = 'open' AND published_at > 0 AND published_at <= ?",
                (close_cutoff,)
            )
            expired_tasks = cur.fetchall()

            for t_id, u_id, ch_id, msg_id, plat, price in expired_tasks:
                closed_text = get_setting("template_closed_task")
                try:
                    await bot.edit_message_text(
                        chat_id=ch_id,
                        message_id=msg_id,
                        text=closed_text,
                        reply_markup=kb_channel_closed_task()
                    )
                except Exception as e:
                    print(f"Не удалось отредактировать пост при автозакрытии #{t_id}: {e}")

                cur.execute("UPDATE tasks SET status = 'closed' WHERE task_id = ?", (t_id,))
                cur.execute("UPDATE users SET closed_count = closed_count + 1 WHERE user_id = ?", (u_id,))
                conn.commit()

                try:
                    await bot.send_message(
                        u_id,
                        f"🔒 <b>Прошло 20 минут! Ваше задание ({plat} — {price}₽) было автоматически закрыто в канале.</b>"
                    )
                except Exception:
                    pass

            conn.close()
        except Exception as e:
            print(f"Ошибка фонового воркера: {e}")

        await asyncio.sleep(5)


# --- РУЧНОЕ ЗАКРЫТИЕ ЗАДАНИЯ / ОТМЕНА БРОНИ ---
@router.callback_query(F.data == "menu_close_task")
async def cb_close_task_menu(call: CallbackQuery):
    if not has_access(call.from_user.id):
        return await call.message.edit_text(get_setting("text_no_access"), reply_markup=kb_no_access())

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT task_id, platform, price, status, scheduled_time FROM tasks "
        "WHERE user_id = ? AND status IN ('open', 'scheduled') ORDER BY task_id DESC",
        (call.from_user.id,)
    )
    active_tasks = cur.fetchall()
    conn.close()

    if not active_tasks:
        return await call.answer("У вас нет активных или запланированных заданий.", show_alert=True)

    if len(active_tasks) == 1 and active_tasks[0][3] == "open":
        await close_specific_task(call, active_tasks[0][0])
    else:
        rows = []
        for t_id, plat, price, status, sched_ts in active_tasks[:10]:
            if status == "open":
                rows.append([make_btn(f"🔒 Закрыть сейчас #{t_id} | {plat} — {price}₽", callback_data=f"close_id_{t_id}")])
            else:
                rows.append([make_btn(f"❌ Отменить бронь ({fmt_ts(sched_ts)}) | {plat}", callback_data=f"close_id_{t_id}")])
        rows.append([make_cfg_btn("btn_back", callback_data="back_to_main")])
        await call.message.edit_text("Выберите задание для досрочного закрытия в канале или отмены брони:", reply_markup=make_kb(rows))


@router.callback_query(F.data.startswith("close_id_"))
async def cb_close_specific(call: CallbackQuery):
    task_id = int(call.data.replace("close_id_", ""))
    await close_specific_task(call, task_id)


async def close_specific_task(call: CallbackQuery, task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT channel_id, message_id, status FROM tasks WHERE task_id = ? AND user_id = ?", (task_id, call.from_user.id))
    row = cur.fetchone()

    if not row or row[2] not in ("open", "scheduled"):
        conn.close()
        return await call.answer("Задание уже закрыто или не найдено.", show_alert=True)

    channel_id, message_id, status = row

    if status == "scheduled":
        cur.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        conn.commit()
        conn.close()
        return await call.message.edit_text("🗑 <b>Запланированный пост отменен, слот времени освобожден!</b>", reply_markup=kb_main_menu(call.from_user.id))

    closed_text = get_setting("template_closed_task")
    try:
        await bot.edit_message_text(
            chat_id=channel_id,
            message_id=message_id,
            text=closed_text,
            reply_markup=kb_channel_closed_task()
        )
    except Exception as e:
        conn.close()
        return await call.answer(f"⚠️ Не удалось изменить пост в канале: {e}", show_alert=True)

    cur.execute("UPDATE tasks SET status = 'closed' WHERE task_id = ?", (task_id,))
    cur.execute("UPDATE users SET closed_count = closed_count + 1 WHERE user_id = ?", (call.from_user.id,))
    conn.commit()
    conn.close()

    await call.message.edit_text("✅ <b>Задание успешно закрыто в канале!</b>", reply_markup=kb_main_menu(call.from_user.id))


# ================= АДМИН-ПАНЕЛЬ =================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def kb_admin_main() -> dict:
    return make_kb([
        [
            make_btn("👥 Пользователи", callback_data="adm_users"),
            make_btn("📅 Очередь постов", callback_data="adm_queue")
        ],
        [
            make_btn("🔑 Выдать доступ", callback_data="adm_give_sub"),
            make_btn("🚫 Забрать доступ", callback_data="adm_revoke_sub")
        ],
        [
            make_btn("📢 Канал и контакты", callback_data="adm_contacts"),
            make_btn("📝 Шаблоны и Тексты", callback_data="adm_texts")
        ],
        [
            make_btn("🔘 Названия кнопок", callback_data="adm_buttons"),
            make_btn("💎 Premium Emoji на кнопки", callback_data="adm_btn_emojis")
        ],
        [
            make_btn("🎨 Цвет кнопок", callback_data="adm_colors")
        ],
        [make_btn("🔙 В главное меню", callback_data="back_to_main")]
    ])


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("⚙️ <b>Панель администратора</b>", reply_markup=kb_admin_main())


@router.callback_query(F.data == "admin_main")
async def cb_admin_main(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.clear()
    await call.message.edit_text("⚙️ <b>Панель администратора</b>", reply_markup=kb_admin_main())


@router.callback_query(F.data == "adm_queue")
async def cb_adm_queue(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT task_id, author_username, platform, price, scheduled_time FROM tasks "
        "WHERE status = 'scheduled' ORDER BY scheduled_time ASC"
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        text = "📅 <b>Очередь запланированных постов пуста.</b>"
    else:
        lines = [f"📅 <b>Запланированные посты ({len(rows)}):</b>\n"]
        for t_id, uname, plat, price, s_ts in rows[:30]:
            lines.append(f"• <b>{fmt_ts(s_ts)} МСК</b> — @{uname} | {plat} ({price}₽)")
        text = "\n".join(lines)

    kb = make_kb([[make_btn("🔙 Назад", callback_data="admin_main")]])
    await call.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "adm_users")
async def cb_adm_users(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, sub_until, posted_count, closed_count FROM users ORDER BY sub_until DESC")
    users = cur.fetchall()
    conn.close()

    now = int(time.time())
    lines = [f"👥 <b>Всего пользователей в боте: {len(users)}</b>\n"]
    for uid, uname, sub, posted, closed in users[:40]:
        status = "✅ До " + fmt_ts(sub) if sub > now else "❌ Нет подписки"
        lines.append(f"• @{uname} (<code>{uid}</code>) — {status} | Выкл: {posted} / Закр: {closed}")

    if len(users) > 40:
        lines.append(f"\n<i>...и еще {len(users) - 40} пользователей.</i>")

    kb = make_kb([[make_btn("🔙 Назад", callback_data="admin_main")]])
    await call.message.edit_text("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data == "adm_give_sub")
async def cb_adm_give_sub(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminSG.give_sub_user)
    kb = make_kb([[make_btn("🔙 Отмена", callback_data="admin_main")]])
    await call.message.edit_text("👤 Введите <b>Telegram ID</b> или <b>@username</b> пользователя для выдачи подписки:", reply_markup=kb)


@router.message(AdminSG.give_sub_user)
async def msg_adm_give_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    target = message.text.strip().lstrip("@")
    await state.update_data(target_user=target)
    await state.set_state(AdminSG.give_sub_days)
    await message.answer("⏳ На сколько <b>дней</b> выдать подписку? (например <code>0.5</code> для 12 часов или <code>30</code> для месяца):")


@router.message(AdminSG.give_sub_days)
async def msg_adm_give_days(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        days = float(message.text.replace(",", ".").strip())
    except ValueError:
        return await message.answer("❌ Введите корректное число дней!")

    data = await state.get_data()
    target = data["target_user"]
    sub_until = int(time.time() + days * 86400)

    conn = get_conn()
    cur = conn.cursor()
    if target.isdigit():
        cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (int(target), "Неизвестно"))
        cur.execute("UPDATE users SET sub_until = ? WHERE user_id = ?", (sub_until, int(target)))
    else:
        cur.execute("UPDATE users SET sub_until = ? WHERE LOWER(username) = LOWER(?)", (sub_until, target))

    affected = cur.rowcount
    conn.commit()
    conn.close()
    await state.clear()

    if affected == 0:
        await message.answer("⚠️ Пользователь с таким @username еще не нажимал /start в боте. Попросите его запустить бота или выдайте доступ по числовому ID.", reply_markup=kb_admin_main())
    else:
        await message.answer(f"✅ Доступ для <b>{target}</b> успешно выдан до <b>{fmt_ts(sub_until)} МСК</b>!", reply_markup=kb_admin_main())


@router.callback_query(F.data == "adm_revoke_sub")
async def cb_adm_revoke(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminSG.revoke_sub_user)
    kb = make_kb([[make_btn("🔙 Отмена", callback_data="admin_main")]])
    await call.message.edit_text("🚫 Введите <b>ID</b> или <b>@username</b> пользователя, у которого нужно забрать доступ:", reply_markup=kb)


@router.message(AdminSG.revoke_sub_user)
async def msg_adm_revoke_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    target = message.text.strip().lstrip("@")
    conn = get_conn()
    cur = conn.cursor()
    if target.isdigit():
        cur.execute("UPDATE users SET sub_until = 0 WHERE user_id = ?", (int(target),))
    else:
        cur.execute("UPDATE users SET sub_until = 0 WHERE LOWER(username) = LOWER(?)", (target,))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer(f"✅ Доступ у пользователя <b>{target}</b> аннулирован.", reply_markup=kb_admin_main())


@router.callback_query(F.data == "adm_contacts")
async def cb_adm_contacts(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    keys = ["channel_id", "access_contact", "support_contact"]
    rows = [[make_btn(SETTING_LABELS[k], callback_data=f"editset_{k}")] for k in keys]
    rows.append([make_btn("🔙 Назад", callback_data="admin_main")])
    await call.message.edit_text(
        f"📢 <b>Текущие настройки:</b>\n"
        f"• Канал: <code>{get_setting('channel_id') or 'Не задан'}</code>\n"
        f"• Контакт доступа: @{get_setting('access_contact').lstrip('@')}\n"
        f"• Контакт поддержки: @{get_setting('support_contact').lstrip('@')}",
        reply_markup=make_kb(rows)
    )


@router.callback_query(F.data == "adm_texts")
async def cb_adm_texts(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    keys = [
        "template_new_task", "template_closed_task", "text_no_access",
        "text_main_menu", "text_choose_platform", "text_enter_custom_platform",
        "text_enter_price", "text_enter_desc", "text_preview"
    ]
    rows = [[make_btn(SETTING_LABELS[k], callback_data=f"editset_{k}")] for k in keys]
    rows.append([make_btn("🔙 Назад", callback_data="admin_main")])
    await call.message.edit_text(
        "📝 <b>Редактирование текстов и шаблонов</b>\n\n"
        "💡 Вы можете отправлять сообщения с <b>любым форматированием</b> и <b>Premium Emoji</b> — бот автоматически сохранит их!",
        reply_markup=make_kb(rows)
    )


@router.callback_query(F.data == "adm_buttons")
async def cb_adm_buttons(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    rows = []
    for i in range(0, len(BUTTON_KEYS), 2):
        row = [make_btn(SETTING_LABELS[BUTTON_KEYS[i]], callback_data=f"editset_{BUTTON_KEYS[i]}")]
        if i + 1 < len(BUTTON_KEYS):
            row.append(make_btn(SETTING_LABELS[BUTTON_KEYS[i + 1]], callback_data=f"editset_{BUTTON_KEYS[i + 1]}"))
        rows.append(row)
    rows.append([make_btn("🔙 Назад", callback_data="admin_main")])
    await call.message.edit_text(
        "🔘 <b>Выберите кнопку для изменения её названия:</b>\n"
        "<i>(Если вы отправите текст вместе с Premium Emoji, бот автоматически установит и текст, и Premium Emoji на кнопку!)</i>",
        reply_markup=make_kb(rows)
    )


# --- НОВЫЙ РАЗДЕЛ: PREMIUM EMOJI НА КНОПКИ ---
@router.callback_query(F.data == "adm_btn_emojis")
async def cb_adm_btn_emojis(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.clear()
    rows = []
    for i in range(0, len(BUTTON_KEYS), 2):
        k1 = BUTTON_KEYS[i]
        em1 = "💎" if get_setting(f"emoji_{k1}") else "⚪️"
        row = [make_btn(f"{em1} {SETTING_LABELS[k1].replace('Кнопка: ', '').replace('Кнопка в канале: ', '')}", callback_data=f"btnemoji_{k1}")]
        if i + 1 < len(BUTTON_KEYS):
            k2 = BUTTON_KEYS[i + 1]
            em2 = "💎" if get_setting(f"emoji_{k2}") else "⚪️"
            row.append(make_btn(f"{em2} {SETTING_LABELS[k2].replace('Кнопка: ', '').replace('Кнопка в канале: ', '')}", callback_data=f"btnemoji_{k2}"))
        rows.append(row)
    rows.append([make_btn("🔙 Назад", callback_data="admin_main")])

    await call.message.edit_text(
        "💎 <b>Установка Premium Emoji на кнопки</b>\n\n"
        "• 💎 — на кнопке установлен Premium Emoji\n"
        "• ⚪️ — без кастомного эмодзи\n\n"
        "Выберите кнопку, чтобы привязать или изменить на ней Premium Emoji:",
        reply_markup=make_kb(rows)
    )


@router.callback_query(F.data.startswith("btnemoji_"))
async def cb_select_btn_emoji(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    btn_key = call.data.replace("btnemoji_", "")
    await state.update_data(emoji_btn_key=btn_key)
    await state.set_state(AdminSG.edit_btn_emoji)

    curr_id = get_setting(f"emoji_{btn_key}")
    curr_status = f"<code>{curr_id}</code> (<tg-emoji emoji-id=\"{curr_id}\">⭐️</tg-emoji>)" if curr_id else "Не установлен"

    rows = [
        [make_btn("🗑 Удалить Premium Emoji с этой кнопки", callback_data=f"clearemoji_{btn_key}")],
        [make_btn("🔙 К списку кнопок", callback_data="adm_btn_emojis")]
    ]
    await call.message.edit_text(
        f"💎 <b>Настройка Premium Emoji для:</b> {SETTING_LABELS.get(btn_key, btn_key)}\n"
        f"Текст кнопки сейчас: <b>{get_setting(btn_key)}</b>\n"
        f"Текущий Premium Emoji: {curr_status}\n\n"
        f"👇 <b>Отправьте сообщение с нужным Premium Emoji (или его числовым ID):</b>",
        reply_markup=make_kb(rows)
    )


@router.callback_query(F.data.startswith("clearemoji_"))
async def cb_clear_btn_emoji(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    btn_key = call.data.replace("clearemoji_", "")
    set_setting(f"emoji_{btn_key}", "")
    await call.answer("✅ Premium Emoji удален с кнопки!")
    await cb_adm_btn_emojis(call, state)


@router.message(AdminSG.edit_btn_emoji)
async def msg_save_btn_emoji(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    btn_key = data["emoji_btn_key"]

    emoji_id = extract_custom_emoji_id(message)
    if not emoji_id:
        return await message.answer(
            "❌ Не удалось обнаружить Premium Emoji в вашем сообщении!\n"
            "Отправьте именно кастомный <b>Telegram Premium Emoji</b> или его числовой ID (например, <code>5368324170671202286</code>):"
        )

    set_setting(f"emoji_{btn_key}", emoji_id)
    await state.clear()
    await message.answer(
        f"✅ <b>Premium Emoji</b> (<tg-emoji emoji-id=\"{emoji_id}\">⭐️</tg-emoji> <code>{emoji_id}</code>) успешно установлен на кнопку <b>{SETTING_LABELS.get(btn_key, btn_key)}</b>!",
        reply_markup=kb_admin_main()
    )


# --- ЦВЕТА И СТИЛИ КНОПОК ---
@router.callback_query(F.data == "adm_colors")
async def cb_adm_colors(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return

    styles = [
        ("Стандартный фон API", ""),
        ("🟦 Синий фон API (primary)", "primary"),
        ("🟩 Зеленый фон API (success)", "success"),
        ("🟥 Красный фон API (danger)", "danger")
    ]
    colors = [
        ("Без маркера", ""),
        ("🔴 Красный маркер", "🔴"),
        ("🟢 Зеленый маркер", "🟢"),
        ("🔵 Синий маркер", "🔵"),
        ("🟡 Желтый маркер", "🟡"),
        ("🟣 Фиолетовый маркер", "🟣"),
        ("⚫️ Черный маркер", "⚫️")
    ]

    rows = []
    for label, val in styles:
        rows.append([make_btn(label, callback_data=f"setstyle_{val}", style=val if val else None)])
    for label, val in colors:
        rows.append([make_btn(label, callback_data=f"setcolor_{val}")])
    rows.append([make_btn("🔙 Назад", callback_data="admin_main")])

    curr_style = get_setting("btn_style") or "Стандартный"
    curr_color = get_setting("btn_color") or "Без маркера"
    await call.message.edit_text(
        f"🎨 <b>Настройка цвета и стиля инлайн-кнопок</b>\n\n"
        f"• Нативный стиль кнопок (Bot API): <b>{curr_style}</b>\n"
        f"• Цветовой маркер: <b>{curr_color}</b>",
        reply_markup=make_kb(rows)
    )


@router.callback_query(F.data.startswith("setstyle_"))
async def cb_set_style(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    style_val = call.data.replace("setstyle_", "")
    set_setting("btn_style", style_val)
    await call.answer("✅ Нативный цвет кнопок обновлен!")
    await cb_adm_colors(call)


@router.callback_query(F.data.startswith("setcolor_"))
async def cb_set_color(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    color_val = call.data.replace("setcolor_", "")
    set_setting("btn_color", color_val)
    await call.answer("✅ Цветовой маркер кнопок обновлен!")
    await cb_adm_colors(call)


@router.callback_query(F.data.startswith("editset_"))
async def cb_edit_setting(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    key = call.data.replace("editset_", "")
    await state.update_data(edit_key=key)
    await state.set_state(AdminSG.edit_setting_value)

    current_val = get_setting(key)
    hint = ""
    if key == "template_new_task":
        hint = "\n\n📌 <b>Доступные переменные:</b>\n<code>{platform}</code> — платформа\n<code>{cena}</code> — цена\n<code>{opisanie}</code> — описание (автоматически цитируется)"
    elif key == "text_preview":
        hint = "\n\n📌 Обязательно используйте переменную <code>{preview}</code> для отображения карточки задания."
    elif key.startswith("btn_"):
        em_id = get_setting(f"emoji_{key}")
        if em_id:
            hint = f"\n💎 Привязанный Premium Emoji ID: <code>{em_id}</code>"

    kb = make_kb([[make_btn("🔙 Отмена", callback_data="admin_main")]])
    await call.message.edit_text(
        f"✏️ <b>Редактирование:</b> {SETTING_LABELS.get(key, key)}\n\n"
        f"<b>Текущее значение:</b>\n{current_val}{hint}\n\n"
        f"👇 <b>Отправьте новое значение ответным сообщением:</b>",
        reply_markup=kb
    )


@router.message(AdminSG.edit_setting_value)
async def msg_save_setting(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    key = data["edit_key"]

    if key in ("channel_id", "access_contact", "support_contact"):
        new_val = (message.text or "").strip()
        set_setting(key, new_val)
    elif key.startswith("btn_"):
        # Если админ отправил текст кнопки вместе с Premium Emoji — сохраняем и текст, и icon_custom_emoji_id!
        emoji_id = extract_custom_emoji_id(message)
        raw_text = message.text or ""
        if emoji_id and message.entities:
            # Убираем дублирующийся стандартный смайлик в начале, если он прикреплен как icon_custom_emoji_id
            for ent in message.entities:
                if ent.type == "custom_emoji" and ent.offset == 0:
                    raw_text = raw_text[ent.length:].strip()
                    break
            set_setting(f"emoji_{key}", emoji_id)
        set_setting(key, raw_text.strip() or (message.text or "").strip())
    else:
        new_val = message.html_text.strip()
        set_setting(key, new_val)

    await state.clear()
    await message.answer(f"✅ Параметр <b>{SETTING_LABELS.get(key, key)}</b> успешно обновлен!", reply_markup=kb_admin_main())


# ================= ЗАПУСК БОТА =================
async def main():
    init_db()
    asyncio.create_task(scheduled_posts_worker())
    print("Бот запущен: поддержка Premium Emoji на кнопках и текстах активна!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
