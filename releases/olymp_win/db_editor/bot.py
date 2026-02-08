# -*- coding: utf-8 -*-
"""Telegram бот для авторизации"""

import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import TELEGRAM_BOT_TOKEN, MAIN_ADMIN_TG_ID, MAIN_DB_PATH
import auth_db

# Инициализация бота
bot = Bot(token=TELEGRAM_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# Состояния FSM
class AuthStates(StatesGroup):
    waiting_identification_code = State()
    waiting_email = State()
    waiting_username = State()


class AdminStates(StatesGroup):
    waiting_user_id = State()
    waiting_remove_id = State()


# === Вспомогательные функции ===

def check_user_in_main_db(email: str, username: str) -> dict:
    """Проверить пользователя в основной БД"""
    try:
        conn = sqlite3.connect(MAIN_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM users 
            WHERE LOWER(email) = LOWER(?) AND LOWER(username) = LOWER(?)
        """, (email, username))

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "found": True,
                "is_admin": row["is_admin"] == 1,
                "email": row["email"],
                "username": row["username"]
            }
        return {"found": False}
    except Exception as e:
        print(f"Ошибка при проверке БД: {e}")
        return {"found": False, "error": str(e)}


def is_main_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь главным администратором"""
    return user_id == MAIN_ADMIN_TG_ID


# === Обработчики команд ===

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    # Проверяем, есть ли пользователь в списке разрешённых
    allowed = auth_db.get_allowed_user(user_id)

    if is_main_admin(user_id):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Войти в систему", callback_data="auth_start")],
            [InlineKeyboardButton(text="👥 Управление доступом", callback_data="admin_panel")]
        ])
        await message.answer(
            "👑 <b>Добро пожаловать, Эндминистратор!</b>\n\n"
            "Вы являетесь главным администратором системы.\n"
            "Выберите действие:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    elif allowed:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Войти в систему", callback_data="auth_start")]
        ])
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Вы имеете доступ к системе управления БД.\n"
            "Нажмите кнопку ниже для авторизации.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "⛔ <b>Доступ запрещён</b>\n\n"
            "Ваш Telegram ID не найден в списке разрешённых пользователей.\n"
            "Обратитесь к администратору для получения доступа.\n\n"
            f"Ваш ID: <code>{user_id}</code>",
            parse_mode="HTML"
        )


@dp.message(Command("myid"))
async def cmd_myid(message: types.Message):
    await message.answer(f"🆔 Ваш Telegram ID: <code>{message.from_user.id}</code>", parse_mode="HTML")


# === Админ-панель ===

@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    users = auth_db.get_all_allowed_users()

    text = "👥 <b>Управление доступом</b>\n\n"

    if users:
        text += "<b>Разрешённые пользователи:</b>\n"
        for u in users:
            status = "✅" if u["is_active"] else "❌"
            text += f"{status} ID: <code>{u['telegram_id']}</code> | Код: <code>{u['identification_code']}</code>\n"
    else:
        text += "<i>Список пуст</i>\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить пользователя", callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Удалить пользователя", callback_data="admin_remove")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "admin_add")
