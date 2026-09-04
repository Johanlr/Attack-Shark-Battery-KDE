"""
Renderização dos ícones.

Junta forma (shapes.py) + efeito (effects.py) + cor, tudo em QPainter num
espaço 100x100 escalado para o tamanho pedido. Nenhum arquivo de imagem é
carregado: o mesmo desenho serve pra bandeja em 22px e pra notificação em 128px.

Ordem de um quadro:
    1. geometria (cacheada)      4. traço apagado + moldura
    2. efeito pre()              5. preenchimento (líquido ou progressivo)
    3. glow + transformação      6. detalhes + efeito post()
"""

from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import effects, shapes
from .effects import Ctx
from .shapes import STYLES  # noqa: F401  (reexportado: o menu importa daqui)

# tamanhos gerados; menos deles enquanto anima, pra não encher o D-Bus
SIZES = (22, 32, 48, 64, 128)
ANIM_SIZES = (22, 32, 48)

# chave -> (rótulo, tipo, cor)   tipo: level | spectrum | mono | fixed | custom
SCHEMES: dict[str, tuple[str, str, str | None]] = {
    "level":    ("Level — green / amber / red", "level", None),
    "spectrum": ("Level — smooth spectrum", "spectrum", None),
    "mono":     ("Monochrome", "mono", "#e8e8ee"),
    "shark":    ("Shark cyan", "fixed", "#00e5ff"),
    "attack":   ("Attack orange", "fixed", "#ff6a00"),
    "cyan":     ("Cyan", "fixed", "#22d3ee"),
    "teal":     ("Teal", "fixed", "#2dd4bf"),
    "violet":   ("Violet", "fixed", "#a45cff"),
    "indigo":   ("Indigo", "fixed", "#7c8cff"),
    "magenta":  ("Magenta", "fixed", "#ff5ecb"),
    "rose":     ("Rose", "fixed", "#ff6b81"),
    "red":      ("Red", "fixed", "#ff453a"),
    "orange":   ("Orange", "fixed", "#ff8c42"),
    "amber":    ("Amber", "fixed", "#ffb020"),
    "lime":     ("Lime", "fixed", "#a3e635"),
    "green":    ("Green", "fixed", "#3ddc84"),
    "white":    ("White", "fixed", "#ffffff"),
    "hotpink":  ("Hot pink", "fixed", "#ff2d9b"),
    "gold":     ("Gold", "fixed", "#ffcc33"),
    "icy":      ("Ice blue", "fixed", "#a5f3fc"),
    "mint":     ("Mint", "fixed", "#6ee7b7"),
    "lavender": ("Lavender", "fixed", "#c4b5fd"),
    "coral":    ("Coral", "fixed", "#ff7a6b"),
    "crimson":  ("Crimson", "fixed", "#dc2626"),
    "emerald":  ("Emerald", "fixed", "#10b981"),
    "sky":      ("Sky", "fixed", "#38bdf8"),
    "peach":    ("Peach", "fixed", "#ffb4a2"),
    "steel":    ("Steel", "fixed", "#94a3b8"),
    "ultra":    ("Ultraviolet", "fixed", "#8b5cf6"),
    # degradês percorridos pelo nível
    "hue":      ("Rainbow by level", "hue", None),
    "fire":     ("Fire", "gradient", ("#ff2d20", "#ff7a1a", "#ffd400")),
    "ice":      ("Ice", "gradient", ("#2563eb", "#22d3ee", "#e0f7ff")),
    "toxic":    ("Toxic", "gradient", ("#166534", "#65a30d", "#bef264")),
    "sunset":   ("Sunset", "gradient", ("#7c3aed", "#ec4899", "#fb923c")),
    "ocean":    ("Ocean", "gradient", ("#0c4a6e", "#0ea5e9", "#5eead4")),
    "candy":    ("Candy", "gradient", ("#f472b6", "#c4b5fd", "#7dd3fc")),
    "cyber":    ("Cyberpunk", "gradient", ("#ff2bd6", "#7c3aed", "#22d3ee")),
    "abyss":    ("Abyss", "gradient", ("#0b1a2b", "#0e7490", "#67e8f9")),
    "reef":     ("Reef", "gradient", ("#0891b2", "#34d399", "#fde68a")),
    "bloodwater": ("Blood in the water", "gradient",
                   ("#450a0a", "#dc2626", "#fca5a5")),
    "steelshark": ("Steel shark", "gradient",
                   ("#334155", "#94a3b8", "#e2e8f0")),
    "custom":   ("Custom colour…", "custom", None),
}

