import sqlite3
import hashlib
import json
import os
import sys
from datetime import datetime


def create_database():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    with open('database.sql', 'r', encoding='utf-8') as file:
        sql_schema = file.read()

    cursor.executescript(sql_schema)

    cursor.execute("SELECT * FROM users WHERE email = ?", ("admin@edu.ru",))
    if cursor.fetchone() is None:
        s = "moy_secret_sol_2024"
        password = hashlib.sha256(("admin123" + s).encode()).hexdigest()

        cursor.execute("""
            INSERT INTO users (username, email, password_hash, rating, level, xp, is_admin, is_active)
            VALUES (?, ?, ?, 1500, 10, 1000, 1, 1)
        """, ("Администратор", "admin@edu.ru", password))

        conn.commit()

    app = [
        ("maintenance_mode", "false", "Режим обслуживания"),
        ("registration_enabled", "true", "Разрешена ли регистрация"),
        ("max_queue_time", "300", "Максимальное время в очереди (сек)"),
        ("bot_difficulty", "medium", "Сложность бота по умолчанию"),
    ]

    for i, c, name in app:
        cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value, description)
            VALUES (?, ?, ?)
        """, (i, c, name))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    os.remove("database.db")
    create_database()