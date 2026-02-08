# -*- coding: utf-8 -*-
"""База данных для авторизации"""

import sqlite3
import secrets
import string
import os
from datetime import datetime, timedelta
from config import AUTH_DB_PATH, LOGIN_CODE_LIFETIME


def get_auth_connection():
    # Создаём директорию если её нет
    db_dir = os.path.dirname(AUTH_DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(AUTH_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db():
    """Инициализация БД авторизации"""
    conn = get_auth_connection()
    cursor = conn.cursor()

    # Таблица разрешённых TG пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            identification_code TEXT NOT NULL,
            added_by INTEGER,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
    """)

    # Таблица одноразовых кодов входа
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            code TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            used_at TEXT
        )
    """)

    # Таблица сессий
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_token TEXT UNIQUE NOT NULL,
            telegram_id INTEGER NOT NULL,
            user_email TEXT,
            user_name TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_activity TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Таблица логов авторизации
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print("✅ БД авторизации инициализирована")


def generate_identification_code():
    """Генерация 4-символьного кода идентификации (A-Z, 0-9)"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(4))


def generate_login_code():
    """Генерация 16-символьного кода входа"""
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(16))


def generate_session_token():
    """Генерация токена сессии"""
    return secrets.token_hex(32)


# === Управление пользователями ===

def add_allowed_user(telegram_id: int, added_by: int) -> dict:
    """Добавить разрешённого пользователя"""
    conn = get_auth_connection()
    cursor = conn.cursor()

    # Проверяем, не добавлен ли уже
    cursor.execute("SELECT * FROM allowed_users WHERE telegram_id = ?", (telegram_id,))
    existing = cursor.fetchone()

    if existing:
        conn.close()
        return {"success": False, "error": "Пользователь уже добавлен", "code": existing["identification_code"]}

    code = generate_identification_code()

    cursor.execute("""
        INSERT INTO allowed_users (telegram_id, identification_code, added_by)
        VALUES (?, ?, ?)
    """, (telegram_id, code, added_by))

    conn.commit()
    conn.close()

    return {"success": True, "code": code}


def remove_allowed_user(telegram_id: int) -> bool:
    """Удалить пользователя из списка разрешённых"""
    conn = get_auth_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM allowed_users WHERE telegram_id = ?", (telegram_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_allowed_user(telegram_id: int) -> dict:
    """Получить информацию о разрешённом пользователе"""
    conn = get_auth_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM allowed_users WHERE telegram_id = ? AND is_active = 1", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_allowed_users() -> list:
    """��олучить всех разрешённых пользователей"""
    conn = get_auth_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM allowed_users ORDER BY added_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def verify_identification_code(telegram_id: int, code: str) -> bool:
    """Проверить код идентификации"""
    user = get_allowed_user(telegram_id)
    if not user:
        return False
    return user["identification_code"].upper() == code.upper()


# === Коды входа ===

def create_login_code(telegram_id: int) -> str:
    """Создать одноразовый код входа"""
    conn = get_auth_connection()
    cursor = conn.cursor()

    code = generate_login_code()
    expires_at = (datetime.now() + timedelta(seconds=LOGIN_CODE_LIFETIME)).isoformat()

    cursor.execute("""
        INSERT INTO login_codes (telegram_id, code, expires_at)
        VALUES (?, ?, ?)
    """, (telegram_id, code, expires_at))

    conn.commit()
    conn.close()

    return code


def verify_login_code(code: str) -> dict:
    """Проверить код входа и вернуть данные пользователя"""
    conn = get_auth_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM login_codes 
        WHERE code = ? AND used = 0 AND expires_at > ?
    """, (code, datetime.now().isoformat()))

    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    # Помечаем код как использованный
    cursor.execute("""
        UPDATE login_codes SET used = 1, used_at = ? WHERE id = ?
    """, (datetime.now().isoformat(), row["id"]))

    conn.commit()
    conn.close()

    return dict(row)


def cleanup_expired_codes():
    """Очистка просроченных кодов"""
    conn = get_auth_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM login_codes WHERE expires_at < ?", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()


# === Сессии ===

def create_session(telegram_id: int, user_email: str, user_name: str) -> str:
    """Создать сессию"""
    conn = get_auth_connection()
    cursor = conn.cursor()

    token = generate_session_token()

    cursor.execute("""
        INSERT INTO sessions (session_token, telegram_id, user_email, user_name)
        VALUES (?, ?, ?, ?)
    """, (token, telegram_id, user_email, user_name))

    conn.commit()
    conn.close()

    return token


def get_session(token: str) -> dict:
    """Получить сессию по токену"""
    conn = get_auth_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE session_token = ?", (token,))
    row = cursor.fetchone()

    if row:
        # Обновляем время последней активности
        cursor.execute("""
            UPDATE sessions SET last_activity = ? WHERE session_token = ?
        """, (datetime.now().isoformat(), token))
        conn.commit()

    conn.close()
    return dict(row) if row else None


def delete_session(token: str):
    """Удалить сессию"""
    conn = get_auth_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE session_token = ?", (token,))
    conn.commit()
    conn.close()


# === Логирование ===

def log_auth_action(telegram_id: int, action: str, details: str = None, ip: str = None):
    """Записать действие в лог"""
    conn = get_auth_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO auth_logs (telegram_id, action, details, ip_address)
        VALUES (?, ?, ?, ?)
    """, (telegram_id, action, details, ip))
    conn.commit()
    conn.close()


# Инициализация при импорте
init_auth_db()