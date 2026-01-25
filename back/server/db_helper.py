# помощник для работы с базой данных
# переписал с json на sqlite потому что json тормозит
# добавил функции для сервера
# 2026 год

import sqlite3
import os
import json
from datetime import datetime

# путь к базе
DB_FILE = "database.db"


def poluchit_connect():
    # получаем соединение с базой
    if os.path.exists(DB_FILE) == False:
        print("база не найдена! запусти сначала database.py")
        return None

    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def zakrit_connect(conn):
    if conn != None:
        conn.close()


def vipolnit_zapros(sql, params=None, fetchone=False, fetchall=False, commit=False):
    # универсальная функция для запросов
    conn = poluchit_connect()
    if conn == None:
        return None

    rezultat = None

    try:
        cursor = conn.cursor()

        if params == None:
            cursor.execute(sql)
        else:
            cursor.execute(sql, params)

        if commit == True:
            conn.commit()
            rezultat = cursor.lastrowid
        elif fetchone == True:
            row = cursor.fetchone()
            if row != None:
                rezultat = dict(row)
        elif fetchall == True:
            rows = cursor.fetchall()
            rezultat = []
            i = 0
            while i < len(rows):
                rezultat.append(dict(rows[i]))
                i = i + 1

    except Exception as e:
        print("ошибка sql: " + str(e))
        print("запрос был: " + sql)
        rezultat = None

    finally:
        zakrit_connect(conn)

    return rezultat


###################################
# функции для юзеров
###################################

def poluchit_usera_po_id(user_id):
    sql = "SELECT * FROM users WHERE id = ?"
    user = vipolnit_zapros(sql, (user_id,), fetchone=True)
    if user != None:
        user = _obogati_usera(user)
    return user


def poluchit_usera_po_email(email):
    sql = "SELECT * FROM users WHERE email = ?"
    user = vipolnit_zapros(sql, (email,), fetchone=True)
    if user != None:
        user = _obogati_usera(user)
    return user


def _obogati_usera(user):
    # добавляем достижения и парсим json поля
    if user == None:
        return None

    # достижения
    achi = vipolnit_zapros(
        "SELECT achievement_id FROM user_achievements WHERE user_id = ?",
        (user["id"],), fetchall=True
    )
    user["achievements"] = []
    if achi != None:
        for a in achi:
            user["achievements"].append(a["achievement_id"])

    # парсим subject_stats
    if user.get("subject_stats"):
        try:
            user["subjectStats"] = json.loads(user["subject_stats"])
        except:
            user["subjectStats"] = {}
    else:
        user["subjectStats"] = {}

    # формируем stats как в старом формате
    user["stats"] = {
        "solved": user.get("solved_count", 0),
        "correct": user.get("correct_count", 0),
        "wins": user.get("wins", 0),
        "losses": user.get("losses", 0),
        "draws": user.get("draws", 0)
    }

    # isAdmin для совместимости
    user["isAdmin"] = user.get("is_admin", 0) == 1

    # name для совместимости
    user["name"] = user.get("username", "")

    return user


def sozdat_usera(name, email, password_hash):
    sql = """
        INSERT INTO users (username, email, password_hash, level, xp, rating)
        VALUES (?, ?, ?, 1, 0, 1000)
    """
    user_id = vipolnit_zapros(sql, (name, email, password_hash), commit=True)
    return user_id


def obnovit_usera(user_id, **polya):
    if len(polya) == 0:
        return False

    # маппинг старых названий на новые
    mapping = {
        "name": "username",
        "isAdmin": "is_admin",
        "subjectStats": "subject_stats"
    }

    set_chasti = []
    znacheniya = []

    for pole, znachenie in polya.items():
        # преобразуем название если надо
        db_pole = mapping.get(pole, pole)

        # преобразуем значение
        if db_pole == "subject_stats" and type(znachenie) == dict:
            znachenie = json.dumps(znachenie)
        elif db_pole == "is_admin":
            znachenie = 1 if znachenie else 0

        set_chasti.append(db_pole + " = ?")
        znacheniya.append(znachenie)

    znacheniya.append(user_id)

    sql = "UPDATE users SET " + ", ".join(set_chasti) + " WHERE id = ?"
    vipolnit_zapros(sql, tuple(znacheniya), commit=True)
    return True


