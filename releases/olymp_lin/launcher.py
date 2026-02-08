# -*- coding: utf-8 -*-
"""
Единая точка входа для всех сервисов
"""

import os
import sys
import time
import threading
import multiprocessing
from multiprocessing import Process, freeze_support

# ============ НАСТРОЙКА ПУТЕЙ ============
if getattr(sys, 'frozen', False):
    # Exe режим
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Python режим
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Добавляем пути
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "db_editor"))

# Устанавливаем рабочую директорию
os.chdir(BASE_DIR)

# Импортируем конфигурацию
from paths import (
    DATABASE_PATH,
    FASTAPI_PORT,
    FLASK_PORT,
    INDEX_HTML_PATH,
    print_paths
)


def run_fastapi_server():
    """Запуск FastAPI сервера (EduBattle v3.2)"""
    import uvicorn
    import asyncio

    # Устанавливаем рабочую директорию
    os.chdir(BASE_DIR)
    sys.path.insert(0, BASE_DIR)

    try:
        # Динамический импорт server.py
        import importlib.util
        server_path = os.path.join(BASE_DIR, "server.py")

        if not os.path.exists(server_path):
            print(f"❌ Файл не найден: {server_path}")
            return

        spec = importlib.util.spec_from_file_location("server", server_path)
        server_module = importlib.util.module_from_spec(spec)

        # Важно: добавляем модуль в sys.modules до выполнения
        sys.modules["server"] = server_module
        spec.loader.exec_module(server_module)

        app = server_module.app

        print(f"FastAPI сервер (EduBattle v3.2) запускается на http://localhost:{FASTAPI_PORT}")

        # Запускаем uvicorn
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=FASTAPI_PORT,
            log_level="info",
            loop="asyncio"
        )
        server = uvicorn.Server(config)

        # Создаём новый event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    except Exception as e:
        print(f"❌ Ошибка FastAPI: {e}")
        import traceback
        traceback.print_exc()


def run_flask_server():
    """Запуск Flask сервера (DB Editor)"""
    db_editor_dir = os.path.join(BASE_DIR, "db_editor")

    os.chdir(db_editor_dir)
    sys.path.insert(0, db_editor_dir)
    sys.path.insert(0, BASE_DIR)

    try:
        import importlib.util
        app_path = os.path.join(db_editor_dir, "app.py")

        if not os.path.exists(app_path):
            print(f"Flask приложение не найдено: {app_path}")
            print("   DB Editor будет пропущен")
            return

        spec = importlib.util.spec_from_file_location("app", app_path)
        app_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app_module)

        flask_app = app_module.app

        print(f"Flask сервер (DB Editor) запускается на http://localhost:{FLASK_PORT}")
        flask_app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False)

    except Exception as e:
        print(f" Ошибка Flask: {e}")
        import traceback
        traceback.print_exc()


def run_telegram_bot():
    """Запуск Telegram бота"""
    import asyncio

    db_editor_dir = os.path.join(BASE_DIR, "db_editor")
    os.chdir(db_editor_dir)
    sys.path.insert(0, db_editor_dir)
    sys.path.insert(0, BASE_DIR)

    try:
        import importlib.util
        bot_path = os.path.join(db_editor_dir, "bot.py")

        if not os.path.exists(bot_path):
            print(f"Telegram бот не найден: {bot_path}")
            return

        spec = importlib.util.spec_from_file_location("bot", bot_path)
        bot_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bot_module)

        print("Telegram бот запускается...")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bot_module.main())

    except Exception as e:
        print(f"Ошибка Telegram бота: {e}")
        import traceback
        traceback.print_exc()


