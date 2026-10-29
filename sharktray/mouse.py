"""
Leitura da bateria do mouse sem fio Attack Shark (dongle Xenta 1d57:fa60).

Nada disso vem de driver: o mouse NAO expoe bateria por HID padrao, entao
`/sys/class/power_supply` esta vazio e upower/waybar/wireless-hid nao veem
nada. O que existe e um canal proprietario na interface vendor do dongle
(bInterfaceNumber 02), que emite a cada ~2s:

    03 E5 40 ST NN
             |  +-- nivel da bateria, 0..100 (%)
             +----- estado: 01 = na bateria, 03 = carregando

Como isso foi estabelecido, para quem for mexer aqui depois:

  * o valor satura exatamente em 0x64 = 100, o que fixa a escala em porcento;
  * cai sozinho, ~1 ponto a cada 30 min de uso, sem religar o mouse;
  * sobe durante a carga, e a flag ST casou com tres janelas de cabo medidas;
  * nao muda com movimento intenso, entao nao e tensao instantanea nem RSSI.

Duas armadilhas que valem o codigo que gastam:

  1. O dongle intercala quadros `03 E5 01 00 00` (byte 2 = 0x01 em vez de 0x40)
     quando o enlace pisca. Ler um desses da 0% e dispara alarme falso. So
     quadro com `03 E5 40` conta.
  2. Com o cabo ligado no PC o mouse sai do radio: o dongle emudece e o mouse
     aparece como outro dispositivo USB (1d57:2155). Isso NAO e bateria
     acabando - e por isso que o silencio vira "asleep", nunca 0%.

O acesso sem root vem da regra udev em udev/70-attackshark-battery.rules, que
libera so a interface vendor. Liberar o dongle inteiro daria a qualquer app do
usuario as interfaces de teclado e mouse, ou seja, teclas por hidraw.
"""

from __future__ import annotations

import glob
import os
import select
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QSocketNotifier, QTimer, Signal

# quadro valido: 03 E5 40 <estado> <nivel>
# Supported 2.4 GHz battery report headers
MAGIC = {
    (0x03, 0xE5, 0x40),  # Original models
    (0x03, 0x24, 0x41),  # Attack Shark V6
}
FRAME_LEN = 5

ST_BATTERY = 0x01
ST_CHARGING = 0x03

# o mouse emite a cada ~2s; abaixo disso e so folga para um quadro perdido
ASLEEP_AFTER = 30.0
REOPEN_EVERY_MS = 4000

STATE_DIR = Path.home() / ".local/state/attackshark-tray"


def find_device() -> str | None:
    """hidraw da interface vendor do dongle.

    O indice do hidraw muda a cada replug, entao nunca fixar o caminho. E o
    match e no `modalias` da usb_interface porque `idVendor` (usb_device) e
    `bInterfaceNumber` (usb_interface) moram em pais diferentes - a mesma
    armadilha que faz a regra udev ingenua nao casar com nada.
    """
    for node in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
        try:
            with open(os.path.join(node, 'device/../modalias')) as f:
                ma = f.read().strip()
        except OSError:
            continue
        if ma.startswith('usb:v1D57pFA60') and ma.endswith('in02'):
            return '/dev/' + os.path.basename(node)
    return None


@dataclass(frozen=True)
class Reading:
    present: bool = False           # ha valor utilizavel para mostrar
    level: int = 0
    charging: bool = False
    status: str = "absent"          # charging | discharging | asleep | absent
    age: float = 0.0                # segundos desde o ultimo quadro bom
    raw: str = ""                   # ultimo quadro, em hex, para diagnostico
    error: str = ""                 # motivo de nao estar lendo

    @property
    def live(self) -> bool:
        """True quando o numero e uma leitura de agora, nao um valor guardado."""
        return self.status in ("charging", "discharging")

    @property
    def label(self) -> str:
        if not self.present:
            return "no mouse"
        return f"{self.level}%"

    @property
    def status_en(self) -> str:
        return {
            "charging": "charging",
            "discharging": "on battery",
            "asleep": "mouse asleep or off",
            "absent": "receiver unplugged",
        }.get(self.status, self.status)


