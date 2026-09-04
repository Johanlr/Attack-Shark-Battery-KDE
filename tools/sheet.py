"""Contact sheet de todos os estilos, para conferir o desenho de olho."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from sharktray import icons, shapes

app = QApplication([])
CELL, PAD, COLS = 96, 14, 8
keys = list(shapes.STYLES)
rows = (len(keys) + COLS - 1) // COLS
W = COLS * (CELL + PAD) + PAD
H = rows * (CELL + PAD + 20) + PAD

img = QImage(W, H, QImage.Format_ARGB32)
img.fill(QColor("#1b1d22"))
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
f = QFont(); f.setPixelSize(11); p.setFont(f)

level = int(sys.argv[1]) if len(sys.argv) > 1 else 64
scheme = sys.argv[2] if len(sys.argv) > 2 else "shark"
for i, key in enumerate(keys):
    cx = PAD + (i % COLS) * (CELL + PAD)
    cy = PAD + (i // COLS) * (CELL + PAD + 20)
    look = icons.Look(style=key, scheme=scheme)
    pm = icons.render(CELL, look, level, "discharging", True, "none", 0.0)
    p.drawPixmap(cx, cy, pm)
    p.setPen(QPen(QColor("#c9ccd4")))
    p.drawText(QRectF(cx - 6, cy + CELL + 2, CELL + 12, 18),
               Qt.AlignHCenter | Qt.AlignTop, shapes.STYLES[key])
p.end()
out = sys.argv[3] if len(sys.argv) > 3 else "/tmp/claude-1000/-home-kxinha/5fa8be1b-0248-470d-b3f4-11c96f17981f/scratchpad/styles.png"
img.save(out)
print(out, f"{len(keys)} styles")
