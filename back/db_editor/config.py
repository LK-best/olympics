# -*- coding: utf-8 -*-
"""Конфигурация приложения"""

import os
import sys
import secrets

if getattr(sys, 'frozen', False):
    # Exe режим
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    # Python режим - поднимаемся на уровень выше из db_editor
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Пробуем импортировать из корневого paths.py
try:
    sys.path.insert(0, _BASE_DIR)
    from paths import DATABASE_PATH, AUTH_DATABASE_PATH, TEMPLATES_DIR, STATIC_DIR, DB_EDITOR_DIR
    MAIN_DB_PATH = DATABASE_PATH
    AUTH_DB_PATH = AUTH_DATABASE_PATH
except ImportError:
    # Fallback на локальные пути
    MAIN_DB_PATH = os.path.join(_BASE_DIR, "database.db")
    AUTH_DB_PATH = os.path.join(_BASE_DIR, "db_editor", "auth_database.db")
    TEMPLATES_DIR = os.path.join(_BASE_DIR, "db_editor", "templates")
    STATIC_DIR = os.path.join(_BASE_DIR, "db_editor", "static")
    DB_EDITOR_DIR = os.path.join(_BASE_DIR, "db_editor")

# Токен Telegram бота
TELEGRAM_BOT_TOKEN = "7912614847:AAG2IFtrCvaqSAy6pSZoBE3N8CAcvxtlqUo"

# OpenRouter API ключ
OPENROUTER_API_KEY = "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"

# Главный аккаунт администратора
MAIN_ADMIN_TG_ID = os.getenv("MAIN_ADMIN_TG_ID", "5224328073")

# Секретный ключ для Flask сессий
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))

# Имя бота
BOT_USERNAME = "syndver_bot"

# Время жизни кода входа (в секундах)
LOGIN_CODE_LIFETIME = 300  # 5 минут

# DeepSeek модель
DEEPSEEK_MODEL = "deepseek/deepseek-r1-0528:free"

# Системный промпт для генерации задач
TASK_GENERATION_SYSTEM_PROMPT = """Ты — ассистент для создания образовательных задач. Твоя задача — генерировать качественные тестовые задания по запросу пользователя.

## Формат вывода задач

Когда генерируешь задачи, ОБЯЗАТЕЛЬНО используй следующий JSON-формат для каждой задачи:

```json
{
  "task": {
    "subject": "Название предмета",
    "difficulty": "easy|medium|hard",
    "topic": "Тема задачи",
    "question": "Текст вопроса",
    "options": ["Вариант 1", "Вариант 2", "Вариант 3", "Вариант 4"],
    "answer": "Правильный ответ (должен совпадать с одним из вариантов)",
    "hint": "Подсказка для решения"
  }
}
Доступные предметы:
    Математика
    Физика
    Информатика
    История
    Русский язык
    
Уровни сложности:
    easy — простые задачи, базовые знания
    medium — средняя сложность, требуется понимание темы
    hard — сложные задачи, требуется глубокое понимание
Правила:
    Всегда генерируй ровно 4 варианта ответа
    Правильный ответ должен ТОЧНО совпадать с одним из вариантов
    Варианты должны быть правдоподобными, но только один верный
    Подсказка должна наводить на решение, но не давать прямой ответ
    Каждую задачу оборачивай в блок json ...
    После JSON-блока можешь добавить пояснение к задаче
Пример вывода:
Вот задача по математике:

JSON

{
  "task": {
    "subject": "Математика",
    "difficulty": "medium",
    "topic": "Квадратные уравнения",
    "question": "Найдите корни уравнения x² - 5x + 6 = 0",
    "options": ["x = 2, x = 3", "x = 1, x = 6", "x = -2, x = -3", "x = 2, x = -3"],
    "answer": "x = 2, x = 3",
    "hint": "Используйте теорему Виета или формулу дискриминанта"
  }
}
Это уравнение решается через разложение на множители: (x-2)(x-3) = 0.

Отвечай на русском языке. Будь точен и внимателен к деталям. Если пользователь просит несколько задач, генерируй их по одной с отдельными JSON-блоками."""