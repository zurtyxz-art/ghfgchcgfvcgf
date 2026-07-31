import asyncio
import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, LabeledPrice, PreCheckoutQuery,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InputFile, ContentType
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
import sqlite3
import hashlib
import time
import uuid

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8511170748:AAF1htcmjb_lf41yAjrSs19o3KQN9jHOtQ8"
PROVIDER_TOKEN = ""  # Оставить пустым для Telegram Stars
ADMIN_IDS = [5254779646]
SUPPORT_LINK = "https://t.me/FexorBS"
MAINTENANCE_MODE = False

# Инициализация
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_name="shop_bot.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.ensure_tables_exist()
        self.create_default_categories()

    def ensure_tables_exist(self):
        """Создает таблицы только если они не существуют (без удаления данных)"""

        # Пользователи
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Категории
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Группы
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                name TEXT NOT NULL,
                parent_group_id INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (category_id) REFERENCES categories (id)
            )
        ''')

        # Товары
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                name TEXT NOT NULL,
                price INTEGER NOT NULL,
                file_id TEXT,
                file_type TEXT,
                is_available BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES groups (id)
            )
        ''')

        # Заказы
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product_id INTEGER,
                comment TEXT,
                username TEXT,
                status TEXT DEFAULT 'pending',
                stars_paid INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        ''')

        # Временные заказы
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_orders (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                product_id INTEGER,
                product_name TEXT,
                price INTEGER,
                username TEXT,
                comment TEXT,
                category_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        self.conn.commit()
        print("✅ Таблицы базы данных проверены/созданы (данные сохранены)")

    def create_default_categories(self):
        self.cursor.execute("SELECT COUNT(*) FROM categories")
        if self.cursor.fetchone()[0] == 0:
            default_categories = ["Водянки", "Стикеры", "Приват"]
            for name in default_categories:
                self.cursor.execute("INSERT INTO categories (name) VALUES (?)", (name,))

            self.conn.commit()

            self.cursor.execute("SELECT id, name FROM categories")
            categories = self.cursor.fetchall()

            for cat_id, cat_name in categories:
                if cat_name == "Водянки":
                    default_groups = ["Водянки АЕ", "Водянки NODE VIDEO"]
                elif cat_name == "Стикеры":
                    default_groups = ["Стикеры 15 звезд", "Стикеры 25 звезд"]
                elif cat_name == "Приват":
                    default_groups = ["Приватный доступ"]
                else:
                    continue

                for group_name in default_groups:
                    self.cursor.execute(
                        "INSERT INTO groups (category_id, name) VALUES (?, ?)",
                        (cat_id, group_name)
                    )

            self.conn.commit()
            print("✅ Дефолтные категории и группы созданы")

    def add_user(self, user_id, username, first_name, last_name):
        self.cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name))
        self.conn.commit()

    def get_all_users(self):
        self.cursor.execute("SELECT user_id FROM users")
        return [row[0] for row in self.cursor.fetchall()]

    def add_category(self, name):
        self.cursor.execute("INSERT INTO categories (name) VALUES (?)", (name,))
        self.conn.commit()
        return self.cursor.lastrowid

    def get_categories(self):
        self.cursor.execute("SELECT id, name FROM categories ORDER BY id")
        return self.cursor.fetchall()

    def get_category(self, category_id):
        self.cursor.execute("SELECT id, name FROM categories WHERE id = ?", (category_id,))
        return self.cursor.fetchone()

    def update_category(self, category_id, name):
        self.cursor.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))
        self.conn.commit()

    def delete_category(self, category_id):
        self.cursor.execute("SELECT id FROM groups WHERE category_id = ?", (category_id,))
        groups = self.cursor.fetchall()

        for (group_id,) in groups:
            self.cursor.execute("DELETE FROM products WHERE group_id = ?", (group_id,))

        self.cursor.execute("DELETE FROM groups WHERE category_id = ?", (category_id,))
        self.cursor.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        self.conn.commit()

    def add_group(self, category_id, name, parent_group_id=0):
        self.cursor.execute(
            "INSERT INTO groups (category_id, name, parent_group_id) VALUES (?, ?, ?)",
            (category_id, name, parent_group_id)
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def get_groups(self, category_id=None, parent_group_id=0):
        if category_id:
            self.cursor.execute(
                '''SELECT id, name FROM groups 
                   WHERE category_id = ? AND parent_group_id = ? 
                   ORDER BY id''',
                (category_id, parent_group_id)
            )
        else:
            self.cursor.execute(
                '''SELECT id, name, category_id FROM groups 
                   WHERE parent_group_id = ? ORDER BY id''',
                (parent_group_id,)
            )
        return self.cursor.fetchall()

    def get_group(self, group_id):
        self.cursor.execute(
            "SELECT id, name, category_id, parent_group_id FROM groups WHERE id = ?",
            (group_id,)
        )
        return self.cursor.fetchone()

    def update_group(self, group_id, name):
        self.cursor.execute("UPDATE groups SET name = ? WHERE id = ?", (name, group_id))
        self.conn.commit()

    def delete_group(self, group_id):
        self.cursor.execute("DELETE FROM products WHERE group_id = ?", (group_id,))
        self.cursor.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        self.conn.commit()

    def add_product(self, group_id, name, price, file_id=None, file_type=None):
        self.cursor.execute(
            "INSERT INTO products (group_id, name, price, file_id, file_type) VALUES (?, ?, ?, ?, ?)",
            (group_id, name, price, file_id, file_type)
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def get_products(self, group_id):
        self.cursor.execute(
            '''SELECT id, name, price, file_id, file_type, is_available 
               FROM products WHERE group_id = ? ORDER BY id''',
            (group_id,)
        )
        return self.cursor.fetchall()

    def get_product(self, product_id):
        self.cursor.execute(
            '''SELECT p.id, p.name, p.price, p.file_id, p.file_type, 
                      p.group_id, g.name as group_name, c.name as category_name
               FROM products p
               JOIN groups g ON p.group_id = g.id
               JOIN categories c ON g.category_id = c.id
               WHERE p.id = ?''',
            (product_id,)
        )
        return self.cursor.fetchone()

    def update_product(self, product_id, name=None, price=None, is_available=None):
        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if price is not None:
            updates.append("price = ?")
            params.append(price)
        if is_available is not None:
            updates.append("is_available = ?")
            params.append(is_available)

        if updates:
            params.append(product_id)
            query = f"UPDATE products SET {', '.join(updates)} WHERE id = ?"
            self.cursor.execute(query, params)
            self.conn.commit()

    def delete_product(self, product_id):
        self.cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
        self.conn.commit()

    def create_pending_order(self, order_id, user_id, product_id, product_name, price, username, comment,
                             category_name):
        self.cursor.execute('''
            INSERT INTO pending_orders (id, user_id, product_id, product_name, price, username, comment, category_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (order_id, user_id, product_id, product_name, price, username, comment, category_name))
        self.conn.commit()

    def get_pending_order(self, order_id):
        self.cursor.execute('''
            SELECT * FROM pending_orders WHERE id = ?
        ''', (order_id,))
        return self.cursor.fetchone()

    def delete_pending_order(self, order_id):
        self.cursor.execute("DELETE FROM pending_orders WHERE id = ?", (order_id,))
        self.conn.commit()

    def create_order(self, user_id, product_id, comment, username, stars_paid):
        self.cursor.execute('''
            INSERT INTO orders (user_id, product_id, comment, username, stars_paid)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, product_id, comment, username, stars_paid))
        self.conn.commit()
        return self.cursor.lastrowid

    def get_orders(self, status="pending"):
        self.cursor.execute('''
            SELECT o.id, o.user_id, o.comment, o.username, o.stars_paid, o.created_at,
                   p.name as product_name, p.price, u.username as user_username,
                   u.first_name, c.name as category_name, g.name as group_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            JOIN users u ON o.user_id = u.user_id
            JOIN groups g ON p.group_id = g.id
            JOIN categories c ON g.category_id = c.id
            WHERE o.status = ?
            ORDER BY o.created_at DESC
        ''', (status,))
        return self.cursor.fetchall()

    def get_order(self, order_id):
        self.cursor.execute('''
            SELECT o.*, p.name as product_name, p.file_id, p.file_type,
                   u.username as user_username, u.first_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            JOIN users u ON o.user_id = u.user_id
            WHERE o.id = ?
        ''', (order_id,))
        return self.cursor.fetchone()

    def update_order_status(self, order_id, status):
        self.cursor.execute(
            "UPDATE orders SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, order_id)
        )
        self.conn.commit()

    def cancel_order(self, order_id):
        self.cursor.execute(
            "UPDATE orders SET status = 'cancelled' WHERE id = ?",
            (order_id,)
        )
        self.conn.commit()


# Инициализация БД
db = Database()


# ========== FSM СОСТОЯНИЯ ==========
class AdminStates(StatesGroup):
    waiting_for_broadcast_message = State()
    waiting_for_broadcast_button = State()
    waiting_for_broadcast_url = State()
    waiting_for_category_name = State()
    waiting_for_group_name = State()
    waiting_for_product_name = State()
    waiting_for_product_price = State()
    waiting_for_product_file = State()
    waiting_for_edit_category_name = State()
    waiting_for_edit_group_name = State()
    waiting_for_edit_product_name = State()
    waiting_for_edit_product_price = State()


class UserStates(StatesGroup):
    waiting_for_comment = State()
    waiting_for_username = State()


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_maintenance_mode() -> bool:
    return MAINTENANCE_MODE


def set_maintenance_mode(value: bool):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = value


def generate_order_id():
    return str(uuid.uuid4())[:8]


# ПОЛЬЗОВАТЕЛЬСКИЕ КЛАВИАТУРЫ
def create_categories_keyboard():
    categories = db.get_categories()
    keyboard = InlineKeyboardBuilder()

    for cat_id, name in categories:
        keyboard.button(text=f"📁 {name}", callback_data=f"cat_{cat_id}")

    keyboard.button(text="🆘 Поддержка", url=SUPPORT_LINK)
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_groups_keyboard(category_id, parent_group_id=0):
    groups = db.get_groups(category_id, parent_group_id)
    keyboard = InlineKeyboardBuilder()

    for group_id, name in groups:
        keyboard.button(text=f"📂 {name}", callback_data=f"grp_{group_id}")

    if parent_group_id > 0:
        keyboard.button(text="🔙 Назад", callback_data=f"grp_{parent_group_id}")
    else:
        keyboard.button(text="🔙 К категориям", callback_data="back_to_cats")

    keyboard.adjust(1)
    return keyboard.as_markup()


def create_products_keyboard(group_id):
    products = db.get_products(group_id)
    group = db.get_group(group_id)

    keyboard = InlineKeyboardBuilder()

    if not products:
        keyboard.button(text="📭 Товаров пока нет", callback_data="no_products")
    else:
        for product_id, name, price, _, _, is_available in products:
            status = "✅" if is_available else "⛔"
            keyboard.button(
                text=f"{status} {name} - {price} звёзд",
                callback_data=f"prod_{product_id}"
            )

    if group:
        _, _, category_id, parent_group_id = group
        if parent_group_id > 0:
            keyboard.button(text="🔙 К подгруппам", callback_data=f"grp_{parent_group_id}")
        else:
            keyboard.button(text="🔙 К группам", callback_data=f"cat_{category_id}")

    keyboard.adjust(1)
    return keyboard.as_markup()


# АДМИН КЛАВИАТУРЫ
def create_admin_main_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📢 Рассылка", callback_data="adm_broadcast")
    keyboard.button(text="⚙️ Технические работы", callback_data="adm_maintenance")
    keyboard.button(text="📁 Управление категориями", callback_data="adm_cats")
    keyboard.button(text="📂 Управление группами", callback_data="adm_grps")
    keyboard.button(text="🛍️ Управление товарами", callback_data="adm_prods")
    keyboard.button(text="📦 Заказы", callback_data="adm_orders")
    keyboard.button(text="📊 Статистика", callback_data="adm_stats")
    keyboard.button(text="🔙 В меню", callback_data="main_menu")
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_admin_categories_keyboard():
    categories = db.get_categories()
    keyboard = InlineKeyboardBuilder()

    for cat_id, name in categories:
        keyboard.button(text=f"✏️ {name}", callback_data=f"adm_cat_edit_{cat_id}")

    keyboard.button(text="➕ Добавить категорию", callback_data="adm_cat_add")
    keyboard.button(text="🔙 В админку", callback_data="adm_back")
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_edit_category_keyboard(category_id):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 Изменить название", callback_data=f"adm_cat_rename_{category_id}")
    keyboard.button(text="🗑️ Удалить категорию", callback_data=f"adm_cat_del_{category_id}")
    keyboard.button(text="🔙 К категориям", callback_data="adm_cats")
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_admin_groups_keyboard():
    categories = db.get_categories()
    keyboard = InlineKeyboardBuilder()

    for cat_id, name in categories:
        keyboard.button(text=f"📁 {name}", callback_data=f"adm_grps_cat_{cat_id}")

    keyboard.button(text="➕ Добавить группу", callback_data="adm_grp_add")
    keyboard.button(text="🔙 В админку", callback_data="adm_back")
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_admin_groups_list_keyboard(category_id):
    groups = db.get_groups(category_id)
    keyboard = InlineKeyboardBuilder()

    for group_id, name in groups:
        keyboard.button(text=f"✏️ {name}", callback_data=f"adm_grp_edit_{group_id}")

    keyboard.button(text="➕ Добавить группу", callback_data=f"adm_grp_add_cat_{category_id}")
    keyboard.button(text="🔙 К группам", callback_data="adm_grps")
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_edit_group_keyboard(group_id):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 Изменить название", callback_data=f"adm_grp_rename_{group_id}")
    keyboard.button(text="🗑️ Удалить группу", callback_data=f"adm_grp_del_{group_id}")
    keyboard.button(text="🔙 К списку групп", callback_data="adm_grps")
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_admin_products_keyboard():
    categories = db.get_categories()
    keyboard = InlineKeyboardBuilder()

    for cat_id, name in categories:
        keyboard.button(text=f"📁 {name}", callback_data=f"adm_prods_cat_{cat_id}")

    keyboard.button(text="➕ Добавить товар", callback_data="adm_prod_add")
    keyboard.button(text="🔙 В админку", callback_data="adm_back")
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_admin_groups_for_products_keyboard(category_id):
    groups = db.get_groups(category_id)
    keyboard = InlineKeyboardBuilder()

    for group_id, name in groups:
        keyboard.button(text=f"📂 {name}", callback_data=f"adm_prods_grp_{group_id}")

    keyboard.button(text="➕ Добавить товар", callback_data=f"adm_prod_add_cat_{category_id}")
    keyboard.button(text="🔙 К товарам", callback_data="adm_prods")
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_admin_products_list_keyboard(group_id):
    products = db.get_products(group_id)
    keyboard = InlineKeyboardBuilder()

    for prod_id, name, price, _, _, is_available in products:
        status = "✅" if is_available else "⛔"
        keyboard.button(text=f"{status} {name}", callback_data=f"adm_prod_edit_{prod_id}")

    keyboard.button(text="➕ Добавить товар", callback_data=f"adm_prod_add_grp_{group_id}")
    keyboard.button(text="🔙 Назад", callback_data=f"adm_prods_cat_{db.get_group(group_id)[2]}")
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_edit_product_keyboard(product_id):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 Изменить название", callback_data=f"adm_prod_rename_{product_id}")
    keyboard.button(text="💰 Изменить цену", callback_data=f"adm_prod_price_{product_id}")
    keyboard.button(text="✅ Вкл/Выкл", callback_data=f"adm_prod_toggle_{product_id}")
    keyboard.button(text="🗑️ Удалить товар", callback_data=f"adm_prod_del_{product_id}")
    keyboard.button(text="🔙 К списку товаров", callback_data=f"adm_prods_grp_{db.get_product(product_id)[5]}")
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_admin_orders_keyboard():
    orders = db.get_orders("pending")
    keyboard = InlineKeyboardBuilder()

    if orders:
        for order in orders[:10]:
            order_id, user_id, comment, username, stars_paid, created_at, product_name, *_ = order
            time_str = created_at.split()[1][:5] if isinstance(created_at, str) else created_at.strftime("%H:%M")
            keyboard.button(
                text=f"#{order_id} {product_name[:15]}... - {stars_paid}⭐",
                callback_data=f"adm_order_{order_id}"
            )
    else:
        keyboard.button(text="📭 Нет ожидающих заказов", callback_data="no_orders")

    keyboard.button(text="🔄 Обновить", callback_data="adm_orders")
    keyboard.button(text="🔙 В админку", callback_data="adm_back")
    keyboard.adjust(1)
    return keyboard.as_markup()


def create_order_detail_keyboard(order_id):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✅ Выдать товар", callback_data=f"adm_order_complete_{order_id}")
    keyboard.button(text="❌ Отменить заказ", callback_data=f"adm_order_cancel_{order_id}")
    keyboard.button(text="🔙 К заказам", callback_data="adm_orders")
    keyboard.adjust(2)
    return keyboard.as_markup()


# ========== ОСНОВНЫЕ КОМАНДЫ ==========
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    db.add_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )

    if get_maintenance_mode() and not is_admin(message.from_user.id):
        await message.answer("⛔ Бот на технических работах. Пожалуйста, зайдите позже.")
        return

    welcome_text = """🛍️ Добро пожаловать в магазин!

Здесь вы можете приобрести:
• Водяные знаки (Каталог: @Zurtyxz_WM)
• Наборы стикеров @zurtyxz_price
• Приват

Выберите категорию:"""

    await message.answer(welcome_text, reply_markup=create_categories_keyboard())


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return

    admin_text = "👑 Админ-панель\n\nВыберите действие:"
    await message.answer(admin_text, reply_markup=create_admin_main_keyboard())


# ========== ПОЛЬЗОВАТЕЛЬСКАЯ НАВИГАЦИЯ ==========
@dp.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🛍️ Добро пожаловать в магазин!\n\nВыберите категорию:",
        reply_markup=create_categories_keyboard()
    )


@dp.callback_query(F.data == "back_to_cats")
async def back_to_categories_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🛍️ Выберите категорию:",
        reply_markup=create_categories_keyboard()
    )


@dp.callback_query(F.data.startswith("cat_"))
async def category_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if get_maintenance_mode() and not is_admin(callback.from_user.id):
        await callback.answer("⛔ Бот на технических работах.", show_alert=True)
        return

    category_id = int(callback.data.split("_")[1])
    category = db.get_category(category_id)

    if category:
        cat_id, name = category
        text = f"📁 {name}\n\nВыберите группу:"
        await callback.message.edit_text(text, reply_markup=create_groups_keyboard(category_id))


@dp.callback_query(F.data.startswith("grp_"))
async def group_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if get_maintenance_mode() and not is_admin(callback.from_user.id):
        await callback.answer("⛔ Бот на технических работах.", show_alert=True)
        return

    group_id = int(callback.data.split("_")[1])
    group = db.get_group(group_id)

    if group:
        g_id, name, category_id, parent_group_id = group

        subgroups = db.get_groups(category_id, group_id)
        if subgroups:
            text = f"📂 {name}\n\nВыберите подгруппу:"
            await callback.message.edit_text(text, reply_markup=create_groups_keyboard(category_id, group_id))
        else:
            text = f"📂 {name}\n\nВыберите товар:"
            await callback.message.edit_text(text, reply_markup=create_products_keyboard(group_id))


@dp.callback_query(F.data.startswith("prod_"))
async def product_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if get_maintenance_mode() and not is_admin(callback.from_user.id):
        await callback.answer("⛔ Бот на технических работах.", show_alert=True)
        return

    product_id = int(callback.data.split("_")[1])
    product = db.get_product(product_id)

    if product:
        (p_id, name, price, file_id, file_type,
         group_id, group_name, category_name) = product

        await state.update_data(
            product_id=product_id,
            product_name=name,
            product_price=price,
            category_name=category_name,
            group_name=group_name
        )

        product_type = "sticker" if "стикер" in category_name.lower() else "watermark" if "водян" in category_name.lower() else "other"
        await state.update_data(product_type=product_type)

        text = f"""🛍️ Товар: {name}
📁 Категория: {category_name}
📂 Группа: {group_name}
💰 Цена: {price} звёзд

Для оформления заказа нажмите кнопку ниже."""

        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="💫 Купить", callback_data=f"buy_{product_id}")
        keyboard.button(text="🔙 Назад", callback_data=f"grp_{group_id}")
        keyboard.adjust(1)

        if file_id and file_type:
            try:
                if file_type == "photo":
                    await callback.message.answer_photo(file_id, caption=text, reply_markup=keyboard.as_markup())
                elif file_type == "video":
                    await callback.message.answer_video(file_id, caption=text, reply_markup=keyboard.as_markup())
                elif file_type == "document":
                    await callback.message.answer_document(file_id, caption=text, reply_markup=keyboard.as_markup())
                else:
                    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
                return
            except:
                pass

        await callback.message.edit_text(text, reply_markup=keyboard.as_markup())


@dp.callback_query(F.data.startswith("buy_"))
async def buy_handler(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[1])
    data = await state.get_data()
    product_type = data.get("product_type", "other")

    await state.update_data(current_product_id=product_id)

    if product_type in ["sticker", "watermark"]:
        await callback.message.answer("✏️ Пожалуйста, введите ник, который должен быть в водянке/стикере:")
        await state.set_state(UserStates.waiting_for_username)
    else:
        await callback.message.answer("✏️ Пожалуйста, введите комментарий к заказу:")
        await state.set_state(UserStates.waiting_for_comment)


@dp.message(UserStates.waiting_for_username)
async def username_handler(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("✏️ Пожалуйста, введите ник, который должен быть в водянке/стикере:")
        return

    username = message.text.strip()
    if not username:
        await message.answer("✏️ Пожалуйста, введите ник, который должен быть в водянке/стикере")
        return

    await state.update_data(username=username)
    await message.answer("✏️ Пожалуйста, введите номер водянки:")
    await state.set_state(UserStates.waiting_for_comment)


@dp.message(UserStates.waiting_for_comment)
async def comment_handler(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("✏️ Пожалуйста, введите номер водянки:")
        return

    comment = message.text.strip()
    if not comment:
        await message.answer("✏️ Пожалуйста, введите номер водянки:")
        return

    data = await state.get_data()

    product_id = data.get("current_product_id")
    if not product_id:
        await message.answer("❌ Ошибка: товар не найден. Начните заново.")
        await state.clear()
        return

    product = db.get_product(product_id)
    if not product:
        await message.answer("❌ Ошибка: товар не найден.")
        await state.clear()
        return

    (p_id, product_name, price, file_id, file_type,
     group_id, group_name, category_name) = product

    username = data.get("username", "")

    order_id = generate_order_id()

    db.create_pending_order(
        order_id=order_id,
        user_id=message.from_user.id,
        product_id=product_id,
        product_name=product_name,
        price=price,
        username=username,
        comment=comment,
        category_name=category_name
    )

    payload = f"order_{order_id}"

    builder = InlineKeyboardBuilder()
    builder.button(text="💫 Оплатить", pay=True)

    description = f"Товар: {product_name}"
    if username:
        description += f"\nНикнейм: {username}"
    if comment:
        description += f"\nКомментарий: {comment[:100]}"

    try:
        await bot.send_invoice(
            chat_id=message.chat.id,
            title=f"Оплата: {product_name}",
            description=description,
            payload=payload,
            provider_token=PROVIDER_TOKEN,
            currency="XTR",
            prices=[LabeledPrice(label=product_name, amount=price)],
            reply_markup=builder.as_markup()
        )
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании инвойса: {str(e)}")
        db.delete_pending_order(order_id)
        await state.clear()


# ========== ОПЛАТА ==========
@dp.pre_checkout_query()
async def pre_checkout_query(pre_checkout: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    try:
        stars_paid = message.successful_payment.total_amount
        payload = message.successful_payment.invoice_payload

        if not payload.startswith("order_"):
            await message.answer("✅ Оплата принята! Обратитесь к администратору.")
            return

        order_id = payload.replace("order_", "")

        pending_order = db.get_pending_order(order_id)

        if not pending_order:
            await message.answer("✅ Оплата принята! Обратитесь к администратору.")
            return

        if pending_order[1] != message.from_user.id:
            await message.answer("✅ Оплата принята! Обратитесь к администратору.")
            return

        order_db_id = db.create_order(
            user_id=pending_order[1],
            product_id=pending_order[2],
            comment=pending_order[6],
            username=pending_order[5],
            stars_paid=stars_paid
        )

        db.delete_pending_order(order_id)

        await message.answer(f"""
✅ Оплата прошла успешно!

📦 Заказ #{order_db_id}
🛍️ Товар: {pending_order[3]}
💰 Сумма: {stars_paid} звёзд

⏳ Ваш заказ будет выполнен в течение 48 часов.
Вы получите уведомление, когда товар будет готов.
""")

        admin_text = f"""
🔔 НОВЫЙ ЗАКАЗ!

📋 Информация о заказе:
├ ID: #{order_db_id}
├ Пользователь: @{message.from_user.username or 'нет'}
├ Имя: {message.from_user.first_name}
├ ID пользователя: {message.from_user.id}
├ Товар: {pending_order[3]}
├ Категория: {pending_order[7]}
├ Никнейм: {pending_order[5] or 'не указан'}
├ Комментарий: {pending_order[6]}
├ Сумма: {stars_paid} звёзд
└ Время: {datetime.now().strftime('%H:%M:%S')}
"""

        for admin_id in ADMIN_IDS:
            try:
                keyboard = InlineKeyboardBuilder()
                keyboard.button(text="📦 Просмотреть заказ", callback_data=f"adm_order_{order_db_id}")
                await bot.send_message(admin_id, admin_text, reply_markup=keyboard.as_markup())
            except Exception as e:
                print(f"❌ Ошибка отправки админу {admin_id}: {str(e)}")

    except Exception as e:
        print(f"❌ Ошибка при обработке оплаты: {str(e)}")
        await message.answer("✅ Оплата принята! Обратитесь к администратору для получения товара.")


# ========== АДМИН ПАНЕЛЬ ==========
@dp.callback_query(F.data == "adm_back")
async def admin_back_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "👑 Админ-панель\n\nВыберите действие:",
        reply_markup=create_admin_main_keyboard()
    )


# РАССЫЛКА
@dp.callback_query(F.data == "adm_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    await callback.message.answer("📢 Отправьте сообщение для рассылки:")
    await state.set_state(AdminStates.waiting_for_broadcast_message)


@dp.message(AdminStates.waiting_for_broadcast_message)
async def admin_broadcast_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    await state.update_data(broadcast_message=message.text)

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="➕ Добавить кнопку", callback_data="adm_broadcast_add_btn")
    keyboard.button(text="🚀 Отправить без кнопки", callback_data="adm_broadcast_send")
    keyboard.adjust(1)

    await message.answer(f"Сообщение для рассылки:\n\n{message.text}\n\nДобавить кнопку?",
                         reply_markup=keyboard.as_markup())


@dp.callback_query(F.data == "adm_broadcast_add_btn")
async def broadcast_add_button(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    await callback.message.answer("Введите текст для кнопки:")
    await state.set_state(AdminStates.waiting_for_broadcast_button)


@dp.message(AdminStates.waiting_for_broadcast_button)
async def broadcast_button_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    await state.update_data(button_text=message.text)
    await message.answer("Теперь введите URL для кнопки:")
    await state.set_state(AdminStates.waiting_for_broadcast_url)


@dp.message(AdminStates.waiting_for_broadcast_url)
async def broadcast_button_url(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    await state.update_data(button_url=message.text)

    data = await state.get_data()
    broadcast_text = data.get("broadcast_message", "")
    button_text = data.get("button_text", "")
    button_url = data.get("button_url", "")

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text=button_text, url=button_url)
    keyboard.adjust(1)

    await message.answer(
        f"Сообщение для рассылки с кнопкой:\n\n{broadcast_text}",
        reply_markup=keyboard.as_markup()
    )

    keyboard2 = InlineKeyboardBuilder()
    keyboard2.button(text="✅ Отправить", callback_data="adm_broadcast_send_with_btn")
    keyboard2.button(text="❌ Отмена", callback_data="adm_back")
    keyboard2.adjust(1)

    await message.answer("Отправить это сообщение?", reply_markup=keyboard2.as_markup())


@dp.callback_query(F.data == "adm_broadcast_send")
async def broadcast_send(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    data = await state.get_data()
    message_text = data.get("broadcast_message", "")

    users = db.get_all_users()
    sent = 0
    failed = 0

    await callback.message.answer(f"📤 Начинаю рассылку для {len(users)} пользователей...")

    for user_id in users:
        try:
            await bot.send_message(user_id, message_text)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1

    await callback.message.answer(f"✅ Рассылка завершена!\n\nОтправлено: {sent}\nНе отправлено: {failed}")
    await state.clear()

    admin_text = "👑 Админ-панель\n\nВыберите действие:"
    await callback.message.answer(admin_text, reply_markup=create_admin_main_keyboard())


@dp.callback_query(F.data == "adm_broadcast_send_with_btn")
async def broadcast_send_with_button(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    data = await state.get_data()
    message_text = data.get("broadcast_message", "")
    button_text = data.get("button_text", "")
    button_url = data.get("button_url", "")

    users = db.get_all_users()
    sent = 0
    failed = 0

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text=button_text, url=button_url)
    keyboard.adjust(1)

    await callback.message.answer(f"📤 Начинаю рассылку для {len(users)} пользователей...")

    for user_id in users:
        try:
            await bot.send_message(user_id, message_text, reply_markup=keyboard.as_markup())
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1

    await callback.message.answer(f"✅ Рассылка завершена!\n\nОтправлено: {sent}\nНе отправлено: {failed}")
    await state.clear()

    admin_text = "👑 Админ-панель\n\nВыберите действие:"
    await callback.message.answer(admin_text, reply_markup=create_admin_main_keyboard())


# ТЕХНИЧЕСКИЕ РАБОТЫ
@dp.callback_query(F.data == "adm_maintenance")
async def admin_maintenance_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    current_mode = get_maintenance_mode()
    new_mode = not current_mode

    set_maintenance_mode(new_mode)
    status = "включен" if new_mode else "выключен"

    await callback.answer(f"Режим технических работ {status}", show_alert=True)

    text = f"👑 Админ-панель\n\nРежим техработ: {'✅ ВКЛЮЧЕН' if new_mode else '❌ ВЫКЛЮЧЕН'}"
    await callback.message.edit_text(text, reply_markup=create_admin_main_keyboard())


# КАТЕГОРИИ
@dp.callback_query(F.data == "adm_cats")
async def admin_categories_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    categories = db.get_categories()
    text = "📁 Управление категориями\n\nСписок категорий:\n"

    for cat_id, name in categories:
        text += f"\n📁 {name}"

    await callback.message.edit_text(text, reply_markup=create_admin_categories_keyboard())


@dp.callback_query(F.data == "adm_cat_add")
async def admin_add_category_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    await callback.message.answer("Введите название новой категории:")
    await state.set_state(AdminStates.waiting_for_category_name)


@dp.message(AdminStates.waiting_for_category_name)
async def admin_add_category_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    category_name = message.text.strip()

    if not category_name:
        await message.answer("❌ Название не может быть пустым. Введите название:")
        return

    db.add_category(category_name)

    await message.answer(f"✅ Категория '{category_name}' добавлена!")
    await state.clear()

    categories = db.get_categories()
    text = "📁 Управление категориями\n\nСписок категорий:\n"

    for cat_id, name in categories:
        text += f"\n📁 {name}"

    await message.answer(text, reply_markup=create_admin_categories_keyboard())


@dp.callback_query(F.data.startswith("adm_cat_edit_"))
async def admin_edit_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    category_id = int(callback.data.split("_")[3])
    category = db.get_category(category_id)

    if category:
        cat_id, name = category
        text = f"✏️ Редактирование категории: {name}"

        await callback.message.edit_text(text, reply_markup=create_edit_category_keyboard(category_id))


@dp.callback_query(F.data.startswith("adm_cat_rename_"))
async def admin_rename_category_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    category_id = int(callback.data.split("_")[3])
    await state.update_data(edit_category_id=category_id)
    await callback.message.answer("Введите новое название категории:")
    await state.set_state(AdminStates.waiting_for_edit_category_name)


@dp.message(AdminStates.waiting_for_edit_category_name)
async def admin_rename_category(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    data = await state.get_data()
    category_id = data.get("edit_category_id")
    new_name = message.text.strip()

    if not new_name:
        await message.answer("❌ Название не может быть пустым. Введите название:")
        return

    db.update_category(category_id, new_name)

    await message.answer(f"✅ Категория переименована в '{new_name}'!")
    await state.clear()

    categories = db.get_categories()
    text = "📁 Управление категориями\n\nСписок категорий:\n"

    for cat_id, name in categories:
        text += f"\n📁 {name}"

    await message.answer(text, reply_markup=create_admin_categories_keyboard())


@dp.callback_query(F.data.startswith("adm_cat_del_"))
async def admin_delete_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    category_id = int(callback.data.split("_")[3])
    category = db.get_category(category_id)

    if category:
        cat_id, name = category

        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="✅ Да, удалить", callback_data=f"adm_cat_del_confirm_{category_id}")
        keyboard.button(text="❌ Нет, отмена", callback_data=f"adm_cat_edit_{category_id}")
        keyboard.adjust(2)

        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить категорию '{name}'?\n\nВсе группы и товары в ней также будут удалены!",
            reply_markup=keyboard.as_markup()
        )


@dp.callback_query(F.data.startswith("adm_cat_del_confirm_"))
async def admin_delete_category_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    try:
        category_id = int(callback.data.split("_")[4])
        db.delete_category(category_id)

        await callback.answer("✅ Категория удалена", show_alert=True)

        categories = db.get_categories()
        text = "📁 Управление категориями\n\nСписок категорий:\n"

        for cat_id, name in categories:
            text += f"\n📁 {name}"

        await callback.message.edit_text(text, reply_markup=create_admin_categories_keyboard())

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


# ГРУППЫ
@dp.callback_query(F.data == "adm_grps")
async def admin_groups_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    text = "📂 Управление группами\n\nВыберите категорию:"
    await callback.message.edit_text(text, reply_markup=create_admin_groups_keyboard())


@dp.callback_query(F.data.startswith("adm_grps_cat_"))
async def admin_groups_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    category_id = int(callback.data.split("_")[3])
    category = db.get_category(category_id)
    groups = db.get_groups(category_id)

    if category:
        cat_id, name = category
        text = f"📂 Группы в категории '{name}':\n"

        if groups:
            for group_id, group_name in groups:
                text += f"\n📂 {group_name}"
        else:
            text += "\n📭 Групп пока нет"

        await callback.message.edit_text(text, reply_markup=create_admin_groups_list_keyboard(category_id))


@dp.callback_query(F.data == "adm_grp_add")
async def admin_add_group_select_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    categories = db.get_categories()
    text = "➕ Добавление группы\n\nВыберите категорию:"

    keyboard = InlineKeyboardBuilder()
    for cat_id, name in categories:
        keyboard.button(text=name, callback_data=f"adm_grp_add_cat_{cat_id}")

    keyboard.button(text="🔙 К группам", callback_data="adm_grps")
    keyboard.adjust(1)

    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())


@dp.callback_query(F.data.startswith("adm_grp_add_cat_"))
async def admin_add_group_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    category_id = int(callback.data.split("_")[4])
    await state.update_data(category_id=category_id)
    await callback.message.answer("Введите название новой группы:")
    await state.set_state(AdminStates.waiting_for_group_name)


@dp.message(AdminStates.waiting_for_group_name)
async def admin_add_group_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    group_name = message.text.strip()

    if not group_name:
        await message.answer("❌ Название не может быть пустым. Введите название:")
        return

    db.add_group(category_id, group_name)

    await message.answer(f"✅ Группа '{group_name}' добавлена!")
    await state.clear()

    category = db.get_category(category_id)
    groups = db.get_groups(category_id)

    if category:
        cat_id, name = category
        text = f"📂 Группы в категории '{name}':\n"

        if groups:
            for group_id, g_name in groups:
                text += f"\n📂 {g_name}"
        else:
            text += "\n📭 Групп пока нет"

        await message.answer(text, reply_markup=create_admin_groups_list_keyboard(category_id))


@dp.callback_query(F.data.startswith("adm_grp_edit_"))
async def admin_edit_group(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    group_id = int(callback.data.split("_")[3])
    group = db.get_group(group_id)

    if group:
        g_id, name, category_id, parent_group_id = group
        text = f"✏️ Редактирование группы: {name}"

        await callback.message.edit_text(text, reply_markup=create_edit_group_keyboard(group_id))


@dp.callback_query(F.data.startswith("adm_grp_rename_"))
async def admin_rename_group_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    group_id = int(callback.data.split("_")[3])
    await state.update_data(edit_group_id=group_id)
    await callback.message.answer("Введите новое название группы:")
    await state.set_state(AdminStates.waiting_for_edit_group_name)


@dp.message(AdminStates.waiting_for_edit_group_name)
async def admin_rename_group(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    data = await state.get_data()
    group_id = data.get("edit_group_id")
    new_name = message.text.strip()

    if not new_name:
        await message.answer("❌ Название не может быть пустым. Введите название:")
        return

    db.update_group(group_id, new_name)

    await message.answer(f"✅ Группа переименована в '{new_name}'!")
    await state.clear()

    group = db.get_group(group_id)
    if group:
        g_id, name, category_id, parent_group_id = group

        text = f"✏️ Редактирование группы: {name}"
        await message.answer(text, reply_markup=create_edit_group_keyboard(group_id))


@dp.callback_query(F.data.startswith("adm_grp_del_"))
async def admin_delete_group(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    group_id = int(callback.data.split("_")[3])
    group = db.get_group(group_id)

    if group:
        g_id, name, category_id, parent_group_id = group

        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="✅ Да, удалить", callback_data=f"adm_grp_del_confirm_{group_id}")
        keyboard.button(text="❌ Нет, отмена", callback_data=f"adm_grp_edit_{group_id}")
        keyboard.adjust(2)

        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить группу '{name}'?\n\nВсе товары в ней также будут удалены!",
            reply_markup=keyboard.as_markup()
        )


@dp.callback_query(F.data.startswith("adm_grp_del_confirm_"))
async def admin_delete_group_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    group_id = int(callback.data.split("_")[4])
    group = db.get_group(group_id)

    if group:
        g_id, name, category_id, parent_group_id = group
        db.delete_group(group_id)

        await callback.answer(f"✅ Группа '{name}' удалена", show_alert=True)

        groups = db.get_groups(category_id)
        category = db.get_category(category_id)

        if category:
            cat_id, cat_name = category
            text = f"📂 Группы в категории '{cat_name}':\n"

            if groups:
                for g_id, g_name in groups:
                    text += f"\n📂 {g_name}"
            else:
                text += "\n📭 Групп пока нет"

            await callback.message.edit_text(text, reply_markup=create_admin_groups_list_keyboard(category_id))


# ТОВАРЫ
@dp.callback_query(F.data == "adm_prods")
async def admin_products_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    text = "🛍️ Управление товарами\n\nВыберите категорию:"
    await callback.message.edit_text(text, reply_markup=create_admin_products_keyboard())


@dp.callback_query(F.data.startswith("adm_prods_cat_"))
async def admin_products_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    category_id = int(callback.data.split("_")[3])
    category = db.get_category(category_id)

    if category:
        cat_id, name = category
        text = f"🛍️ Товары в категории '{name}'\n\nВыберите группу:"
        await callback.message.edit_text(text, reply_markup=create_admin_groups_for_products_keyboard(category_id))


@dp.callback_query(F.data.startswith("adm_prods_grp_"))
async def admin_products_group(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    group_id = int(callback.data.split("_")[3])
    group = db.get_group(group_id)
    products = db.get_products(group_id)

    if group:
        g_id, name, category_id, parent_group_id = group
        text = f"🛍️ Товары в группе '{name}':\n"

        if products:
            for prod_id, prod_name, price, _, _, is_available in products:
                status = "✅" if is_available else "⛔"
                text += f"\n{status} {prod_name} - {price} звёзд"
        else:
            text += "\n📭 Товаров пока нет"

        await callback.message.edit_text(text, reply_markup=create_admin_products_list_keyboard(group_id))


@dp.callback_query(F.data == "adm_prod_add")
async def admin_add_product_select_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    categories = db.get_categories()
    text = "➕ Добавление товара\n\nВыберите категорию:"

    keyboard = InlineKeyboardBuilder()
    for cat_id, name in categories:
        keyboard.button(text=name, callback_data=f"adm_prod_add_cat_{cat_id}")

    keyboard.button(text="🔙 К товарам", callback_data="adm_prods")
    keyboard.adjust(1)

    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())


@dp.callback_query(F.data.startswith("adm_prod_add_cat_"))
async def admin_add_product_select_group(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    category_id = int(callback.data.split("_")[4])
    groups = db.get_groups(category_id)

    if not groups:
        await callback.answer("❌ В этой категории нет групп! Сначала добавьте группу.", show_alert=True)
        return

    text = "➕ Добавление товара\n\nВыберите группу:"

    keyboard = InlineKeyboardBuilder()
    for group_id, name in groups:
        keyboard.button(text=name, callback_data=f"adm_prod_add_grp_{group_id}")

    keyboard.button(text="🔙 Назад", callback_data="adm_prod_add")
    keyboard.adjust(1)

    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())


@dp.callback_query(F.data.startswith("adm_prod_add_grp_"))
async def admin_add_product_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    group_id = int(callback.data.split("_")[4])
    await state.update_data(group_id=group_id)
    await callback.message.answer("Введите название товара:")
    await state.set_state(AdminStates.waiting_for_product_name)


@dp.message(AdminStates.waiting_for_product_name)
async def admin_add_product_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    product_name = message.text.strip()

    if not product_name:
        await message.answer("❌ Название не может быть пустым. Введите название:")
        return

    await state.update_data(product_name=product_name)
    await message.answer("Введите цену в звездах (только число):")
    await state.set_state(AdminStates.waiting_for_product_price)


@dp.message(AdminStates.waiting_for_product_price)
async def admin_add_product_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    try:
        price = int(message.text)
        if price <= 0:
            await message.answer("❌ Цена должна быть положительным числом. Введите цену:")
            return

        await state.update_data(product_price=price)
        await message.answer("Отправьте файл товара (фото, видео, документ) или напишите /skip:")
        await state.set_state(AdminStates.waiting_for_product_file)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите число:")


@dp.message(AdminStates.waiting_for_product_file)
async def admin_add_product_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    data = await state.get_data()

    file_id = None
    file_type = None

    if message.text and message.text.lower() == "/skip":
        pass
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"
    else:
        await message.answer("❌ Пожалуйста, отправьте файл (фото, видео, документ) или напишите /skip")
        return

    group_id = data.get("group_id")
    name = data.get("product_name")
    price = data.get("product_price")

    if not name or not price:
        await message.answer("❌ Ошибка: данные товара неполные. Начните заново.")
        await state.clear()
        return

    try:
        db.add_product(group_id, name, price, file_id, file_type)
        await message.answer(f"✅ Товар '{name}' успешно добавлен!")
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении товара: {str(e)}")

    await state.clear()

    group = db.get_group(group_id)
    if group:
        g_id, g_name, category_id, parent_group_id = group

        text = f"✅ Товар добавлен в группу '{g_name}'!\n\nЧто дальше?"

        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="➕ Добавить еще товар", callback_data=f"adm_prod_add_grp_{group_id}")
        keyboard.button(text="📋 Посмотреть товары", callback_data=f"adm_prods_grp_{group_id}")
        keyboard.button(text="🔙 К товарам", callback_data="adm_prods")
        keyboard.adjust(1)

        await message.answer(text, reply_markup=keyboard.as_markup())


@dp.callback_query(F.data.startswith("adm_prod_edit_"))
async def admin_edit_product(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    product_id = int(callback.data.split("_")[3])
    product = db.get_product(product_id)

    if product:
        (p_id, name, price, file_id, file_type,
         group_id, group_name, category_name) = product

        has_file = "✅ Есть" if file_id else "❌ Нет"

        text = f"""✏️ Редактирование товара

📝 Название: {name}
💰 Цена: {price} звёзд
📎 Файл: {has_file}
📂 Группа: {group_name}
📁 Категория: {category_name}"""

        await callback.message.edit_text(text, reply_markup=create_edit_product_keyboard(product_id))


@dp.callback_query(F.data.startswith("adm_prod_rename_"))
async def admin_rename_product_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    product_id = int(callback.data.split("_")[3])
    await state.update_data(edit_product_id=product_id)
    await callback.message.answer("Введите новое название товара:")
    await state.set_state(AdminStates.waiting_for_edit_product_name)


@dp.message(AdminStates.waiting_for_edit_product_name)
async def admin_rename_product(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    data = await state.get_data()
    product_id = data.get("edit_product_id")
    new_name = message.text.strip()

    if not new_name:
        await message.answer("❌ Название не может быть пустым. Введите название:")
        return

    db.update_product(product_id, name=new_name)

    await message.answer(f"✅ Товар переименован в '{new_name}'!")
    await state.clear()

    product = db.get_product(product_id)
    if product:
        (p_id, name, price, file_id, file_type,
         group_id, group_name, category_name) = product

        has_file = "✅ Есть" if file_id else "❌ Нет"

        text = f"""✏️ Редактирование товара

📝 Название: {name}
💰 Цена: {price} звёзд
📎 Файл: {has_file}
📂 Группа: {group_name}
📁 Категория: {category_name}"""

        await message.answer(text, reply_markup=create_edit_product_keyboard(product_id))


@dp.callback_query(F.data.startswith("adm_prod_price_"))
async def admin_change_price_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    product_id = int(callback.data.split("_")[3])
    await state.update_data(edit_product_price_id=product_id)
    await callback.message.answer("Введите новую цену в звездах:")
    await state.set_state(AdminStates.waiting_for_edit_product_price)


@dp.message(AdminStates.waiting_for_edit_product_price)
async def admin_change_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа")
        await state.clear()
        return

    try:
        data = await state.get_data()
        product_id = data.get("edit_product_price_id")
        new_price = int(message.text)

        if new_price <= 0:
            await message.answer("❌ Цена должна быть положительным числом. Введите цену:")
            return

        db.update_product(product_id, price=new_price)

        await message.answer(f"✅ Цена товара изменена на {new_price} звёзд!")
        await state.clear()

        product = db.get_product(product_id)
        if product:
            (p_id, name, price, file_id, file_type,
             group_id, group_name, category_name) = product

            has_file = "✅ Есть" if file_id else "❌ Нет"

            text = f"""✏️ Редактирование товара

📝 Название: {name}
💰 Цена: {price} звёзд
📎 Файл: {has_file}
📂 Группа: {group_name}
📁 Категория: {category_name}"""

            await message.answer(text, reply_markup=create_edit_product_keyboard(product_id))
    except ValueError:
        await message.answer("❌ Пожалуйста, введите число:")


@dp.callback_query(F.data.startswith("adm_prod_toggle_"))
async def admin_toggle_product(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    product_id = int(callback.data.split("_")[3])
    product = db.get_product(product_id)

    if product:
        (p_id, name, price, file_id, file_type,
         group_id, group_name, category_name) = product

        db.cursor.execute("SELECT is_available FROM products WHERE id = ?", (product_id,))
        result = db.cursor.fetchone()
        if result:
            current_status = result[0]
            new_status = not current_status

            db.update_product(product_id, is_available=new_status)

            status_text = "включен" if new_status else "выключен"
            await callback.answer(f"✅ Товар {status_text}", show_alert=True)

            has_file = "✅ Есть" if file_id else "❌ Нет"

            text = f"""✏️ Редактирование товара

📝 Название: {name}
💰 Цена: {price} звёзд
📎 Файл: {has_file}
📂 Группа: {group_name}
📁 Категория: {category_name}
🔄 Статус: {'✅ Включен' if new_status else '⛔ Выключен'}"""

            await callback.message.edit_text(text, reply_markup=create_edit_product_keyboard(product_id))


@dp.callback_query(F.data.startswith("adm_prod_del_"))
async def admin_delete_product(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    product_id = int(callback.data.split("_")[3])
    product = db.get_product(product_id)

    if product:
        (p_id, name, price, file_id, file_type,
         group_id, group_name, category_name) = product

        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="✅ Да, удалить", callback_data=f"adm_prod_del_confirm_{product_id}")
        keyboard.button(text="❌ Нет, отмена", callback_data=f"adm_prod_edit_{product_id}")
        keyboard.adjust(2)

        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить товар '{name}'?",
            reply_markup=keyboard.as_markup()
        )


@dp.callback_query(F.data.startswith("adm_prod_del_confirm_"))
async def admin_delete_product_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    product_id = int(callback.data.split("_")[4])
    product = db.get_product(product_id)

    if product:
        (p_id, name, price, file_id, file_type,
         group_id, group_name, category_name) = product

        db.delete_product(product_id)

        await callback.answer(f"✅ Товар '{name}' удален", show_alert=True)

        products = db.get_products(group_id)
        group = db.get_group(group_id)

        if group:
            g_id, g_name, category_id, parent_group_id = group
            text = f"🛍️ Товары в группе '{g_name}':\n"

            if products:
                for prod_id, prod_name, prod_price, _, _, is_available in products:
                    status = "✅" if is_available else "⛔"
                    text += f"\n{status} {prod_name} - {prod_price} звёзд"
            else:
                text += "\n📭 Товаров пока нет"

            await callback.message.edit_text(text, reply_markup=create_admin_products_list_keyboard(group_id))


# ЗАКАЗЫ
@dp.callback_query(F.data == "adm_orders")
async def admin_orders_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    orders = db.get_orders("pending")

    if not orders:
        text = "📦 Заказы\n\n📭 Нет ожидающих заказов"
    else:
        text = f"📦 Заказы\n\nОжидают выдачи: {len(orders)} заказов\n"
        for order in orders[:10]:
            order_id, user_id, comment, username, stars_paid, created_at, product_name, *_ = order
            time_str = created_at.split()[1][:5] if isinstance(created_at, str) else created_at.strftime("%H:%M")
            text += f"\n#{order_id} {product_name} - {username} ({time_str})"

    await callback.message.edit_text(text, reply_markup=create_admin_orders_keyboard())


@dp.callback_query(F.data.startswith("adm_order_"))
async def admin_order_detail(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    try:
        order_id = int(callback.data.split("_")[2])
        order = db.get_order(order_id)

        if order:
            (o_id, user_id, product_id, comment, username, status,
             stars_paid, created_at, completed_at, product_name,
             file_id, file_type, user_username, first_name) = order

            created_time = created_at.split()[1][:5] if isinstance(created_at, str) else created_at.strftime("%H:%M")
            status_text = {
                'pending': '⏳ Ожидает',
                'completed': '✅ Выполнен',
                'cancelled': '❌ Отменен'
            }.get(status, status)

            text = f"""📦 Заказ #{order_id} ({status_text})

👤 Пользователь:
├ ID: {user_id}
├ Username: @{user_username or 'нет'}
├ Имя: {first_name}
├ Ник для заказа: {username}

🛍️ Товар: {product_name}
💰 Сумма: {stars_paid} звёзд
🕐 Время создания: {created_time}
"""
            if completed_at:
                completed_time = completed_at.split()[1][:5] if isinstance(completed_at,
                                                                           str) else completed_at.strftime("%H:%M")
                text += f"🕐 Время завершения: {completed_time}\n"

            text += f"""
📝 Комментарий:
{comment}
"""
            if file_id:
                text += f"\n📎 Файл товара: {'Есть' if file_id else 'Нет'}"

            await callback.message.edit_text(text, reply_markup=create_order_detail_keyboard(order_id))
        else:
            await callback.answer("❌ Заказ не найден", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@dp.callback_query(F.data.startswith("adm_order_complete_"))
async def admin_complete_order(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    try:
        order_id = int(callback.data.split("_")[3])
        order = db.get_order(order_id)

        if order:
            (o_id, user_id, product_id, comment, username, status,
             stars_paid, created_at, completed_at, product_name,
             file_id, file_type, user_username, first_name) = order

            db.update_order_status(order_id, "completed")

            if file_id and file_type:
                try:
                    caption = f"✅ Ваш заказ #{order_id} готов!\n\nТовар: {product_name}"

                    if file_type == "photo":
                        await bot.send_photo(user_id, file_id, caption=caption)
                    elif file_type == "video":
                        await bot.send_video(user_id, file_id, caption=caption)
                    elif file_type == "document":
                        await bot.send_document(user_id, file_id, caption=caption)
                    else:
                        await bot.send_message(user_id, caption)

                    await bot.send_message(
                        user_id,
                        f"✅ Ваш заказ #{order_id} выполнен!\n\n"
                        f"🛍️ Товар: {product_name}\n"
                        f"💰 Сумма: {stars_paid} звёзд\n\n"
                        f"Спасибо за покупку! ❤️"
                    )
                except Exception as e:
                    print(f"❌ Ошибка отправки файла пользователю {user_id}: {str(e)}")
            else:
                await bot.send_message(
                    user_id,
                    f"✅ Ваш заказ #{order_id} выполнен!\n\n"
                    f"🛍️ Товар: {product_name}\n"
                    f"💰 Сумма: {stars_paid} звёзд\n\n"
                    f"Спасибо за покупку! ❤️"
                )

            await callback.answer("✅ Товар отправлен пользователю", show_alert=True)

            created_time = created_at.split()[1][:5] if isinstance(created_at, str) else created_at.strftime("%H:%M")
            current_time = datetime.now().strftime("%H:%M")

            text = f"""✅ Заказ #{order_id} ВЫПОЛНЕН

👤 Пользователь:
├ ID: {user_id}
├ Username: @{user_username or 'нет'}
├ Имя: {first_name}
├ Ник для заказа: {username}

🛍️ Товар: {product_name}
💰 Сумма: {stars_paid} звёзд
🕐 Время заказа: {created_time}
🕐 Время выдачи: {current_time}

📝 Комментарий:
{comment}
"""

            keyboard = InlineKeyboardBuilder()
            keyboard.button(text="🔙 К заказам", callback_data="adm_orders")
            keyboard.adjust(1)

            await callback.message.edit_text(text, reply_markup=keyboard.as_markup())

        else:
            await callback.answer("❌ Заказ не найден", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@dp.callback_query(F.data.startswith("adm_order_cancel_"))
async def admin_cancel_order(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    try:
        order_id = int(callback.data.split("_")[3])
        order = db.get_order(order_id)

        if order:
            (o_id, user_id, product_id, comment, username, status,
             stars_paid, created_at, completed_at, product_name,
             file_id, file_type, user_username, first_name) = order

            db.cancel_order(order_id)

            try:
                await bot.send_message(
                    user_id,
                    f"❌ Ваш заказ #{order_id} отменен администратором.\n\n"
                    f"🛍️ Товар: {product_name}\n"
                    f"💰 Сумма: {stars_paid} звёзд\n\n"
                    f"По всем вопросам обращайтесь в поддержку."
                )
            except:
                pass

            await callback.answer("✅ Заказ отменен", show_alert=True)

            created_time = created_at.split()[1][:5] if isinstance(created_at, str) else created_at.strftime("%H:%M")

            text = f"""❌ Заказ #{order_id} ОТМЕНЕН

👤 Пользователь:
├ ID: {user_id}
├ Username: @{user_username or 'нет'}
├ Имя: {first_name}
├ Ник для заказа: {username}

🛍️ Товар: {product_name}
💰 Сумма: {stars_paid} звёзд
🕐 Время заказа: {created_time}
🕐 Время отмены: {datetime.now().strftime('%H:%M')}

📝 Комментарий:
{comment}
"""

            keyboard = InlineKeyboardBuilder()
            keyboard.button(text="🔙 К заказам", callback_data="adm_orders")
            keyboard.adjust(1)

            await callback.message.edit_text(text, reply_markup=keyboard.as_markup())

        else:
            await callback.answer("❌ Заказ не найден", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


# СТАТИСТИКА
@dp.callback_query(F.data == "adm_stats")
async def admin_stats_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа", show_alert=True)
        return

    db.cursor.execute("SELECT COUNT(*) FROM users")
    total_users = db.cursor.fetchone()[0]

    db.cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
    completed_orders = db.cursor.fetchone()[0]

    db.cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'")
    pending_orders = db.cursor.fetchone()[0]

    db.cursor.execute("SELECT SUM(stars_paid) FROM orders WHERE status = 'completed'")
    total_stars = db.cursor.fetchone()[0] or 0

    db.cursor.execute("SELECT COUNT(*) FROM products")
    total_products = db.cursor.fetchone()[0]

    db.cursor.execute("SELECT COUNT(*) FROM categories")
    total_categories = db.cursor.fetchone()[0]

    db.cursor.execute("SELECT COUNT(*) FROM groups")
    total_groups = db.cursor.fetchone()[0]

    text = f"""📊 Статистика бота

👥 Пользователи: {total_users}
📁 Категории: {total_categories}
📂 Группы: {total_groups}
🛍️ Товары: {total_products}

📦 Заказы:
├ Выполнено: {completed_orders}
├ Ожидают: {pending_orders}
└ Всего: {completed_orders + pending_orders}

💰 Звёзд получено: {total_stars}
⚙️ Техработы: {'✅ ВКЛ' if get_maintenance_mode() else '❌ ВЫКЛ'}
"""

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 Обновить", callback_data="adm_stats")
    keyboard.button(text="🔙 В админку", callback_data="adm_back")
    keyboard.adjust(1)

    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())


# ОБРАБОТЧИКИ ДЛЯ НЕСУЩЕСТВУЮЩИХ КНОПОК
@dp.callback_query(F.data == "no_products")
async def no_products_handler(callback: CallbackQuery):
    await callback.answer("📭 Товаров пока нет", show_alert=True)


@dp.callback_query(F.data == "no_orders")
async def no_orders_handler(callback: CallbackQuery):
    await callback.answer("📭 Нет ожидающих заказов", show_alert=True)


# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
async def main():
    print("✅ Бот запущен!")
    print(f"👑 Админы: {ADMIN_IDS}")
    print(f"⚙️ Режим техработ: {'ВКЛ' if get_maintenance_mode() else 'ВЫКЛ'}")
    print(f"💰 Провайдер оплаты: {'Telegram Stars' if not PROVIDER_TOKEN else 'ЮKassa'}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    if BOT_TOKEN == "8511170748:AAF1htcmjb_lf41yAjrSs19o3KQN9jHOtQ8":
        print("\n" + "=" * 60)
        print("⚠️ ВНИМАНИЕ! Бот запускается с вашим токеном")
        print("=" * 60)

    asyncio.run(main())