async def admin_add_user(callback: types.CallbackQuery, state: FSMContext):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_user_id)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]
    ])

    await callback.message.edit_text(
        "➕ <b>Добавление пользователя</b>\n\n"
        "Введите Telegram ID пользователя, которому нужно предоставить доступ:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(StateFilter(AdminStates.waiting_user_id))
async def process_add_user_id(message: types.Message, state: FSMContext):
    if not is_main_admin(message.from_user.id):
        return

    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число:")
        return

    result = auth_db.add_allowed_user(user_id, message.from_user.id)

    await state.clear()

    if result["success"]:
        await message.answer(
            f"✅ <b>Пользователь добавлен!</b>\n\n"
            f"Telegram ID: <code>{user_id}</code>\n"
            f"Код идентификации: <code>{result['code']}</code>\n\n"
            f"Передайте этот код пользователю для входа.",
            parse_mode="HTML"
        )
        auth_db.log_auth_action(message.from_user.id, "ADD_USER", f"Added user {user_id}")
    else:
        await message.answer(
            f"⚠️ {result.get('error', 'Ошибка')}\n"
            f"Существующий код: <code>{result.get('code', 'N/A')}</code>",
            parse_mode="HTML"
        )


@dp.callback_query(F.data == "admin_remove")
async def admin_remove_user(callback: types.CallbackQuery, state: FSMContext):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_remove_id)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]
    ])

    await callback.message.edit_text(
        "➖ <b>Удаление пользователя</b>\n\n"
        "Введите Telegram ID пользователя для удаления:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(StateFilter(AdminStates.waiting_remove_id))
async def process_remove_user_id(message: types.Message, state: FSMContext):
    if not is_main_admin(message.from_user.id):
        return

    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число:")
        return

    if auth_db.remove_allowed_user(user_id):
        await message.answer(f"✅ Пользователь <code>{user_id}</code> удалён из списка доступа.", parse_mode="HTML")
        auth_db.log_auth_action(message.from_user.id, "REMOVE_USER", f"Removed user {user_id}")
    else:
        await message.answer("❌ Пользователь не найден в списке.")

    await state.clear()


# === Авторизация ===

@dp.callback_query(F.data == "auth_start")
async def auth_start(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    # Проверяем доступ
    if not is_main_admin(user_id) and not auth_db.get_allowed_user(user_id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    await state.set_state(AuthStates.waiting_identification_code)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_start")]
    ])

    await callback.message.edit_text(
        "🔐 <b>Авторизация - Шаг 1/3</b>\n\n"
        "Введите ваш <b>код идентификации</b> (4 символа):\n\n"
        "<i>Код был выдан вам при получении доступа к системе.</i>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(StateFilter(AuthStates.waiting_identification_code))
async def process_identification_code(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    code = message.text.strip().upper()

    # Для главного админа генерируем код если его нет
    if is_main_admin(user_id):
        if not auth_db.get_allowed_user(user_id):
            auth_db.add_allowed_user(user_id, user_id)

    if not auth_db.verify_identification_code(user_id, code):
        await message.answer(
            "❌ <b>Неверный код идентификации!</b>\n\n"
            "Попробуйте ещё раз или обратитесь к администратору.",
            parse_mode="HTML"
        )
        return

    await state.update_data(identification_code=code)
    await state.set_state(AuthStates.waiting_email)

    await message.answer(
        "✅ Код принят!\n\n"
        "🔐 <b>Авторизация - Шаг 2/3</b>\n\n"
        "Введите вашу <b>электронную почту</b> от аккаунта в системе:",
        parse_mode="HTML"
    )


@dp.message(StateFilter(AuthStates.waiting_email))
async def process_email(message: types.Message, state: FSMContext):
    email = message.text.strip()

    if "@" not in email or "." not in email:
        await message.answer("❌ Неверный формат email. Попробуйте ещё раз:")
        return

    await state.update_data(email=email)
    await state.set_state(AuthStates.waiting_username)

    await message.answer(
        "✅ Email принят!\n\n"
        "🔐 <b>Авторизация - Шаг 3/3</b>\n\n"
        "Введите ваш <b>никнейм (имя пользователя)</b> от аккаунта:",
        parse_mode="HTML"
    )


@dp.message(StateFilter(AuthStates.waiting_username))
async def process_username(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.text.strip()

    data = await state.get_data()
    email = data.get("email")

    # Проверяем в основной БД
    db_check = check_user_in_main_db(email, username)

    if not db_check["found"]:
        await message.answer(
            "❌ <b>Пользователь не найден!</b>\n\n"
            "Проверьте правильность email и имени пользователя.",
            parse_mode="HTML"
        )
        await state.clear()
        return

    if not db_check["is_admin"]:
        await message.answer(
            "⛔ <b>Доступ запрещён!</b>\n\n"
            "Вы не являетесь администратором в системе.\n"
            "Для доступа к панели управления БД требуется статус администратора.",
            parse_mode="HTML"
        )
        auth_db.log_auth_action(user_id, "AUTH_DENIED", f"User {email} is not admin")
        await state.clear()
        return

    # Генерируем код входа
    login_code = auth_db.create_login_code(user_id)

    await state.update_data(db_email=db_check["email"], db_username=db_check["username"])
    await state.clear()

    auth_db.log_auth_action(user_id, "AUTH_SUCCESS", f"Generated login code for {email}")

    await message.answer(
        "✅ <b>Верификация пройдена!</b>\n\n"
        "🔑 Ваш одноразовый код входа:\n\n"
        f"<code>{login_code}</code>\n\n"
        "⏱ Код действителен <b>5 минут</b>.\n"
        "⚠️ Код можно использовать только <b>один раз</b>!\n\n"
        "Скопируйте код и вставьте его на странице входа в веб-интерфейс.",
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "back_to_start")
async def back_to_start(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()

    user_id = callback.from_user.id

    if is_main_admin(user_id):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Войти в систему", callback_data="auth_start")],
            [InlineKeyboardButton(text="👥 Управление доступом", callback_data="admin_panel")]
        ])
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Войти в систему", callback_data="auth_start")]
        ])

    await callback.message.edit_text(
        "👋 <b>Главное меню</b>\n\n"
        "Выберите действие:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


# === Запуск бота ===

async def main():
    print("🤖 Бот авторизации запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())