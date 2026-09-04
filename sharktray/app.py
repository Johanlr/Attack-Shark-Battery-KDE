"""Bandeja que monitora a bateria do mouse sem fio Attack Shark."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import __version__, effects, eta, icons, prefs, shapes, sounds
from .config import Config
from .mouse import MouseMonitor, Reading

APP_NAME = "Attack Shark Mouse"
UNIT = "attackshark-tray.service"
DESKTOP_ID = "attackshark-tray"
AUTOSTART_FILE = Path.home() / ".config/autostart" / f"{DESKTOP_ID}.desktop"

# rede de seguranca: o app e movido a evento, mas o estado "dormindo" e o ETA
# mudam com o RELOGIO, nao com um quadro chegando - sem isso o icone so
# perceberia que o mouse sumiu quando ele voltasse
TICK_MS = 5000


class Tray(QSystemTrayIcon):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = Config()
        self.monitor = MouseMonitor(self)
        self.estimator = eta.Estimator()
        self.player = sounds.Player(self.cfg["snd_volume"])
        self.reading = Reading()
        self.eta = eta.Estimate()
        self.phase = 0.0
        self.dialog: prefs.Preferences | None = None

        # memoria dos avisos, pra nao repetir a cada leitura
        self._warned_at_level: int | None = None
        self._warned_time = 0.0
        self._was_present: bool | None = None
        self._was_status = ""
        self._full_since = 0.0

        self._build_menu()
        self.activated.connect(self._on_activated)
        self.messageClicked.connect(self.open_preferences)
        self.cfg.changed.connect(self._on_config_changed)
        self.monitor.changed.connect(self.refresh)

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.refresh)
        self.tick_timer.start(TICK_MS)

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._tick)

        self.refresh()
        self.show()

    # -- aparencia -------------------------------------------
    def look(self) -> icons.Look:
        c = self.cfg
        return icons.Look(style=c["style"], scheme=c["scheme"],
                          custom=c["custom_color"], glow=c["glow"],
                          weight=c["weight"], show_number=c["show_number"],
                          low_at=c.low_at, crit_at=c.crit_at,
                          scale=c["icon_scale"])

    def current_effect(self) -> str:
        """Qual animacao vale agora. A ordem aqui e a prioridade dos estados."""
        c = self.cfg
        r = self.reading
        if not c["anim"] or not r.present:
            return "none"
        if r.status == "asleep":
            return c["fx_asleep"]
        if self.is_full(r):
            limit = c["full_seconds"]
            if limit and self._full_since and time.time() - self._full_since > limit:
                return c["fx_idle"]
            return c["fx_full"]
        if r.charging:
            return c["fx_charging"]
        if r.level <= c.crit_at:
            return c["fx_critical"]
        if r.level <= c.low_at:
            return c["fx_low"]
        return c["fx_idle"]

    def is_full(self, r: Reading) -> bool:
        return r.present and r.level >= self.cfg["full_at"]

    # -- menu ------------------------------------------------
    def _build_menu(self) -> None:
        self.menu = QMenu()

        self.header = QAction("…", self.menu)
        self.header.setEnabled(False)
        self.menu.addAction(self.header)
        self.subheader = QAction("", self.menu)
        self.subheader.setEnabled(False)
        self.menu.addAction(self.subheader)
        self.eta_line = QAction("", self.menu)
        self.eta_line.setEnabled(False)
        self.menu.addAction(self.eta_line)
        self.menu.addSeparator()

        act_prefs = QAction("Preferences…", self.menu)
        act_prefs.triggered.connect(self.open_preferences)
        self.menu.addAction(act_prefs)

        icon_menu = self.menu.addMenu("Icon")
        self.icon_group = QActionGroup(icon_menu)
        self.icon_group.setExclusive(True)
        for key, label in shapes.STYLES.items():
            act = QAction(label, icon_menu, checkable=True)
            act.setChecked(key == self.cfg["style"])
            act.setData(key)
            act.triggered.connect(lambda _=False, k=key: self._set("style", k))
            self.icon_group.addAction(act)
            icon_menu.addAction(act)

        colour_menu = self.menu.addMenu("Colour")
        self.colour_group = QActionGroup(colour_menu)
        self.colour_group.setExclusive(True)
        for key, (label, _kind, _c) in icons.SCHEMES.items():
            if key == "custom":
                continue
            act = QAction(label, colour_menu, checkable=True)
            act.setChecked(key == self.cfg["scheme"])
            act.setData(key)
            act.triggered.connect(lambda _=False, k=key: self._set("scheme", k))
            self.colour_group.addAction(act)
            colour_menu.addAction(act)

        self.act_anim = QAction("Animation", self.menu, checkable=True)
        self.act_anim.setChecked(self.cfg["anim"])
        self.act_anim.triggered.connect(lambda v: self._set("anim", v))
        self.menu.addAction(self.act_anim)

        self.act_notify = QAction("Notifications", self.menu, checkable=True)
        self.act_notify.setChecked(self.cfg["notify"])
        self.act_notify.triggered.connect(lambda v: self._set("notify", v))
        self.menu.addAction(self.act_notify)

        self.menu.addSeparator()
        act_why = QAction("How is this read?", self.menu)
        act_why.triggered.connect(self.explain)
        self.menu.addAction(act_why)
        act_diag = QAction("Copy diagnostics", self.menu)
        act_diag.triggered.connect(self.copy_diagnostics)
        self.menu.addAction(act_diag)

        self.menu.addSeparator()
        self.act_boot = QAction("Start at login", self.menu, checkable=True)
        self.act_boot.setChecked(self.autostart_enabled())
        self.act_boot.triggered.connect(self._toggle_autostart)
        self.menu.addAction(self.act_boot)

        act_quit = QAction("Quit", self.menu)
        act_quit.triggered.connect(QApplication.quit)
        self.menu.addAction(act_quit)

        self.setContextMenu(self.menu)

    def _sync_menu(self) -> None:
        for act in self.icon_group.actions():
            act.setChecked(act.data() == self.cfg["style"])
        for act in self.colour_group.actions():
            act.setChecked(act.data() == self.cfg["scheme"])
        self.act_anim.setChecked(self.cfg["anim"])
        self.act_notify.setChecked(self.cfg["notify"])

    def _set(self, key: str, value) -> None:
        self.cfg[key] = value

    def _on_config_changed(self, key: str) -> None:
        if key in ("snd_volume", "*"):
            self.player.set_volume(self.cfg["snd_volume"])
        self._sync_menu()
        self.refresh()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.open_preferences()
            return
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.MiddleClick):
            self.refresh()
            geo = self.geometry()
            self.menu.popup(geo.bottomLeft() if geo.isValid()
                            else QGuiApplication.primaryScreen()
                            .availableGeometry().center())

    # -- ciclo -----------------------------------------------
    def refresh(self) -> None:
        self.reading = self.monitor.read()
        self.estimator.update(self.reading)
        # calculada uma vez por leitura, nao a cada quadro da animacao
        self.eta = self.estimator.estimate(self.reading, self.cfg["eta_history"])
        self._track_transitions()
        self._update_visual()
        self._maybe_alert()

        fx = self.current_effect()
        want = self.cfg["anim"] and not effects.is_static(fx)
        interval = max(8, int(1000 / max(1, self.cfg["fps"])))
        if want:
            if not self.anim_timer.isActive() or self.anim_timer.interval() != interval:
                self.anim_timer.start(interval)
        elif self.anim_timer.isActive():
            self.anim_timer.stop()
            self.phase = 0.0
            self._update_visual()

    def _tick(self) -> None:
        # a fase avanca por segundo, nao por quadro: mudar o fps muda a fluidez,
        # nao a velocidade da animacao
        step = self.cfg["speed"] / 100.0 * 0.9 / max(1, self.cfg["fps"])
        self.phase = (self.phase + step) % 1.0
        self._update_visual()
        if self.cfg["full_seconds"] and self._full_since:
            if effects.is_static(self.current_effect()):
                self.refresh()

    def _update_visual(self) -> None:
        r = self.reading
        fx = self.current_effect()
        self.setIcon(icons.make_icon(self.look(), r.level, r.status, r.present,
                                     fx, self.phase,
                                     animating=self.anim_timer.isActive()))
        if r.present:
            self.header.setText(f"{APP_NAME} — {r.label}")
            state = "fully charged" if (self.is_full(r) and not r.charging) \
                else r.status_en
            self.subheader.setText(state)
            tip = [APP_NAME, f"Battery: {r.label}", f"State: {state}"]
            if r.status == "asleep":
                tip.append(f"Last frame {int(r.age)}s ago — the level shown is "
                           "the last one the mouse reported")
            self._update_eta_line(tip)
            self.setToolTip("\n".join(tip))
        else:
            self.header.setText("Mouse not reporting")
            self.subheader.setText(r.error or "receiver unplugged")
            self.eta_line.setVisible(False)
            self.setToolTip(r.error or "Receiver unplugged")

    def _update_eta_line(self, tip: list[str]) -> None:
        """Linha do tempo restante - some quando o usuario desliga a opcao."""
        if not self.cfg["eta"]:
            self.eta_line.setVisible(False)
            return
        self.eta_line.setVisible(True)
        e = self.eta
        if e.ok:
            text = e.text.capitalize()
            self.eta_line.setText(text)
            tip.append(text)
            if e.rate:
                source = ("learned in earlier sessions" if e.from_history
                          else f"median of {e.steps} recent step(s)")
                kind = "charge" if e.kind == "full" else "drain"
                tip.append(f"Measured {kind}: {e.rate:.2f} %/h — {source}")
        else:
            self.eta_line.setText("Time left: measuring…")
            self.eta_line.setToolTip(e.pending)
            if e.pending:
                tip.append(f"Time left: {e.pending}")

    # -- avisos e sons ---------------------------------------
    def _track_transitions(self) -> None:
        """Marca quando entrou em 'cheio', pra animacao de carga expirar."""
        if self.is_full(self.reading):
            if not self._full_since:
                self._full_since = time.time()
        else:
            self._full_since = 0.0

    def _maybe_alert(self) -> None:
        c = self.cfg
        r = self.reading
        now = time.time()

        if self._was_present is not None and r.present != self._was_present:
            if r.present:
                self.notify(APP_NAME, "Mouse back on the air", "conn")
                self.play_sound(c["snd_conn"] if c["snd_conn_on"] else "")
            else:
                self.notify(APP_NAME, "Mouse not reporting", "conn")
                self.play_sound(c["snd_disc"] if c["snd_disc_on"] else "")
        self._was_present = r.present

        if not r.present:
            self._was_status = ""
            self._warned_at_level = None
            return

        if r.status == "charging" and self._was_status not in ("charging", ""):
            self.notify(f"{APP_NAME} — {r.level}%", "Charging.", "charge")
            self.play_sound(c["snd_charge"] if c["snd_charge_on"] else "")
        elif (self._was_status == "charging" and r.status == "discharging"
              and not self.is_full(r)):
            self.notify(f"{APP_NAME} — {r.level}%", "Back on battery.", "charge")

        was_full = self._was_status == "full"
        self._was_status = "full" if self.is_full(r) else r.status

        if self.is_full(r):
            if not was_full:
                self.notify(f"{APP_NAME} — {r.level}%",
                            "Mouse fully charged.", "full")
                self.play_sound(c["snd_full"] if c["snd_full_on"] else "")
            self._warned_at_level = None
            return

        # dormindo ou carregando nao dispara alarme de bateria: no primeiro caso
        # o numero e antigo, no segundo o cabo ja esta resolvendo o problema
        if r.status != "discharging":
            self._warned_at_level = None
            return

        critical = r.level <= c.crit_at
        low = r.level <= c.low_at
        if not low:
            self._warned_at_level = None
            return

        level_band = c.crit_at if critical else c.low_at
        repeat = c["repeat_min"] * 60
        due = (self._warned_at_level is None
               or level_band < self._warned_at_level
               or (repeat and now - self._warned_time >= repeat))
        if not due:
            return

        self._warned_at_level = level_band
        self._warned_time = now
        left = (f" About {self.eta.text}."
                if c["eta"] and self.eta.ok and self.eta.kind == "empty" else "")
        if critical:
            self.notify(f"{APP_NAME} — {r.level}%",
                        "Battery critical, charge it now." + left, "crit")
            self.play_sound(c["snd_crit"] if c["snd_crit_on"] else "")
        else:
            self.notify(f"{APP_NAME} — {r.level}%", "Battery low." + left, "low")
            self.play_sound(c["snd_low"] if c["snd_low_on"] else "")

    def notify(self, title: str, body: str, kind: str = "",
               force: bool = False) -> None:
        c = self.cfg
        if not force:
            if not c["notify"]:
                return
            gate = {"low": "notify_low", "crit": "notify_crit",
                    "full": "notify_full", "conn": "notify_conn",
                    "charge": "notify_charge"}.get(kind)
            if gate and not c[gate]:
                return
        r = self.reading
        icon = icons.make_icon(self.look(), r.level, r.status, r.present,
                               "none", 0.0)
        self.showMessage(title, body, icon, c["notify_ms"])

    def play_sound(self, value: str, force: bool = False) -> None:
        if not value and not force:
            return
        self.player.play(value)

    # -- autostart -------------------------------------------
    #
    # Duas vias, porque as duas instalacoes existem: por pacote vem a unit do
    # systemd; rodando da arvore de fontes nao vem nada, e ai o .desktop em
    # ~/.config/autostart e o que sobra. A unit tem preferencia quando existe.
    @staticmethod
    def _unit_state() -> str | None:
        try:
            out = subprocess.run(["systemctl", "--user", "is-enabled", UNIT],
                                 capture_output=True, text=True, timeout=4)
        except (OSError, subprocess.SubprocessError):
            return None
        state = out.stdout.strip()
        return state if state in ("enabled", "disabled", "static",
                                  "enabled-runtime") else None

    def autostart_enabled(self) -> bool:
        state = self._unit_state()
        if state is not None:
            return state in ("enabled", "enabled-runtime")
        return AUTOSTART_FILE.is_file()

    def set_autostart(self, on: bool) -> bool:
        """Devolve o estado real depois de tentar mudar."""
        if self._unit_state() is not None:
            try:
                subprocess.run(["systemctl", "--user",
                                "enable" if on else "disable", UNIT],
                               capture_output=True, timeout=8)
            except (OSError, subprocess.SubprocessError):
                pass
            return self.autostart_enabled()

        try:
            if on:
                AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
                AUTOSTART_FILE.write_text(
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    f"Name={APP_NAME} Battery\n"
                    f"Exec={self._launch_command()}\n"
                    "Terminal=false\n"
                    "X-GNOME-Autostart-enabled=true\n")
            elif AUTOSTART_FILE.exists():
                AUTOSTART_FILE.unlink()
        except OSError:
            pass
        return self.autostart_enabled()

    @staticmethod
    def _launch_command() -> str:
        """Como reexecutar este app.

        Preferir o lancador instalado no PATH; rodando da arvore de fontes ele
        nao existe, e ai o Exec precisa carregar o diretorio do projeto - um
        `python3 -m sharktray` solto so funcionaria se o cwd fosse o certo, o
        que nao vale para uma entrada de autostart."""
        for base in os.environ.get("PATH", "").split(os.pathsep):
            if base and os.access(Path(base) / "attackshark-tray", os.X_OK):
                return "attackshark-tray"
        root = Path(__file__).resolve().parent.parent
        return f"python3 -c \'import sys; sys.path.insert(0, \"{root}\"); " \
               f"import sharktray.app as a; sys.exit(a.main())\'"

    def _toggle_autostart(self, value: bool) -> None:
        ok = self.set_autostart(value)
        self.act_boot.setChecked(ok)
        if ok != value:
            self.notify(APP_NAME, "Could not change autostart.", force=True)

    # -- acoes -----------------------------------------------
    def open_preferences(self) -> None:
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        self.dialog = prefs.Preferences(self.cfg, lambda: self.reading, self)
        self.dialog.diagnostics_requested.connect(self.copy_diagnostics)
        self.dialog.explain_requested.connect(self.explain)
        self.dialog.finished.connect(self._dialog_closed)
        self.dialog.show()

    def _dialog_closed(self) -> None:
        self.dialog = None
        self.refresh()

    def copy_diagnostics(self) -> None:
        text = (self.monitor.diagnostics() + "\n"
                + self.estimator.summary() + "\n"
                + f"estimate       {self.eta.text or self.eta.pending}")
        QGuiApplication.clipboard().setText(text)
        self.notify(APP_NAME, "Diagnostics copied to the clipboard.", force=True)

    def explain(self) -> None:
        box = QMessageBox()
        box.setWindowTitle("How is this read?")
        box.setIcon(QMessageBox.Information)
        box.setText("This mouse does not report its battery over standard HID.")
        box.setInformativeText(
            "Nothing shows up in /sys/class/power_supply, so upower, the panel "
            "battery widget and tools like wireless-hid have nothing to read — "
            "and no driver fills that gap.\n\n"
            "What does exist is a vendor channel on the receiver, which pushes "
            "a five byte frame every couple of seconds:\n\n"
            "        03 E5 40 ST NN\n\n"
            "NN is the battery percentage and ST is the state: 01 on battery, "
            "03 charging. That was established by watching the value saturate "
            "at exactly 100, fall on its own about one point every half hour, "
            "rise while a cable was in, and stay put under heavy movement — "
            "which rules out voltage and signal strength.\n\n"
            "Two traps this app handles for you: the receiver slips in "
            "03 E5 01 00 00 frames when the link blinks, which would read as "
            "0%; and plugging the cable into the PC takes the mouse off the "
            "air entirely, which is silence, not an empty battery.\n\n"
            "Reading it without root comes from a udev rule that opens only "
            "that vendor interface — never the keyboard and mouse ones, which "
            "would hand any app your keystrokes.")
        box.exec()


def main() -> int:
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(DESKTOP_ID)
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("system tray unavailable", flush=True)
        return 1

    tray = Tray()  # noqa: F841 - precisa continuar referenciado
    return app.exec()
