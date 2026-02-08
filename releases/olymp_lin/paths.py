# -*- coding: utf-8 -*-
"""
Конфигурация путей проекта
Работает как в режиме разработки, так и после сборки в exe
"""

import os
import sys

def get_base_dir():
    """
    Получить базовую директорию проекта.
    """
    if getattr(sys, 'frozen', False):
        # Запущено как exe (PyInstaller)
        return os.path.dirname(sys.executable)
    else:
        # Запущено как python скрипт
        return os.path.dirname(os.path.abspath(__file__))

# Базовая директория проекта
BASE_DIR = get_base_dir()

# Пути к файлам
DATABASE_PATH = os.path.join(BASE_DIR, "database.db")
AUTH_DATABASE_PATH = os.path.join(BASE_DIR, "db_editor", "auth_database.db")
INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")

# Пути к папкам db_editor
DB_EDITOR_DIR = os.path.join(BASE_DIR, "db_editor")
TEMPLATES_DIR = os.path.join(DB_EDITOR_DIR, "templates")
STATIC_DIR = os.path.join(DB_EDITOR_DIR, "static")

# ⚠️ Порты серверов (обновлено под ваш server.py)
FASTAPI_PORT = 8080  # Ваш сервер использует 8080
FLASK_PORT = 5000

def print_paths():
    print("=" * 50)
    print("📁 Конфигурация путей:")
    print(f"   BASE_DIR: {BASE_DIR}")
    print(f"   DATABASE_PATH: {DATABASE_PATH}")
    print(f"   INDEX_HTML_PATH: {INDEX_HTML_PATH}")
    print(f"   DB_EDITOR_DIR: {DB_EDITOR_DIR}")
    print(f"   FASTAPI_PORT: {FASTAPI_PORT}")
    print(f"   FLASK_PORT: {FLASK_PORT}")
    print("=" * 50)

if __name__ == "__main__":
    print_paths()