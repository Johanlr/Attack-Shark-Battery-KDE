"""Amplia poucos estilos, para inspecionar o desenho de perto."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from sharktray import icons

app = QApplication([])
keys = sys.argv[1].split(",")
CELL = 220
img = QImage(CELL * len(keys), CELL, QImage.Format_ARGB32)
img.fill(QColor("#1b1d22"))
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
for i, k in enumerate(keys):
    look = icons.Look(style=k, scheme="shark", show_number=False)
    p.drawPixmap(i * CELL, 0, icons.render(CELL, look, 64, "discharging", True))
p.end()
out = "/tmp/claude-1000/-home-kxinha/5fa8be1b-0248-470d-b3f4-11c96f17981f/scratchpad/zoom.png"
img.save(out)
print(out)
