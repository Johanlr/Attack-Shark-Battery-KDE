"""
Estimativa de tempo restante.

O mouse manda porcentagem e nada mais - sem corrente, sem tensao, sem contador
de carga. Entao nao existe ETA "do dispositivo": a unica forma honesta e MEDIR
o que acontece nesta maquina, com este mouse, e so mostrar numero quando
houver medida que o sustente.

**Por que degraus e nao minimos quadrados.** O sinal aqui cai 1 ponto a cada
~30 minutos. Numa janela de 3h isso da 6 pontos, todos inteiros: ajustar uma
reta em cima disso mede mais o arredondamento do que a bateria. O que o sinal
oferece de verdade e o INTERVALO ENTRE DEGRAUS, que e uma medida direta de
"quanto tempo dura 1%". Guardamos esses intervalos e usamos a mediana - que
aguenta um degrau estranho no meio sem contaminar a conta.

Um degrau so vale se:

  * o nivel andou 1..3 pontos na direcao esperada;
  * o tempo entre eles cabe numa faixa plausivel (nem 10s, nem 3h);
  * o mouse ficou acordado o tempo todo. Dormindo ele gasta muito menos, e um
    degrau que atravessa a madrugada diria que a bateria dura uma semana.

**Descarga e carga** usam o mesmo mecanismo, so muda a direcao e a faixa de
tempo - carregar anda ~1 ponto por minuto, descarregar ~1 por meia hora.

**Historico.** As taxas medidas sobrevivem entre sessoes, entao o ETA nasce
pronto em vez de "medindo..." por meia hora. Enquanto a sessao atual nao tem
degraus proprios, a estimativa sai do historico e diz isso (`from_history`).
"""

from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

from .mouse import STATE_DIR, Reading

STATE_FILE = STATE_DIR / "eta.json"

# log do coletor antigo, importado uma vez para o ETA ja nascer calibrado
LEGACY_LOG = Path.home() / ".local/share/bateria-mouse.log"

MAX_STEPS = 60              # degraus guardados por direcao
FRESH_STEPS = 12            # quantos entram na mediana
MIN_STEPS_LIVE = 2          # degraus desta sessao para dizer "medido agora"

# faixas plausiveis de tempo por ponto percentual (segundos)
DRAIN_MIN_S, DRAIN_MAX_S = 3 * 60, 3 * 3600
CHARGE_MIN_S, CHARGE_MAX_S = 10, 30 * 60

MAX_JUMP = 3                # degrau maior que isso e salto, nao ritmo
TOO_LONG_S = 60 * 3600      # acima disso nao vale fingir precisao

# Depois de tirar o cabo o medidor ainda desce depressa por um tempo: sao os
# primeiros pontos "de superficie" indo embora, nao o consumo real. Medido no
# log: 13 min por ponto logo apos a carga contra ~36 min uma hora depois. Sem
# esta carencia o ETA sai quase pela metade.
SETTLE_AFTER_CHARGE_S = 20 * 60


def human(seconds: float) -> str:
    """Duracao em texto curto, sem falsa precisao."""
    seconds = max(0.0, seconds)
    if seconds < 90:
        return "a minute"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours >= 10:
        minutes = 0
    return f"{hours} h {minutes:02d} min" if minutes else f"{hours} h"


@dataclass
class Estimate:
    kind: str = ""              # empty | full
    seconds: float = 0.0
    text: str = ""              # vazio = nao ha numero para mostrar
    pending: str = ""           # o que falta para ter numero
    rate: float = 0.0           # %/h
    steps: int = 0              # degraus na mediana
    from_history: bool = False  # ritmo veio de sessoes anteriores

    @property
    def ok(self) -> bool:
        return bool(self.text)


@dataclass
class _State:
    drain: list = field(default_factory=list)    # [[ts, segundos_por_ponto]]
    charge: list = field(default_factory=list)
    imported: bool = False


