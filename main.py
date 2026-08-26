import asyncio
import sqlite3
import random
import string
from datetime import datetime, timedelta
import os
import aiohttp
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# ==================== КОНФИГУРАЦИЯ ====================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан! Добавьте его в переменные окружения.")

# ADMIN_IDS задаётся через env как строка "123456789,987654321"
_admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip().isdigit()]

# ID группового чата для логов
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "-5487311704"))

# ==================== КУРСЫ ВАЛЮТ ====================
async def get_rates(rub_amount: int) -> str:
    """Конвертирует рубли в USD, UZS, TJS по актуальному курсу."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.exchangerate-api.com/v4/latest/RUB",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                data = await resp.json()
                rates = data.get("rates", {})
                usd = round(rub_amount * rates.get("USD", 0), 2)
                uzs = round(rub_amount * rates.get("UZS", 0))
                tjs = round(rub_amount * rates.get("TJS", 0), 1)
                return f"<b>{rub_amount}₽</b> | <b>{usd}$</b> | <b>{uzs:,} сум</b> | <b>{tjs} сомони</b>".replace(",", " ")
    except Exception:
        # Фоллбэк на фиксированные курсы если API недоступен
        usd = round(rub_amount / 90, 2)
        uzs = round(rub_amount * 140)
        tjs = round(rub_amount * 10.5, 1)
        return f"<b>{rub_amount}₽</b> | <b>{usd}$</b> | <b>{uzs} сум</b> | <b>{tjs} сомони</b>"

# ==================== РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ ====================
PAYMENT_DETAILS = """
💳 РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ:

🏦 АЛЬФА БАНК
📱 +992003443844

🏦 ДУШАНБЕ СИТИ
📱 По номеру: +992003443844
💳 Карта: 5058270377765135

🏦 СБЕРБАНК
📱 +7 977 176-68-84

🏦 Т-БАНК
📱 +7 985 435-31-15