class MouseMonitor(QObject):
    """Escuta o dongle e publica a ultima leitura boa.

    Orientado a evento, nao a polling: o dongle so fala quando quer, entao um
    QSocketNotifier acorda no quadro em vez de acordar a CPU a cada N segundos
    para descobrir que nada mudou.
    """

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fd: int | None = None
        self._path: str = ""
        self._notifier: QSocketNotifier | None = None
        self._error = ""
        self._last_frame: bytes | None = None
        self._last_ts = 0.0
        self._level = 0
        self._charging = False

        self._watch = QTimer(self)
        self._watch.timeout.connect(self._ensure_open)
        self._watch.start(REOPEN_EVERY_MS)
        self._ensure_open()

    # -- abertura ------------------------------------------------------
    def _ensure_open(self) -> None:
        """Abre o dispositivo, ou detecta que ele sumiu. Chamado por timer."""
        if self._fd is not None:
            if self._path and os.path.exists(self._path):
                self._emit_if_stale()
                return
            self._close()          # dongle removido

        path = find_device()
        if path is None:
            self._set_error("")    # ausencia normal, nao e erro
            return
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except PermissionError:
            self._set_error(f"no permission to read {path} — is the udev rule "
                            "installed? (udev/70-attackshark-battery.rules)")
            return
        except OSError as exc:
            self._set_error(f"cannot open {path}: {exc.strerror}")
            return

        self._fd = fd
        self._path = path
        self._error = ""
        self._notifier = QSocketNotifier(fd, QSocketNotifier.Read, self)
        self._notifier.activated.connect(self._on_ready)
        self.changed.emit()

    def _close(self) -> None:
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier.deleteLater()
            self._notifier = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
        self._fd = None
        self._path = ""
        self._last_frame = None
        self._last_ts = 0.0
        self.changed.emit()

    def _set_error(self, message: str) -> None:
        if message != self._error:
            self._error = message
            self.changed.emit()

    # -- leitura -------------------------------------------------------
    def _on_ready(self) -> None:
        if self._fd is None:
            return
        got = False
        # drena tudo que estiver na fila: interessa o quadro mais novo
        while True:
            try:
                r, _, _ = select.select([self._fd], [], [], 0)
            except OSError:
                self._close()
                return
            if not r:
                break
            try:
                data = os.read(self._fd, 64)
            except BlockingIOError:
                break
            except OSError:
                self._close()
                return
            if not data:
                break
            if self._accept(data):
                got = True
        if got:
            self.changed.emit()

    def _accept(self, data: bytes) -> bool:
        """Guarda o quadro se for um quadro de bateria de verdade."""
        if len(data) < FRAME_LEN or tuple(data[:3]) not in MAGIC:
            return False            # inclui o `03 E5 01 00 00` do enlace piscando
        level = data[4]
        if level > 100:
            return False
        self._last_frame = bytes(data[:FRAME_LEN])
        self._last_ts = time.time()
        self._level = level
        self._charging = data[3] == ST_CHARGING
        return True

    def _emit_if_stale(self) -> None:
        """Avisa quando o mouse cala a boca, para a bandeja mudar de estado."""
        if self._last_ts and time.time() - self._last_ts > ASLEEP_AFTER:
            self.changed.emit()

    # -- resultado -----------------------------------------------------
    def read(self) -> Reading:
        now = time.time()
        if self._fd is None or self._last_frame is None:
            return Reading(status="absent", error=self._error)

        age = now - self._last_ts
        raw = ' '.join(f'{b:02X}' for b in self._last_frame)
        if age > ASLEEP_AFTER:
            # o mouse parou de falar. O nivel que ele disse por ultimo continua
            # valendo - fingir 0% aqui seria alarme sobre um numero inventado.
            return Reading(True, self._level, self._charging, "asleep", age, raw)
        return Reading(True, self._level, self._charging,
                       "charging" if self._charging else "discharging", age, raw)

    def diagnostics(self) -> str:
        from . import __version__
        r = self.read()
        lines = [f"app            attackshark-tray {__version__}"]
        if self._path:
            lines.append(f"device         {self._path}")
        else:
            found = find_device()
            lines.append(f"device         not open ({found or 'no dongle found'})")
        lines += [
            f"last frame     {r.raw or '(none)'}",
            f"frame age      {r.age:.1f}s",
            f"level          {r.level}%",
            f"state          {r.status_en}",
        ]
        if r.error:
            lines.append(f"error          {r.error}")
        return "\n".join(lines)
