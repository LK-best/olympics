import sqlite3
import os

DB_NAME = "alien_signals.db"
SCHEMA_FILE = "database.sql"


class Database:

    def __init__(self, db_name=DB_NAME):
        self.db_name = db_name
        self.conn = None

    def connect(self):
        self.conn = sqlite3.connect(self.db_name)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row
        return self.conn

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    # Инициализация БД из SQL-файла
    def init_db(self):
        conn = self.connect()
        cursor = conn.cursor()

        with open(SCHEMA_FILE, 'r', encoding='utf-8') as file:
            sql_schema = file.read()

        cursor.executescript(sql_schema)
        conn.commit()
        self.close()
        print(f"[DB] База данных '{self.db_name}' инициализирована из '{SCHEMA_FILE}'")

    # Пользователи
    def authenticate(self, login: str, password: str) -> dict | None:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, role, first_name, last_name FROM users WHERE login=? AND password=?",
            (login, password)
        )
        row = cursor.fetchone()
        self.close()

        if row:
            self.log_session(row["id"])
            return {
                "id": row["id"],
                "role": row["role"],
                "first_name": row["first_name"],
                "last_name": row["last_name"]
            }
        return None

    def create_user(self, login: str, password: str, role: str,
                    first_name: str, last_name: str) -> bool:
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (login, password, role, first_name, last_name) VALUES (?, ?, ?, ?, ?)",
                (login, password, role, first_name, last_name)
            )
            conn.commit()
            self.close()
            return True
        except sqlite3.IntegrityError:
            self.close()
            return False

    def get_all_users(self) -> list:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id, login, role, first_name, last_name, created_at FROM users")
        rows = cursor.fetchall()
        self.close()
        return [dict(row) for row in rows]

    # Сессии
    def log_session(self, user_id: int):
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sessions (user_id) VALUES (?)", (user_id,))
        conn.commit()
        self.close()

    def get_sessions(self, user_id: int = None) -> list:
        conn = self.connect()
        cursor = conn.cursor()
        if user_id:
            cursor.execute(
                "SELECT s.id, u.login, u.first_name, u.last_name, s.login_time "
                "FROM sessions s JOIN users u ON s.user_id = u.id "
                "WHERE s.user_id = ? ORDER BY s.login_time DESC",
                (user_id,)
            )
        else:
            cursor.execute(
                "SELECT s.id, u.login, u.first_name, u.last_name, s.login_time "
                "FROM sessions s JOIN users u ON s.user_id = u.id "
                "ORDER BY s.login_time DESC"
            )
        rows = cursor.fetchall()
        self.close()
        return [dict(row) for row in rows]

    # История обучения
    def save_training_history(self, history: list[dict]):
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM training_history")
        for entry in history:
            cursor.execute(
                "INSERT INTO training_history (epoch, train_accuracy, val_accuracy, train_loss, val_loss) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry["epoch"], entry["train_accuracy"], entry["val_accuracy"],
                 entry["train_loss"], entry["val_loss"])
            )
        conn.commit()
        self.close()

    def