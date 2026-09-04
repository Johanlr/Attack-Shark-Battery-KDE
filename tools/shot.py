"""Abre a janela de preferencias offscreen e salva um PNG de cada aba."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication, QTabWidget
from sharktray import prefs
from sharktray.config import Config
from sharktray.mouse import Reading

app = QApplication([])
cfg = Config("/tmp/claude-1000/-home-kxinha/5fa8be1b-0248-470d-b3f4-11c96f17981f/scratchpad/shot.ini")
r = Reading(True, 97, False, "discharging", 1.0, "03 E5 40 01 61")
w = prefs.Preferences(cfg, lambda: r, None)
w.resize(760, 840)
w.show()
app.processEvents()
tabs = w.findChild(QTabWidget)
out = "/tmp/claude-1000/-home-kxinha/5fa8be1b-0248-470d-b3f4-11c96f17981f/scratchpad"
for i in range(tabs.count()):
    tabs.setCurrentIndex(i)
    for _ in range(4):
        app.processEvents()
    w.grab().save(f"{out}/prefs-{i}-{tabs.tabText(i).lower()}.png")
    print(tabs.tabText(i))
