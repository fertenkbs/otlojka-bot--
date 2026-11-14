import asyncio
import html
import sqlite3
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)

# ================= КОНФИГУРАЦИЯ =================
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"
ADMIN_IDS = [123456789, 987654321]  # Укажите Telegram ID администраторов (можно 2 и более)
DB_PATH = "bot_database.db"
COOLDOWN_SECONDS = 20 * 60  # 20 минут ограничение между публикациями
# ================================================

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)


# ================= БАЗА ДАННЫХ =================
def init_db():
    conn = sqlite3.connect(DB_PATH)
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
            channel_id TEXT,
            message_id INTEGER,
            platform TEXT,
            price TEXT,
            description TEXT,
            status TEXT DEFAULT 'open'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    default_settings = {
        # Технические настройки
        "channel_id": "",
        "access_contact": "elenesing",
        "support_contact": "help_freecash",
        "btn_color": "",  # Цветовой маркер кнопок

        # Тексты и шаблоны (поддерживают HTML и <tg-emoji>)
        "text_no_access": "❌ <b>У вас нету доступа.</b>\nЧтобы получить доступ, напишите: @elenesing",
        "text_main_menu": "👋 <b>Добро пожаловать в панель управления заданиями!</b>\nВыберите нужное действие ниже:",
        "text_choose_platform": "📌 <b>Выберите платформу для задания:</b>",
        "text_enter_custom_platform": "✍️ <b>Введите название платформы:</b>",
        "text_enter_price": "💰 <b>Введите цену в рублях (₽):</b>",
        "text_enter_desc": "📝 <b>Введите описание задания:</b>",
        "text_preview": "👀 <b>Предпросмотр вашего задания:</b>\n\n{preview}\n\nПодтвердите публикацию:",
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

        # Названия всех инлайн-кнопок
        "btn_get_access": "🔑 Получить доступ",
        "btn_post_task": "📤 Выложить задание",
        "btn_profile": "👤 Профиль",
        "btn_close_task": "🔒 Закрыть задание",
        "btn_p_2gis": "2ГИС",
        "btn_p_yamaps": "Яндекс карты",
        "btn_p_gmaps": "Гугл карты",
        "btn_p_yabrowser": "Яндекс Браузер",
        "btn_p_other": "Другое...",
        "btn_confirm_post": "✅ Выложить задание",
        "btn_cancel": "❌ Отменить",
        "btn_support": "🛟 Поддержка",
        "btn_take_task": "⚡️ Взять задание",
        "btn_back": "🔙 Назад"
    }

    for k, v in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()


def get_setting(key: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else ""


def set_setting(key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def register_or_update_user(user_id: int, username: str):
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
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


def btn_label(key: str) -> str:
    """Формирует текст кнопки с учетом выбранного в админке цветового маркера."""
    color = get_setting("btn_color")
    text = get_setting(key)
    return f"{color} {text}".strip() if color else text


# ================= FSM СОСТОЯНИЯ =================
class CreateTaskSG(StatesGroup):
    platform_custom = State()
    price = State()
    description = State()
    confirm = State()


class AdminSG(StatesGroup):
    give_sub_user = State()
    give_sub_days = State()
    revoke_sub_user = State()
    edit_setting_value = State()


# ================= КЛАВИАТУРЫ =================
def kb_no_access() -> InlineKeyboardMarkup:
    contact = get_setting("access_contact").lstrip("@")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn_label("btn_get_access"), url=f"https://t.me/{contact}")]
    ])