C_HIGH = QColor("#3ddc84")
C_MID = QColor("#ffb020")
C_LOW = QColor("#ff453a")
C_TRACK = QColor(146, 148, 158, 108)      # traço apagado, legível em tema claro e escuro
C_OFF = QColor(150, 152, 162, 130)        # headset ausente


class Look:
    """Aparência escolhida pelo usuário, sem depender do QSettings."""

    __slots__ = ("style", "scheme", "custom", "glow", "weight", "show_number",
                 "low_at", "crit_at", "scale")

    def __init__(self, style="mouse", scheme="shark", custom="#00e5ff",
                 glow=55, weight="normal", show_number=True,
                 low_at=20, crit_at=10, scale=100):
        self.style = style if style in shapes.STYLES else "mouse"
        self.scheme = scheme if scheme in SCHEMES else "level"
        self.custom = custom
        self.glow = max(0, min(100, int(glow)))
        self.weight = weight if weight in shapes.WEIGHTS else "normal"
        self.show_number = show_number
        self.low_at = low_at
        self.crit_at = crit_at
        self.scale = max(60, min(140, int(scale)))

    def key(self) -> tuple:
        return (self.style, self.scheme, self.custom, self.glow, self.weight,
                self.show_number, self.low_at, self.crit_at, self.scale)


def track_color(color: QColor) -> QColor:
    """Pista apagada, puxando um pouco para a cor do nível.

    Neutra demais e o ícone em 5% lê como desligado; saturada demais e o
    "vazio" some. 35% da cor sobre o cinza resolve os dois."""
    out = _mix(QColor(146, 148, 158), color, 0.35)
    out.setAlpha(112)
    return out


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


def scheme_color(look: Look, level: int) -> QColor:
    label, kind, fixed = SCHEMES.get(look.scheme, SCHEMES["level"])
    if kind == "level":
        if level < look.crit_at:
            return QColor(C_LOW)
        if level < look.low_at:
            return QColor(C_MID)
        return QColor(C_HIGH)
    if kind == "spectrum":
        # vermelho -> âmbar -> verde, contínuo
        t = max(0.0, min(1.0, level / 85.0))
        return _mix(C_LOW, C_MID, t / 0.5) if t < 0.5 \
            else _mix(C_MID, C_HIGH, (t - 0.5) / 0.5)
    if kind == "hue":
        # vermelho -> violeta conforme enche; 0 e 100 não podem cair na mesma cor
        c = QColor()
        c.setHsvF(max(0.0, min(1.0, level / 100.0)) * 0.85, 0.9, 1.0)
        return c
    if kind == "gradient":
        stops = fixed
        t = max(0.0, min(0.9999, level / 100.0)) * (len(stops) - 1)
        i = int(t)
        return _mix(QColor(stops[i]), QColor(stops[i + 1]), t - i)
    if kind == "custom":
        c = QColor(look.custom)
        return c if c.isValid() else QColor("#00e5ff")
    return QColor(fixed)


# ── região de preenchimento ─────────────────────────────────

def surface_path(frac: float, axis: str,
                 wave: tuple[float, float] | None) -> QPainterPath:
    """Só a linha da superfície do líquido (usada pro brilho da borda)."""
    frac = max(0.0, min(1.0, frac))
    path = QPainterPath()
    amp, ph = wave if wave else (0.0, 0.0)
    if axis == "v":
        base = 100 - 100 * frac
        for i in range(0, 29):
            x = -6 + i * (112 / 28)
            # duas senoides sobrepostas: uma só fica com cara de gráfico
            y = (base
                 + amp * math.sin((x / 100 * 2.1 + ph) * 2 * math.pi)
                 + amp * 0.45 * math.sin((x / 100 * 3.7 - ph * 1.7) * 2 * math.pi))
            path.lineTo(x, y) if i else path.moveTo(x, y)
    else:
        base = 100 * frac
        for i in range(0, 29):
            y = -6 + i * (112 / 28)
            x = (base
                 + amp * math.sin((y / 100 * 2.1 + ph) * 2 * math.pi)
                 + amp * 0.45 * math.sin((y / 100 * 3.7 - ph * 1.7) * 2 * math.pi))
            path.lineTo(x, y) if i else path.moveTo(x, y)
    return path


