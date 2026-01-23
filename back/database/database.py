import sqlite3
import os

class Create:
    def __init__(self, file='database.db'):
        self.file = file
        self.create_db()

    def create_db(self):
        name = 'database.sql'
        if not os.path.exists(name):
            print('Перепроверь файл')
            return

        with open(name, 'r', encoding='utf-8') as file:
            imp = file.read()
            print(imp)
        with sqlite3.connect(self.file) as conn:
            conn.executescript(imp)

s = Create()