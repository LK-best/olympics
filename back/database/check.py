import sys
import sqlite3
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QPlainTextEdit, QComboBox, QStatusBar, QMessageBox
)
from PyQt6.QtCore import Qt


class MyWidget(QMainWindow):
    def __init__(self):
        super().__init__()
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.UI()
        self.tabWidget.currentChanged.connect(self.tab_changed)
        self.update_films()
        self.update_genres()

    def UI(self):
        self.setGeometry(100, 100, 800, 700)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.all = QVBoxLayout(central_widget)

        self.tabWidget = QTabWidget()
        self.all.addWidget(self.tabWidget)

        self.filmsTab = QWidget()
        self.filmsTable = QTableWidget()
        self.filmsTable.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.filmsTable.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)

        self.addFilmButton = QPushButton("Добавить фильм")
        self.editFilmButton = QPushButton("Изменить фильм")
        self.deleteFilmButton = QPushButton("Удалить фильм")

        layout_buttons = QHBoxLayout()
        layout_buttons.addWidget(self.addFilmButton)
        layout_buttons.addWidget(self.editFilmButton)
        layout_buttons.addWidget(self.deleteFilmButton)

        layout_films = QVBoxLayout(self.filmsTab)
        layout_films.addLayout(layout_buttons)
        layout_films.addWidget(self.filmsTable)

        self.tabWidget.addTab(self.filmsTab, "Фильмы")
        self.addFilmButton.clicked.connect(self.add_film)
        self.editFilmButton.clicked.connect(self.edit_film)
        self.deleteFilmButton.clicked.connect(self.delete_film)

        self.genresTab = QWidget()
        self.genresTable = QTableWidget()
        self.genresTable.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.genresTable.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)

        self.addGenreButton = QPushButton("Добавить жанр")
        self.editGenreButton = QPushButton("Изменить жанр")
        self.deleteGenreButton = QPushButton("Удалить жанр")

        layout_genre_buttons = QHBoxLayout()
        layout_genre_buttons.addWidget(self.addGenreButton)
        layout_genre_buttons.addWidget(self.editGenreButton)
        layout_genre_buttons.addWidget(self.deleteGenreButton)

        layout_genres = QVBoxLayout(self.genresTab)
        layout_genres.addLayout(layout_genre_buttons)
        layout_genres.addWidget(self.genresTable)

        self.tabWidget.addTab(self.genresTab, "Жанры")
        self.addGenreButton.clicked.connect(self.add_genre)
        self.editGenreButton.clicked.connect(self.edit_genre)
        self.deleteGenreButton.clicked.connect(self.delete_genre)

    def get_genres(self):
        with sqlite3.connect('films_db.sqlite') as con:
            cursor = con.cursor()
            cursor.execute('SELECT id, title FROM genres')
            return cursor.fetchall()

    def update_films(self):
        with sqlite3.connect('films_db.sqlite') as con:
            cur = con.cursor()
            cur.execute('''
                SELECT films.id, films.title, films.year,
                       IFNULL(genres.title, films.genre),
                       films.duration
                FROM films
                LEFT JOIN genres ON films.genre = genres.id
            ''')
            result = cur.fetchall()
            self.filmsTable.setRowCount(len(result))
            self.filmsTable.setColumnCount(5)
            self.filmsTable.setHorizontalHeaderLabels(
                ('ИД', 'Название', 'Год', 'Жанр', 'Длительность')
            )
            for i, row in enumerate(result):
                for j, val in enumerate(row):
                    item = QTableWidgetItem(str(val))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.filmsTable.setItem(i, j, item)

    def update_genres(self):
        with sqlite3.connect('films_db.sqlite') as con:
            cur = con.cursor()
            cur.execute('SELECT id, title FROM genres')
            result = cur.fetchall()
            self.genresTable.setRowCount(len(result))
            self.genresTable.setColumnCount(2)
            self.genresTable.setHorizontalHeaderLabels(['ИД', 'Название жанра'])
            for i, row in enumerate(result):
                for j, val in enumerate(row):
                    item = QTableWidgetItem(str(val))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.genresTable.setItem(i, j, item)

    def edit_film(self):
        act = self.filmsTable.selectedItems()
        if not act:
            self.statusBar.showMessage("Выберите фильм для редактирования", 4000)
            return
        sett = {i.row() for i in act}
        if len(sett) != 1:
            self.statusBar.showMessage("Выберите фильм для редактирования", 4000)
            return
        ittemm = self.filmsTable.item(next(iter(sett)), 0)
        if not ittemm or not ittemm.text().isdigit():
            self.statusBar.showMessage("Некорректный ID фильма", 4000)
            return
        idd = int(ittemm.text())
        self.edit_film_widget = AddFilmWidget(self, film_id=idd)
        self.edit_film_widget.show()

    def check(self):
        act = self.filmsTable.selectedItems()
        if not act:
            self.statusBar.showMessage("Выберите один или несколько фильмов для удаления", 4000)
            return []
        sett = {i.row() for i in act}
        lis = []
        for row in sorted(sett):
            id_item = self.filmsTable.item(row, 0)
            if id_item and id_item.text().isdigit():
                lis.append(int(id_item.text()))
        if not lis:
            self.statusBar.showMessage("Некорректные ID фильмов", 4000)
        return lis

    def add_film(self):
        self.add_film_widget = AddFilmWidget(self)
        self.add_film_widget.show()

    def add_genre(self):
        self.add_genre_widget = AddGenreWidget(self)
        self.add_genre_widget.show()

    def get_selected_genre_ids(self):
        act = self.genresTable.selectedItems()
        if not act:
            self.statusBar.showMessage("Выберите один или несколько жанров для удаления", 4000)
            return []
        sett = {i.row() for i in act}
        lis = []
        for c in sorted(sett):
            id_item = self.genresTable.item(c, 0)
            if id_item and id_item.text().isdigit():
                lis.append(int(id_item.text()))
        if not lis:
            self.statusBar.showMessage("Некорректные ID жанров", 4000)
        return lis

    def tab_changed(self, index):
        if index == 0:
            self.update_films()
        else:
            self.update_genres()

    def edit_genre(self):
        selected = self.genresTable.selectedItems()
        if not selected:
            self.statusBar.showMessage("Выберите жанр для редактирования", 4000)
            return
        rows = {item.row() for item in selected}
        if len(rows) != 1:
            self.statusBar.showMessage("Для редактирования выберите ровно один жанр", 4000)
            return
        ittemm = self.genresTable.item(next(iter(rows)), 0)
        if not ittemm or not ittemm.text().isdigit():
            self.statusBar.showMessage("Некорректный ID жанра", 4000)
            return
        idd = int(ittemm.text())
        self.edit_genre_widget = AddGenreWidget(self, genre_id=idd)
        self.edit_genre_widget.show()

    def delete_film(self):
        idd = self.check()
        if not idd:
            return
        reply = QMessageBox.question(
            self, '',
            f'Вы действительно хотите удалить фильмы с id {" ".join(map(str, idd))}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            with sqlite3.connect('films_db.sqlite') as con:
                for c in idd:
                    con.execute('DELETE FROM films WHERE id = ?', (c,))
            self.update_films()

    def delete_genre(self):
        idd = self.get_selected_genre_ids()
        if not idd:
            return
        reply = QMessageBox.question(
            self, '',
            f'Вы действительно хотите удалить жанры с id {" ".join(map(str, idd))}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            with sqlite3.connect('films_db.sqlite') as con:
                for c in idd:
                    con.execute('DELETE FROM genres WHERE id = ?', (c,))
            self.update_genres()
            self.update_films()


class AddFilmWidget(QMainWindow):
    def __init__(self, parent=None, film_id=None):
        super().__init__(parent)
        self.film_id = film_id
        self.add_true, self.edit_true = False, False
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.UI()
        if self.film_id is not None:
            self.setWindowTitle("Редактирование фильма")
            self.pushButton.setText("Сохранить изменения")
            self.pushButton.clicked.disconnect()
            self.pushButton.clicked.connect(self.edit_elem)
            self.load_film_data()

    def UI(self):
        self.params = {}
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.title, self.year, self.duration = QPlainTextEdit(), QPlainTextEdit(), QPlainTextEdit()
        for c in (self.title, self.year, self.duration):
            c.setFixedSize(400, 30)

        genres = self.parent().get_genres() if self.parent() else []
        for k, c in genres:
            self.params[c] = k

        self.comboBox = QComboBox()
        self.comboBox.addItems(self.params.keys())

        def make_row(label_text, widget):
            row_layout = QHBoxLayout()
            row_layout.addWidget(QLabel(label_text))
            row_layout.addWidget(widget)
            return row_layout

        layout.addLayout(make_row("Название", self.title))
        layout.addLayout(make_row("Год", self.year))
        layout.addLayout(make_row("Жанр", self.comboBox))
        layout.addLayout(make_row("Длительность", self.duration))

        self.pushButton = QPushButton("Добавить")
        self.pushButton.clicked.connect(self.add_elem)
        layout.addWidget(self.pushButton)

        self.setGeometry(200, 200, 500, 250)

    def load_film_data(self):
        with sqlite3.connect('films_db.sqlite') as con:
            cur = con.cursor()
            cur.execute('SELECT title, year, genre, duration FROM films WHERE id = ?', (self.film_id,))
            ans = cur.fetchone()
            if ans:
                title, year, genre, duration = ans
                self.title.setPlainText(title)
                self.year.setPlainText(str(year))
                self.duration.setPlainText(str(duration))
                for k, c in self.params.items():
                    if c == genre:
                        self.comboBox.setCurrentText(k)
                        return

    def get_adding_verdict(self):
        return self.add_true

    def get_editing_verdict(self):
        return self.edit_true

    def validate(self):
        title = self.title.toPlainText()
        year_text = self.year.toPlainText()
        duration_text = self.duration.toPlainText()
        genre_title = self.comboBox.currentText()

        if not title:
            self.statusBar.showMessage("Название не может быть пустым", 4000)
            return None, None, None, None

        try:
            year = int(year_text)
            if year < 0 or year > 2025:
                raise ValueError
        except ValueError:
            self.statusBar.showMessage("Год должен быть от 0 до текущего года", 4000)
            return None, None, None, None

        try:
            duration = int(duration_text)
            if duration <= 0:
                raise ValueError
        except ValueError:
            self.statusBar.showMessage("Длительность должна быть положительным числом", 4000)
            return None, None, None, None

        genre_id = self.params.get(genre_title)
        if genre_id is None:
            self.statusBar.showMessage("Выберите корректный жанр", 4000)
            return None, None, None, None

        return title, year, genre_id, duration

    def add_elem(self):
        data = self.validate()
        if data[0] is None:
            return
        title, year, genre_id, duration = data
        with sqlite3.connect('films_db.sqlite') as con:
            con.execute(
                'INSERT INTO films (title, year, genre, duration) VALUES (?, ?, ?, ?)',
                (title, year, genre_id, duration)
            )
        self.add_true = True
        self.parent().update_films()
        self.close()

    def edit_elem(self):
        data = self.validate()
        if data[0] is None:
            return
        title, year, genre_id, duration = data
        with sqlite3.connect('films_db.sqlite') as con:
            con.execute(
                'UPDATE films SET title = ?, year = ?, genre = ?, duration = ? WHERE id = ?',
                (title, year, genre_id, duration, self.film_id)
            )
        self.edit_true = True
        self.parent().update_films()
        self.close()


class AddGenreWidget(QMainWindow):
    def __init__(self, parent=None, genre_id=None):
        super().__init__(parent)
        self.genre_id = genre_id
        self.add_true = False
        self.edit_true = False
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.UI()
        if self.genre_id is not None:
            self.setWindowTitle("Редактирование жанра")
            self.pushButton.setText("Сохранить изменения")
            self.pushButton.clicked.disconnect()
            self.pushButton.clicked.connect(self.edit_elem)
            self.load_genre_data()

    def UI(self):
        self.setWindowTitle("Добавить жанр")
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.title = QPlainTextEdit()
        self.title.setFixedSize(400, 30)

        layout.addWidget(QLabel("Название жанра:"))
        layout.addWidget(self.title)

        self.pushButton = QPushButton("Добавить")
        self.pushButton.clicked.connect(self.add_elem)
        layout.addWidget(self.pushButton)

        self.setGeometry(200, 200, 400, 150)

    def load_genre_data(self):
        with sqlite3.connect('films_db.sqlite') as con:
            cur = con.cursor()
            ans = cur.execute('SELECT title FROM genres WHERE id = ?', (self.genre_id,)).fetchone()
            if ans:
                self.title.setPlainText(ans[0])

    def validate(self):
        title = self.title.toPlainText().strip()
        if not title:
            self.statusBar.showMessage("Название жанра не может быть пустым", 4000)
            return None
        return title

    def get_adding_verdict(self):
        return self.add_true

    def add_elem(self):
        title = self.validate()
        if title is None:
            return

        with sqlite3.connect('films_db.sqlite') as con:
            con.execute('INSERT INTO genres (title) VALUES (?)', (title,))
        self.add_true = True
        self.parent().update_genres()
        self.close()

    def get_editing_verdict(self):
        return self.edit_true

    def edit_elem(self):
        title = self.validate()
        if title is None:
            return

        with sqlite3.connect('films_db.sqlite') as con:
            con.execute('UPDATE genres SET title = ? WHERE id = ?', (title, self.genre_id))
        self.edit_true = True
        self.parent().update_genres()
        self.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MyWidget()
    window.show()
    sys.exit(app.exec())