def fill_region(frac: float, axis: str,
                wave: tuple[float, float] | None) -> QPainterPath:
    """Área preenchida; com `wave` a superfície vira onda de líquido."""
    frac = max(0.0, min(1.0, frac))
    if wave is None:
        path = QPainterPath()
        if axis == "h":
            path.addRect(QRectF(-6, -6, 6 + 106 * frac, 112))
        else:
            path.addRect(QRectF(-6, 100 - 106 * frac, 112, 112))
        return path

    path = surface_path(frac, axis, wave)
    if axis == "v":
        path.lineTo(106, 112)
        path.lineTo(-6, 112)
    else:
        path.lineTo(-6, 106)
        path.lineTo(-6, -6)
    path.closeSubpath()
    return path


def _progress_path(route: QPainterPath, frac: float, width: float) -> QPainterPath:
    """Traço colorido acompanhando a rota até `frac` (medidor angular)."""
    if frac <= 0.004:
        return QPainterPath()
    seg = effects._sub_route(route, 0.0, min(1.0, frac), 40)
    st = shapes.QPainterPathStroker()
    st.setWidth(width)
    st.setCapStyle(Qt.RoundCap)
    st.setJoinStyle(Qt.RoundJoin)
    return st.createStroke(seg)


# ── desenho ─────────────────────────────────────────────────