def poluchit_vseh_userov():
    sql = "SELECT * FROM users ORDER BY rating DESC"
    usery = vipolnit_zapros(sql, fetchall=True)
    if usery != None:
        rezultat = []
        for u in usery:
            rezultat.append(_obogati_usera(u))
        return rezultat
    return []


###################################
# достижения
###################################

def poluchit_dostizheniya(user_id):
    sql = "SELECT achievement_id FROM user_achievements WHERE user_id = ?"
    rows = vipolnit_zapros(sql, (user_id,), fetchall=True)
    rezultat = []
    if rows != None:
        for r in rows:
            rezultat.append(r["achievement_id"])
    return rezultat


def dobavit_dostizhenie(user_id, achievement_id):
    sql = """
        INSERT OR IGNORE INTO user_achievements (user_id, achievement_id)
        VALUES (?, ?)
    """
    vipolnit_zapros(sql, (user_id, achievement_id), commit=True)
    return True


###################################
# история юзера
###################################

def dobavit_v_istoriyu(user_id, text, date_str=None):
    if date_str == None:
        date_str = datetime.now().strftime("%d.%m.%Y")

    sql = """
        INSERT INTO user_history (user_id, action_text, action_date)
        VALUES (?, ?, ?)
    """
    vipolnit_zapros(sql, (user_id, text, date_str), commit=True)
    return True


def poluchit_istoriyu(user_id, limit=50):
    sql = """
        SELECT * FROM user_history 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    """
    return vipolnit_zapros(sql, (user_id, limit), fetchall=True)


###################################
# история матчей юзера
###################################

def dobavit_match_v_istoriyu(user_id, match_id, opponent_name, opponent_rating,
                             my_score, opp_score, result, rating_change,
                             subject, mode):
    sql = """
        INSERT INTO user_match_history 
        (user_id, match_id, opponent_name, opponent_rating, my_score, opp_score,
         result, rating_change, subject, mode, match_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    match_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    params = (user_id, match_id, opponent_name, opponent_rating, my_score,
              opp_score, result, rating_change, subject, mode, match_date)
    vipolnit_zapros(sql, params, commit=True)
    return True


def poluchit_istoriyu_matchey_usera(user_id, limit=20):
    sql = """
        SELECT * FROM user_match_history 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    """
    return vipolnit_zapros(sql, (user_id, limit), fetchall=True)


###################################
# задачи
###################################

def poluchit_vse_zadachi():
    sql = "SELECT * FROM tasks"
    tasks = vipolnit_zapros(sql, fetchall=True)
    return _parse_tasks(tasks)


def poluchit_zadachi_s_filtrami(subject=None, difficulty=None, topic=None, search=None):
    sql = "SELECT * FROM tasks WHERE 1=1"
    params = []

    if subject != None and subject != "":
        sql = sql + " AND subject = ?"
        params.append(subject)

    if difficulty != None and difficulty != "":
        sql = sql + " AND difficulty = ?"
        params.append(difficulty)

    if topic != None and topic != "":
        sql = sql + " AND topic = ?"
        params.append(topic)

    if search != None and search != "":
        sql = sql + " AND LOWER(question) LIKE ?"
        params.append("%" + search.lower() + "%")

    tasks = vipolnit_zapros(sql, tuple(params), fetchall=True)
    return _parse_tasks(tasks)


def poluchit_zadachu_po_id(task_id):
    sql = "SELECT * FROM tasks WHERE id = ?"
    task = vipolnit_zapros(sql, (task_id,), fetchone=True)
    if task != None:
        task = _parse_task(task)
    return task


def _parse_tasks(tasks):
    if tasks == None:
        return []
    rezultat = []
    for t in tasks:
        rezultat.append(_parse_task(t))
    return rezultat


def _parse_task(task):
    if task == None:
        return None
    # парсим options из json
    if task.get("options"):
        try:
            task["options"] = json.loads(task["options"])
        except:
            task["options"] = []
    else:
        task["options"] = []
    return task


def sozdat_zadachu(subject, difficulty, topic, question, options, answer, hint=""):
    # options должен быть списком, сохраняем как json
    options_json = json.dumps(options)

    sql = """
        INSERT INTO tasks (subject, difficulty, topic, question, options, answer, hint)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    return vipolnit_zapros(sql, (subject, difficulty, topic, question, options_json, answer, hint), commit=True)


def udalit_zadachu(task_id):
    sql = "DELETE FROM tasks WHERE id = ?"
    vipolnit_zapros(sql, (task_id,), commit=True)
    return True