def kb_main_menu(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=btn_label("btn_post_task"), callback_data="menu_post_task")],
        [
            InlineKeyboardButton(text=btn_label("btn_profile"), callback_data="menu_profile"),
            InlineKeyboardButton(text=btn_label("btn_close_task"), callback_data="menu_close_task")
        ]
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_platforms() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=btn_label("btn_p_2gis"), callback_data="plat_p_2gis"),
            InlineKeyboardButton(text=btn_label("btn_p_yamaps"), callback_data="plat_p_yamaps")
        ],
        [
            InlineKeyboardButton(text=btn_label("btn_p_gmaps"), callback_data="plat_p_gmaps"),
            InlineKeyboardButton(text=btn_label("btn_p_yabrowser"), callback_data="plat_p_yabrowser")
        ],
        [InlineKeyboardButton(text=btn_label("btn_p_other"), callback_data="plat_other")],
        [InlineKeyboardButton(text=btn_label("btn_cancel"), callback_data="cancel_action")]
    ])


def kb_confirm_task() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn_label("btn_confirm_post"), callback_data="task_publish")],
        [InlineKeyboardButton(text=btn_label("btn_cancel"), callback_data="cancel_action")]
    ])


def kb_channel_active_task(author_username: str) -> InlineKeyboardMarkup:
    support = get_setting("support_contact").lstrip("@")
    author = author_username.lstrip("@")
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=btn_label("btn_take_task"), url=f"https://t.me/{author}"),
            InlineKeyboardButton(text=btn_label("btn_support"), url=f"https://t.me/{support}")
        ]
    ])


def kb_channel_closed_task() -> InlineKeyboardMarkup:
    support = get_setting("support_contact").lstrip("@")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn_label("btn_support"), url=f"https://t.me/{support}")]
    ])


def kb_back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn_label("btn_back"), callback_data="back_to_main")]
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
        sub_str = datetime.fromtimestamp(sub_until).strftime("%d.%m.%Y %H:%M")

    text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🆔 ID: <code>{call.from_user.id}</code>\n"
        f"⏳ Подписка активна до: <b>{sub_str}</b>\n\n"
        f"📤 Выложено заданий: <b>{posted}</b>\n"
        f"🔒 Закрыто заданий: <b>{closed}</b>"
    )
    await call.message.edit_text(text, reply_markup=kb_back_to_menu())


