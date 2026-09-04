"""
Configuracao central.

Tudo que o usuario pode mexer mora aqui: um dicionario de padroes, tipos
explicitos e um QSettings por tras. O resto do app nunca fala com o QSettings
direto - assim renomear uma chave e um lugar so, e "Restore defaults" e apagar
tudo e reemitir um sinal.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal

ORG = "attackshark-tray"
APP = "attackshark-tray"

# chave -> valor padrao. O TIPO do padrao manda na leitura (bool, int, str).
DEFAULTS: dict[str, object] = {
    # -- aparencia -------------------------------------------
    "style": "shark",
    "scheme": "shark",
    "custom_color": "#00e5ff",
    "glow": 55,             # 0..100, intensidade do brilho externo
    "weight": "normal",     # thin | normal | bold - espessura dos tracos
    "show_number": True,    # numero sobreposto nos estilos que suportam
    "icon_scale": 100,      # 60..140 (%) - tamanho do desenho dentro da bandeja

    # -- animacao --------------------------------------------
    "anim": True,
    "fps": 30,              # 12 | 20 | 30 | 45 | 60
    "speed": 100,           # 25..300 (%)
    "fx_charging": "wave_rise",
    "fx_low": "breathe",
    "fx_critical": "flash",
    "fx_full": "halo",
    "fx_idle": "none",
    "fx_asleep": "none",
    "full_seconds": 12,     # 0 = anima para sempre enquanto estiver cheio

    # -- limiares --------------------------------------------
    "low_at": 20,
    "crit_at": 10,
    "full_at": 100,
    "repeat_min": 15,       # repetir o aviso a cada N minutos (0 = so uma vez)

    # -- notificacoes ----------------------------------------
    "notify": True,
    "notify_low": True,
    "notify_crit": True,
    "notify_full": True,
    "notify_conn": True,
    "notify_charge": False,
    "notify_ms": 6000,

    # -- sons ------------------------------------------------
    "snd_volume": 85,
    "snd_low_on": True,      "snd_low": "@default:low",
    "snd_crit_on": True,     "snd_crit": "@default:critical",
    "snd_full_on": True,     "snd_full": "@default:full",
    "snd_conn_on": False,    "snd_conn": "@default:connected",
    "snd_disc_on": False,    "snd_disc": "@default:disconnected",
    "snd_charge_on": False,  "snd_charge": "@default:charging",

    # -- geral -----------------------------------------------
    "eta": True,            # mostrar quanto tempo falta
    "eta_history": True,    # usar ritmo aprendido antes de medir o de agora
    "first_run": True,
}

# limites usados pelos spinners e para sanear valor vindo do arquivo
RANGES: dict[str, tuple[int, int]] = {
    "glow": (0, 100),
    "icon_scale": (60, 140),
    "fps": (12, 60),
    "speed": (25, 300),
    "full_seconds": (0, 120),
    "low_at": (5, 60),
    "crit_at": (1, 40),
    "full_at": (80, 100),
    "repeat_min": (0, 240),
    "notify_ms": (2000, 20000),
    "snd_volume": (0, 100),
}


class Config(QObject):
    """Estado de configuracao observavel."""

    changed = Signal(str)   # nome da chave (ou "*" quando tudo mudou)

    def __init__(self, ini_path: str | None = None) -> None:
        """`ini_path` so e usado pelas ferramentas de tools/, para gerar imagens
        com os padroes em vez de mexer na configuracao de quem esta rodando."""
        super().__init__()
        self._s = (QSettings(ini_path, QSettings.IniFormat) if ini_path
                   else QSettings(ORG, APP))

    # -- leitura ---------------------------------------------
    def __getitem__(self, key: str):
        default = DEFAULTS[key]
        if isinstance(default, bool):
            value = self._s.value(key, default, type=bool)
        elif isinstance(default, int):
            try:
                value = int(self._s.value(key, default))
            except (TypeError, ValueError):
                value = default
            lo, hi = RANGES.get(key, (None, None))
            if lo is not None:
                value = max(lo, min(hi, value))
        else:
            value = str(self._s.value(key, default))
        return value

    def get(self, key: str, fallback=None):
        return self[key] if key in DEFAULTS else fallback

    # -- escrita ---------------------------------------------
    def __setitem__(self, key: str, value) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        if self[key] == value:
            return
        self._s.setValue(key, value)
        self._s.sync()
        self.changed.emit(key)

    def set_many(self, pairs: dict) -> None:
        for k, v in pairs.items():
            if k in DEFAULTS:
                self._s.setValue(k, v)
        self._s.sync()
        self.changed.emit("*")

    def reset(self) -> None:
        self._s.clear()
        self._s.sync()
        self.changed.emit("*")

    # -- conveniencias ---------------------------------------
    @property
    def low_at(self) -> int:
        return self["low_at"]

    @property
    def crit_at(self) -> int:
        """Critico nunca pode passar do limiar de baixo - senao nunca dispara."""
        return min(self["crit_at"], self["low_at"])