###################################
# матчи
###################################

def sozdat_match(player1_id, player1_name, player1_rating, player2_id, player2_name,
                 player2_rating, subject, mode, tasks, is_bot=False):
    # tasks - список задач, сохраняем как json
    tasks_json = json.dumps(tasks)
    is_bot_int = 1 if is_bot else 0

    sql = """
        INSERT INTO matches 
        (player1_id, player1_name, player1_rating, player2_id, player2_name,
         player2_rating, subject, mode, tasks, status, is_bot)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
    """
    params = (player1_id, player1_name, player1_rating, player2_id, player2_name,
              player2_rating, subject, mode, tasks_json, is_bot_int)
    return vipolnit_zapros(sql, params, commit=True)


def poluchit_match_po_id(match_id):
    sql = "SELECT * FROM matches WHERE id = ?"
    match = vipolnit_zapros(sql, (match_id,), fetchone=True)
    if match != None:
        match = _parse_match(match)
    return match


def _parse_match(match):
    if match == None:
        return None

    # парсим json поля
    json_polya = ["tasks", "player1_answers", "player2_answers"]
    for pole in json_polya:
        if match.get(pole):
            try:
                match[pole] = json.loads(match[pole])
            except:
                match[pole] = []
        else:
            match[pole] = []

    # is_bot в bool
    match["is_bot"] = match.get("is_bot", 0) == 1

    return match


def obnovit_match(match_id, **polya):
    if len(polya) == 0:
        return False

    set_chasti = []
    znacheniya = []

    for pole, znachenie in polya.items():
        set_chasti.append(pole + " = ?")

        # json поля сериализуем
        if pole in ["tasks", "player1_answers", "player2_answers"]:
            znachenie = json.dumps(znachenie)
        elif pole == "is_bot":
            znachenie = 1 if znachenie else 0

        znacheniya.append(znachenie)

    znacheniya.append(match_id)

    sql = "UPDATE matches SET " + ", ".join(set_chasti) + " WHERE id = ?"
    vipolnit_zapros(sql, tuple(znacheniya), commit=True)
    return True


def poluchit_aktivnie_matchi_usera(user_id):
    sql = """
        SELECT * FROM matches 
        WHERE (player1_id = ? OR player2_id = ?) AND status = 'active'
    """
    matchi = vipolnit_zapros(sql, (user_id, user_id), fetchall=True)
    if matchi != None:
        rezultat = []
        for m in matchi:
            rezultat.append(_parse_match(m))
        return rezultat
    return []


def poluchit_vse_matchi():
    sql = "SELECT * FROM matches ORDER BY created_at DESC"
    matchi = vipolnit_zapros(sql, fetchall=True)
    if matchi != None:
        rezultat = []
        for m in matchi:
            rezultat.append(_parse_match(m))
        return rezultat
    return []


###################################
# очередь матчмейкинга
###################################

def dobavit_v_ochered(user_id, user_name, user_rating, subject, mode):
    # проверяем не в очереди ли уже
    proverka = vipolnit_zapros(
        "SELECT * FROM matchmaking_queue WHERE user_id = ?",
        (user_id,), fetchone=True
    )

    if proverka != None:
        return proverka["id"]

    sql = """
        INSERT INTO matchmaking_queue (user_id, user_name, user_rating, subject, mode)
        VALUES (?, ?, ?, ?, ?)
    """
    return vipolnit_zapros(sql, (user_id, user_name, user_rating, subject, mode), commit=True)


def ubrat_iz_ocheredi(user_id):
    sql = "DELETE FROM matchmaking_queue WHERE user_id = ?"
    vipolnit_zapros(sql, (user_id,), commit=True)
    return True


def poluchit_ochered():
    sql = "SELECT * FROM matchmaking_queue ORDER BY created_at ASC"
    return vipolnit_zapros(sql, fetchall=True)


def poluchit_poziciyu_v_ocheredi(user_id):
    ochered = poluchit_ochered()
    if ochered == None:
        return -1

    i = 0
    while i < len(ochered):
        if ochered[i]["user_id"] == user_id:
            return i
        i = i + 1
    return -1