# --- СОЗДАНИЕ ЗАДАНИЯ ---
@router.callback_query(F.data == "menu_post_task")
async def cb_post_task(call: CallbackQuery, state: FSMContext):
    if not has_access(call.from_user.id):
        return await call.message.edit_text(get_setting("text_no_access"), reply_markup=kb_no_access())

    if not call.from_user.username:
        return await call.answer("⚠️ Установите @username в настройках Telegram, чтобы заказчики могли вам написать!", show_alert=True)

    channel_id = get_setting("channel_id")
    if not channel_id:
        return await call.answer("⚠️ Канал для публикаций еще не настроен администратором!", show_alert=True)

    user = get_user(call.from_user.id)
    last_post = user[5]
    now = int(time.time())
    if call.from_user.id not in ADMIN_IDS and (now - last_post) < COOLDOWN_SECONDS:
        left_min = ((COOLDOWN_SECONDS - (now - last_post)) // 60) + 1
        return await call.answer(f"⏳ Ограничение! Вы сможете выложить следующее задание через {left_min} мин.", show_alert=True)

    await state.clear()
    await call.message.edit_text(get_setting("text_choose_platform"), reply_markup=kb_platforms())


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
    # Если в шаблоне еще нет тега <blockquote> вокруг {opisanie}, оборачиваем цитатой автоматически
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

    # html_text сохраняет кастомные премиум-эмодзи и форматирование пользователя
    desc_html = message.html_text.strip()
    await state.update_data(description=desc_html)
    data = await state.get_data()

    preview_post = render_task_template(data["platform"], data["price"], desc_html)
    preview_wrapper = get_setting("text_preview").replace("{preview}", preview_post)

    await state.set_state(CreateTaskSG.confirm)
    await message.answer(preview_wrapper, reply_markup=kb_confirm_task())


@router.callback_query(CreateTaskSG.confirm, F.data == "task_publish")
async def cb_task_publish(call: CallbackQuery, state: FSMContext):
    if not has_access(call.from_user.id):
        return await call.message.edit_text(get_setting("text_no_access"), reply_markup=kb_no_access())

    user = get_user(call.from_user.id)
    now = int(time.time())
    if call.from_user.id not in ADMIN_IDS and (now - user[5]) < COOLDOWN_SECONDS:
        left_min = ((COOLDOWN_SECONDS - (now - user[5])) // 60) + 1
        return await call.answer(f"⏳ Подождите еще {left_min} мин. перед публикацией!", show_alert=True)

    data = await state.get_data()
    channel_id = get_setting("channel_id")
    post_text = render_task_template(data["platform"], data["price"], data["description"])

    try:
        sent_msg = await bot.send_message(
            chat_id=channel_id,
            text=post_text,
            reply_markup=kb_channel_active_task(call.from_user.username)
        )
    except Exception as e:
        return await call.answer(f"❌ Ошибка отправки в канал: {e}", show_alert=True)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tasks (user_id, channel_id, message_id, platform, price, description) VALUES (?, ?, ?, ?, ?, ?)",
        (call.from_user.id, channel_id, sent_msg.message_id, data["platform"], data["price"], data["description"])
    )
    cur.execute(
        "UPDATE users SET posted_count = posted_count + 1, last_post_time = ? WHERE user_id = ?",
        (now, call.from_user.id)
    )
    conn.commit()
    conn.close()

    await state.clear()
    await call.message.edit_text("✅ <b>Ваше задание успешно опубликовано в канале!</b>", reply_markup=kb_main_menu(call.from_user.id))


# --- ЗАКРЫТИЕ ЗАДАНИЯ ---
@router.callback_query(F.data == "menu_close_task")
async def cb_close_task_menu(call: CallbackQuery):
    if not has_access(call.from_user.id):
        return await call.message.edit_text(get_setting("text_no_access"), reply_markup=kb_no_access())

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT task_id, platform, price FROM tasks WHERE user_id = ? AND status = 'open' ORDER BY task_id DESC", (call.from_user.id,))
    open_tasks = cur.fetchall()
    conn.close()

    if not open_tasks:
        return await call.answer("У вас нет активных (открытых) заданий.", show_alert=True)

    # Если у пользователя 1 открытое задание — закрываем сразу, если несколько — даем выбор
    if len(open_tasks) == 1:
        await close_specific_task(call, open_tasks[0][0])
    else:
        kb = []
        for t_id, plat, price in open_tasks[:10]:
            kb.append([InlineKeyboardButton(text=f"🔒 #{t_id} | {plat} — {price}₽", callback_data=f"close_id_{t_id}")])
        kb.append([InlineKeyboardButton(text=btn_label("btn_back"), callback_data="back_to_main")])
        await call.message.edit_text("Выберите задание, которое хотите закрыть:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("close_id_"))
async def cb_close_specific(call: CallbackQuery):
    task_id = int(call.data.replace("close_id_", ""))
    await close_specific_task(call, task_id)


async def close_specific_task(call: CallbackQuery, task_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT channel_id, message_id, status FROM tasks WHERE task_id = ? AND user_id = ?", (task_id, call.from_user.id))
    row = cur.fetchone()

    if not row or row[2] != "open":
        conn.close()
        return await call.answer("Задание уже закрыто или не найдено.", show_alert=True)

    channel_id, message_id, _ = row
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


def kb_admin_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users"),
            InlineKeyboardButton(text="🔑 Выдать доступ", callback_data="adm_give_sub")
        ],
        [
            InlineKeyboardButton(text="🚫 Забрать доступ", callback_data="adm_revoke_sub"),
            InlineKeyboardButton(text="📢 Канал и контакты", callback_data="adm_contacts")
        ],
        [
            InlineKeyboardButton(text="📝 Шаблоны и Тексты (Premium Emoji)", callback_data="adm_texts")
        ],
        [
            InlineKeyboardButton(text="🔘 Названия кнопок", callback_data="adm_buttons"),
            InlineKeyboardButton(text="🎨 Цвет кнопок", callback_data="adm_colors")
        ],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_main")]
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


# --- СПИСОК ПОЛЬЗОВАТЕЛЕЙ ---
@router.callback_query(F.data == "adm_users")
async def cb_adm_users(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, sub_until, posted_count, closed_count FROM users ORDER BY sub_until DESC")
    users = cur.fetchall()
    conn.close()

    now = int(time.time())
    lines = [f"👥 <b>Всего пользователей в боте: {len(users)}</b>\n"]
    for uid, uname, sub, posted, closed in users[:40]:
        status = "✅ Активен до " + datetime.fromtimestamp(sub).strftime("%d.%m %H:%M") if sub > now else "❌ Нет подписки"
        lines.append(f"• @{uname} (<code>{uid}</code>) — {status} | Выкл: {posted} / Закр: {closed}")

    if len(users) > 40:
        lines.append(f"\n<i>...и еще {len(users) - 40} пользователей.</i>")

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")]])
    await call.message.edit_text("\n".join(lines), reply_markup=kb)


# --- ВЫДАЧА / ОТЗЫВ ПОДПИСКИ ---
@router.callback_query(F.data == "adm_give_sub")
async def cb_adm_give_sub(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminSG.give_sub_user)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_main")]])
    await call.message.edit_text("👤 Введите <b>Telegram ID</b> или <b>@username</b> пользователя для выдачи подписки:", reply_markup=kb)


@router.message(AdminSG.give_sub_user)
async def msg_adm_give_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    target = message.text.strip().lstrip("@")
    await state.update_data(target_user=target)
    await state.set_state(AdminSG.give_sub_days)
    await message.answer("⏳ На сколько <b>дней</b> выдать подписку? (Можно ввести дробное число, например <code>0.5</code> для 12 часов или <code>30</code> для месяца):")


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

    conn = sqlite3.connect(DB_PATH)
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
        dt_str = datetime.fromtimestamp(sub_until).strftime("%d.%m.%Y %H:%M")
        await message.answer(f"✅ Доступ для <b>{target}</b> успешно выдан до <b>{dt_str}</b>!", reply_markup=kb_admin_main())


@router.callback_query(F.data == "adm_revoke_sub")
async def cb_adm_revoke(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminSG.revoke_sub_user)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_main")]])
    await call.message.edit_text("🚫 Введите <b>ID</b> или <b>@username</b> пользователя, у которого нужно забрать доступ:", reply_markup=kb)


@router.message(AdminSG.revoke_sub_user)
async def msg_adm_revoke_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    target = message.text.strip().lstrip("@")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if target.isdigit():
        cur.execute("UPDATE users SET sub_until = 0 WHERE user_id = ?", (int(target),))
    else:
        cur.execute("UPDATE users SET sub_until = 0 WHERE LOWER(username) = LOWER(?)", (target,))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer(f"✅ Доступ у пользователя <b>{target}</b> аннулирован.", reply_markup=kb_admin_main())


# --- УНИВЕРСАЛЬНОЕ РЕДАКТИРОВАНИЕ НАСТРОЕК (ТЕКСТЫ, ШАБЛОНЫ, КНОПКИ, КАНАЛ) ---
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
    "btn_post_task": "Кнопка: Выложить задание",
    "btn_profile": "Кнопка: Профиль",
    "btn_close_task": "Кнопка: Закрыть задание",
    "btn_p_2gis": "Кнопка: 2ГИС",
    "btn_p_yamaps": "Кнопка: Яндекс карты",
    "btn_p_gmaps": "Кнопка: Гугл карты",
    "btn_p_yabrowser": "Кнопка: Яндекс Браузер",
    "btn_p_other": "Кнопка: Другое...",
    "btn_confirm_post": "Кнопка: Подтвердить публикацию",
    "btn_cancel": "Кнопка: Отменить",
    "btn_support": "Кнопка в канале: Поддержка",
    "btn_take_task": "Кнопка в канале: Взять задание",
    "btn_back": "Кнопка: Назад"
}


@router.callback_query(F.data == "adm_contacts")
async def cb_adm_contacts(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    keys = ["channel_id", "access_contact", "support_contact"]
    kb = [[InlineKeyboardButton(text=SETTING_LABELS[k], callback_data=f"editset_{k}")] for k in keys]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")])
    await call.message.edit_text(
        f"📢 <b>Текущие настройки:</b>\n"
        f"• Канал: <code>{get_setting('channel_id') or 'Не задан'}</code>\n"
        f"• Контакт доступа: @{get_setting('access_contact').lstrip('@')}\n"
        f"• Контакт поддержки: @{get_setting('support_contact').lstrip('@')}\n\n"
        f"<i>Бота необходимо добавить в администраторы канала с правом публикации и изменения сообщений!</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
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
    kb = [[InlineKeyboardButton(text=SETTING_LABELS[k], callback_data=f"editset_{k}")] for k in keys]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")])
    await call.message.edit_text(
        "📝 <b>Редактирование текстов и шаблонов</b>\n\n"
        "💡 Вы можете отправлять сообщения с <b>любым форматированием</b> и <b>Premium Emoji</b> — бот автоматически считает их и сохранит!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


@router.callback_query(F.data == "adm_buttons")
async def cb_adm_buttons(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    keys = [k for k in SETTING_LABELS.keys() if k.startswith("btn_")]
    kb = []
    for i in range(0, len(keys), 2):
        row = [InlineKeyboardButton(text=SETTING_LABELS[keys[i]], callback_data=f"editset_{keys[i]}")]
        if i + 1 < len(keys):
            row.append(InlineKeyboardButton(text=SETTING_LABELS[keys[i + 1]], callback_data=f"editset_{keys[i + 1]}"))
        kb.append(row)
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")])
    await call.message.edit_text("🔘 <b>Выберите кнопку для изменения её текста/эмодзи:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "adm_colors")
async def cb_adm_colors(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    colors = [
        ("Без маркера", ""),
        ("🔴 Красный", "🔴"),
        ("🟢 Зеленый", "🟢"),
        ("🔵 Синий", "🔵"),
        ("🟡 Желтый", "🟡"),
        ("🟣 Фиолетовый", "🟣"),
        ("⚫️ Черный", "⚫️")
    ]
    kb = [[InlineKeyboardButton(text=label, callback_data=f"setcolor_{val}")] for label, val in colors]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")])
    curr = get_setting("btn_color") or "Без маркера"
    await call.message.edit_text(f"🎨 <b>Выберите цветовой стиль инлайн-кнопок</b>\nТекущий: {curr}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("setcolor_"))
async def cb_set_color(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    color_val = call.data.replace("setcolor_", "")
    set_setting("btn_color", color_val)
    await call.answer("✅ Цветовой стиль кнопок обновлен!")
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

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_main")]])
    await call.message.edit_text(
        f"✏️ <b>Редактирование:</b> {SETTING_LABELS.get(key, key)}\n\n"
        f"<b>Текущее значение:</b>\n{current_val}{hint}\n\n"
        f"👇 <b>Отправьте новое значение ответным сообщением (поддерживаются Premium Emoji и форматирование):</b>",
        reply_markup=kb
    )


@router.message(AdminSG.edit_setting_value)
async def msg_save_setting(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    key = data["edit_key"]

    # Для технических полей и обычных кнопок берем чистый текст, для шаблонов и сообщений — html_text (с <tg-emoji>)
    if key in ("channel_id", "access_contact", "support_contact") or key.startswith("btn_"):
        new_val = message.text.strip()
    else:
        new_val = message.html_text.strip()

    set_setting(key, new_val)
    await state.clear()
    await message.answer(f"✅ Параметр <b>{SETTING_LABELS.get(key, key)}</b> успешно обновлен!", reply_markup=kb_admin_main())


# ================= ЗАПУСК БОТА =================
async def main():
    init_db()
    print("Бот успешно запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
