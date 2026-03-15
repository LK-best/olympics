import sys
import os

from back.database.database import Database
from front.pyqt import AppController
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":
    db = Database()
    db.init_db()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = AppController()
    window.show()
    sys.exit(app.exec())