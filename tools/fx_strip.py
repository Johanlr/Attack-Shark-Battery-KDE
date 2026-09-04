"""Tira com um quadro de cada animacao, para o README."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication
from sharktray import effects, icons

app = QApplication([])
keys = [k for k in effects.EFFECTS if k != "none"]
CELL, PAD, COLS = 72, 12, 9
rows = (len(keys) + COLS - 1) // COLS
img = QImage(COLS * (CELL + PAD) + PAD, rows * (CELL + PAD + 18) + PAD,
             QImage.Format_ARGB32)
img.fill(QColor("#1b1d22"))
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
f = QFont(); f.setPixelSize(10); p.setFont(f)
look = icons.Look(style="shark", scheme="shark")
for i, key in enumerate(keys):
    cx = PAD + (i % COLS) * (CELL + PAD)
    cy = PAD + (i // COLS) * (CELL + PAD + 18)
    p.drawPixmap(cx, cy, icons.render(CELL, look, 64, "discharging", True,
                                      key, 0.34))
    p.setPen(QPen(QColor("#c9ccd4")))
    p.drawText(QRectF(cx - 6, cy + CELL, CELL + 12, 16),
               Qt.AlignHCenter | Qt.AlignTop, effects.EFFECTS[key].label)
p.end()
img.save("assets/effects.png")
print(len(keys), "effects")
