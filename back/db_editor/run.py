# -*- coding: utf-8 -*-
"""Запуск всех сервисов"""

import subprocess
import sys
import time
import threading
import os


def run_flask():
    """Запуск Flask приложения"""
    subprocess.run([sys.executable, "app.py"])


def run_bot():
    """Запуск Telegram бота"""
    subprocess.run([sys.executable, "bot.py"])


if __name__ == "__main__":
    print("=" * 50)
    print("🚀 Запуск DB Editor")
    print("=" * 50)

    # Проверяем наличие основной БД
    if not os.path.exists(r"C:\Users\Admin\Liz\olimp\database.db"):
        print("⚠️  Файл database.db не найден!")
        print("   Сначала запустите database.py для создания БД")
        sys.exit(1)

    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("🤖 Telegram бот запущен")

    time.sleep(1)

    # Запускаем Flask
    print("🌐 Flask сервер запускается на http://localhost:5000")
    print("=" * 50)
    run_flask()