📝 ИНСТРУКЦИЯ:
1. Переведите сумму на любой из указанных реквизитов
2. Отправьте скриншот платежа в техподдержку
3. Дождитесь пополнения баланса (до 5 минут)
"""

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self, db_name=None):
        if db_name is None:
            import os
            db_name = os.getenv("DB_PATH", "shop.db")
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        # Таблица пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                registered_at TEXT
            )
        ''')

        # Таблица обработанных заявок (защита от двойного нажатия)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_requests (
                message_id INTEGER PRIMARY KEY
            )
        ''')

        # Таблица файлов товаров
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS product_files (
                category TEXT PRIMARY KEY,
                file_id TEXT,
                file_type TEXT
            )
        ''')

        # Таблица ключей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS keys (
                key TEXT PRIMARY KEY,
                user_id INTEGER,
                password TEXT,
                expiry_date TEXT,
                status TEXT DEFAULT 'active',
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # Таблица товаров
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                category TEXT,
                price INTEGER,
                description TEXT
            )
        ''')

        # Добавляем товары, если их нет
        self.cursor.execute('SELECT COUNT(*) FROM products')
        if self.cursor.fetchone()[0] == 0:
            products = [
                # AIM BOT PC
                ("Aim Bot - 1 день",   "AIM BOT PC",  88,   "Доступ на 1 день"),
                ("Aim Bot - 7 дней",   "AIM BOT PC",  444,  "Доступ на 7 дней"),
                ("Aim Bot - 30 дней",  "AIM BOT PC",  1000, "Доступ на 30 дней"),
                # PRIVATE PC
                ("Private - 1 день",   "PRIVATE PC",  120,  "Доступ на 1 день"),
                ("Private - 7 дней",   "PRIVATE PC",  555,  "Доступ на 7 дней"),
                ("Private - 30 дней",  "PRIVATE PC",  1300, "Доступ на 30 дней"),
                # BASIC PC
                ("Basic - 1 день",     "BASIC PC",    150,  "Доступ на 1 день"),
                ("Basic - 7 дней",     "BASIC PC",    700,  "Доступ на 7 дней"),
                ("Basic - 30 дней",    "BASIC PC",    1200, "Доступ на 30 дней"),
                # BR MOD PC
                ("BR Mod PC - 1 день",  "BR MOD PC",  150,  "Доступ на 1 день"),
                ("BR Mod PC - 7 дней",  "BR MOD PC",  700,  "Доступ на 7 дней"),
                ("BR Mod PC - 30 дней", "BR MOD PC",  1200, "Доступ на 30 дней"),
                # DRIP CLIENT ANDROID
                ("Drip Client - 1 день",  "DRIP CLIENT", 111, "Доступ на 1 день"),
                ("Drip Client - 7 дней",  "DRIP CLIENT", 333, "Доступ на 7 дней"),
                ("Drip Client - 30 дней", "DRIP CLIENT", 888, "Доступ на 30 дней"),
                # HG CHEATS ANDROID
                ("HG Cheats - 10 дней", "HG CHEATS", 499, "Доступ на 10 дней"),
                ("HG Cheats - 30 дней", "HG CHEATS", 888, "Доступ на 30 дней"),
                # PRIME MOD ANDROID
                ("Prime Mod - 5 дней",  "PRIME MOD", 300, "Доступ на 5 дней"),
                ("Prime Mod - 10 дней", "PRIME MOD", 500, "Доступ на 10 дней"),
                # FLOURITE PANEL IOS
                ("Flourite Panel - 1 день",  "FLOURITE PANEL IOS", 400,  "Доступ на 1 день"),
                ("Flourite Panel - 7 дней",  "FLOURITE PANEL IOS", 1000, "Доступ на 7 дней"),
                ("Flourite Panel - 30 дней", "FLOURITE PANEL IOS", 2000, "Доступ на 30 дней"),
                # MIGULE PANEL IOS
                ("Migule Panel - 1 день",  "MIGULE PANEL IOS", 400,  "Доступ на 1 день"),
                ("Migule Panel - 7 дней",  "MIGULE PANEL IOS", 1100, "Доступ на 7 дней"),
                ("Migule Panel - 30 дней", "MIGULE PANEL IOS", 1999, "Доступ на 30 дней"),
                # PROXY IOS
                ("Proxy iOS - 30 дней", "PROXY IOS", 1000, "Доступ на 30 дней"),
                # СЕРТИФИКАТ IOS
                ("Сертификат iOS - 1 год (365 дней)", "СЕРТИФИКАТ IOS", 800, "Сертификат на 365 дней"),
            ]
            self.cursor.executemany(
                'INSERT INTO products (name, category, price, description) VALUES (?, ?, ?, ?)',
                products
            )
        self.conn.commit()

    def add_user(self, user_id, username):
        self.cursor.execute(
            'INSERT OR IGNORE INTO users (user_id, username, registered_at) VALUES (?, ?, ?)',
            (user_id, username, datetime.now().isoformat())
        )
        self.conn.commit()

    def get_user(self, user_id):
        self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone()

    def get_user_balance(self, user_id):
        self.cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        return result[0] if result else 0

    def update_balance(self, user_id, amount):
        self.cursor.execute(
            'UPDATE users SET balance = balance + ? WHERE user_id = ?',
            (amount, user_id)
        )
        self.conn.commit()

    def check_key(self, password):
        self.cursor.execute(
            'SELECT key, user_id, expiry_date, status FROM keys WHERE password = ?',
            (password,)
        )
        return self.cursor.fetchone()

    def get_user_keys(self, user_id):
        self.cursor.execute(
            'SELECT key, expiry_date, status FROM keys WHERE user_id = ?',
            (user_id,)
        )
        return self.cursor.fetchall()

    def add_key(self, key, user_id, password, days):
        expiry = (datetime.now() + timedelta(days=days)).isoformat()
        self.cursor.execute(
            'INSERT INTO keys (key, user_id, password, expiry_date) VALUES (?, ?, ?, ?)',
            (key, user_id, password, expiry)
        )
        self.conn.commit()
        return expiry

    def get_products_by_category(self, category):
        self.cursor.execute(
            'SELECT id, name, price, description FROM products WHERE category = ?',
            (category,)
        )
        return self.cursor.fetchall()

    def get_all_products(self):
        self.cursor.execute('SELECT id, name, category, price, description FROM products')
        return self.cursor.fetchall()

    def close(self):
        self.conn.close()

    def set_product_file(self, category, file_id, file_type):
        self.cursor.execute(
            'INSERT OR REPLACE INTO product_files (category, file_id, file_type) VALUES (?, ?, ?)',
            (category, file_id, file_type)
        )
        self.conn.commit()

    def get_product_file(self, category):
        self.cursor.execute('SELECT file_id, file_type FROM product_files WHERE category = ?', (category,))
        return self.cursor.fetchone()

    def is_processed(self, message_id):
        self.cursor.execute('SELECT 1 FROM processed_requests WHERE message_id = ?', (message_id,))
        return self.cursor.fetchone() is not None

    def mark_processed(self, message_id):
        self.cursor.execute('INSERT OR IGNORE INTO processed_requests (message_id) VALUES (?)', (message_id,))
        self.conn.commit()

# Создаем экземпляр БД
db = Database()

# ==================== КЛАВИАТУРЫ ====================
def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 МАГАЗИН")],
            [KeyboardButton(text="👤 ПРОФИЛЬ"), KeyboardButton(text="🔧 ТЕХ.ПОДДЕРЖКА")],
            [KeyboardButton(text="⭐ ОТЗЫВЫ"), KeyboardButton(text="🔑 ПРОВЕРИТЬ МОЙ КЛЮЧ")],
            [KeyboardButton(text="💰 ПОПОЛНИТЬ БАЛАНС")]
        ],
        resize_keyboard=True
    )

def category_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💻 PC")],
            [KeyboardButton(text="📱 ANDROID")],
            [KeyboardButton(text="🍎 IOS")],
            [KeyboardButton(text="◀️ НАЗАД")]
        ],
        resize_keyboard=True
    )

def pc_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎯 AIM BOT PC")],
            [KeyboardButton(text="🔒 PRIVATE PC")],
            [KeyboardButton(text="⚙️ BASIC PC")],
            [KeyboardButton(text="💥 BR MOD PC")],
            [KeyboardButton(text="◀️ В МАГАЗИН")]
        ],
        resize_keyboard=True
    )

def android_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💧 DRIP CLIENT")],
            [KeyboardButton(text="🎮 HG CHEATS")],
            [KeyboardButton(text="⭐ PRIME MOD")],
            [KeyboardButton(text="◀️ В МАГАЗИН")]
        ],
        resize_keyboard=True
    )

def ios_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍏 FLOURITE PANEL IOS")],
            [KeyboardButton(text="🍎 MIGULE PANEL IOS")],
            [KeyboardButton(text="🔗 PROXY IOS")],
            [KeyboardButton(text="📜 СЕРТИФИКАТ IOS")],
            [KeyboardButton(text="◀️ В МАГАЗИН")]
        ],
        resize_keyboard=True
    )

# ==================== СОСТОЯНИЯ FSM ====================
class KeyCheck(StatesGroup):
    waiting_for_password = State()

class TopUp(StatesGroup):
    waiting_for_amount = State()
    waiting_for_screenshot = State()

class Purchase(StatesGroup):
    waiting_for_payment_screenshot = State()

class KeyRequest(StatesGroup):
    waiting_for_user = State()
    waiting_for_pass = State()

class UploadFile(StatesGroup):
    waiting_for_file = State()

# ==================== РОУТЕРЫ ====================
router = Router()

# ==================== ОБРАБОТЧИКИ ====================

# ---------- СТАРТ ----------
@router.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # Добавляем пользователя в БД
    db.add_user(user_id, username)
    
    await message.answer(
        f"👋 Добро пожаловать, {username}!\n\n"
        "🏪 Это магазин по продаже доступов к панелям.\n"
        "Выберите категорию или воспользуйтесь кнопками ниже.",
        reply_markup=main_keyboard()
    )

# ---------- ПОПОЛНЕНИЕ БАЛАНСА ----------
@router.message(lambda msg: msg.text == "💰 ПОПОЛНИТЬ БАЛАНС")
async def show_payment_details(message: types.Message, state: FSMContext):
    await state.set_state(TopUp.waiting_for_amount)
    await message.answer(
        f"💰 Текущий баланс: {db.get_user_balance(message.from_user.id)}₽\n\n"
        f"Введите сумму которую желаете пополнить:",
        reply_markup=main_keyboard()
    )

@router.message(TopUp.waiting_for_amount)
async def process_amount(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ Введите только число, например: 500")
        return
    amount = int(text)
    await state.update_data(amount=amount)
    await state.set_state(TopUp.waiting_for_screenshot)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить скриншот", callback_data="send_screenshot_noop")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_main")]
    ])
    await message.answer(
        f"💵 Сумма к пополнению: <b>{amount}₽</b>\n\n"
        f"{PAYMENT_DETAILS}\n"
        f"После оплаты нажмите кнопку ниже и отправьте скриншот.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@router.callback_query(lambda call: call.data == "send_screenshot_noop")
async def request_screenshot(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "📤 Отправьте скриншот платежа:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_main")]
        ])
    )
    await call.answer()

@router.message(TopUp.waiting_for_screenshot)
async def process_screenshot(message: types.Message, state: FSMContext):
    if message.photo:
        # Получаем информацию о фото
        photo = message.photo[-1]
        file_id = photo.file_id
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name

        data = await state.get_data()
        amount = data.get("amount", 0)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=f"✅ Подтвердить {amount}₽", callback_data=f"topup_accept:{user_id}:{amount}"),
            ],
            [
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"topup_reject:{user_id}"),
            ],
        ])

        try:
            await message.bot.send_photo(
                LOG_CHAT_ID,
                photo=file_id,
                caption=f"📥 <b>Новый запрос на пополнение!</b>\n"
                        f"👤 Пользователь: @{username}\n"
                        f"🆔 ID: <code>{user_id}</code>\n"
                        f"💰 Текущий баланс: {db.get_user_balance(user_id)}₽\n"
                        f"💵 Сумма к зачислению: <b>{amount}₽</b>",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка отправки в лог-чат: {e}")

        await message.answer(
            "✅ Ваш скриншот отправлен на проверку!\n"
            "⏰ Ожидайте пополнения баланса в течение 5-10 минут.\n\n"
            "Если у вас возникли вопросы, обратитесь в техподдержку: @NorovK1ng",
            reply_markup=main_keyboard()
        )
        await state.clear()
    else:
        await message.answer(
            "❌ Пожалуйста, отправьте фото скриншота платежа.",
            reply_markup=main_keyboard()
        )

# ---------- ПРИНЯТЬ ПОПОЛНЕНИЕ ----------
@router.callback_query(lambda call: call.data.startswith("topup_accept:"))
async def topup_accept(call: types.CallbackQuery):
    message_id = call.message.message_id

    if db.is_processed(message_id):
        await call.answer("⚠️ Эта заявка уже обработана!", show_alert=True)
        return

    db.mark_processed(message_id)

    parts = call.data.split(":")
    user_id = int(parts[1])
    amount = int(parts[2])

    db.update_balance(user_id, amount)

    try:
        await call.bot.send_message(
            user_id,
            f"✅ На ваш счёт поступило <b>{amount}₽</b>!\n"
            f"💰 Текущий баланс: <b>{db.get_user_balance(user_id)}₽</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Не удалось уведомить пользователя {user_id}: {e}")

    try:
        await call.message.edit_caption(
            call.message.caption + f"\n\n✅ <b>Принято — зачислено {amount}₽</b>\n"
                                   f"👤 Обработал: @{call.from_user.username or call.from_user.first_name}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[])
        )
    except Exception as e:
        print(f"Ошибка edit_caption (topup_accept): {e}")
    await call.answer(f"✅ Зачислено {amount}₽")

# ---------- ОТКЛОНИТЬ ПОПОЛНЕНИЕ ----------
@router.callback_query(lambda call: call.data.startswith("topup_reject:"))
async def topup_reject(call: types.CallbackQuery):
    message_id = call.message.message_id

    if db.is_processed(message_id):
        await call.answer("⚠️ Эта заявка уже обработана!", show_alert=True)
        return

    db.mark_processed(message_id)

    user_id = int(call.data.split(":")[1])

    try:
        await call.bot.send_message(
            user_id,
            "❌ Ваш чек был отклонён.\n\n"
            "Возможные причины:\n"
            "• Сумма не совпадает\n"
            "• Скриншот нечитаемый\n"
            "• Платёж не найден\n\n"
            "Обратитесь в поддержку: @NorovK1ng"
        )
    except Exception as e:
        print(f"Не удалось уведомить пользователя {user_id}: {e}")

    try:
        await call.message.edit_caption(
            call.message.caption + f"\n\n❌ <b>Отклонено</b>\n"
                                   f"👤 Обработал: @{call.from_user.username or call.from_user.first_name}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[])
        )
    except Exception as e:
        print(f"Ошибка edit_caption (topup_reject): {e}")
    await call.answer("❌ Заявка отклонена")

@router.callback_query(lambda call: call.data == "back_to_main")
async def back_to_main_from_payment(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.delete()
    except:
        pass
    await call.bot.send_message(
        call.from_user.id,
        "🏠 Главное меню",
        reply_markup=main_keyboard()
    )
    await call.answer()

# ---------- МАГАЗИН ----------
@router.message(lambda msg: msg.text == "🛒 МАГАЗИН")
async def shop(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💻 PC",      callback_data="platform_PC")],
        [InlineKeyboardButton(text="📱 ANDROID", callback_data="platform_ANDROID")],
        [InlineKeyboardButton(text="🍎 IOS",     callback_data="platform_IOS")],
    ])
    await message.answer("📂 Выберите платформу:", reply_markup=keyboard)

@router.message(lambda msg: msg.text == "💻 PC")
async def pc_section(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 AIM BOT PC",  callback_data="cat_AIM BOT PC")],
        [InlineKeyboardButton(text="🔒 PRIVATE PC",  callback_data="cat_PRIVATE PC")],
        [InlineKeyboardButton(text="⚙️ BASIC PC",    callback_data="cat_BASIC PC")],
        [InlineKeyboardButton(text="💥 BR MOD PC",   callback_data="cat_BR MOD PC")],
        [InlineKeyboardButton(text="◀️ Назад",       callback_data="back_to_platform")],
    ])
    await message.answer("💻 Выберите товар:", reply_markup=keyboard)

@router.message(lambda msg: msg.text == "📱 ANDROID")
async def android_section(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💧 DRIP CLIENT", callback_data="cat_DRIP CLIENT")],
        [InlineKeyboardButton(text="🎮 HG CHEATS",   callback_data="cat_HG CHEATS")],
        [InlineKeyboardButton(text="⭐ PRIME MOD",   callback_data="cat_PRIME MOD")],
        [InlineKeyboardButton(text="◀️ Назад",       callback_data="back_to_platform")],
    ])
    await message.answer("📱 Выберите товар:", reply_markup=keyboard)

@router.message(lambda msg: msg.text == "🍎 IOS")
async def ios_section(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍏 FLOURITE PANEL IOS", callback_data="cat_FLOURITE PANEL IOS")],
        [InlineKeyboardButton(text="🍎 MIGULE PANEL IOS",   callback_data="cat_MIGULE PANEL IOS")],
        [InlineKeyboardButton(text="🔗 PROXY IOS",          callback_data="cat_PROXY IOS")],
        [InlineKeyboardButton(text="📜 СЕРТИФИКАТ IOS",     callback_data="cat_СЕРТИФИКАТ IOS")],
        [InlineKeyboardButton(text="◀️ Назад",              callback_data="back_to_platform")],
    ])
    await message.answer("🍎 Выберите товар:", reply_markup=keyboard)

@router.callback_query(lambda call: call.data == "back_to_platform")
async def back_to_platform(call: types.CallbackQuery):
    await call.message.edit_text(
        "📂 Выберите платформу:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💻 PC",      callback_data="platform_PC")],
            [InlineKeyboardButton(text="📱 ANDROID", callback_data="platform_ANDROID")],
            [InlineKeyboardButton(text="🍎 IOS",     callback_data="platform_IOS")],
        ])
    )
    await call.answer()

@router.callback_query(lambda call: call.data == "platform_PC")
async def cb_pc(call: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 AIM BOT PC",  callback_data="cat_AIM BOT PC")],
        [InlineKeyboardButton(text="🔒 PRIVATE PC",  callback_data="cat_PRIVATE PC")],
        [InlineKeyboardButton(text="⚙️ BASIC PC",    callback_data="cat_BASIC PC")],
        [InlineKeyboardButton(text="💥 BR MOD PC",   callback_data="cat_BR MOD PC")],
        [InlineKeyboardButton(text="◀️ Назад",       callback_data="back_to_platform")],
    ])
    await call.message.edit_text("💻 Выберите товар:", reply_markup=keyboard)
    await call.answer()

@router.callback_query(lambda call: call.data == "platform_ANDROID")
async def cb_android(call: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💧 DRIP CLIENT", callback_data="cat_DRIP CLIENT")],
        [InlineKeyboardButton(text="🎮 HG CHEATS",   callback_data="cat_HG CHEATS")],
        [InlineKeyboardButton(text="⭐ PRIME MOD",   callback_data="cat_PRIME MOD")],
        [InlineKeyboardButton(text="◀️ Назад",       callback_data="back_to_platform")],
    ])
    await call.message.edit_text("📱 Выберите товар:", reply_markup=keyboard)
    await call.answer()

@router.callback_query(lambda call: call.data == "platform_IOS")
async def cb_ios(call: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍏 FLOURITE PANEL IOS", callback_data="cat_FLOURITE PANEL IOS")],
        [InlineKeyboardButton(text="🍎 MIGULE PANEL IOS",   callback_data="cat_MIGULE PANEL IOS")],
        [InlineKeyboardButton(text="🔗 PROXY IOS",          callback_data="cat_PROXY IOS")],
        [InlineKeyboardButton(text="📜 СЕРТИФИКАТ IOS",     callback_data="cat_СЕРТИФИКАТ IOS")],
        [InlineKeyboardButton(text="◀️ Назад",              callback_data="back_to_platform")],
    ])
    await call.message.edit_text("🍎 Выберите товар:", reply_markup=keyboard)
    await call.answer()

@router.callback_query(lambda call: call.data.startswith("cat_"))
async def show_products_inline(call: types.CallbackQuery):
    category = call.data[4:]
    products = db.get_products_by_category(category)

    if not products:
        await call.answer("📭 Нет товаров", show_alert=True)
        return

    # Проверяем загружен ли файл для категории
    product_file = db.get_product_file(category)
    if not product_file:
        await call.answer("🚫 Этот товар временно недоступен", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for product in products:
        product_id, name, price, desc = product
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=f"{name} — {price}₽", callback_data=f"buy_{product_id}")
        ])
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_categories")
    ])

    await call.message.edit_text(f"📦 {category}:", reply_markup=keyboard)
    await call.answer()

@router.message(lambda msg: msg.text in ["🎯 AIM BOT PC", "🔒 PRIVATE PC", "⚙️ BASIC PC", "💥 BR MOD PC", "💧 DRIP CLIENT", "🎮 HG CHEATS", "⭐ PRIME MOD", "🍏 FLOURITE PANEL IOS", "🍎 MIGULE PANEL IOS", "🔗 PROXY IOS", "📜 СЕРТИФИКАТ IOS"])
async def show_products(message: types.Message):
    category_map = {
        "🎯 AIM BOT PC":          "AIM BOT PC",
        "🔒 PRIVATE PC":          "PRIVATE PC",
        "⚙️ BASIC PC":            "BASIC PC",
        "💥 BR MOD PC":           "BR MOD PC",
        "💧 DRIP CLIENT":         "DRIP CLIENT",
        "🎮 HG CHEATS":           "HG CHEATS",
        "⭐ PRIME MOD":           "PRIME MOD",
        "🍏 FLOURITE PANEL IOS":  "FLOURITE PANEL IOS",
        "🍎 MIGULE PANEL IOS":    "MIGULE PANEL IOS",
        "🔗 PROXY IOS":           "PROXY IOS",
        "📜 СЕРТИФИКАТ IOS":      "СЕРТИФИКАТ IOS",
    }
    category = category_map.get(message.text)
    
    if not category:
        await message.answer("❌ Категория не найдена", reply_markup=category_keyboard())
        return
    
    products = db.get_products_by_category(category)
    
    if not products:
        await message.answer("📭 В этой категории пока нет товаров", reply_markup=category_keyboard())
        return
    
    # Создаем инлайн-клавиатуру с товарами
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for product in products:
        product_id, name, price, desc = product
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{name} - {price}₽",
                callback_data=f"buy_{product_id}"
            )
        ])
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_categories")
    ])
    
    await message.answer(
        f"📦 Товары в категории {category}:",
        reply_markup=keyboard
    )

@router.callback_query(lambda call: call.data.startswith("buy_"))
async def buy_product(call: types.CallbackQuery, state: FSMContext):
    product_id = int(call.data.split("_")[1])
    user_id = call.from_user.id

    db.cursor.execute('SELECT name, price, description FROM products WHERE id = ?', (product_id,))
    product = db.cursor.fetchone()

    if not product:
        await call.answer("❌ Товар не найден")
        return

    name, price, desc = product

    # Определяем дни
    if "365" in name:
        days = 365
    elif "30" in name:
        days = 30
    elif "10" in name:
        days = 10
    elif "7" in name:
        days = 7
    elif "5" in name:
        days = 5
    else:
        days = 1

    balance = db.get_user_balance(user_id)
    rates_str = await get_rates(price)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Оплатить с баланса", callback_data=f"pay_balance:{product_id}")],
        [InlineKeyboardButton(text="💳 Оплатить переводом", callback_data=f"pay_transfer:{product_id}:{days}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_categories")],
    ])

    await call.message.edit_text(
        f"💳 <b>Выберите способ оплаты</b>\n\n"
        f"📦 Товар: <b>{name}</b>\n"
        f"📅 Дней: <b>{days}</b>\n\n"
        f"💵 Сумма в разных валютах:\n"
        f"{rates_str}\n\n"
        f"💰 Ваш баланс: <b>{balance}₽</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await call.answer()

# ---------- ОПЛАТА С БАЛАНСА ----------
@router.callback_query(lambda call: call.data.startswith("pay_balance:"))
async def pay_with_balance(call: types.CallbackQuery, state: FSMContext):
    product_id = int(call.data.split(":")[1])
    user_id = call.from_user.id

    db.cursor.execute('SELECT name, price, description FROM products WHERE id = ?', (product_id,))
    product = db.cursor.fetchone()
    if not product:
        await call.answer("❌ Товар не найден")
        return

    name, price, desc = product
    balance = db.get_user_balance(user_id)

    if balance < price:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="topup")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"buy_{product_id}")],
        ])
        await call.message.edit_text(
            f"❌ Недостаточно средств!\n"
            f"💰 Ваш баланс: {balance}₽\n"
            f"💳 Стоимость: {price}₽",
            reply_markup=keyboard
        )
        await call.answer()
        return

    db.update_balance(user_id, -price)
    await _complete_purchase(call, product_id, name, price, user_id)

# ---------- ОПЛАТА ПЕРЕВОДОМ ----------
@router.callback_query(lambda call: call.data.startswith("pay_transfer:"))
async def pay_with_transfer(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    product_id = int(parts[1])
    days = int(parts[2])

    db.cursor.execute('SELECT name, price FROM products WHERE id = ?', (product_id,))
    product = db.cursor.fetchone()
    if not product:
        await call.answer("❌ Товар не найден")
        return

    name, price = product
    rates_str = await get_rates(price)

    await state.set_state(Purchase.waiting_for_payment_screenshot)
    await state.update_data(product_id=product_id, price=price, name=name, days=days)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Загрузить скриншот", callback_data="upload_purchase_screenshot")],
        [InlineKeyboardButton(text="◀️ Назад к оплате", callback_data=f"buy_{product_id}")],
    ])

    await call.message.edit_text(
        f"💳 <b>Оплата переводом</b>\n\n"
        f"📦 Товар: <b>{name}</b>\n"
        f"📅 Дней: <b>{days}</b>\n"
        f"💵 Сумма к оплате: {rates_str}\n\n"
        f"<b>Реквизиты для оплаты:</b>\n\n"
        f"{PAYMENT_DETAILS}\n"
        f"📸 <b>ВАЖНО:</b> После оплаты сделайте скриншот чека!\n\n"
        f"👇 Нажмите кнопку ниже когда будете готовы отправить скриншот:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(lambda call: call.data == "upload_purchase_screenshot")
async def request_purchase_screenshot(call: types.CallbackQuery):
    await call.message.edit_text(
        "📸 Отправьте скриншот оплаты одним фото:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_main")]
        ])
    )
    await call.answer()

@router.message(Purchase.waiting_for_payment_screenshot)
async def process_purchase_screenshot(message: types.Message, state: FSMContext):
    if not message.photo:
        await message.answer("❌ Отправьте фото скриншота оплаты.")
        return

    data = await state.get_data()
    product_id = data.get("product_id")
    price = data.get("price")
    name = data.get("name")
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    photo_file_id = message.photo[-1].file_id

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Подтвердить и выдать товар", callback_data=f"purchase_accept:{user_id}:{product_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"purchase_reject:{user_id}")],
    ])

    try:
        await message.bot.send_photo(
            LOG_CHAT_ID,
            photo=photo_file_id,
            caption=f"🛒 <b>Новая покупка (перевод)!</b>\n"
                    f"👤 Пользователь: @{username}\n"
                    f"🆔 ID: <code>{user_id}</code>\n"
                    f"📦 Товар: <b>{name}</b>\n"
                    f"💵 Сумма: <b>{price}₽</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Ошибка отправки в лог-чат: {e}")

    await message.answer(
        "✅ Скриншот отправлен на проверку!\n"
        "⏰ После подтверждения товар будет выдан автоматически.\n\n"
        "По вопросам: @NorovK1ng",
        reply_markup=main_keyboard()
    )
    await state.clear()

# ---------- ПОДТВЕРДИТЬ ПОКУПКУ ПЕРЕВОДОМ ----------
@router.callback_query(lambda call: call.data.startswith("purchase_accept:"))
async def purchase_accept(call: types.CallbackQuery):
    message_id = call.message.message_id
    if db.is_processed(message_id):
        await call.answer("⚠️ Уже обработано!", show_alert=True)
        return
    db.mark_processed(message_id)

    parts = call.data.split(":")
    user_id = int(parts[1])
    product_id = int(parts[2])

    db.cursor.execute('SELECT name, price FROM products WHERE id = ?', (product_id,))
    product = db.cursor.fetchone()
    if not product:
        await call.answer("❌ Товар не найден")
        return
    name, price = product

    await _complete_purchase(call, product_id, name, price, user_id, via_transfer=True)
    try:
        await call.message.edit_caption(
            call.message.caption + f"\n\n✅ <b>Подтверждено, товар выдан</b>\n"
                                   f"👤 @{call.from_user.username or call.from_user.first_name}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[])
        )
    except Exception as e:
        print(f"Ошибка edit_caption (purchase_accept): {e}")
    await call.answer("✅ Товар выдан")

@router.callback_query(lambda call: call.data.startswith("purchase_reject:"))
async def purchase_reject(call: types.CallbackQuery):
    message_id = call.message.message_id
    if db.is_processed(message_id):
        await call.answer("⚠️ Уже обработано!", show_alert=True)
        return
    db.mark_processed(message_id)

    user_id = int(call.data.split(":")[1])
    try:
        await call.bot.send_message(
            user_id,
            "❌ Ваш платёж был отклонён.\n"
            "По вопросам: @NorovK1ng"
        )
    except:
        pass

    try:
        await call.message.edit_caption(
            call.message.caption + f"\n\n❌ <b>Отклонено</b>\n"
                                   f"👤 @{call.from_user.username or call.from_user.first_name}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[])
        )
    except Exception as e:
        print(f"Ошибка edit_caption (purchase_reject): {e}")
    await call.answer("❌ Отклонено")

# ---------- ОБЩАЯ ФУНКЦИЯ ВЫДАЧИ ТОВАРА ----------
async def _complete_purchase(call, product_id, name, price, user_id, via_transfer=False):
    key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
    password = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

    if "365" in name:
        days = 365
    elif "30" in name:
        days = 30
    elif "10" in name:
        days = 10
    elif "7" in name:
        days = 7
    elif "5" in name:
        days = 5
    else:
        days = 1

    expiry = db.add_key(key, user_id, password, days)
    purchase_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    username = call.from_user.username or call.from_user.first_name

    text = (
        f"✅ <b>Оплата подтверждена!</b>\n\n"
        f"📦 Товар: <b>{name}</b>\n"
        f"📅 Действует до: {expiry}\n\n"
        f"💰 Баланс: {db.get_user_balance(user_id)}₽"
    )

    try:
        await call.bot.send_message(user_id, text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Запросить ключ", callback_data=f"request_key:{user_id}:{product_id}")]
            ])
        )
    except:
        pass

    db.cursor.execute('SELECT category FROM products WHERE id = ?', (product_id,))
    cat_row = db.cursor.fetchone()
    if cat_row:
        product_file = db.get_product_file(cat_row[0])
        if product_file:
            pf_id, pf_type = product_file
            try:
                if pf_type == "document":
                    await call.bot.send_document(user_id, pf_id, caption="📦 Файл вашего товара")
                elif pf_type == "photo":
                    await call.bot.send_photo(user_id, pf_id, caption="📦 Файл вашего товара")
                elif pf_type == "video":
                    await call.bot.send_video(user_id, pf_id, caption="📦 Файл вашего товара")
                elif pf_type == "audio":
                    await call.bot.send_audio(user_id, pf_id, caption="📦 Файл вашего товара")
            except Exception as e:
                print(f"Ошибка отправки файла: {e}")

    if not via_transfer:
        try:
            await call.message.edit_text(text, parse_mode="HTML")
        except:
            pass

    # Чек в лог-чат
    receipt = (
        f"🧾 <b>ЧЕК О ПОКУПКЕ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 @{username}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"🛒 Товар: {name}\n"
        f"💳 Сумма: {price}₽\n"
        f"📅 До: {expiry}\n"
        f"🕐 Время: {purchase_time}\n"
        f"💰 Баланс после: {db.get_user_balance(user_id)}₽\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    try:
        await call.bot.send_message(LOG_CHAT_ID, receipt, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка отправки чека: {e}")

@router.callback_query(lambda call: call.data == "back_to_categories")
async def back_to_categories(call: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💻 PC",      callback_data="platform_PC")],
        [InlineKeyboardButton(text="📱 ANDROID", callback_data="platform_ANDROID")],
        [InlineKeyboardButton(text="🍎 IOS",     callback_data="platform_IOS")],
    ])
    await call.message.edit_text("📂 Выберите платформу:", reply_markup=keyboard)
    await call.answer()

@router.callback_query(lambda call: call.data == "topup")
async def topup_balance_callback(call: types.CallbackQuery):
    await call.message.edit_text(
        f"{PAYMENT_DETAILS}\n\n"
        f"💰 Текущий баланс: {db.get_user_balance(call.from_user.id)}₽",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Отправить скриншот", callback_data="send_screenshot")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
        ])
    )
    await call.answer()

@router.message(lambda msg: msg.text == "◀️ НАЗАД")
async def back_to_main(message: types.Message):
    await message.answer(
        "🏠 Главное меню",
        reply_markup=main_keyboard()
    )
# ---------- ПРОФИЛЬ ----------
@router.message(lambda msg: msg.text == "👤 ПРОФИЛЬ")
async def profile(message: types.Message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await message.answer("❌ Пользователь не найден\n\nНажмите /start")
        return
    
    balance = db.get_user_balance(user_id)
    keys = db.get_user_keys(user_id)
    
    text = f"👤 Профиль\n\n"
    text += f"🆔 ID: {user[0]}\n"
    text += f"👤 Имя: {user[1] or 'Не указано'}\n"
    text += f"💰 Баланс: {balance}₽\n"
    text += f"📅 Зарегистрирован: {user[3]}\n\n"
    
    if keys:
        text += "🔑 Ваши ключи:\n"
        for key, expiry, status in keys:
            text += f"• {key} - {status} (до {expiry})\n"
    else:
        text += "🔑 У вас нет активных ключей"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="topup")]
    ])
    
    await message.answer(text, reply_markup=keyboard)

# ---------- ПРОВЕРКА КЛЮЧА ----------
@router.message(lambda msg: msg.text == "🔑 ПРОВЕРИТЬ МОЙ КЛЮЧ")
async def check_key_button(message: types.Message, state: FSMContext):
    await state.set_state(KeyCheck.waiting_for_password)
    await message.answer(
        "🔑 Введите ваш ключ:",
        reply_markup=main_keyboard()
    )

@router.message(KeyCheck.waiting_for_password)
async def process_key_check(message: types.Message, state: FSMContext):
    password = message.text.strip()
    user_id = message.from_user.id
    
    # Проверяем ключ в БД
    key_data = db.check_key(password)
    
    if key_data:
        key, key_user_id, expiry_date, status = key_data
        
        # Проверяем, принадлежит ли ключ пользователю
        if key_user_id == user_id:
            await message.answer(
                f"✅ Ключ найден!\n\n"
                f"🔑 Ключ: {key}\n"
                f"👤 Владелец: @{message.from_user.username or 'Не указан'}\n"
                f"📅 Действует до: {expiry_date}\n"
                f"📊 Статус: {status}",
                reply_markup=main_keyboard()
            )
        else:
            await message.answer(
                "❌ Этот ключ не принадлежит вам!\n"
                "Пожалуйста, введите свой пароль.",
                reply_markup=main_keyboard()
            )
    else:
        await message.answer(
            "❌ У вас нету ключа или он не добавлен в базу данных.\n"
            "Пожалуйста, приобретите ключ в магазине.",
            reply_markup=main_keyboard()
        )
    
    await state.clear()

# ---------- ТЕХ.ПОДДЕРЖКА ----------
@router.message(lambda msg: msg.text == "🔧 ТЕХ.ПОДДЕРЖКА")
async def support(message: types.Message):
    await message.answer(
        "🔧 Техническая поддержка\n\n"
        "По всем вопросам обращайтесь:\n"
        "📱 Telegram: @NorovK1ng\n\n"
        "💰 Для пополнения баланса используйте кнопку 'ПОПОЛНИТЬ БАЛАНС'",
        reply_markup=main_keyboard()
    )

# ---------- ОТЗЫВЫ ----------
@router.message(lambda msg: msg.text == "⭐ ОТЗЫВЫ")
async def reviews(message: types.Message):
    await message.answer(
        "⭐ Отзывы\n\n"
        "😔 Пока что нету отзывов.",
        reply_markup=main_keyboard()
    )

# ---------- АДМИН-КОМАНДЫ ----------
@router.message(Command("add_balance"))
async def admin_add_balance(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет прав для этой команды")
        return
    
    try:
        args = message.text.split()
        if len(args) != 3:
            await message.answer("❌ Использование: /add_balance <user_id> <сумма>")
            return
        
        user_id = int(args[1])
        amount = int(args[2])
        
        db.update_balance(user_id, amount)
        await message.answer(f"✅ Пользователю {user_id} добавлено {amount}₽")
        
        # Уведомляем пользователя о пополнении
        try:
            await message.bot.send_message(
                user_id,
                f"💰 Ваш баланс пополнен на {amount}₽!\n"
                f"💰 Текущий баланс: {db.get_user_balance(user_id)}₽"
            )
        except:
            pass
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("remove_balance"))
async def admin_remove_balance(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет прав для этой команды")
        return

    try:
        args = message.text.split()
        if len(args) != 3:
            await message.answer("❌ Использование: /remove_balance <user_id> <сумма>")
            return

        user_id = int(args[1])
        amount = int(args[2])
        current = db.get_user_balance(user_id)

        if current < amount:
            await message.answer(f"❌ У пользователя {user_id} только {current}₽ на балансе")
            return

        db.update_balance(user_id, -amount)
        await message.answer(f"✅ У пользователя {user_id} снято {amount}₽\n💰 Остаток: {db.get_user_balance(user_id)}₽")

        try:
            await message.bot.send_message(
                user_id,
                f"💸 С вашего баланса списано {amount}₽\n"
                f"💰 Текущий баланс: {db.get_user_balance(user_id)}₽"
            )
        except:
            pass
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("add_key"))
async def admin_add_key(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет прав для этой команды")
        return
    
    try:
        args = message.text.split()
        if len(args) != 4:
            await message.answer("❌ Использование: /add_key <user_id> <пароль> <дней>")
            return
        
        user_id = int(args[1])
        password = args[2]
        days = int(args[3])
        
        key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
        expiry = db.add_key(key, user_id, password, days)
        
        await message.answer(
            f"✅ Ключ создан!\n\n"
            f"🔑 Ключ: {key}\n"
            f"🔒 Пароль: {password}\n"
            f"👤 Пользователь: {user_id}\n"
            f"📅 Действует до: {expiry}"
        )
        
        # Уведомляем пользователя
        try:
            await message.bot.send_message(
                user_id,
                f"🎉 Вам выдан новый ключ!\n\n"
                f"🔑 Ключ: {key}\n"
                f"🔒 Пароль: {password}\n"
                f"📅 Действует до: {expiry}"
            )
        except:
            pass
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("stats"))
async def admin_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет прав для этой команды")
        return
    
    db.cursor.execute('SELECT COUNT(*) FROM users')
    users_count = db.cursor.fetchone()[0]
    
    db.cursor.execute('SELECT COUNT(*) FROM keys')
    keys_count = db.cursor.fetchone()[0]
    
    db.cursor.execute('SELECT SUM(balance) FROM users')
    total_balance = db.cursor.fetchone()[0] or 0
    
    await message.answer(
        f"📊 СТАТИСТИКА БОТА\n\n"
        f"👤 Всего пользователей: {users_count}\n"
        f"🔑 Всего ключей: {keys_count}\n"
        f"💰 Общий баланс: {total_balance}₽"
    )

# ==================== КОМАНДЫ ЗАГРУЗКИ ФАЙЛОВ ====================

# Маппинг команд к категориям
UPLOAD_COMMANDS = {
    "basic":           "BASIC PC",
    "aimbot":          "AIM BOT PC",
    "private":         "PRIVATE PC",
    "brmod":           "BR MOD PC",
    "dripclient":      "DRIP CLIENT",
    "hgcheats":        "HG CHEATS",
    "primemod":        "PRIME MOD",
    "flourite":        "FLOURITE PANEL IOS",
    "migule":          "MIGULE PANEL IOS",
    "proxy":           "PROXY IOS",
    "sertificat":      "СЕРТИФИКАТ IOS",
}

def make_upload_handler(category):
    async def handler(message: types.Message, state: FSMContext):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("⛔ У вас нет прав для этой команды")
            return
        await state.set_state(UploadFile.waiting_for_file)
        await state.update_data(upload_category=category)
        await message.answer(
            f"📂 Категория: <b>{category}</b>\n\n"
            f"Отправьте файл (документ, фото, архив) для этой категории.\n"
            f"Он будет автоматически выдаваться клиентам при покупке.",
            parse_mode="HTML"
        )
    return handler

@router.message(lambda msg: msg.chat.type == "private" and msg.from_user.id in ADMIN_IDS and msg.text and not msg.text.startswith("/"))
async def admin_private_message(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state in [KeyRequest.waiting_for_user, KeyRequest.waiting_for_pass]:
        return  # Уже обрабатывается FSM

    # Проверяем есть ли pending запрос
    db.cursor.execute('CREATE TABLE IF NOT EXISTS pending_key_issue (admin_id INTEGER PRIMARY KEY, target_user_id INTEGER, product_id INTEGER)')
    db.conn.commit()
    db.cursor.execute('SELECT target_user_id, product_id FROM pending_key_issue WHERE admin_id = ?', (message.from_user.id,))
    row = db.cursor.fetchone()
    if row:
        target_user_id, product_id = row
        await state.set_state(KeyRequest.waiting_for_user)
        await state.update_data(target_user_id=target_user_id, product_id=product_id)
        db.cursor.execute('DELETE FROM pending_key_issue WHERE admin_id = ?', (message.from_user.id,))
        db.conn.commit()
        # Обрабатываем текущее сообщение как username
        await state.update_data(panel_user=message.text.strip())
        await state.set_state(KeyRequest.waiting_for_pass)
        await message.answer("🔒 Теперь введите <b>Password</b>:", parse_mode="HTML")

for cmd, cat in UPLOAD_COMMANDS.items():
    router.message(Command(cmd))(make_upload_handler(cat))

@router.message(UploadFile.waiting_for_file)
async def process_upload_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    category = data.get("upload_category")

    file_id = None
    file_type = None

    # Поддержка пересланных сообщений и прямых файлов
    if message.document:
        file_id = message.document.file_id
        file_type = "document"
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"
    elif message.audio:
        file_id = message.audio.file_id
        file_type = "audio"
    elif message.forward_from or message.forward_from_chat:
        # Пересланное сообщение — ищем файл внутри него
        if message.document:
            file_id = message.document.file_id
            file_type = "document"
        elif message.photo:
            file_id = message.photo[-1].file_id
            file_type = "photo"
        elif message.video:
            file_id = message.video.file_id
            file_type = "video"

    if not file_id:
        await message.answer(
            "❌ Файл не найден.\n\n"
            "Отправьте файл <b>напрямую</b> (не пересылайте) — просто прикрепите файл через скрепку 📎",
            parse_mode="HTML"
        )
        return

    db.set_product_file(category, file_id, file_type)
    await state.clear()
    await message.answer(
        f"✅ Файл для <b>{category}</b> сохранён!\n"
        f"📎 Тип: {file_type}\n"
        f"Теперь он будет выдаваться клиентам при покупке.",
        parse_mode="HTML"
    )

# ==================== ЗАПРОС КЛЮЧА ====================

@router.callback_query(lambda call: call.data.startswith("request_key:"))
async def request_key_start(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    user_id = int(parts[1])
    product_id = int(parts[2])
    username = call.from_user.username or call.from_user.first_name

    db.cursor.execute('SELECT name FROM products WHERE id = ?', (product_id,))
    row = db.cursor.fetchone()
    product_name = row[0] if row else "Неизвестно"

    # Убираем кнопку чтобы не нажали дважды
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except:
        pass

    # Отправляем запрос в лог-чат с полями для заполнения
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Выдать ключ",
            callback_data=f"give_key:{user_id}:{product_id}"
        )]
    ])

    try:
        await call.bot.send_message(
            LOG_CHAT_ID,
            f"🔑 <b>Запрос ключа!</b>\n\n"
            f"👤 @{username} (ID: <code>{user_id}</code>)\n"
            f"📦 Товар: <b>{product_name}</b>\n\n"
            f"📝 Отправьте клиенту:\n"
            f"🖥 Username: \n"
            f"🔒 Password: ",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Ошибка отправки в лог-чат: {e}")

    await call.answer("✅ Запрос отправлен!")
    await call.bot.send_message(
        user_id,
        "✅ Ваш запрос на ключ отправлен!\n"
        "⏰ Ожидайте — администратор скоро выдаст вам данные.\n\n"
        "По вопросам: @NorovK1ng"
    )

@router.callback_query(lambda call: call.data.startswith("give_key:"))
async def give_key_handler(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    user_id = int(parts[1])
    product_id = int(parts[2])

    admin_id = call.from_user.id

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except:
        pass

    # Отправляем запрос ЛИЧНО админу в личку
    try:
        await call.bot.send_message(
            admin_id,
            f"📝 Введите <b>Username</b> для клиента <code>{user_id}</code>:\n\n"
            f"(Напишите сюда в личку боту, не в группу)",
            parse_mode="HTML"
        )
    except Exception as e:
        await call.answer(f"❌ Не могу написать вам в личку. Напишите боту /start сначала.", show_alert=True)
        return

    # Используем простой способ - сохраняем через state напрямую
    # state здесь привязан к chat где была нажата кнопка (группа)
    # Нам нужно установить state для личного чата админа
    # Делаем это через отдельный механизм - сохраняем pending в БД
    db.cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_key_issue (
            admin_id INTEGER PRIMARY KEY,
            target_user_id INTEGER,
            product_id INTEGER
        )
    ''')
    db.conn.commit()
    db.cursor.execute(
        'INSERT OR REPLACE INTO pending_key_issue (admin_id, target_user_id, product_id) VALUES (?, ?, ?)',
        (admin_id, user_id, product_id)
    )
    db.conn.commit()

    await call.answer("✅ Проверьте личные сообщения бота!")

@router.message(KeyRequest.waiting_for_user)
async def admin_enter_username(message: types.Message, state: FSMContext):
    # Проверяем есть ли pending запрос для этого админа
    db.cursor.execute('SELECT target_user_id, product_id FROM pending_key_issue WHERE admin_id = ?', (message.from_user.id,))
    row = db.cursor.fetchone()
    if row:
        target_user_id, product_id = row
        await state.update_data(panel_user=message.text.strip(), target_user_id=target_user_id, product_id=product_id)
        # Удаляем pending
        db.cursor.execute('DELETE FROM pending_key_issue WHERE admin_id = ?', (message.from_user.id,))
        db.conn.commit()
    else:
        await state.update_data(panel_user=message.text.strip())

    await state.set_state(KeyRequest.waiting_for_pass)
    await message.answer("🔒 Теперь введите <b>Password</b>:", parse_mode="HTML")

@router.message(KeyRequest.waiting_for_pass)
async def admin_enter_password(message: types.Message, state: FSMContext):
    data = await state.get_data()
    # Дебаг - показываем что получили из state
    await message.answer(
        f"🔍 Дебаг:\n"
        f"panel_user: <code>{data.get('panel_user')}</code>\n"
        f"target_user_id: <code>{data.get('target_user_id')}</code>\n"
        f"product_id: <code>{data.get('product_id')}</code>",
        parse_mode="HTML"
    )
    panel_user = data.get("panel_user")
    panel_pass = message.text.strip()
    target_user_id = data.get("target_user_id")
    product_id = data.get("product_id")

    db.cursor.execute('SELECT name FROM products WHERE id = ?', (product_id,))
    row = db.cursor.fetchone()
    product_name = row[0] if row else "Неизвестно"

    delivered = False
    try:
        await message.bot.send_message(
            target_user_id,
            f"🎉 <b>Ваши данные для входа готовы!</b>\n\n"
            f"📦 Товар: <b>{product_name}</b>\n"
            f"🖥 Username: <code>{panel_user}</code>\n"
            f"🔒 Password: <code>{panel_pass}</code>",
            parse_mode="HTML"
        )
        delivered = True
    except Exception as e:
        print(f"Ошибка отправки клиенту {target_user_id}: {e}")

    if delivered:
        await message.answer(
            f"✅ Данные успешно отправлены клиенту!\n"
            f"👤 ID: <code>{target_user_id}</code>\n"
            f"🖥 Username: <code>{panel_user}</code>\n"
            f"🔒 Password: <code>{panel_pass}</code>",
            parse_mode="HTML"
        )
        # Уведомление в лог-чат
        try:
            await message.bot.send_message(
                LOG_CHAT_ID,
                f"✅ <b>Ключ выдан!</b>\n"
                f"👤 Клиент ID: <code>{target_user_id}</code>\n"
                f"📦 Товар: <b>{product_name}</b>\n"
                f"🖥 Username: <code>{panel_user}</code>\n"
                f"🔒 Password: <code>{panel_pass}</code>\n"
                f"👨‍💼 Выдал: @{message.from_user.username or message.from_user.first_name}",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка отправки в лог-чат: {e}")
    else:
        await message.answer(
            f"❌ <b>Не удалось отправить клиенту!</b>\n"
            f"Возможно пользователь заблокировал бота.\n\n"
            f"Данные которые нужно передать вручную:\n"
            f"👤 ID: <code>{target_user_id}</code>\n"
            f"🖥 Username: <code>{panel_user}</code>\n"
            f"🔒 Password: <code>{panel_pass}</code>",
            parse_mode="HTML"
        )

    await state.clear()

# ==================== ЗАПУСК БОТА ====================
async def main():
    # Инициализация бота
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Подключаем роутер
    dp.include_router(router)
    
    print("🤖 Бот запущен...")
    print("📊 База данных инициализирована")
    print(f"👤 Админы: {ADMIN_IDS}")
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())