def check_database():
    """Проверка наличия базы данных"""
    if not os.path.exists(DATABASE_PATH):
        print(f"  База данных не найдена: {DATABASE_PATH}")
        print("   Попытка создать базу данных...")

        try:
            import importlib.util
            db_script = os.path.join(BASE_DIR, "database.py")

            if os.path.exists(db_script):
                spec = importlib.util.spec_from_file_location("database", db_script)
                db_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(db_module)

                # Вызываем функцию создания БД (если есть)
                if hasattr(db_module, 'sozdat_bazu'):
                    db_module.sozdat_bazu()
                elif hasattr(db_module, 'create_database'):
                    db_module.create_database()
                elif hasattr(db_module, 'init_db'):
                    db_module.init_db()

                print("✅ База данных создана")
            else:
                print(f"❌ Скрипт создания БД не найден: {db_script}")
                return False

        except Exception as e:
            print(f"❌ Ошибка создания БД: {e}")
            import traceback
            traceback.print_exc()
            return False
    else:
        print(f"✅ База данных найдена: {DATABASE_PATH}")

    return True


def check_index_html():
    """Проверка наличия index.html"""
    if not os.path.exists(INDEX_HTML_PATH):
        print(f" index.html не найден: {INDEX_HTML_PATH}")
        return False
    print(f"✅ index.html найден")
    return True


def print_banner():
    """Вывод баннера при запуске"""
    banner = """
    ╔═══════════════════════════════════════════════════════╗
    ║                                                       ║
    ║     ███████╗██████╗ ██╗   ██╗                        ║
    ║     ██╔════╝██╔══██╗██║   ██║                        ║
    ║     █████╗  ██║  ██║██║   ██║                        ║
    ║     ██╔══╝  ██║  ██║██║   ██║                        ║
    ║     ███████╗██████╔╝╚██████╔╝                        ║
    ║     ╚══════╝╚═════╝  ╚═════╝  BATTLE v3.2            ║
    ║                                                       ║
    ║         🎮 Образовательная платформа                  ║
    ║         + Активный heartbeat механизм                 ║
    ║         + Мгновенная отмена при отключении            ║
    ║                                                       ║
    ╚═══════════════════════════════════════════════════════╝
    """
    print(banner)


def main():
    """Главная функция запуска"""
    print_banner()
    print_paths()

    # Проверяем необходимые файлы
    if not check_database():
        print("\n❌ Не удалось инициализировать базу данных.")
        input("Нажмите Enter для выхода...")
        sys.exit(1)

    check_index_html()

    print("\nЗапуск всех сервисов...\n")

    processes = []

    try:
        # Запускаем FastAPI в отдельном процессе
        fastapi_process = Process(target=run_fastapi_server, name="FastAPI-EduBattle")
        fastapi_process.start()
        processes.append(fastapi_process)

        time.sleep(2)  # Даём время на запуск

        # Запускаем Flask (если есть db_editor)
        db_editor_app = os.path.join(BASE_DIR, "db_editor", "app.py")
        if os.path.exists(db_editor_app):
            flask_process = Process(target=run_flask_server, name="Flask-DBEditor")
            flask_process.start()
            processes.append(flask_process)
            time.sleep(1)

        # Запускаем Telegram бота (если есть)
        bot_file = os.path.join(BASE_DIR, "db_editor", "bot.py")
        if os.path.exists(bot_file):
            bot_process = Process(target=run_telegram_bot, name="TelegramBot")
            bot_process.start()
            processes.append(bot_process)

        print("\n" + "=" * 55)
        print("✅ Все сервисы запущены!")
        print("=" * 55)
        print(f"\n📱 EduBattle:           http://localhost:{FASTAPI_PORT}")
        if os.path.exists(db_editor_app):
            print(f"Редактор БД:         http://localhost:{FLASK_PORT}")
        print(f"\nАдмин: admin@edu.ru / admin123")
        print("\n Для остановки нажмите Ctrl+C")
        print("=" * 55 + "\n")

        # Ждём завершения процессов
        for p in processes:
            p.join()

    except KeyboardInterrupt:
        print("\n\n🛑 Получен сигнал остановки...")

        for p in processes:
            if p.is_alive():
                print(f"   Останавливаю {p.name}...")
                p.terminate()
                p.join(timeout=5)
                if p.is_alive():
                    p.kill()

        print("✅ Все сервисы остановлены")

    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()

        for p in processes:
            if p.is_alive():
                p.terminate()


if __name__ == "__main__":
    freeze_support()
    main()