def _paint_absent(p: QPainter, look: Look) -> None:
    """Mesma silhueta do estilo escolhido, apagada e cortada."""
    geom = shapes.geometry(look.style, look.weight)
    p.setPen(Qt.NoPen)
    p.setBrush(C_OFF)
    if geom.custom is not None:
        geom.custom(p, 0, C_OFF, C_OFF, 0.0, 64)
    else:
        p.drawPath(geom.body)
        for _, part in geom.parts:
            p.drawPath(part)
    # corte diagonal: um vão escuro e a barra por cima
    p.setPen(QPen(QColor(0, 0, 0, 190), 15, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(20, 20), QPointF(80, 80))
    p.setPen(QPen(QColor(225, 226, 235, 220), 7, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(22, 22), QPointF(78, 78))


def render(size: int, look: Look, level: int, status: str, present: bool,
           effect: str = "none", phase: float = 0.0) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    # 100x100 com uma folga de 3% pro glow e pro halo não serem cortados
    p.scale(size / 100.0, size / 100.0)
    p.translate(2.0, 2.0)
    p.scale(0.96, 0.96)

    # tamanho escolhido pelo usuário: escala em torno do centro, para o ícone
    # continuar centrado na célula da bandeja seja qual for o valor
    if look.scale != 100:
        k = look.scale / 100.0
        p.translate(50, 50)
        p.scale(k, k)
        p.translate(-50, -50)

    if not present:
        _paint_absent(p, look)
        p.end()
        return pm

    geom = shapes.geometry(look.style, look.weight)
    color = scheme_color(look, level)

    # dormindo: o número continua sendo o último que o mouse disse, então o
    # ícone é o mesmo, só apagado. Inventar 0% aqui seria alarme sobre nada.
    asleep = status == "asleep"
    if asleep:
        color = _mix(color, QColor(150, 152, 162), 0.45)

    ctx = Ctx(level=level, status=status, present=present, phase=phase % 1.0,
              size=size, color=color, dim=track_color(color),
              fill=level / 100.0, real_fill=level / 100.0,
              glow=look.glow / 100.0 * 0.55,
              body=geom.body, route=geom.route, axis=geom.axis,
              show_number=look.show_number)

    fx = effects.get(effect)
    if fx.pre is not None:
        fx.pre(ctx)
    if asleep:
        ctx.alpha *= 0.62
        ctx.glow *= 0.35

    p.setOpacity(max(0.0, min(1.0, ctx.alpha)))
    if ctx.scale != 1.0 or ctx.dx or ctx.dy:
        p.translate(50, 50)
        p.scale(ctx.scale, ctx.scale)
        p.translate(-50 + ctx.dx, -50 + ctx.dy)

    # glow externo: só a partir de 32px, senão vira borrão na bandeja
    if look.glow > 0 and size >= 32:
        strength = ctx.glow * (0.55 + look.glow / 100.0 * 0.75)
        effects.paint_glow(p, geom.body, ctx.color, strength,
                           6.0 + look.glow / 100.0 * 5.0)

    p.setPen(Qt.NoPen)

    # moldura (casca da pilha, aro externo…) sempre apagada
    for kind, part in geom.parts:
        p.setBrush(ctx.dim if kind != "frame_dim"
                   else QColor(146, 148, 158, 70))
        p.drawPath(part)

    if geom.custom is not None:
        geom.custom(p, level, ctx.color, ctx.dim, ctx.fill, size)
    else:
        p.setBrush(ctx.dim)
        p.drawPath(geom.body)

        use_progress = geom.prefer == "progress" and geom.route is not None
        if use_progress:
            solid = _progress_path(geom.route, ctx.fill, geom.stroke_w)
            if not solid.isEmpty():
                p.setBrush(ctx.color)
                p.drawPath(solid.intersected(geom.body))
            if ctx.ghost is not None:
                gfrac, galpha = ctx.ghost
                gp = _progress_path(geom.route, gfrac, geom.stroke_w)
                if not gp.isEmpty():
                    gp = gp.subtracted(solid).intersected(geom.body)
                    c = QColor(ctx.color)
                    c.setAlphaF(galpha)
                    p.setBrush(c)
                    p.drawPath(gp)
                    # cabeça brilhante na ponta do que está enchendo
                    head = geom.route.pointAtPercent(max(0.0, min(1.0, gfrac)))
                    hot = effects.lighter(ctx.color, 200)
                    hot.setAlphaF(min(1.0, galpha + 0.3))
                    p.setBrush(hot)
                    p.drawEllipse(head, geom.stroke_w * 0.34, geom.stroke_w * 0.34)
        else:
            region = fill_region(ctx.fill, geom.axis, ctx.wave)
            if ctx.ghost is not None:
                gfrac, galpha = ctx.ghost
                gregion = fill_region(gfrac, geom.axis, ctx.wave).subtracted(region)
                c = QColor(ctx.color)
                c.setAlphaF(galpha)
                p.save()
                p.setClipPath(gregion)
                p.setBrush(c)
                p.drawPath(geom.body)
                p.restore()
                # linha de superfície: é ela que dá a sensação de líquido
                p.save()
                p.setClipPath(geom.body)
                hot = effects.lighter(ctx.color, 210)
                hot.setAlphaF(min(1.0, galpha + 0.35))
                p.setPen(QPen(hot, 3.0, Qt.SolidLine, Qt.RoundCap))
                p.setBrush(Qt.NoBrush)
                p.drawPath(surface_path(gfrac, geom.axis, ctx.wave))
                p.restore()
                p.setPen(Qt.NoPen)
            p.save()
            p.setClipPath(region)
            p.setBrush(ctx.color)
            p.drawPath(geom.body)
            p.restore()
            if ctx.wave is not None and ctx.fill > 0.02:
                p.save()
                p.setClipPath(geom.body)
                hot = effects.lighter(ctx.color, 200)
                hot.setAlphaF(0.85)
                p.setPen(QPen(hot, 2.6, Qt.SolidLine, Qt.RoundCap))
                p.setBrush(Qt.NoBrush)
                p.drawPath(surface_path(ctx.fill, geom.axis, ctx.wave))
                p.restore()
                p.setPen(Qt.NoPen)

    if geom.detail is not None:
        geom.detail(p, level, ctx.color, ctx.dim, ctx.fill, size)

    if geom.over is not None and (look.show_number
                                  or look.style not in shapes.NUMBER_STYLES):
        geom.over(p, level, ctx.color, ctx.fill, size)

    if fx.post is not None:
        fx.post(p, ctx)

    p.end()

    # o glitch mexe na imagem pronta: é o que rasga o ícone inteiro (número,
    # velas e tudo) em vez de colar um enfeite por cima dele
    if fx.pixel is not None:
        pm = QPixmap.fromImage(fx.pixel(pm.toImage(), ctx))
    return pm


# A fase é quantizada e o QIcon guardado: depois da primeira volta da animação
# o laço inteiro sai do cache, e o custo vira só o envio pro StatusNotifierItem.
PHASE_STEPS = 120


@lru_cache(maxsize=512)
def _icon_cached(key: tuple, level: int, status: str, present: bool,
                 effect: str, qphase: int, animating: bool) -> QIcon:
    look = Look(*key)
    phase = qphase / PHASE_STEPS
    icon = QIcon()
    for size in (ANIM_SIZES if animating else SIZES):
        icon.addPixmap(render(size, look, level, status, present, effect, phase))
    return icon


def make_icon(look: Look, level: int, status: str, present: bool,
              effect: str = "none", phase: float = 0.0,
              animating: bool = False) -> QIcon:
    qphase = int(round(phase * PHASE_STEPS)) % PHASE_STEPS
    return _icon_cached(look.key(), level, status, present, effect, qphase,
                        animating)