class Estimator:
    """Mede o ritmo real e responde quanto falta."""

    def __init__(self, path: Path = STATE_FILE) -> None:
        self.path = path
        self.s = _State()
        # ancora do degrau em curso: (instante, nivel, carregando)
        self._anchor: tuple[float, int, bool] | None = None
        self._settle_until = 0.0
        self._live_drain = 0
        self._live_charge = 0
        self._load()
        if not self.s.imported:
            self.import_legacy()

    # -- persistencia ----------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        try:
            self.s.drain = [[float(t), float(v)] for t, v in
                            data.get("drain", [])][-MAX_STEPS:]
            self.s.charge = [[float(t), float(v)] for t, v in
                             data.get("charge", [])][-MAX_STEPS:]
            self.s.imported = bool(data.get("imported", False))
        except (TypeError, ValueError):
            self.s = _State()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "drain": self.s.drain,
                "charge": self.s.charge,
                "imported": self.s.imported,
            }))
            tmp.replace(self.path)
        except OSError:
            pass

    def forget(self) -> None:
        self.s = _State()
        self.s.imported = True      # nao reimportar o log por tras do usuario
        self._anchor = None
        self._live_drain = self._live_charge = 0
        self._save()

    # -- importacao do log antigo ----------------------------
    def import_legacy(self, path: Path = LEGACY_LOG) -> int:
        """Semeia as taxas com o log do coletor, se ele existir.

        O log guarda so MUDANCAS de quadro, que e exatamente o que interessa:
        cada par consecutivo ja e um degrau. Roda uma vez; depois o proprio app
        e a fonte."""
        self.s.imported = True
        added = 0
        try:
            lines = path.read_text().splitlines()
        except OSError:
            self._save()
            return 0

        pat = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+"
                         r"03 E5 40 (\w\w) (\w\w)$")
        anchor: tuple[float, int, bool] | None = None
        settle_until = 0.0
        for line in lines:
            line = line.strip()
            m = pat.match(line)
            if not m:
                # linha de ausencia do dongle corta a serie; um quadro espurio
                # do enlace piscando nao - ele dura 2s e nao diz nada sobre a
                # bateria. Tratar os dois igual truncava o degrau em curso e
                # fazia o ritmo sair rapido demais.
                if "--" in line:
                    anchor = None
                continue
            try:
                ts = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
                charging = int(m.group(2), 16) == 0x03
                level = int(m.group(3), 16)
            except ValueError:
                anchor = None
                continue
            if level > 100:
                anchor = None
                continue

            point = (ts, level, charging)
            if anchor is None or anchor[2] != charging:
                if anchor is not None and anchor[2] and not charging:
                    settle_until = ts + SETTLE_AFTER_CHARGE_S
                anchor = point
                continue
            if level == anchor[1]:
                # mesmo nivel: a ancora TEM que ficar onde estava, senao o
                # tempo do degrau conta so a partir da ultima repeticao
                continue
            if not (not charging and anchor[0] < settle_until):
                if self._learn(anchor, point):
                    added += 1
            anchor = point

        self._save()
        return added

    # -- coleta ao vivo --------------------------------------
    def update(self, r: Reading, now: float | None = None) -> None:
        now = time.time() if now is None else now

        if not r.live:
            # dormindo ou sem dongle: o tempo passa sem drenar do mesmo jeito,
            # entao o degrau em curso nao vale mais
            self._anchor = None
            return

        point = (now, int(r.level), bool(r.charging))
        if self._anchor is None:
            self._anchor = point
            return

        if self._anchor[2] != point[2]:
            # trocou de direcao (cabo entrou ou saiu): recomeca a contar
            if self._anchor[2] and not point[2]:
                self._settle_until = now + SETTLE_AFTER_CHARGE_S
            self._anchor = point
            return

        if point[1] == self._anchor[1]:
            return                   # ainda no mesmo degrau

        if not point[2] and self._anchor[0] < self._settle_until:
            # degrau comecado durante o assentamento: nao mede consumo real
            self._anchor = point
            return

        if self._learn(self._anchor, point):
            if point[2]:
                self._live_charge += 1
            else:
                self._live_drain += 1
            self._save()
        self._anchor = point

    def _learn(self, a: tuple[float, int, bool],
               b: tuple[float, int, bool]) -> bool:
        """Guarda segundos-por-ponto de um degrau. True se o degrau valeu."""
        ts0, lvl0, ch0 = a
        ts1, lvl1, ch1 = b
        if ch0 != ch1:
            return False
        dt = ts1 - ts0
        delta = (lvl1 - lvl0) if ch1 else (lvl0 - lvl1)
        if delta <= 0 or delta > MAX_JUMP or dt <= 0:
            return False
        per_point = dt / delta
        lo, hi = (CHARGE_MIN_S, CHARGE_MAX_S) if ch1 else (DRAIN_MIN_S, DRAIN_MAX_S)
        if not lo <= per_point <= hi:
            return False
        bucket = self.s.charge if ch1 else self.s.drain
        bucket.append([ts1, round(per_point, 1)])
        del bucket[:-MAX_STEPS]
        return True

    # -- calculo ---------------------------------------------
    def _per_point(self, charging: bool) -> float | None:
        """Mediana dos degraus recentes, em segundos por ponto percentual."""
        bucket = self.s.charge if charging else self.s.drain
        recent = [v for _, v in bucket[-FRESH_STEPS:]]
        if not recent:
            return None
        return statistics.median(recent)

    def rate_pph(self, charging: bool) -> float | None:
        per_point = self._per_point(charging)
        return None if not per_point else 3600.0 / per_point

    def estimate(self, r: Reading, use_history: bool = True) -> Estimate:
        live_steps = self._live_charge if r.charging else self._live_drain
        bucket = self.s.charge if r.charging else self.s.drain

        if not r.present:
            return Estimate(pending="mouse not reporting")

        if r.status == "asleep":
            return Estimate(pending="mouse is asleep — the level is the last "
                                    "one it reported")

        if r.charging and r.level >= 100:
            return Estimate(kind="full", text="fully charged")

        per_point = self._per_point(r.charging)
        if per_point is None:
            what = "charge" if r.charging else "drain"
            return Estimate(pending=f"measuring the {what} — a time appears "
                                    f"after the level moves one point")

        from_history = live_steps < MIN_STEPS_LIVE
        if from_history and not use_history:
            what = "charge" if r.charging else "drain"
            return Estimate(pending=f"measuring this session's {what} — needs "
                                    f"{MIN_STEPS_LIVE} steps of one point")

        remaining = (100 - r.level) if r.charging else r.level
        seconds = remaining * per_point
        rate = 3600.0 / per_point
        steps = len(bucket[-FRESH_STEPS:])

        if r.charging:
            if seconds <= 60:
                return Estimate(kind="full", text="any minute now", rate=rate,
                                steps=steps, from_history=from_history)
            return Estimate(kind="full", seconds=seconds, rate=rate, steps=steps,
                            from_history=from_history,
                            text=f"{human(seconds)} to full")

        if seconds > TOO_LONG_S:
            return Estimate(kind="empty", seconds=seconds, rate=rate,
                            steps=steps, from_history=from_history,
                            text="more than two days left")
        return Estimate(kind="empty", seconds=seconds, rate=rate, steps=steps,
                        from_history=from_history, text=f"{human(seconds)} left")

    # -- transparencia ---------------------------------------
    def summary(self) -> str:
        """O que o app mediu, em texto - para a janela e para o diagnostico."""
        lines = []
        for charging, name in ((False, "drain"), (True, "charge")):
            bucket = self.s.charge if charging else self.s.drain
            per_point = self._per_point(charging)
            if per_point is None:
                lines.append(f"{name:7s} not measured yet")
                continue
            live = self._live_charge if charging else self._live_drain
            lines.append(
                f"{name:7s} {3600.0 / per_point:.2f} %/h "
                f"({human(per_point)} per point), median of "
                f"{len(bucket[-FRESH_STEPS:])} recent step(s) "
                f"out of {len(bucket)} kept, {live} from this session")
        return "\n".join(lines)