def nayti_sopernika_v_ocheredi(user_id, user_rating, subject, mode, diapason=300):
    # ищем подходящего соперника
    min_r = user_rating - diapason
    max_r = user_rating + diapason

    sql = """
        SELECT * FROM matchmaking_queue
        WHERE user_id != ?
        AND subject = ?
        AND mode = ?
        AND user_rating BETWEEN ? AND ?
        ORDER BY created_at ASC
        LIMIT 1
    """

    # для casual режима рейтинг не важен
    if mode == "casual":
        sql = """
            SELECT * FROM matchmaking_queue
            WHERE user_id != ?
            AND subject = ?
            AND mode = ?
            ORDER BY created_at ASC
            LIMIT 1
        """
        return vipolnit_zapros(sql, (user_id, subject, mode), fetchone=True)

    return vipolnit_zapros(sql, (user_id, subject, mode, min_r, max_r), fetchone=True)


###################################
# статистика по дням
###################################

def obnovit_daily_stats(user_id, solved, correct, subject):
    segodnya = datetime.now().strftime("%Y-%m-%d")

    # день недели
    dni = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    den_nedeli = dni[datetime.now().weekday()]

    # обновляем общую статистику за день
    _obnovit_ili_sozdat_stat(user_id, segodnya, den_nedeli, "all", solved, correct)

    # обновляем статистику по предмету
    _obnovit_ili_sozdat_stat(user_id, segodnya, den_nedeli, subject, solved, correct)

    return True


def _obnovit_ili_sozdat_stat(user_id, stat_date, day_of_week, subject, solved, correct):
    # проверяем есть ли запись
    sql = """
        SELECT * FROM daily_stats 
        WHERE user_id = ? AND stat_date = ? AND subject = ?
    """
    existing = vipolnit_zapros(sql, (user_id, stat_date, subject), fetchone=True)

    if existing != None:
        # обновляем
        sql = """
            UPDATE daily_stats 
            SET solved = solved + ?, correct = correct + ?
            WHERE user_id = ? AND stat_date = ? AND subject = ?
        """
        vipolnit_zapros(sql, (solved, correct, user_id, stat_date, subject), commit=True)
    else:
        # создаём
        sql = """
            INSERT INTO daily_stats (user_id, stat_date, day_of_week, subject, solved, correct)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        vipolnit_zapros(sql, (user_id, stat_date, day_of_week, subject, solved, correct), commit=True)


def poluchit_stats_po_dnyam_nedeli(user_id):
    # агрегируем статистику по дням недели
    sql = """
        SELECT day_of_week, SUM(solved) as solved, SUM(correct) as correct
        FROM daily_stats
        WHERE user_id = ? AND subject = 'all'
        GROUP BY day_of_week
    """
    rows = vipolnit_zapros(sql, (user_id,), fetchall=True)

    # формируем результат с дефолтными значениями
    dni = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    rezultat = {}

    for den in dni:
        rezultat[den] = {"solved": 0, "correct": 0}

    if rows != None:
        for r in rows:
            if r["day_of_week"] in rezultat:
                rezultat[r["day_of_week"]] = {
                    "solved": r["solved"],
                    "correct": r["correct"]
                }

    return rezultat


def poluchit_stats_za_nedelyu(user_id):
    # статистика за последние 7 дней
    from datetime import timedelta

    segodnya = datetime.now()
    rezultat = []

    dni = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    i = 0
    while i < 7:
        delta = 6 - i
        data = segodnya - timedelta(days=delta)
        data_str = data.strftime("%Y-%m-%d")
        den_nedeli = dni[data.weekday()]

        # ищем данные за этот день
        sql = """
            SELECT SUM(solved) as solved, SUM(correct) as correct
            FROM daily_stats
            WHERE user_id = ? AND stat_date = ? AND subject = 'all'
        """
        row = vipolnit_zapros(sql, (user_id, data_str), fetchone=True)

        solved = 0
        correct = 0
        if row != None and row["solved"] != None:
            solved = row["solved"]
            correct = row["correct"]

        rezultat.append({
            "date": data_str,
            "day": den_nedeli,
            "solved": solved,
            "correct": correct
        })

        i = i + 1

    return rezultat


###################################
# проверка базы
###################################

def proverit_bazu():
    conn = poluchit_connect()
    if conn == None:
        return False

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        print("в базе " + str(count) + " юзеров")
        zakrit_connect(conn)
        return True
    except Exception as e:
        print("ошибка проверки базы: " + str(e))
        zakrit_connect(conn)
        return False


if __name__ == "__main__":
    if proverit_bazu():
        print("база работает нормально")
    else:
        print("проблемы с базой! запусти database.py")
