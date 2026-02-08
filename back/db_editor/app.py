# -*- coding: utf-8 -*-
"""Flask приложение для редактирования БД"""

import sqlite3
import json
import csv
import io
import asyncio
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response, \
    stream_with_context
from config import SECRET_KEY, MAIN_DB_PATH, BOT_USERNAME
import auth_db
from ai_service import ai_service, AIService

app = Flask(__name__)
app.secret_key = SECRET_KEY


# === Вспомогательные функции ===

def get_db_connection():
    conn = sqlite3.connect(MAIN_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'session_token' not in session:
            return redirect(url_for('login'))

        sess = auth_db.get_session(session['session_token'])
        if not sess:
            session.clear()
            return redirect(url_for('login'))

        return f(*args, **kwargs)

    return decorated_function


def get_all_tables():
    """Получить список всех таблиц"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row['name'] for row in cursor.fetchall()]
    conn.close()
    return tables


def get_table_info(table_name):
    """Получить информацию о столбцах таблицы"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    conn.close()
    return columns


def get_table_data(table_name, page=1, per_page=50, search=None, order_by=None, order_dir='ASC'):
    """Получить данные таблицы с пагинацией"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Получаем общее количество
    if search:
        columns = get_table_info(table_name)
        search_conditions = []
        for col in columns:
            search_conditions.append(f"CAST({col['name']} AS TEXT) LIKE ?")

        where_clause = " OR ".join(search_conditions)
        cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {where_clause}",
                       tuple([f"%{search}%"] * len(columns)))
    else:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")

    total = cursor.fetchone()[0]

    offset = (page - 1) * per_page

    order_clause = ""
    if order_by:
        order_clause = f" ORDER BY {order_by} {order_dir}"

    if search:
        columns = get_table_info(table_name)
        search_conditions = []
        for col in columns:
            search_conditions.append(f"CAST({col['name']} AS TEXT) LIKE ?")
        where_clause = " OR ".join(search_conditions)
        cursor.execute(
            f"SELECT * FROM {table_name} WHERE {where_clause}{order_clause} LIMIT ? OFFSET ?",
            tuple([f"%{search}%"] * len(columns)) + (per_page, offset)
        )
    else:
        cursor.execute(f"SELECT * FROM {table_name}{order_clause} LIMIT ? OFFSET ?", (per_page, offset))

    rows = cursor.fetchall()
    conn.close()

    return {
        'rows': [dict(row) for row in rows],
        'total': total,
        'pages': (total + per_page - 1) // per_page,
        'current_page': page
    }


def run_async(coro):
    """Запуск асинхронной функции в синхронном контексте"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# === Вспомогательные функции для импорта задач ===

def validate_task(task: dict) -> tuple:
    """
    Валидация задачи. Возвращает (is_valid, error_message, normalized_task)
    """
    required_fields = ['subject', 'question', 'options', 'answer']

    for field in required_fields:
        if field not in task or not task[field]:
            return False, f'Отсутствует обязательное поле: {field}', None

    # Нормализуем options
    options = task['options']
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except json.JSONDecodeError:
            return False, 'Невозможно распарсить options как JSON', None

    if not isinstance(options, list) or len(options) < 2:
        return False, 'options должен быть списком минимум из 2 элементов', None

    # Проверяем что answer есть среди options (мягкая проверка — предупреждение, не ошибка)
    normalized = {
        'subject': str(task.get('subject', '')).strip(),
        'difficulty': str(task.get('difficulty', 'medium')).strip().lower(),
        'topic': str(task.get('topic', '')).strip(),
        'question': str(task.get('question', '')).strip(),
        'options': [str(o).strip() for o in options],
        'answer': str(task.get('answer', '')).strip(),
        'hint': str(task.get('hint', '')).strip()
    }

    # Валидация difficulty
    if normalized['difficulty'] not in ('easy', 'medium', 'hard'):
        normalized['difficulty'] = 'medium'

    return True, None, normalized


def insert_task_to_db(cursor, task: dict, has_llm_column: bool):
    """Вставка задачи в БД. Возвращает ID вставленной записи."""
    options_json = json.dumps(task['options'], ensure_ascii=False)

    if has_llm_column:
        cursor.execute("""
            INSERT INTO tasks (subject, difficulty, topic, question, options, answer, hint, generated_by_llm, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, datetime('now'))
        """, (
            task['subject'],
            task['difficulty'],
            task['topic'],
            task['question'],
            options_json,
            task['answer'],
            task['hint']
        ))
    else:
        cursor.execute("""
            INSERT INTO tasks (subject, difficulty, topic, question, options, answer, hint, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            task['subject'],
            task['difficulty'],
            task['topic'],
            task['question'],
            options_json,
            task['answer'],
            task['hint']
        ))

    return cursor.lastrowid


def parse_tasks_from_json_data(data) -> tuple:
    """
    Парсит задачи из JSON данных (уже десериализованных).
    Поддерживает форматы:
    1. {"task": {...}}                      — одна задача
    2. [{"task": {...}}, {"task": {...}}]    — массив задач в обёртке
    3. [{"subject":..., "question":...}]    — массив задач напрямую
    4. {"tasks": [...]}                     — объект с ключом tasks

    Возвращает (tasks_list, errors_list)
    """
    tasks = []
    errors = []

    def extract_task(item, index=0):
        """Извлечь задачу из элемента"""
        if isinstance(item, dict):
            if 'task' in item:
                return item['task']
            elif 'subject' in item and 'question' in item:
                return item
        return None

    if isinstance(data, dict):
        # Формат: {"task": {...}}
        if 'task' in data:
            task_data = extract_task(data)
            if task_data:
                is_valid, error, normalized = validate_task(task_data)
                if is_valid:
                    tasks.append(normalized)
                else:
                    errors.append(f'Задача 1: {error}')

        # Формат: {"tasks": [...]}
        elif 'tasks' in data and isinstance(data['tasks'], list):
            for i, item in enumerate(data['tasks']):
                task_data = extract_task(item, i)
                if task_data is None and isinstance(item, dict):
                    task_data = item
                if task_data:
                    is_valid, error, normalized = validate_task(task_data)
                    if is_valid:
                        tasks.append(normalized)
                    else:
                        errors.append(f'Задача {i + 1}: {error}')
                else:
                    errors.append(f'Задача {i + 1}: неверный формат')

        # Формат: {"subject": ..., "question": ...} — одна задача без обёртки
        elif 'subject' in data and 'question' in data:
            is_valid, error, normalized = validate_task(data)
            if is_valid:
                tasks.append(normalized)
            else:
                errors.append(f'Задача 1: {error}')
        else:
            errors.append('Неизвестный формат JSON. Ожидается {"task": {...}} или {"tasks": [...]}')

    elif isinstance(data, list):
        for i, item in enumerate(data):
            task_data = extract_task(item, i)
            if task_data is None and isinstance(item, dict):
                task_data = item
            if task_data:
                is_valid, error, normalized = validate_task(task_data)
                if is_valid:
                    tasks.append(normalized)
                else:
                    errors.append(f'Задача {i + 1}: {error}')
            else:
                errors.append(f'Задача {i + 1}: неверный формат')
    else:
        errors.append('Корень JSON должен быть объектом или массивом')

    return tasks, errors


def parse_tasks_from_csv_data(csv_text: str) -> tuple:
    """
    Парсит задачи из CSV текста.
    Ожидаемые колонки: subject, difficulty, topic, question, options, answer, hint
    options — JSON-строка: ["opt1","opt2","opt3","opt4"]

    Возвращает (tasks_list, errors_list)
    """
    tasks = []
    errors = []

    try:
        reader = csv.DictReader(io.StringIO(csv_text))
    except Exception as e:
        return [], [f'Ошибка чтения CSV: {str(e)}']

    # Проверяем наличие необходимых колонок
    if reader.fieldnames is None:
        return [], ['CSV файл пуст или не содержит заголовков']

    # Нормализуем имена колонок (убираем пробелы, приводим к нижнему регистру)
    normalized_fieldnames = [f.strip().lower() for f in reader.fieldnames]

    required_csv_cols = ['subject', 'question', 'options', 'answer']
    missing = [col for col in required_csv_cols if col not in normalized_fieldnames]

    if missing:
        return [], [f'Отсутствуют обязательные колонки: {", ".join(missing)}']

    for i, row in enumerate(reader, start=1):
        # Нормализуем ключи строки
        normalized_row = {}
        for key, value in row.items():
            normalized_row[key.strip().lower()] = value

        task_data = {
            'subject': normalized_row.get('subject', ''),
            'difficulty': normalized_row.get('difficulty', 'medium'),
            'topic': normalized_row.get('topic', ''),
            'question': normalized_row.get('question', ''),
            'options': normalized_row.get('options', '[]'),
            'answer': normalized_row.get('answer', ''),
            'hint': normalized_row.get('hint', '')
        }

        is_valid, error, normalized = validate_task(task_data)
        if is_valid:
            tasks.append(normalized)
        else:
            errors.append(f'Строка {i + 1}: {error}')

    return tasks, errors


# === Маршруты ===

@app.route('/')
def index():
    if 'session_token' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        code = request.form.get('code', '').strip()

        if not code:
            flash('Введите код входа', 'error')
            return render_template('login.html', bot_username=BOT_USERNAME)

        code_data = auth_db.verify_login_code(code)

        if not code_data:
            flash('Неверный или просроченный код', 'error')
            auth_db.log_auth_action(None, "LOGIN_FAILED", f"Invalid code: {code[:4]}...", request.remote_addr)
            return render_template('login.html', bot_username=BOT_USERNAME)

        allowed_user = auth_db.get_allowed_user(code_data['telegram_id'])

        if not allowed_user:
            flash('Пользователь не найден', 'error')
            return render_template('login.html', bot_username=BOT_USERNAME)

        session_token = auth_db.create_session(
            code_data['telegram_id'],
            'admin@edu.ru',
            'Admin'
        )

        session['session_token'] = session_token
        session['telegram_id'] = code_data['telegram_id']

        auth_db.log_auth_action(code_data['telegram_id'], "LOGIN_SUCCESS", None, request.remote_addr)

        flash('Вход выполнен успешно!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('login.html', bot_username=BOT_USERNAME)


@app.route('/logout')
def logout():
    if 'session_token' in session:
        auth_db.delete_session(session['session_token'])
        auth_db.log_auth_action(session.get('telegram_id'), "LOGOUT", None, request.remote_addr)
        # Очищаем историю AI чата
        ai_service.clear_conversation(session['session_token'])
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    tables = get_all_tables()

    stats = {}
    conn = get_db_connection()
    cursor = conn.cursor()
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        stats[table] = cursor.fetchone()[0]
    conn.close()

    return render_template('dashboard.html', tables=tables, stats=stats)


@app.route('/table/<table_name>')
@login_required
def view_table(table_name):
    tables = get_all_tables()

    if table_name not in tables:
        flash('Таблица не найдена', 'error')
        return redirect(url_for('dashboard'))

    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    order_by = request.args.get('order_by', '')
    order_dir = request.args.get('order_dir', 'ASC')

    columns = get_table_info(table_name)
    data = get_table_data(table_name, page, 50, search if search else None,
                          order_by if order_by else None, order_dir)

    return render_template('table_view.html',
                           table_name=table_name,
                           columns=columns,
                           data=data,
                           search=search,
                           order_by=order_by,
                           order_dir=order_dir,
                           tables=tables)


@app.route('/table/<table_name>/add', methods=['GET', 'POST'])
@login_required
def add_row(table_name):
    tables = get_all_tables()

    if table_name not in tables:
        flash('Таблица не найдена', 'error')
        return redirect(url_for('dashboard'))

    columns = get_table_info(table_name)

    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()

        col_names = []
        values = []
        placeholders = []

        for col in columns:
            if col['name'] == 'id' and col['pk']:
                continue

            value = request.form.get(col['name'], '')

            if value == '' and col['notnull'] == 0:
                value = None

            col_names.append(col['name'])
            values.append(value)
            placeholders.append('?')

        try:
            sql = f"INSERT INTO {table_name} ({', '.join(col_names)}) VALUES ({', '.join(placeholders)})"
            cursor.execute(sql, values)
            conn.commit()
            flash('Запись успешно добавлена', 'success')
            auth_db.log_auth_action(session.get('telegram_id'), "INSERT", f"Table: {table_name}")
        except Exception as e:
            flash(f'Ошибка: {str(e)}', 'error')
        finally:
            conn.close()

        return redirect(url_for('view_table', table_name=table_name))

    return render_template('edit_row.html',
                           table_name=table_name,
                           columns=columns,
                           row=None,
                           mode='add',
                           tables=tables)


@app.route('/table/<table_name>/edit/<int:row_id>', methods=['GET', 'POST'])
@login_required
def edit_row(table_name, row_id):
    tables = get_all_tables()

    if table_name not in tables:
        flash('Таблица не найдена', 'error')
        return redirect(url_for('dashboard'))

    columns = get_table_info(table_name)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(f"SELECT * FROM {table_name} WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash('Запись не найдена', 'error')
        return redirect(url_for('view_table', table_name=table_name))

    row = dict(row)

    if request.method == 'POST':
        updates = []
        values = []

        for col in columns:
            if col['name'] == 'id':
                continue

            value = request.form.get(col['name'], '')

            if value == '' and col['notnull'] == 0:
                value = None

            updates.append(f"{col['name']} = ?")
            values.append(value)

        values.append(row_id)

        try:
            sql = f"UPDATE {table_name} SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(sql, values)
            conn.commit()
            flash('Запись успешно обновлена', 'success')
            auth_db.log_auth_action(session.get('telegram_id'), "UPDATE", f"Table: {table_name}, ID: {row_id}")
        except Exception as e:
            flash(f'Ошибка: {str(e)}', 'error')
        finally:
            conn.close()

        return redirect(url_for('view_table', table_name=table_name))

    conn.close()

    return render_template('edit_row.html',
                           table_name=table_name,
                           columns=columns,
                           row=row,
                           mode='edit',
                           tables=tables)


@app.route('/table/<table_name>/delete/<int:row_id>', methods=['POST'])
@login_required
def delete_row(table_name, row_id):
    tables = get_all_tables()

    if table_name not in tables:
        return jsonify({'success': False, 'error': 'Таблица не найдена'})

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (row_id,))
        conn.commit()
        auth_db.log_auth_action(session.get('telegram_id'), "DELETE", f"Table: {table_name}, ID: {row_id}")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@app.route('/api/table/<table_name>/raw')
@login_required
def get_raw_data(table_name):
    tables = get_all_tables()

    if table_name not in tables:
        return jsonify({'error': 'Таблица не найдена'}), 404

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return jsonify(rows)


@app.route('/sql', methods=['GET', 'POST'])
@login_required
def sql_console():
    tables = get_all_tables()
    result = None
    error = None
    query = ''

    if request.method == 'POST':
        query = request.form.get('query', '').strip()

        if query:
            conn = get_db_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(query)

                if query.upper().startswith('SELECT'):
                    rows = cursor.fetchall()
                    if rows:
                        columns = [description[0] for description in cursor.description]
                        result = {
                            'columns': columns,
                            'rows': [dict(row) for row in rows]
                        }
                    else:
                        result = {'columns': [], 'rows': []}
                else:
                    conn.commit()
                    result = {'message': f'Запрос выполнен. Затронуто строк: {cursor.rowcount}'}
                    auth_db.log_auth_action(session.get('telegram_id'), "SQL_EXECUTE", query[:100])

            except Exception as e:
                error = str(e)
            finally:
                conn.close()

    return render_template('sql_console.html',
                           tables=tables,
                           result=result,
                           error=error,
                           query=query)


# === AI Task Generator ===

@app.route('/ai-tasks')
@login_required
def ai_tasks():
    """Страница AI-генератора задач"""
    tables = get_all_tables()
    return render_template('ai_tasks.html', tables=tables)


@app.route('/api/ai/chat', methods=['POST'])
@login_required
def ai_chat():
    """API для стриминга ответа от AI"""
    data = request.get_json()
    user_message = data.get('message', '').strip()

    if not user_message:
        return jsonify({'error': 'Пустое сообщение'}), 400

    session_id = session.get('session_token', 'default')

    def generate():
        """Генератор для SSE стриминга"""

        async def stream():
            async for chunk in ai_service.stream_chat(session_id, user_message):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

        # Запускаем асинхронный генератор
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async_gen = stream()

        try:
            while True:
                try:
                    chunk = loop.run_until_complete(async_gen.__anext__())
                    yield chunk
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/ai/parse-tasks', methods=['POST'])
@login_required
def parse_tasks():
    """Парсинг задач из текста"""
    data = request.get_json()
    text = data.get('text', '')

    tasks = AIService.parse_tasks_from_response(text)

    return jsonify({'tasks': tasks})


@app.route('/api/ai/add-task', methods=['POST'])
@login_required
def add_ai_task():
    """Добавление задачи из AI в базу данных"""
    data = request.get_json()
    task = data.get('task', {})

    # Валидация
    required = ['subject', 'question', 'options', 'answer']
    for field in required:
        if field not in task:
            return jsonify({'success': False, 'error': f'Отсутствует поле: {field}'})

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Сериализуем options в JSON
        options_json = json.dumps(task['options'], ensure_ascii=False)

        # Проверяем наличие колонки generated_by_llm
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'generated_by_llm' in columns:
            cursor.execute("""
                INSERT INTO tasks (subject, difficulty, topic, question, options, answer, hint, generated_by_llm, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
            """, (
                task.get('subject', ''),
                task.get('difficulty', 'medium'),
                task.get('topic', ''),
                task.get('question', ''),
                options_json,
                task.get('answer', ''),
                task.get('hint', '')
            ))
        else:
            cursor.execute("""
                INSERT INTO tasks (subject, difficulty, topic, question, options, answer, hint, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                task.get('subject', ''),
                task.get('difficulty', 'medium'),
                task.get('topic', ''),
                task.get('question', ''),
                options_json,
                task.get('answer', ''),
                task.get('hint', '')
            ))

        conn.commit()
        task_id = cursor.lastrowid

        auth_db.log_auth_action(
            session.get('telegram_id'),
            "AI_TASK_ADDED",
            f"Task ID: {task_id}, Subject: {task.get('subject')}"
        )

        return jsonify({'success': True, 'task_id': task_id})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@app.route('/api/ai/clear-history', methods=['POST'])
@login_required
def clear_ai_history():
    """Очистка истории чата"""
    session_id = session.get('session_token', 'default')
    ai_service.clear_conversation(session_id)
    return jsonify({'success': True})


@app.route('/api/ai/get-history', methods=['GET'])
@login_required
def get_ai_history():
    """Получение истории чата"""
    session_id = session.get('session_token', 'default')
    history = ai_service.get_conversation(session_id)
    return jsonify({'history': history})


# === Import Tasks from Files ===

@app.route('/import-tasks')
@login_required
def import_tasks_page():
    """Страница импорта задач из файлов"""
    tables = get_all_tables()
    return render_template('import_tasks.html', tables=tables)


@app.route('/api/import/json', methods=['POST'])
@login_required
def import_json():
    """Импорт задач из JSON файла"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не выбран'})

    file = request.files['file']

    if file.filename == '':
        return jsonify({'success': False, 'error': 'Файл не выбран'})

    if not file.filename.lower().endswith('.json'):
        return jsonify({'success': False, 'error': 'Допускаются только .json файлы'})

    try:
        content = file.read().decode('utf-8')
    except UnicodeDecodeError:
        try:
            file.seek(0)
            content = file.read().decode('cp1251')
        except Exception:
            return jsonify({'success': False, 'error': 'Не удалось прочитать файл. Проверьте кодировку (UTF-8).'})

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return jsonify({'success': False, 'error': f'Ошибка парсинга JSON: {str(e)}'})

    tasks, parse_errors = parse_tasks_from_json_data(data)

    if not tasks:
        error_msg = 'Не найдено валидных задач.'
        if parse_errors:
            error_msg += ' Ошибки: ' + '; '.join(parse_errors[:5])
        return jsonify({'success': False, 'error': error_msg})

    # Вставляем задачи в БД
    conn = get_db_connection()
    cursor = conn.cursor()

    # Проверяем наличие колонки generated_by_llm
    cursor.execute("PRAGMA table_info(tasks)")
    columns = [col[1] for col in cursor.fetchall()]
    has_llm_column = 'generated_by_llm' in columns

    added_ids = []
    insert_errors = []

    for i, task in enumerate(tasks):
        try:
            task_id = insert_task_to_db(cursor, task, has_llm_column)
            added_ids.append(task_id)
        except Exception as e:
            insert_errors.append(f'Задача {i + 1}: {str(e)}')

    conn.commit()
    conn.close()

    auth_db.log_auth_action(
        session.get('telegram_id'),
        "IMPORT_JSON",
        f"File: {file.filename}, Added: {len(added_ids)}, Errors: {len(insert_errors) + len(parse_errors)}"
    )

    return jsonify({
        'success': True,
        'added': len(added_ids),
        'added_ids': added_ids,
        'total_in_file': len(tasks) + len(parse_errors),
        'parse_errors': parse_errors[:10],
        'insert_errors': insert_errors[:10]
    })


@app.route('/api/import/csv', methods=['POST'])
@login_required
def import_csv():
    """Импорт задач из CSV файла"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не выбран'})

    file = request.files['file']

    if file.filename == '':
        return jsonify({'success': False, 'error': 'Файл не выбран'})

    if not file.filename.lower().endswith('.csv'):
        return jsonify({'success': False, 'error': 'Допускаются только .csv файлы'})

    try:
        content = file.read().decode('utf-8')
    except UnicodeDecodeError:
        try:
            file.seek(0)
            content = file.read().decode('cp1251')
        except Exception:
            return jsonify({'success': False, 'error': 'Не удалось прочитать файл. Проверьте кодировку (UTF-8).'})

    tasks, parse_errors = parse_tasks_from_csv_data(content)

    if not tasks:
        error_msg = 'Не найдено валидных задач.'
        if parse_errors:
            error_msg += ' Ошибки: ' + '; '.join(parse_errors[:5])
        return jsonify({'success': False, 'error': error_msg})

    # Вставляем задачи в БД
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(tasks)")
    columns = [col[1] for col in cursor.fetchall()]
    has_llm_column = 'generated_by_llm' in columns

    added_ids = []
    insert_errors = []

    for i, task in enumerate(tasks):
        try:
            task_id = insert_task_to_db(cursor, task, has_llm_column)
            added_ids.append(task_id)
        except Exception as e:
            insert_errors.append(f'Задача {i + 1}: {str(e)}')

    conn.commit()
    conn.close()

    auth_db.log_auth_action(
        session.get('telegram_id'),
        "IMPORT_CSV",
        f"File: {file.filename}, Added: {len(added_ids)}, Errors: {len(insert_errors) + len(parse_errors)}"
    )

    return jsonify({
        'success': True,
        'added': len(added_ids),
        'added_ids': added_ids,
        'total_in_file': len(tasks) + len(parse_errors),
        'parse_errors': parse_errors[:10],
        'insert_errors': insert_errors[:10]
    })


@app.route('/api/import/json-text', methods=['POST'])
@login_required
def import_json_text():
    """Импорт задач из JSON текста (вставленного в textarea)"""
    data = request.get_json()
    text = data.get('text', '').strip()

    if not text:
        return jsonify({'success': False, 'error': 'Пустой текст'})

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return jsonify({'success': False, 'error': f'Ошибка парсинга JSON: {str(e)}'})

    tasks, parse_errors = parse_tasks_from_json_data(parsed)

    if not tasks:
        error_msg = 'Не найдено валидных задач.'
        if parse_errors:
            error_msg += ' Ошибки: ' + '; '.join(parse_errors[:5])
        return jsonify({'success': False, 'error': error_msg})

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(tasks)")
    columns = [col[1] for col in cursor.fetchall()]
    has_llm_column = 'generated_by_llm' in columns

    added_ids = []
    insert_errors = []

    for i, task in enumerate(tasks):
        try:
            task_id = insert_task_to_db(cursor, task, has_llm_column)
            added_ids.append(task_id)
        except Exception as e:
            insert_errors.append(f'Задача {i + 1}: {str(e)}')

    conn.commit()
    conn.close()

    auth_db.log_auth_action(
        session.get('telegram_id'),
        "IMPORT_JSON_TEXT",
        f"Added: {len(added_ids)}, Errors: {len(insert_errors) + len(parse_errors)}"
    )

    return jsonify({
        'success': True,
        'added': len(added_ids),
        'added_ids': added_ids,
        'total_in_file': len(tasks) + len(parse_errors),
        'parse_errors': parse_errors[:10],
        'insert_errors': insert_errors[:10]
    })


@app.route('/api/import/preview', methods=['POST'])
@login_required
def import_preview():
    """Предпросмотр задач из загруженного файла (без сохранения в БД)"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не выбран'})

    file = request.files['file']
    filename = file.filename.lower()

    try:
        content = file.read().decode('utf-8')
    except UnicodeDecodeError:
        try:
            file.seek(0)
            content = file.read().decode('cp1251')
        except Exception:
            return jsonify({'success': False, 'error': 'Не удалось прочитать файл.'})

    if filename.endswith('.json'):
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            return jsonify({'success': False, 'error': f'Ошибка парсинга JSON: {str(e)}'})
        tasks, errors = parse_tasks_from_json_data(data)
    elif filename.endswith('.csv'):
        tasks, errors = parse_tasks_from_csv_data(content)
    else:
        return jsonify({'success': False, 'error': 'Неподдерживаемый формат файла'})

    return jsonify({
        'success': True,
        'tasks': tasks,
        'errors': errors
    })


# === Запуск ===

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)