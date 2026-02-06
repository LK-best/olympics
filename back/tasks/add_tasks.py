"""
Добавляет как тестовые задачи, так и задачи из JSON/CSV файлов
"""

import sqlite3
import json
import csv
from datetime import datetime
import os

DB_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "database.db")



def test_tasks():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM tasks")
    if cursor.fetchone()[0] > 0:
        print("В базе уже есть задачи. Пропускаю добавление тестовых задач.")
        conn.close()
        return

    tests_tasks = [
        # Математика
        {
            "subject": "Математика",
            "difficulty": "easy",
            "topic": "Арифметика",
            "question": "Чему равно 15 + 27?",
            "options": ["42", "41", "43", "40"],
            "answer": "42",
            "hint": "Сложите единицы, затем десятки"
        },
        {
            "subject": "Математика",
            "difficulty": "easy",
            "topic": "Арифметика",
            "question": "Чему равно 8 × 7?",
            "options": ["54", "56", "58", "52"],
            "answer": "56",
            "hint": "Вспомните таблицу умножения"
        },
        {
            "subject": "Математика",
            "difficulty": "medium",
            "topic": "Алгебра",
            "question": "Решите уравнение: 2x + 5 = 15",
            "options": ["x = 5", "x = 10", "x = 7", "x = 4"],
            "answer": "x = 5",
            "hint": "Перенесите 5 в правую часть"
        },
        {
            "subject": "Математика",
            "difficulty": "hard",
            "topic": "Геометрия",
            "question": "Площадь круга с радиусом 3 равна:",
            "options": ["9π", "6π", "3π", "12π"],
            "answer": "9π",
            "hint": "S = πr²"
        },
        # Физика
        {
            "subject": "Физика",
            "difficulty": "easy",
            "topic": "Механика",
            "question": "Единица измерения силы в СИ:",
            "options": ["Ньютон", "Джоуль", "Ватт", "Паскаль"],
            "answer": "Ньютон",
            "hint": "Названа в честь известного учёного"
        },
        {
            "subject": "Физика",
            "difficulty": "medium",
            "topic": "Механика",
            "question": "Скорость тела массой 2 кг, если его импульс 10 кг·м/с:",
            "options": ["5 м/с", "20 м/с", "8 м/с", "12 м/с"],
            "answer": "5 м/с",
            "hint": "p = mv"
        },
        # Информатика
        {
            "subject": "Информатика",
            "difficulty": "easy",
            "topic": "Системы счисления",
            "question": "Число 1010 в двоичной системе равно в десятичной:",
            "options": ["10", "8", "12", "6"],
            "answer": "10",
            "hint": "1×8 + 0×4 + 1×2 + 0×1"
        },
        {
            "subject": "Информатика",
            "difficulty": "medium",
            "topic": "Алгоритмы",
            "question": "Какова сложность бинарного поиска?",
            "options": ["O(log n)", "O(n)", "O(n²)", "O(1)"],
            "answer": "O(log n)",
            "hint": "Массив делится пополам на каждом шаге"
        },
        # История
        {
            "subject": "История",
            "difficulty": "easy",
            "topic": "Россия",
            "question": "В каком году была Куликовская битва?",
            "options": ["1380", "1242", "1480", "1612"],
            "answer": "1380",
            "hint": "XIV век"
        },
        {
            "subject": "История",
            "difficulty": "medium",
            "topic": "Мир",
            "question": "Кто открыл Америку в 1492 году?",
            "options": ["Колумб", "Магеллан", "Веспуччи", "Кук"],
            "answer": "Колумб",
            "hint": "Итальянский мореплаватель на службе Испании"
        },
        # Русский язык
        {
            "subject": "Русский язык",
            "difficulty": "easy",
            "topic": "Орфография",
            "question": "Как правильно пишется?",
            "options": ["Искусство", "Исскуство", "Искуство", "Иcкусство"],
            "answer": "Искусство",
            "hint": "Две буквы С в середине"
        },
    ]

    for c in tests_tasks:
        cursor.execute("""
            INSERT INTO tasks (subject, difficulty, topic, question, options, answer, hint, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            c["subject"],
            c["difficulty"],
            c["topic"],
            c["question"],
            json.dumps(c["options"], ensure_ascii=False),
            c["answer"],
            c["hint"],
            datetime.now().isoformat()
        ))

    conn.commit()
    conn.close()


def json_files(json_file="tasks.json"):
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        s1 = 0
        s2 = 0

        for i in data:
            useges = i.get("task", i)

            app = ["subject", "difficulty", "question", "options", "answer"]
            if not all(sss in useges for sss in app):
                s2 += 1
                continue

            cursor.execute(
                "SELECT id FROM tasks WHERE question = ? AND subject = ?",
                (useges["question"], useges["subject"])
            )
            if cursor.fetchone():
                s2 += 1
                continue

            cursor.execute("""
                INSERT INTO tasks (subject, difficulty, topic, question, options, answer, hint, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                useges.get("subject", ""),
                useges.get("difficulty", "medium"),
                useges.get("topic", ""),
                useges.get("question", ""),
                json.dumps(useges.get("options", []), ensure_ascii=False),
                useges.get("answer", ""),
                useges.get("hint", ""),
                datetime.now().isoformat()
            ))
            s1 += 1

        conn.commit()
        conn.close()

    except FileNotFoundError:
        print(f"Файл {json_file} не найден")


def csv_files(name="tasks.csv"):
    try:
        with open(name, 'r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            s1 = 0
            s2 = 0

            for c in reader:
                options = [
                    c.get("option1", ""),
                    c.get("option2", ""),
                    c.get("option3", ""),
                    c.get("option4", "")
                ]

                cursor.execute(
                    "SELECT id FROM tasks WHERE question = ? AND subject = ?",
                    (c.get("question", ""), c.get("subject", ""))
                )
                if cursor.fetchone():
                    s2 += 1
                    continue

                cursor.execute("""
                    INSERT INTO tasks (subject, difficulty, topic, question, options, answer, hint, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    c.get("subject", ""),
                    c.get("difficulty", "medium"),
                    c.get("topic", ""),
                    c.get("question", ""),
                    json.dumps(options, ensure_ascii=False),
                    c.get("answer", ""),
                    c.get("hint", ""),
                    datetime.now().isoformat()
                ))
                s1 += 1

            conn.commit()
            conn.close()

    except FileNotFoundError:
        print(f"Файл {name} не найден")


if __name__ == "__main__":
    test_tasks()
    json_files()
    csv_files()
