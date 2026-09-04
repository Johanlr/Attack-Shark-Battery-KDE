"""
Janela de preferencias.

O menu da bandeja nao comporta o que o app faz, e escolher animacao sem ver a
animacao e chute. Entao tudo mora aqui, com preview ao vivo: um timer so para a
janela inteira, e cada preview desenha com o mesmo `icons.render` que a bandeja
usa - o que aparece aqui e exatamente o que vai pra bandeja.

Nada de OK/Apply: cada mudanca ja vale, igual as configuracoes do KDE.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QFont,
                           QLinearGradient, QPainter, QPalette, QPen)
from PySide6.QtWidgets import (QAbstractButton, QCheckBox, QColorDialog,
                               QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QScrollArea, QSlider, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

from . import __version__, effects, icons, shapes, sounds
from .config import DEFAULTS, RANGES

# estados que da pra pre-visualizar; "live" usa a leitura de verdade
PREVIEW_STATES = [
    ("live", "Live reading"),
    ("full100", "Full — 100%"),
    ("ok", "Normal — 62%"),
    ("charging", "Charging"),
    ("low", "Low battery"),
    ("critical", "Critical battery"),
    ("fullevent", "Just fully charged"),
    ("asleep", "Mouse asleep"),
    ("absent", "Receiver unplugged"),
]

FPS_CHOICES = [12, 20, 30, 45, 60]


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


class IconPreview(QWidget):
    """Um icone desenhado ao vivo. A fase vem de fora, num timer so."""

    def __init__(self, px: int, frame: Callable, label: str = "",
                 parent=None) -> None:
        super().__init__(parent)
        self.px = px
        self.frame = frame          # () -> (look, level, status, present, fx)
        self.label = label
        self.phase = 0.0
        pad = 18 if label else 6
        self.setFixedSize(px + 8, px + pad)

    def paintEvent(self, _event) -> None:
        look, level, status, present, fx = self.frame()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pm = icons.render(self.px, look, level, status, present, fx, self.phase)
        p.drawPixmap(4, 2, pm)
        if self.label:
            f = QFont()
            f.setPixelSize(10)
            p.setFont(f)
            p.setPen(QPen(self.palette().color(self.foregroundRole())))
            p.drawText(QRectF(0, self.px + 3, self.width(), 14),
                       Qt.AlignHCenter | Qt.AlignTop, self.label)


class StyleTile(QAbstractButton):
    """Botao do grid de estilos, com o icone animando dentro."""

    SIZE = 46

    def __init__(self, key: str, label: str, frame: Callable, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.text_label = label
        self.frame = frame
        self.phase = 0.0
        self.setCheckable(True)
        self.setToolTip(label)
        self.setFixedSize(92, 88)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(92, 88)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        if self.isChecked():
            bg = pal.color(QPalette.Highlight)
            bg.setAlpha(70)
            p.setBrush(bg)
            p.setPen(QPen(pal.color(QPalette.Highlight), 2))
        elif self.underMouse():
            bg = pal.color(QPalette.Text)
            bg.setAlpha(22)
            p.setBrush(bg)
            p.setPen(Qt.NoPen)
        else:
            p.setBrush(Qt.NoBrush)
            p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(1.5, 1.5, self.width() - 3, self.height() - 3), 8, 8)

        look, level, status, present, fx = self.frame(self.key)
        pm = icons.render(self.SIZE, look, level, status, present, fx, self.phase)
        p.drawPixmap(int((self.width() - self.SIZE) / 2), 8, pm)

        f = QFont()
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QPen(pal.color(QPalette.Text)))
        p.drawText(QRectF(3, self.SIZE + 12, self.width() - 6, 30),
                   Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, self.text_label)


class ColorSwatch(QAbstractButton):
    """Bolinha de cor. Os esquemas que nao sao uma cor so tem desenho proprio,
    senao 'level' e 'green' ficariam identicos na tela."""

    def __init__(self, key: str, label: str, color: QColor, kind: str = "fixed",
                 stops=None, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.color = color
        self.kind = kind
        self.stops = stops
        self.setCheckable(True)
        self.setToolTip(label)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        disc = QRectF(3, 3, 20, 20)
        if self.kind == "level":
            for i, col in enumerate(("#ff453a", "#ffb020", "#3ddc84")):
                p.setBrush(QColor(col))
                p.drawPie(disc, int((90 + i * 120) * 16), 120 * 16)
        elif self.kind in ("spectrum", "gradient", "hue"):
            grad = QLinearGradient(disc.topLeft(), disc.bottomRight())
            if self.kind == "spectrum":
                stops = ("#ff453a", "#ffb020", "#3ddc84")
            elif self.kind == "hue":
                stops = [QColor.fromHsvF(h / 6 * 0.85, 0.9, 1.0).name()
                         for h in range(7)]
            else:
                stops = self.stops or ("#888888", "#cccccc")
            for i, colour in enumerate(stops):
                grad.setColorAt(i / (len(stops) - 1), QColor(colour))
            p.setBrush(QBrush(grad))
            p.drawEllipse(disc)
        else:
            p.setBrush(self.color)
            p.drawEllipse(disc)
            if self.kind == "custom":
                p.setPen(QPen(QColor("#ffffff"), 2.0, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(9, 13, 17, 13)
                p.drawLine(13, 9, 13, 17)
        if self.isChecked():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(self.palette().color(QPalette.Highlight), 2.5))
            p.drawEllipse(QRectF(1.4, 1.4, 23.2, 23.2))
        elif self.underMouse():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(self.palette().color(QPalette.Text), 1.2))
            p.drawEllipse(QRectF(1.8, 1.8, 22.4, 22.4))


class Preferences(QDialog):
    """Janela unica de configuracao; aplica na hora."""

    diagnostics_requested = Signal()
    explain_requested = Signal()

    def __init__(self, cfg, reading_source: Callable, tray=None) -> None:
        super().__init__()
        self.cfg = cfg
        self.reading_source = reading_source
        self.tray = tray
        self.phase = 0.0
        self.previews: list = []
        self.tiles: list[StyleTile] = []

        self.setWindowTitle("Attack Shark Mouse Battery")
        self.setMinimumWidth(680)
        self.resize(760, 840)

        root = QVBoxLayout(self)
        root.addWidget(self._build_header())
        root.addWidget(hline())

        tabs = QTabWidget()
        tabs.addTab(self._tab_icon(), "Icon")
        tabs.addTab(self._tab_animation(), "Animation")
        tabs.addTab(self._tab_alerts(), "Alerts")
        tabs.addTab(self._tab_sounds(), "Sounds")
        tabs.addTab(self._tab_general(), "General")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox()
        reset = buttons.addButton("Restore defaults", QDialogButtonBox.ResetRole)
        reset.clicked.connect(self._restore_defaults)
        close = buttons.addButton(QDialogButtonBox.Close)
        close.clicked.connect(self.accept)
        root.addWidget(buttons)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(int(1000 / 20))

    # -- cabecalho com o preview grande ----------------------
    def _build_header(self) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(4, 4, 4, 4)

        self.big = IconPreview(104, lambda: self._frame())
        lay.addWidget(self.big)

        right = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("Preview:"))
        self.state_combo = QComboBox()
        for key, label in PREVIEW_STATES:
            self.state_combo.addItem(label, key)
        self.state_combo.currentIndexChanged.connect(self._refresh_all)
        row.addWidget(self.state_combo, 1)
        right.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Level:"))
        self.level_slider = QSlider(Qt.Horizontal)
        self.level_slider.setRange(0, 100)
        self.level_slider.setValue(62)
        self.level_slider.valueChanged.connect(self._level_moved)
        row2.addWidget(self.level_slider, 1)
        self.level_label = QLabel("62%")
        self.level_label.setMinimumWidth(38)
        row2.addWidget(self.level_label)
        right.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Tray sizes:"))
        for px in (22, 32, 48):
            prev = IconPreview(px, lambda: self._frame(), f"{px}px")
            self.previews.append(prev)
            row3.addWidget(prev)
        row3.addStretch(1)
        right.addLayout(row3)
        right.addStretch(1)
        lay.addLayout(right, 1)
        self.previews.append(self.big)
        return box

    def _level_moved(self, value: int) -> None:
        self.level_label.setText(f"{value}%")
        if self.state_combo.currentData() == "live":
            self.state_combo.setCurrentIndex(2)   # sai do "live" ao mexer
        self._refresh_all()

    # -- estado mostrado no preview --------------------------
    def look(self) -> icons.Look:
        c = self.cfg
        return icons.Look(style=c["style"], scheme=c["scheme"],
                          custom=c["custom_color"], glow=c["glow"],
                          weight=c["weight"], show_number=c["show_number"],
                          low_at=c.low_at, crit_at=c.crit_at,
                          scale=c["icon_scale"])

    def _state(self, key: str | None = None) -> tuple[int, str, bool, str]:
        """(nivel, status, presente, efeito) do preview."""
        c = self.cfg
        key = key or self.state_combo.currentData()
        anim = c["anim"]
        lvl = self.level_slider.value()
        if key == "live":
            r = self.reading_source()
            fx = self.tray.current_effect() if self.tray else "none"
            return r.level, r.status, r.present, fx
        if key == "absent":
            return 0, "absent", False, "none"
        if key == "asleep":
            return lvl, "asleep", True, c["fx_asleep"] if anim else "none"
        if key == "charging":
            return lvl, "charging", True, c["fx_charging"] if anim else "none"
        if key == "low":
            return min(lvl, max(c.crit_at + 1, c.low_at - 5)), "discharging", True, \
                c["fx_low"] if anim else "none"
        if key == "critical":
            return min(lvl, max(1, c.crit_at - 5)), "discharging", True, \
                c["fx_critical"] if anim else "none"
        if key == "fullevent":
            return 100, "charging", True, c["fx_full"] if anim else "none"
        if key == "full100":
            return 100, "discharging", True, c["fx_idle"] if anim else "none"
        return lvl, "discharging", True, c["fx_idle"] if anim else "none"

    def _frame(self, style: str | None = None):
        level, status, present, fx = self._state()
        look = self.look()
        if style is not None:
            look.style = style
        return look, level, status, present, fx

    def _tick(self) -> None:
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self._ticks % 40 == 0 and hasattr(self, "eta_now"):
            self._refresh_eta()
        self.phase = (self.phase + self.cfg["speed"] / 100.0 * 0.022) % 1.0
        for prev in self.previews:
            prev.phase = self.phase
            prev.update()
        for tile in self.tiles:
            tile.phase = self.phase
            tile.update()

    def _refresh_all(self) -> None:
        for prev in self.previews:
            prev.update()
        for tile in self.tiles:
            tile.setChecked(tile.key == self.cfg["style"])
            tile.update()
        if self.tray is not None:
            self.tray.refresh()

    def _set(self, key: str, value) -> None:
        self.cfg[key] = value
        self._refresh_all()

    # -- aba: icone ------------------------------------------
    def _tab_icon(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setSpacing(4)
        for i, (key, label) in enumerate(shapes.STYLES.items()):
            tile = StyleTile(key, label, self._frame)
            tile.setChecked(key == self.cfg["style"])
            tile.clicked.connect(lambda _=False, k=key: self._pick_style(k))
            grid.addWidget(tile, i // 7, i % 7)
            self.tiles.append(tile)
        grid.setRowStretch(grid.rowCount(), 1)
        area.setWidget(holder)
        lay.addWidget(area, 1)

        colours = QGroupBox("Colour")
        cl = QVBoxLayout(colours)
        swatch_grid = QGridLayout()
        swatch_grid.setSpacing(2)
        self.swatches: list[ColorSwatch] = []
        per_row = 14
        for i, (key, (label, kind, fixed)) in enumerate(icons.SCHEMES.items()):
            if kind in ("level", "spectrum", "gradient", "hue"):
                col = QColor("#3ddc84")
            elif kind == "custom":
                col = QColor(self.cfg["custom_color"])
            else:
                col = QColor(fixed)
            sw = ColorSwatch(key, label, col, kind, fixed)
            sw.setChecked(key == self.cfg["scheme"])
            sw.clicked.connect(lambda _=False, k=key: self._pick_scheme(k))
            swatch_grid.addWidget(sw, i // per_row, i % per_row)
            self.swatches.append(sw)
        swatch_grid.setColumnStretch(per_row, 1)
        cl.addLayout(swatch_grid)

        self.scheme_label = QLabel()
        self.scheme_label.setStyleSheet("color: palette(mid);")
        cl.addWidget(self.scheme_label)
        lay.addWidget(colours)

        form = QFormLayout()
        size_row = QHBoxLayout()
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(*RANGES["icon_scale"])
        self.scale_slider.setValue(self.cfg["icon_scale"])
        self.scale_slider.setToolTip(
            "How much of the tray cell the drawing fills. The panel decides the "
            "cell; this decides the icon inside it.")
        self.scale_label = QLabel(f"{self.cfg['icon_scale']}%")
        self.scale_label.setMinimumWidth(40)
        self.scale_slider.valueChanged.connect(self._scale_changed)
        size_row.addWidget(self.scale_slider, 1)
        size_row.addWidget(self.scale_label)
        form.addRow("Icon size", size_row)

        self.glow_slider = QSlider(Qt.Horizontal)
        self.glow_slider.setRange(*RANGES["glow"])
        self.glow_slider.setValue(self.cfg["glow"])
        self.glow_slider.valueChanged.connect(lambda v: self._set("glow", v))
        form.addRow("Glow", self.glow_slider)

        self.weight_combo = QComboBox()
        for key in ("thin", "normal", "bold"):
            self.weight_combo.addItem(key.capitalize(), key)
        self.weight_combo.setCurrentIndex(
            list(shapes.WEIGHTS).index(self.cfg["weight"]))
        self.weight_combo.currentIndexChanged.connect(
            lambda i: self._set("weight", self.weight_combo.itemData(i)))
        form.addRow("Line weight", self.weight_combo)

        self.number_check = QCheckBox("Show the percentage inside the icon "
                                      "(styles that have room for it)")
        self.number_check.setChecked(self.cfg["show_number"])
        self.number_check.toggled.connect(lambda v: self._set("show_number", v))
        form.addRow("", self.number_check)
        lay.addLayout(form)
        self._sync_scheme_label()
        return page

    def _scale_changed(self, value: int) -> None:
        self.scale_label.setText(f"{value}%")
        self._set("icon_scale", value)

    def _pick_style(self, key: str) -> None:
        self._set("style", key)

    def _pick_scheme(self, key: str) -> None:
        if key == "custom":
            start = QColor(self.cfg["custom_color"])
            chosen = QColorDialog.getColor(start, self, "Icon colour")
            if not chosen.isValid():
                self._sync_swatches()
                return
            self.cfg["custom_color"] = chosen.name()
            for sw in self.swatches:
                if sw.key == "custom":
                    sw.color = chosen
        self._set("scheme", key)
        self._sync_swatches()
        self._sync_scheme_label()

    def _sync_swatches(self) -> None:
        for sw in self.swatches:
            sw.setChecked(sw.key == self.cfg["scheme"])
            sw.update()

    def _sync_scheme_label(self) -> None:
        label = icons.SCHEMES.get(self.cfg["scheme"], ("", "", ""))[0]
        extra = ""
        if self.cfg["scheme"] == "custom":
            extra = f"  ({self.cfg['custom_color']})"
        self.scheme_label.setText(label + extra)

    # -- aba: animacao ---------------------------------------
    def _tab_animation(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        self.anim_check = QCheckBox("Animate the tray icon")
        self.anim_check.setChecked(self.cfg["anim"])
        self.anim_check.toggled.connect(lambda v: self._set("anim", v))
        lay.addWidget(self.anim_check)

        note = QLabel("The animation timer only runs while there is something "
                      "to animate — it stops on its own otherwise.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        lay.addWidget(note)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        rows = [
            ("fx_charging", "charging", "Charging", "charging"),
            ("fx_full", "full", "Fully charged", "fullevent"),
            ("fx_low", "low", "Low battery", "low"),
            ("fx_critical", "critical", "Critical battery", "critical"),
            ("fx_idle", "idle", "Normal (idle)", "ok"),
            ("fx_asleep", "idle", "Mouse asleep", "asleep"),
        ]
        for r, (key, event, title, state) in enumerate(rows):
            grid.addWidget(QLabel(title), r, 0)
            combo = QComboBox()
            for fx_key, fx_label in effects.options(event):
                combo.addItem(fx_label, fx_key)
            idx = max(0, combo.findData(self.cfg[key]))
            combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(
                lambda i, k=key, cb=combo: self._set(k, cb.itemData(i)))
            grid.addWidget(combo, r, 1)

            prev = IconPreview(44, lambda k=key, s=state: self._event_frame(k, s))
            self.previews.append(prev)
            grid.addWidget(prev, r, 2)

            btn = QPushButton("Preview")
            btn.setToolTip("Show this state in the big preview above")
            btn.clicked.connect(lambda _=False, s=state: self._jump_state(s))
            grid.addWidget(btn, r, 3)
        lay.addLayout(grid)
        lay.addWidget(hline())

        form = QFormLayout()
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(*RANGES["speed"])
        self.speed_slider.setValue(self.cfg["speed"])
        self.speed_label = QLabel(f"{self.cfg['speed']}%")
        self.speed_slider.valueChanged.connect(self._speed_changed)
        speed_row = QHBoxLayout()
        speed_row.addWidget(self.speed_slider, 1)
        speed_row.addWidget(self.speed_label)
        form.addRow("Speed", speed_row)

        self.fps_combo = QComboBox()
        for fps in FPS_CHOICES:
            self.fps_combo.addItem(f"{fps} fps", fps)
        self.fps_combo.setCurrentIndex(
            max(0, self.fps_combo.findData(self.cfg["fps"])))
        self.fps_combo.currentIndexChanged.connect(
            lambda i: self._set("fps", self.fps_combo.itemData(i)))
        form.addRow("Frame rate", self.fps_combo)

        self.full_spin = QSpinBox()
        self.full_spin.setRange(*RANGES["full_seconds"])
        self.full_spin.setSuffix(" s")
        self.full_spin.setSpecialValueText("keep animating")
        self.full_spin.setValue(self.cfg["full_seconds"])
        self.full_spin.valueChanged.connect(lambda v: self._set("full_seconds", v))
        form.addRow("Full-charge animation lasts", self.full_spin)
        lay.addLayout(form)
        lay.addStretch(1)
        return page

    def _speed_changed(self, value: int) -> None:
        self.speed_label.setText(f"{value}%")
        self._set("speed", value)

    def _event_frame(self, cfg_key: str, state: str):
        """Preview de uma linha: o efeito daquela linha, no estado daquela linha."""
        level, status, present, _fx = self._state(state)
        fx = self.cfg[cfg_key] if self.cfg["anim"] else "none"
        return self.look(), level, status, present, fx

    def _jump_state(self, state: str) -> None:
        idx = self.state_combo.findData(state)
        if idx >= 0:
            self.state_combo.setCurrentIndex(idx)

    # -- aba: alertas ----------------------------------------
    def _tab_alerts(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        thresholds = QGroupBox("Thresholds")
        form = QFormLayout(thresholds)
        self.low_spin = QSpinBox()
        self.low_spin.setRange(*RANGES["low_at"])
        self.low_spin.setSuffix(" %")
        self.low_spin.setValue(self.cfg["low_at"])
        self.low_spin.valueChanged.connect(self._low_changed)
        form.addRow("Low battery at or below", self.low_spin)

        self.crit_spin = QSpinBox()
        self.crit_spin.setRange(*RANGES["crit_at"])
        self.crit_spin.setSuffix(" %")
        self.crit_spin.setValue(self.cfg["crit_at"])
        self.crit_spin.valueChanged.connect(self._crit_changed)
        form.addRow("Critical battery at or below", self.crit_spin)

        self.full_at_spin = QSpinBox()
        self.full_at_spin.setRange(*RANGES["full_at"])
        self.full_at_spin.setSuffix(" %")
        self.full_at_spin.setValue(self.cfg["full_at"])
        self.full_at_spin.valueChanged.connect(lambda v: self._set("full_at", v))
        form.addRow("Count as fully charged at", self.full_at_spin)

        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(*RANGES["repeat_min"])
        self.repeat_spin.setSuffix(" min")
        self.repeat_spin.setSpecialValueText("warn once only")
        self.repeat_spin.setValue(self.cfg["repeat_min"])
        self.repeat_spin.valueChanged.connect(lambda v: self._set("repeat_min", v))
        form.addRow("Repeat the warning every", self.repeat_spin)
        lay.addWidget(thresholds)

        notes = QGroupBox("Desktop notifications")
        nl = QVBoxLayout(notes)
        self.notify_boxes = {}
        for key, label in (("notify", "Show notifications at all"),
                           ("notify_low", "Low battery"),
                           ("notify_crit", "Critical battery"),
                           ("notify_full", "Fully charged"),
                           ("notify_charge", "Charger plugged in / unplugged"),
                           ("notify_conn", "Mouse connected / gone")):
            box = QCheckBox(label)
            box.setChecked(self.cfg[key])
            box.toggled.connect(lambda v, k=key: self._notify_changed(k, v))
            if key != "notify":
                box.setStyleSheet("margin-left: 18px;")
            nl.addWidget(box)
            self.notify_boxes[key] = box

        timeout = QHBoxLayout()
        timeout.addWidget(QLabel("Notification stays for"))
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(RANGES["notify_ms"][0] // 1000,
                                   RANGES["notify_ms"][1] // 1000)
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.setValue(self.cfg["notify_ms"] // 1000)
        self.timeout_spin.valueChanged.connect(
            lambda v: self._set("notify_ms", v * 1000))
        timeout.addWidget(self.timeout_spin)
        timeout.addStretch(1)
        test = QPushButton("Test notification")
        test.clicked.connect(self._test_notification)
        timeout.addWidget(test)
        nl.addLayout(timeout)
        lay.addWidget(notes)

        why = QLabel(
            "A sleeping mouse never raises a warning. When it stops reporting, "
            "the last level it sent is still the truth — treating silence as an "
            "empty battery would cry wolf every time you walk away.")
        why.setWordWrap(True)
        why.setStyleSheet("color: palette(mid);")
        lay.addWidget(why)
        lay.addStretch(1)
        self._sync_notify_enabled()
        return page

    def _low_changed(self, value: int) -> None:
        self._set("low_at", value)
        if self.cfg["crit_at"] >= value:
            self.crit_spin.setValue(max(1, value - 5))

    def _crit_changed(self, value: int) -> None:
        if value >= self.cfg["low_at"]:
            value = max(1, self.cfg["low_at"] - 1)
            self.crit_spin.setValue(value)
            return
        self._set("crit_at", value)

    def _notify_changed(self, key: str, value: bool) -> None:
        self._set(key, value)
        self._sync_notify_enabled()

    def _sync_notify_enabled(self) -> None:
        on = self.cfg["notify"]
        for key, box in self.notify_boxes.items():
            if key != "notify":
                box.setEnabled(on)

    def _test_notification(self) -> None:
        if self.tray is not None:
            self.tray.notify("Attack Shark Mouse Battery",
                             "This is what a warning looks like.", force=True)

    # -- aba: sons -------------------------------------------
    def _tab_sounds(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        grid = QGridLayout()
        grid.setColumnStretch(2, 1)
        self.sound_combos = {}
        rows = [
            ("snd_crit", "snd_crit_on", "Critical battery"),
            ("snd_low", "snd_low_on", "Low battery"),
            ("snd_full", "snd_full_on", "Fully charged"),
            ("snd_charge", "snd_charge_on", "Charger plugged in"),
            ("snd_conn", "snd_conn_on", "Mouse back on the air"),
            ("snd_disc", "snd_disc_on", "Mouse gone"),
        ]
        for r, (key, on_key, title) in enumerate(rows):
            check = QCheckBox(title)
            check.setChecked(self.cfg[on_key])
            check.setToolTip("Play a sound for this event")
            check.toggled.connect(lambda v, k=on_key: self.cfg.__setitem__(k, v))
            grid.addWidget(check, r, 0, 1, 2)

            combo = QComboBox()
            combo.addItem(sounds.label_for(DEFAULTS[key]), DEFAULTS[key])
            for label, path in sounds.catalog():
                combo.addItem(label, path)
            combo.addItem("Custom file…", "@browse")
            self._select_sound(combo, self.cfg[key])
            combo.activated.connect(
                lambda i, k=key, cb=combo: self._sound_chosen(k, cb, i))
            grid.addWidget(combo, r, 2)
            self.sound_combos[key] = combo

            play = QPushButton("▶")
            play.setFixedWidth(34)
            play.setToolTip("Play it now")
            play.clicked.connect(lambda _=False, k=key: self._test_sound(k))
            grid.addWidget(play, r, 3)
        lay.addLayout(grid)
        lay.addWidget(hline())

        row = QHBoxLayout()
        row.addWidget(QLabel("Volume"))
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(*RANGES["snd_volume"])
        self.vol_slider.setValue(self.cfg["snd_volume"])
        self.vol_label = QLabel(f"{self.cfg['snd_volume']}%")
        self.vol_slider.valueChanged.connect(self._volume_changed)
        row.addWidget(self.vol_slider, 1)
        row.addWidget(self.vol_label)
        lay.addLayout(row)

        note = QLabel("Sounds come from the sound themes already installed on "
                      "this machine; nothing is bundled or downloaded. "
                      '"Custom file…" takes any audio file you point at.')
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        lay.addWidget(note)
        lay.addStretch(1)
        return page

    @staticmethod
    def _select_sound(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx < 0:
            combo.insertItem(1, sounds.label_for(value), value)
            idx = 1
        combo.setCurrentIndex(idx)

    def _sound_chosen(self, key: str, combo: QComboBox, index: int) -> None:
        value = combo.itemData(index)
        if value == "@browse":
            path, _ = QFileDialog.getOpenFileName(
                self, "Pick a sound file", str(sounds.THEME_DIRS[0]),
                "Audio (*.oga *.ogg *.wav *.flac *.opus *.mp3);;All files (*)")
            if not path:
                self._select_sound(combo, self.cfg[key])
                return
            value = path
            self._select_sound(combo, value)
        self.cfg[key] = value
        self._test_sound(key)

    def _test_sound(self, key: str) -> None:
        if self.tray is not None:
            self.tray.play_sound(self.cfg[key], force=True)

    def _volume_changed(self, value: int) -> None:
        self.vol_label.setText(f"{value}%")
        self.cfg["snd_volume"] = value
        if self.tray is not None:
            self.tray.player.set_volume(value)

    # -- aba: geral ------------------------------------------
    def _tab_general(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        form = QFormLayout()
        self.boot_check = QCheckBox("Start automatically when I log in")
        self.boot_check.setChecked(self.tray.autostart_enabled()
                                   if self.tray else False)
        self.boot_check.toggled.connect(self._autostart)
        form.addRow("", self.boot_check)
        lay.addLayout(form)

        note = QLabel("There is no polling interval to set: the receiver pushes "
                      "a frame every couple of seconds and the app is woken by "
                      "it, so it costs nothing while the mouse is quiet.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        lay.addWidget(note)

        est = QGroupBox("Time remaining")
        el = QVBoxLayout(est)
        self.eta_check = QCheckBox("Show how much time is left")
        self.eta_check.setChecked(self.cfg["eta"])
        self.eta_check.toggled.connect(lambda v: self._set("eta", v))
        el.addWidget(self.eta_check)

        self.hist_check = QCheckBox(
            "Use the pace learned in earlier sessions until this one has "
            "measured its own")
        self.hist_check.setChecked(self.cfg["eta_history"])
        self.hist_check.toggled.connect(lambda v: self._set("eta_history", v))
        el.addWidget(self.hist_check)

        self.eta_now = QLabel()
        self.eta_now.setWordWrap(True)
        el.addWidget(self.eta_now)

        self.eta_detail = QLabel()
        self.eta_detail.setWordWrap(True)
        self.eta_detail.setStyleSheet("color: palette(mid);")
        el.addWidget(self.eta_detail)

        how = QLabel(
            "The mouse reports a percentage and nothing else, so there is no "
            "time to read anywhere. It is measured here, from how long each "
            "single percentage point actually lasts — the median of the recent "
            "steps, which survives one odd step. With too little measured, the "
            "app says so instead of guessing.")
        how.setWordWrap(True)
        how.setStyleSheet("color: palette(mid);")
        el.addWidget(how)

        forget = QPushButton("Forget what was measured")
        forget.clicked.connect(self._forget_eta)
        row0 = QHBoxLayout()
        row0.addWidget(forget)
        row0.addStretch(1)
        el.addLayout(row0)
        lay.addWidget(est)
        self._refresh_eta()

        about = QGroupBox("About")
        al = QVBoxLayout(about)
        al.addWidget(QLabel(f"Attack Shark Mouse Battery {__version__}"))
        blurb = QLabel(
            "Reads a battery that no Linux driver exposes, straight off the "
            "receiver's vendor channel. Nothing here touches the network.")
        blurb.setWordWrap(True)
        blurb.setStyleSheet("color: palette(mid);")
        al.addWidget(blurb)
        row2 = QHBoxLayout()
        why = QPushButton("How is this read?")
        why.clicked.connect(self.explain_requested.emit)
        row2.addWidget(why)
        diag = QPushButton("Copy diagnostics")
        diag.clicked.connect(self.diagnostics_requested.emit)
        row2.addWidget(diag)
        row2.addStretch(1)
        al.addLayout(row2)
        lay.addWidget(about)
        lay.addStretch(1)
        return page

    def _refresh_eta(self) -> None:
        if self.tray is None:
            self.eta_now.setText("—")
            self.eta_detail.setText("")
            return
        e = self.tray.eta
        if e.ok:
            tail = "  (from earlier sessions)" if e.from_history else ""
            self.eta_now.setText(f"<b>{e.text.capitalize()}</b>{tail}")
        else:
            self.eta_now.setText(f"No number yet — {e.pending}.")
        self.eta_now.setTextFormat(Qt.RichText)
        self.eta_detail.setText(self.tray.estimator.summary())

    def _forget_eta(self) -> None:
        if self.tray is None:
            return
        answer = QMessageBox.question(
            self, "Forget measurements",
            "Throw away every measured step, for both draining and charging?\n\n"
            "The app will go back to saying it has no number until it has "
            "measured enough again — about half an hour of use for the first "
            "drain step.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.tray.estimator.forget()
            self.tray.refresh()
            self._refresh_eta()

    def _autostart(self, value: bool) -> None:
        if self.tray is None:
            return
        ok = self.tray.set_autostart(value)
        self.boot_check.blockSignals(True)
        self.boot_check.setChecked(ok)
        self.boot_check.blockSignals(False)
        if ok != value:
            QMessageBox.information(
                self, "Autostart",
                "Could not change autostart — neither the systemd user unit nor "
                "the autostart folder could be written.")

    # -- restaurar -------------------------------------------
    def _restore_defaults(self) -> None:
        answer = QMessageBox.question(
            self, "Restore defaults",
            "Reset every setting — icon, animation, thresholds and sounds — "
            "back to the defaults?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.cfg.reset()
        if self.tray is not None:
            self.tray.refresh()
        QMessageBox.information(
            self, "Restore defaults",
            "Done. Close and reopen this window to see the controls reset.")
        self._refresh_all()

    def closeEvent(self, event) -> None:
        self.timer.stop()
        super().closeEvent(event)
