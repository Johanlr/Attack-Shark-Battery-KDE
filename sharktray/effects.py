"""
Efeitos de animação.

A ideia central: o efeito não sabe qual é a forma. Ele só recebe a silhueta
(`body`), a linha de centro (`route`) e mexe no contexto. Por isso qualquer
efeito combina com qualquer um dos estilos de ícone, sem par proibido.

A família temática do fim do arquivo (mordida, barbatana, sonar, ondas de
rádio, clique) segue a mesma regra: nada supõe qual forma está embaixo, então
a mordida funciona igual num tubarão e numa pilha.

Dois momentos:
    pre(ctx)        antes da forma ser desenhada: cor, nível, brilho, deslocamento
    post(p, ctx)    depois: sobreposições (cometa, faísca, brilho, halo)

Nada de raio genérico colado por cima de tudo: o efeito tem que dialogar com
a silhueta, senão vira adesivo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen, QRadialGradient)


@dataclass
class Ctx:
    """Tudo que o desenho de um quadro precisa."""
    level: int = 0
    status: str = "discharging"
    present: bool = True
    phase: float = 0.0          # 0..1, cíclico
    size: int = 64
    color: QColor = field(default_factory=lambda: QColor("#3ddc84"))
    dim: QColor = field(default_factory=lambda: QColor(255, 255, 255, 52))
    fill: float = 0.0           # 0..1, o que a forma vai preencher
    real_fill: float = 0.0      # nível verdadeiro, sem efeito nenhum
    alpha: float = 1.0          # multiplicador global
    glow: float = 0.0           # 0..1
    dx: float = 0.0
    dy: float = 0.0
    scale: float = 1.0
    wave: tuple[float, float] | None = None   # (amplitude, deslocamento)
    ghost: tuple[float, float] | None = None  # (nível, opacidade) subindo por cima
    body: QPainterPath | None = None
    route: QPainterPath | None = None
    axis: str = "v"
    show_number: bool = True


# ── curvas ──────────────────────────────────────────────────

def wave01(phase: float, lo: float = 0.0) -> float:
    """Cosseno normalizado em 0..1, começando no topo."""
    return lo + (1 - lo) * (0.5 + 0.5 * math.cos(phase * 2 * math.pi))


def tri(phase: float) -> float:
    """Sobe e desce linearmente."""
    t = phase % 1.0
    return t * 2 if t < 0.5 else (1 - t) * 2


def smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _rng(i: int, salt: float = 0.0) -> float:
    """Ruído determinístico 0..1 — mesmo quadro, mesmo desenho."""
    return (math.sin(i * 12.9898 + salt * 78.233) * 43758.5453) % 1.0


def lighter(c: QColor, amount: int = 160) -> QColor:
    out = QColor(c).lighter(amount)
    out.setAlpha(c.alpha())
    return out


# ── ajudantes de pintura ────────────────────────────────────

def paint_glow(p: QPainter, path: QPainterPath, color: QColor,
               strength: float, spread: float = 9.0) -> None:
    """Bloom barato: o mesmo contorno várias vezes, cada vez mais largo e fraco."""
    if strength <= 0.01:
        return
    layers = 4
    for i in range(layers, 0, -1):
        c = QColor(color)
        c.setAlphaF(max(0.0, min(1.0, strength * 0.16 * (i / layers) ** 1.7)))
        p.setPen(QPen(c, spread * i / layers * 2.2, Qt.SolidLine,
                      Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


def _sub_route(route: QPainterPath, t0: float, t1: float,
               steps: int = 26) -> QPainterPath:
    """Pedaço da rota entre duas frações (para rastro do cometa)."""
    t0 = max(0.0, min(1.0, t0))
    t1 = max(0.0, min(1.0, t1))
    if t1 <= t0:
        return QPainterPath()
    out = QPainterPath(route.pointAtPercent(t0))
    for i in range(1, steps + 1):
        out.lineTo(route.pointAtPercent(t0 + (t1 - t0) * i / steps))
    return out


def _outline(ctx: Ctx) -> QPainterPath:
    """Rota para efeitos que correm pela borda; cai na silhueta se não houver."""
    return ctx.route if ctx.route is not None else ctx.body


# ── efeitos: pre ────────────────────────────────────────────

def _pre_pulse(ctx: Ctx) -> None:
    u = wave01(ctx.phase)
    ctx.color = lighter(ctx.color, int(100 + 45 * u))
    ctx.alpha *= 0.66 + 0.34 * u
    ctx.glow = max(ctx.glow, 0.35 + 0.5 * u)


def _ghost_rise(ctx: Ctx) -> None:
    """Camada translúcida subindo do nível real até o topo e sumindo lá em cima.

    Fazer o próprio nível subir (v1) dava um corte seco no fim do laço e ainda
    mentia o valor. Assim o nível real continua sólido embaixo e o que sobe é
    só a "energia entrando"."""
    base = ctx.real_fill
    top = base + (1.0 - base) * smooth(ctx.phase)
    fade = 1.0 - smooth(max(0.0, (ctx.phase - 0.62) / 0.38))
    ctx.ghost = (min(1.0, top), 0.62 * fade)


def _pre_rise(ctx: Ctx) -> None:
    _ghost_rise(ctx)
    ctx.glow = max(ctx.glow, 0.35)


def _pre_wave(ctx: Ctx) -> None:
    ctx.wave = (4.0, ctx.phase)
    ctx.fill = min(1.0, ctx.real_fill + 0.015 * math.sin(ctx.phase * 2 * math.pi))
    ctx.glow = max(ctx.glow, 0.3)


def _pre_wave_rise(ctx: Ctx) -> None:
    _ghost_rise(ctx)
    ctx.wave = (4.2, ctx.phase * 3.0)
    ctx.glow = max(ctx.glow, 0.4)


def _pre_breathe(ctx: Ctx) -> None:
    u = wave01(ctx.phase)
    ctx.glow = max(ctx.glow, 0.15 + 0.85 * u)
    ctx.alpha *= 0.78 + 0.22 * u


def _pre_blink(ctx: Ctx) -> None:
    on = smooth(min(1.0, abs(math.cos(ctx.phase * math.pi * 2)) * 2.4))
    ctx.alpha *= 0.38 + 0.62 * on
    ctx.glow = max(ctx.glow, on * 0.6)


def _pre_strobe(ctx: Ctx) -> None:
    on = 1.0 if (ctx.phase * 4) % 1.0 < 0.45 else 0.32
    ctx.alpha *= on
    ctx.glow = max(ctx.glow, on)


def _pre_flash(ctx: Ctx) -> None:
    """Batida dupla e pausa — chama atenção sem virar pisca-pisca."""
    t = ctx.phase
    beat = 0.0
    for centre in (0.06, 0.24):
        d = abs(t - centre)
        if d < 0.09:
            beat = max(beat, 1.0 - d / 0.09)
    ctx.alpha *= 0.48 + 0.52 * smooth(beat)
    ctx.glow = max(ctx.glow, beat)


def _pre_shake(ctx: Ctx) -> None:
    burst = max(0.0, 1.0 - (ctx.phase % 1.0) * 2.2)
    ctx.dx = math.sin(ctx.phase * 2 * math.pi * 7) * 3.4 * burst
    ctx.glow = max(ctx.glow, burst * 0.5)


def _pre_throb(ctx: Ctx) -> None:
    ctx.scale = 1.0 + 0.075 * wave01(ctx.phase)
    ctx.glow = max(ctx.glow, 0.3 + 0.4 * wave01(ctx.phase))


def _pre_drain(ctx: Ctx) -> None:
    ctx.fill = ctx.real_fill * (1.0 - smooth(ctx.phase) * 0.85)
    ctx.glow = max(ctx.glow, 0.3)


def _pre_pop(ctx: Ctx) -> None:
    t = ctx.phase
    ctx.scale = 1.0 + 0.12 * math.sin(t * math.pi * 2) * math.exp(-t * 2.2)
    ctx.glow = max(ctx.glow, 0.5 * math.exp(-t * 2.0))


def _pre_glow_on(ctx: Ctx) -> None:
    ctx.glow = max(ctx.glow, 0.9)


def _pre_sheen(ctx: Ctx) -> None:
    ctx.glow = max(ctx.glow, 0.35)


# ── efeitos: post ───────────────────────────────────────────

def _post_comet(p: QPainter, ctx: Ctx) -> None:
    route = _outline(ctx)
    if route is None or route.isEmpty():
        return
    head = ctx.phase
    tail = 0.24
    p.setBrush(Qt.NoBrush)
    width = 9.0
    for i in range(7):
        a = (i + 1) / 7
        seg = _sub_route(route, head - tail * (1 - a * 0.86) - 0.012,
                         head - tail * (1 - a) + 0.012, 8)
        if seg.isEmpty():
            continue
        c = lighter(ctx.color, 190)
        c.setAlphaF(0.10 + 0.72 * a ** 2)
        p.setPen(QPen(c, width * (0.55 + 0.45 * a), Qt.SolidLine, Qt.RoundCap))
        p.drawPath(seg)
    pt = route.pointAtPercent(max(0.0, min(1.0, head)))
    grad = QRadialGradient(pt, 11)
    hot = lighter(ctx.color, 210)
    hot.setAlphaF(0.95)
    grad.setColorAt(0.0, hot)
    edge = QColor(hot)
    edge.setAlphaF(0.0)
    grad.setColorAt(1.0, edge)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    p.drawEllipse(pt, 11, 11)


def _post_shine(p: QPainter, ctx: Ctx) -> None:
    """Reflexo diagonal cruzando a silhueta."""
    if ctx.body is None:
        return
    pos = -40 + ctx.phase * 190
    grad = QLinearGradient(QPointF(pos - 26, 0), QPointF(pos + 26, 100))
    clear = QColor(255, 255, 255, 0)
    mid = QColor(255, 255, 255, 165)
    grad.setColorAt(0.0, clear)
    grad.setColorAt(0.45, clear)
    grad.setColorAt(0.5, mid)
    grad.setColorAt(0.55, clear)
    grad.setColorAt(1.0, clear)
    p.save()
    p.setClipPath(ctx.body, Qt.IntersectClip)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRect(QRectF(-10, -10, 120, 120))
    p.restore()


def _post_scan(p: QPainter, ctx: Ctx) -> None:
    """Varredura horizontal subindo, com borda suave."""
    if ctx.body is None:
        return
    y = 112 - ctx.phase * 132
    grad = QLinearGradient(QPointF(0, y - 20), QPointF(0, y + 12))
    c0 = lighter(ctx.color, 200)
    c0.setAlphaF(0.0)
    c1 = lighter(ctx.color, 210)
    c1.setAlphaF(0.75)
    grad.setColorAt(0.0, c0)
    grad.setColorAt(0.8, c1)
    grad.setColorAt(1.0, c0)
    p.save()
    p.setClipPath(ctx.body, Qt.IntersectClip)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRect(QRectF(-10, y - 20, 120, 32))
    p.restore()


def _post_spark(p: QPainter, ctx: Ctx) -> None:
    """Partículas subindo dentro da forma, como bolhas de energia."""
    if ctx.body is None:
        return
    p.save()
    p.setClipPath(ctx.body, Qt.IntersectClip)
    p.setPen(Qt.NoPen)
    for i in range(18):
        t = (ctx.phase + _rng(i)) % 1.0
        x = 8 + _rng(i, 3.7) * 84
        y = 98 - t * 100
        r = 2.2 + _rng(i, 9.1) * 3.2
        c = lighter(ctx.color, 200)
        c.setAlphaF(0.85 * (1 - t) * min(1.0, t * 5))
        p.setBrush(c)
        p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


def _bolt_path() -> QPainterPath:
    pts = [(57, 26), (36, 55), (48, 55), (42, 78), (64, 47), (52, 47)]
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(QPointF(*pt))
    path.closeSubpath()
    return path


def _post_bolt(p: QPainter, ctx: Ctx) -> None:
    """Selo de raio no canto, pulsando.

    Centralizado (v1) ele cobria o ícone inteiro; no canto continua óbvio e
    deixa a forma escolhida aparecer."""
    hit = smooth(max(0.0, 1.0 - (ctx.phase % 1.0) * 2.6))
    k = 0.6 + 0.4 * wave01(ctx.phase)
    cx, cy, r = 74.0, 74.0, 22.0
    p.save()
    p.setPen(Qt.NoPen)
    aura = lighter(ctx.color, 180)
    aura.setAlphaF(0.30 * (0.5 + 0.5 * hit))
    p.setBrush(aura)
    p.drawEllipse(QPointF(cx, cy), r * (1.12 + 0.16 * hit), r * (1.12 + 0.16 * hit))
    disc = QColor(18, 18, 22, 225)
    p.setBrush(disc)
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setPen(QPen(lighter(ctx.color, 150), 2.6))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r, r)

    p.translate(cx, cy)
    p.scale(0.34, 0.34)
    p.translate(-50, -52)
    body = lighter(ctx.color, 190)
    body.setAlphaF(0.75 + 0.25 * k)
    p.setPen(Qt.NoPen)
    p.setBrush(body)
    p.drawPath(_bolt_path())
    p.restore()


def _post_electric(p: QPainter, ctx: Ctx) -> None:
    """Arcos elétricos estalando ao redor do contorno."""
    route = _outline(ctx)
    if route is None or route.isEmpty():
        return
    step = int(ctx.phase * 14)          # troca de desenho em degraus, como faísca
    p.setBrush(Qt.NoBrush)
    for i in range(4):
        t = _rng(i + step * 3, 1.3)
        pt = route.pointAtPercent(t)
        nxt = route.pointAtPercent(min(1.0, t + 0.02))
        # normal ao caminho: o arco sai pra fora da forma, não em direção aleatória
        nx, ny = -(nxt.y() - pt.y()), (nxt.x() - pt.x())
        norm = math.hypot(nx, ny) or 1.0
        nx, ny = nx / norm, ny / norm
        if (pt.x() - 50) * nx + (pt.y() - 50) * ny < 0:
            nx, ny = -nx, -ny
        x, y = pt.x(), pt.y()
        path = QPainterPath(QPointF(x, y))
        for k in range(2):
            reach = 2.2 + _rng(i * 11 + k + step, 6.6) * 2.6
            side = (_rng(i * 7 + k + step, 2.1) - 0.5) * 6.0
            x += nx * reach - ny * side
            y += ny * reach + nx * side
            path.lineTo(QPointF(x, y))
        c = lighter(ctx.color, 230)
        c.setAlphaF(0.5)
        p.setPen(QPen(c, 5.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        c2 = QColor("#ffffff")
        c2.setAlphaF(0.9)
        p.setPen(QPen(c2, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)


def _post_ripple(p: QPainter, ctx: Ctx) -> None:
    """Ondas concêntricas saindo do centro."""
    if ctx.body is None:
        return
    p.save()
    p.setClipPath(ctx.body, Qt.IntersectClip)
    p.setBrush(Qt.NoBrush)
    for k in range(3):
        t = (ctx.phase + k / 3) % 1.0
        r = 6 + t * 62
        c = lighter(ctx.color, 200)
        c.setAlphaF(0.55 * (1 - t))
        p.setPen(QPen(c, 4.5 * (1 - t * 0.6)))
        p.drawEllipse(QPointF(50, 50), r, r)
    p.restore()


def _post_orbit(p: QPainter, ctx: Ctx) -> None:
    """Satélite girando por fora, com rastro."""
    cx = cy = 50.0
    rad = 45.0
    p.setPen(Qt.NoPen)
    for i in range(6):
        a = (ctx.phase - i * 0.022) * 2 * math.pi
        c = lighter(ctx.color, 200)
        c.setAlphaF(0.75 * (1 - i / 6) ** 1.6)
        p.setBrush(c)
        r = 4.6 * (1 - i / 9)
        p.drawEllipse(QPointF(cx + rad * math.cos(a), cy + rad * math.sin(a)), r, r)


def _post_halo(p: QPainter, ctx: Ctx) -> None:
    """Anéis saindo da própria silhueta — bom pra 'carga completa'."""
    if ctx.body is None:
        return
    p.setBrush(Qt.NoBrush)
    for k in range(2):
        t = (ctx.phase + k * 0.5) % 1.0
        c = QColor(ctx.color)
        c.setAlphaF(0.55 * (1 - t) ** 1.3)
        p.setPen(QPen(c, 2.5 + 4 * (1 - t)))
        p.save()
        p.translate(50, 50)
        # começa menor que a forma e cresce só um pouco: crescer pra fora
        # cortava o anel nas formas que já ocupam a caixa toda
        z = 0.86 + t * 0.2
        p.scale(z, z)
        p.translate(-50, -50)
        p.drawPath(ctx.body)
        p.restore()


def _post_sparkle(p: QPainter, ctx: Ctx) -> None:
    """Brilhinhos de quatro pontas piscando em posições fixas."""
    spots = [(22, 24), (78, 28), (30, 78), (74, 72), (50, 14)]
    p.setPen(Qt.NoPen)
    for i, (x, y) in enumerate(spots):
        t = (ctx.phase * 2 + i / len(spots)) % 1.0
        k = math.sin(t * math.pi)
        if k <= 0.02:
            continue
        r = 10 * k
        star = QPainterPath(QPointF(x, y - r))
        star.quadTo(x + r * 0.16, y - r * 0.16, x + r, y)
        star.quadTo(x + r * 0.16, y + r * 0.16, x, y + r)
        star.quadTo(x - r * 0.16, y + r * 0.16, x - r, y)
        star.quadTo(x - r * 0.16, y - r * 0.16, x, y - r)
        c = QColor("#ffffff")
        c.setAlphaF(0.9 * k)
        p.setBrush(c)
        p.drawPath(star)


def _post_check(p: QPainter, ctx: Ctx) -> None:
    """Tique desenhando-se e sumindo."""
    t = ctx.phase
    draw = smooth(min(1.0, t * 2.4))
    fade = 1.0 if t < 0.6 else max(0.0, 1 - (t - 0.6) / 0.4)
    path = QPainterPath(QPointF(30, 52))
    path.lineTo(QPointF(44, 68))
    path.lineTo(QPointF(72, 32))
    seg = _sub_route(path, 0.0, draw, 14)
    if seg.isEmpty():
        return
    p.setBrush(Qt.NoBrush)
    shadow = QColor(0, 0, 0, int(120 * fade))
    p.setPen(QPen(shadow, 13, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(seg)
    c = QColor("#ffffff")
    c.setAlphaF(fade)
    p.setPen(QPen(c, 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(seg)


def _post_alert(p: QPainter, ctx: Ctx) -> None:
    """Selo de exclamação pulsando no canto."""
    k = 0.55 + 0.45 * wave01(ctx.phase)
    cx, cy, r = 76.0, 76.0, 20.0
    p.setPen(Qt.NoPen)
    ring = QColor("#ff453a")
    ring.setAlphaF(0.35 * k)
    p.setBrush(ring)
    p.drawEllipse(QPointF(cx, cy), r * 1.18, r * 1.18)
    body = QColor("#ff453a")
    body.setAlphaF(0.6 + 0.4 * k)
    p.setBrush(body)
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(cx - 2.6, cy - 11, 5.2, 13), 2.4, 2.4)
    p.drawEllipse(QPointF(cx, cy + 8.5), 3.0, 3.0)


# ── arco-íris ───────────────────────────────────────────────
#
# Cor deixa de ser fixa e passa a ser função da fase. Como o `pre` roda antes
# da forma ser desenhada, trocar `ctx.color` recolore tudo — inclusive a pista,
# via `track_color` do renderizador.

def _hue(h: float, sat: float = 0.95, val: float = 1.0) -> QColor:
    c = QColor()
    c.setHsvF(h % 1.0, max(0.0, min(1.0, sat)), max(0.0, min(1.0, val)))
    return c


def _pre_rainbow(ctx: Ctx) -> None:
    ctx.color = _hue(ctx.phase, 0.85, 1.0)
    ctx.glow = max(ctx.glow, 0.5)


def _pre_crazy_rainbow(ctx: Ctx) -> None:
    ctx.color = _hue(ctx.phase * 3.0, 1.0, 1.0)
    ctx.glow = max(ctx.glow, 0.55 + 0.45 * wave01(ctx.phase * 3))
    ctx.scale = 1.0 + 0.05 * wave01(ctx.phase * 6)
    ctx.dx = math.sin(ctx.phase * 2 * math.pi * 5) * 1.2


def _pre_party(ctx: Ctx) -> None:
    """Salta de cor em cor, em degraus, como luz de festa."""
    step = int(ctx.phase * 8)
    ctx.color = _hue(_rng(step, 5.5), 1.0, 1.0)
    beat = smooth(max(0.0, 1.0 - (ctx.phase * 8 % 1.0) * 2.2))
    ctx.glow = max(ctx.glow, 0.35 + 0.65 * beat)
    ctx.scale = 1.0 + 0.06 * beat


def _rainbow_gradient(ctx: Ctx, turns: float, angle: float) -> QLinearGradient:
    a = angle * 2 * math.pi
    dx, dy = math.cos(a) * 90, math.sin(a) * 90
    grad = QLinearGradient(QPointF(50 - dx / 2, 50 - dy / 2),
                           QPointF(50 + dx / 2, 50 + dy / 2))
    for i in range(13):
        t = i / 12
        grad.setColorAt(t, _hue(t * turns + ctx.phase, 0.95, 1.0))
    return grad


def _paint_rainbow_over(p: QPainter, ctx: Ctx, turns: float,
                        angle: float, alpha: float) -> None:
    """Recolore o que já foi desenhado, sem pintar fora dele.

    SourceAtop é a peça central: ele só escreve onde já existe alfa, então o
    arco-íris segue exatamente a silhueta do estilo escolhido, seja qual for."""
    p.save()
    p.setOpacity(alpha)
    p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_rainbow_gradient(ctx, turns, angle)))
    p.drawRect(QRectF(-10, -10, 120, 120))
    p.restore()


def _post_rainbow_wave(p: QPainter, ctx: Ctx) -> None:
    _paint_rainbow_over(p, ctx, 1.0, 0.12, 0.92)


def _post_crazy_rainbow_wave(p: QPainter, ctx: Ctx) -> None:
    _paint_rainbow_over(p, ctx, 2.4, ctx.phase * 1.5, 1.0)
    # brilho extra correndo por cima, senão a cor sozinha fica chapada
    _post_shine(p, ctx)


# ── glitch ──────────────────────────────────────────────────
#
# Estes mexem na imagem já pronta, não no desenho: é a única forma de rasgar o
# ícone de verdade (número, velas e tudo) em vez de colar um enfeite por cima.
# Tudo é feito com QPainter e modos de composição — nenhum laço de pixel em
# Python, senão a animação não pagaria o próprio custo.

def _channel(img: QImage, colour: QColor) -> QImage:
    """Isola um canal multiplicando a imagem pela cor pura.

    Multiply no Qt também COMPÕE: onde o destino é transparente sobra a cor
    pura, e os três canais somados davam um fundo branco sólido no ícone
    inteiro. DestinationIn logo depois devolve o alfa original e o fundo some."""
    layer = img.copy()
    p = QPainter(layer)
    p.setCompositionMode(QPainter.CompositionMode_Multiply)
    p.fillRect(layer.rect(), colour)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.drawImage(0, 0, img)
    p.end()
    return layer


def _split(img: QImage, dx: int, dy: int = 0) -> QImage:
    """Aberração cromática: R pra um lado, B pro outro, G no lugar."""
    if dx == 0 and dy == 0:
        return img
    out = QImage(img.size(), QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_Plus)
    for colour, ox, oy in ((QColor(255, 0, 0), dx, dy),
                           (QColor(0, 255, 0), 0, 0),
                           (QColor(0, 0, 255), -dx, -dy)):
        p.drawImage(ox, oy, _channel(img, colour))
    p.end()
    return out


def _slices(img: QImage, seed: int, bands: int, amp: float) -> QImage:
    """Fatias horizontais deslocadas, deixando o rasgo aparecer."""
    w, h = img.width(), img.height()
    if h < 8 or bands <= 0:
        return img
    out = img.copy()
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_Source)
    for i in range(bands):
        y = int(_rng(seed * 7 + i, 1.7) * h)
        bh = max(1, int(h * (0.05 + 0.12 * _rng(seed * 11 + i, 3.3))))
        bh = min(bh, h - y) if y < h else 0
        if bh <= 0:
            continue
        shift = int(round((_rng(seed * 13 + i, 8.1) - 0.5) * 2 * amp * w))
        if shift == 0:
            continue
        band = img.copy(0, y, w, bh)
        p.fillRect(0, y, w, bh, Qt.transparent)
        p.drawImage(shift, y, band)
    p.end()
    return out


def _blocks(img: QImage, ctx: Ctx, seed: int, count: int) -> QImage:
    """Blocos de ruído, como um quadro que não terminou de chegar."""
    w, h = img.width(), img.height()
    out = img
    p = QPainter(out)
    # SourceAtop mantém o ruído dentro do ícone; com Plus os blocos apareciam
    # soltos no painel, do lado de fora do desenho
    p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
    p.setPen(Qt.NoPen)
    for i in range(count):
        bw = max(1, int(w * (0.12 + 0.3 * _rng(seed * 3 + i, 2.2))))
        bh = max(1, int(h * (0.02 + 0.06 * _rng(seed * 5 + i, 4.4))))
        x = int(_rng(seed * 17 + i, 6.6) * (w - bw))
        y = int(_rng(seed * 19 + i, 9.9) * (h - bh))
        c = QColor(ctx.color) if i % 2 else QColor("#ffffff")
        c.setAlphaF(0.25 + 0.35 * _rng(seed * 23 + i, 1.1))
        p.setBrush(c)
        p.drawRect(x, y, bw, bh)
    p.end()
    return out


def _scanlines(img: QImage, alpha: float, gap: int = 3) -> QImage:
    out = img
    p = QPainter(out)
    # mesma armadilha do _channel: Multiply pintaria as linhas no vazio também
    p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
    dark = QColor(0, 0, 0)
    dark.setAlphaF(alpha)
    for y in range(0, img.height(), gap):
        p.fillRect(0, y, img.width(), 1, dark)
    p.end()
    return out


def _glitch_frame(img: QImage, ctx: Ctx, hard: bool) -> QImage:
    """Nem todo quadro estala: o glitch bom é o que aparece e some."""
    steps = 16 if hard else 12
    seed = int(ctx.phase * steps)
    burst = _rng(seed, 0.3)
    active = burst > (0.35 if hard else 0.62)
    scale = img.width() / 48.0

    if not active:
        return _split(img, max(1, int(round(1 * scale)))) if hard else img

    amp = (0.16 if hard else 0.07) * (0.4 + 0.6 * _rng(seed, 4.7))
    img = _slices(img, seed, 5 if hard else 2, amp)
    img = _split(img, max(1, int(round((4 if hard else 2) * scale * (0.5 + burst)))),
                 int(round((1 if hard else 0) * scale)))
    if hard:
        img = _blocks(img, ctx, seed, 3)
    return img


def _pixel_glitch(img: QImage, ctx: Ctx) -> QImage:
    return _glitch_frame(img, ctx, hard=False)


def _pixel_crazy_glitch(img: QImage, ctx: Ctx) -> QImage:
    return _glitch_frame(img, ctx, hard=True)


def _pixel_vhs(img: QImage, ctx: Ctx) -> QImage:
    """Fita gasta: aberração constante, linhas e um tremor lento."""
    scale = img.width() / 48.0
    img = _split(img, max(1, int(round(2 * scale))))
    img = _scanlines(img, 0.35, max(2, int(round(3 * scale))))
    seed = int(ctx.phase * 10)
    if _rng(seed, 7.7) > 0.75:
        img = _slices(img, seed, 2, 0.08)
    return img


def _pre_neon(ctx: Ctx) -> None:
    """Letreiro de neon com mau contato."""
    step = int(ctx.phase * 22)
    dead = _rng(step, 2.9) > 0.86
    ctx.alpha *= 0.16 if dead else (0.82 + 0.18 * _rng(step, 5.1))
    ctx.glow = 0.0 if dead else 1.0
    if not dead:
        ctx.color = lighter(ctx.color, 125)



# ── família temática: tubarão, rádio e clique ───────────────
#
# Estes existem porque o aparelho é um mouse sem fio de marca de tubarão, e um
# ícone genérico desperdiça isso. Todos respeitam a regra da casa: recortam ou
# orbitam a silhueta recebida, nunca desenham uma forma própria por cima.

def _jaw_path(open_frac: float, upper: bool) -> QPainterPath:
    """Arcada de dentes. `open_frac` 0 = fechada, 1 = escancarada."""
    gap = 6 + 30 * open_frac
    y = 50 - gap if upper else 50 + gap
    sign = -1.0 if upper else 1.0
    path = QPainterPath(QPointF(-8, y - sign * 16))
    path.lineTo(QPointF(-8, y))
    n = 7
    for i in range(n):
        x0 = -8 + i * (116 / n)
        x1 = -8 + (i + 0.5) * (116 / n)
        x2 = -8 + (i + 1) * (116 / n)
        path.lineTo(QPointF(x1, y + sign * (9 + 3 * (i % 2))))
        path.lineTo(QPointF(x2, y))
    path.lineTo(QPointF(108, y - sign * 16))
    path.closeSubpath()
    return path


def _post_bite(p: QPainter, ctx: Ctx) -> None:
    """Duas arcadas fechando sobre o ícone e abrindo de novo."""
    t = ctx.phase
    # fecha rápido, segura, abre devagar: mordida tem tempo, não é senoide
    if t < 0.35:
        openness = 1.0 - smooth(t / 0.35)
    elif t < 0.5:
        openness = 0.0
    else:
        openness = smooth((t - 0.5) / 0.5)
    shut = 1.0 - openness
    p.setPen(Qt.NoPen)
    body = QColor("#f2f4f8")
    body.setAlphaF(0.90)
    p.setBrush(body)
    p.drawPath(_jaw_path(openness, True))
    p.drawPath(_jaw_path(openness, False))
    if shut > 0.75 and ctx.body is not None:
        # clarão no impacto, recortado pela silhueta
        flash = QColor("#ffffff")
        flash.setAlphaF(0.5 * (shut - 0.75) / 0.25)
        p.save()
        p.setClipPath(ctx.body, Qt.IntersectClip)
        p.setBrush(flash)
        p.drawRect(QRectF(-10, -10, 120, 120))
        p.restore()


def _fin_path() -> QPainterPath:
    """Barbatana dorsal, com a curvatura para trás que a torna reconhecível."""
    path = QPainterPath(QPointF(0, 0))
    path.cubicTo(QPointF(6, -20), QPointF(20, -30), QPointF(34, -34))
    path.cubicTo(QPointF(24, -18), QPointF(20, -8), QPointF(20, 0))
    path.closeSubpath()
    return path


def _post_fin(p: QPainter, ctx: Ctx) -> None:
    """Barbatana cruzando o ícone, deixando esteira."""
    x = -30 + ctx.phase * 170
    y = 78 + 3 * math.sin(ctx.phase * 2 * math.pi * 2)
    p.setPen(Qt.NoPen)
    # esteira
    wake = lighter(ctx.color, 190)
    wake.setAlphaF(0.35)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(wake, 2.4, Qt.SolidLine, Qt.RoundCap))
    trail = QPainterPath(QPointF(x - 46, y + 2))
    for i in range(1, 13):
        tx = x - 46 + i * 4
        trail.lineTo(QPointF(tx, y + 2 + 2.2 * math.sin(i * 0.9 + ctx.phase * 8)))
    p.drawPath(trail)
    p.setPen(Qt.NoPen)
    p.save()
    p.translate(x, y)
    fin = QColor("#e9edf4")
    fin.setAlphaF(0.95)
    p.setBrush(fin)
    p.drawPath(_fin_path())
    p.restore()


def _post_bubbles(p: QPainter, ctx: Ctx) -> None:
    """Bolhas subindo dentro da silhueta — anel claro, miolo vazado."""
    if ctx.body is None:
        return
    p.save()
    p.setClipPath(ctx.body, Qt.IntersectClip)
    p.setBrush(Qt.NoBrush)
    for i in range(14):
        t = (ctx.phase + _rng(i, 2.4)) % 1.0
        x = 8 + _rng(i, 5.1) * 84 + 3.5 * math.sin(t * 6 + i)
        y = 102 - t * 108
        r = 2.0 + _rng(i, 8.3) * 4.0
        c = lighter(ctx.color, 220)
        c.setAlphaF(0.75 * (1 - t) * min(1.0, t * 6))
        p.setPen(QPen(c, 1.8))
        p.drawEllipse(QPointF(x, y), r, r)
    p.restore()
    p.setPen(Qt.NoPen)


def _post_sonar(p: QPainter, ctx: Ctx) -> None:
    """Ping de sonar: anéis nítidos saindo de um foco baixo, com eco."""
    p.setBrush(Qt.NoBrush)
    focus = QPointF(50, 86)
    for k in range(3):
        t = (ctx.phase + k / 3) % 1.0
        r = 4 + t * 78
        c = lighter(ctx.color, 210)
        c.setAlphaF(0.6 * (1 - t) ** 1.6)
        p.setPen(QPen(c, 3.4 * (1 - t * 0.5)))
        p.drawEllipse(focus, r, r * 0.82)
    hot = lighter(ctx.color, 230)
    hot.setAlphaF(0.8)
    p.setPen(Qt.NoPen)
    p.setBrush(hot)
    p.drawEllipse(focus, 3.2, 3.2)


def _post_radar(p: QPainter, ctx: Ctx) -> None:
    """Varredura giratória com rastro, recortada pela silhueta."""
    if ctx.body is None:
        return
    p.save()
    p.setClipPath(ctx.body, Qt.IntersectClip)
    p.setPen(Qt.NoPen)
    a0 = ctx.phase * 360.0
    for i in range(10):
        span = 5.0
        c = lighter(ctx.color, 200)
        c.setAlphaF(0.5 * (1 - i / 10) ** 1.8)
        p.setBrush(c)
        p.drawPie(QRectF(-14, -14, 128, 128),
                  int((-a0 - i * span) * 16), int(-span * 16))
    p.restore()


def _post_wireless(p: QPainter, ctx: Ctx) -> None:
    """Arcos de rádio saindo do canto — o elo 2.4 GHz, que é o que fala aqui."""
    cx, cy = 76.0, 76.0
    p.setBrush(Qt.NoBrush)
    for k in range(3):
        t = (ctx.phase + k / 3) % 1.0
        r = 10 + t * 34
        c = lighter(ctx.color, 200)
        c.setAlphaF(0.85 * (1 - t) ** 1.2)
        p.setPen(QPen(c, 4.2 * (1 - t * 0.4), Qt.SolidLine, Qt.RoundCap))
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        path = QPainterPath()
        path.arcMoveTo(rect, 100)
        path.arcTo(rect, 100, 80)
        p.drawPath(path)
    p.setPen(Qt.NoPen)
    dot = lighter(ctx.color, 220)
    dot.setAlphaF(0.9)
    p.setBrush(dot)
    p.drawEllipse(QPointF(cx, cy), 4.0, 4.0)


def _pre_click(ctx: Ctx) -> None:
    """Batida curta e seca, como clique — some entre uma e outra."""
    t = ctx.phase % 1.0
    hit = smooth(max(0.0, 1.0 - t * 5.0))
    ctx.scale = 1.0 - 0.05 * hit
    ctx.dy = 2.2 * hit
    ctx.glow = max(ctx.glow, hit * 0.8)


def _post_click(p: QPainter, ctx: Ctx) -> None:
    """Onda de choque saindo do topo, onde ficariam os botões."""
    t = ctx.phase % 1.0
    if t > 0.55:
        return
    k = t / 0.55
    c = lighter(ctx.color, 210)
    c.setAlphaF(0.55 * (1 - k))
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(c, 3.0 * (1 - k * 0.5)))
    p.drawEllipse(QPointF(50, 26), 8 + k * 40, 8 + k * 40)


def _pre_dive(ctx: Ctx) -> None:
    """Mergulha e volta, com a água escurecendo no fundo do movimento."""
    t = ctx.phase
    depth = 0.5 - 0.5 * math.cos(t * 2 * math.pi)
    ctx.dy = 7.0 * depth
    ctx.scale = 1.0 - 0.05 * depth
    ctx.alpha *= 1.0 - 0.22 * depth
    ctx.glow = max(ctx.glow, 0.25 + 0.35 * (1 - depth))


def _post_prowl(p: QPainter, ctx: Ctx) -> None:
    """Barbatana rondando em volta do ícone, como quem circula a presa."""
    a = ctx.phase * 2 * math.pi
    rad = 46.0
    x, y = 50 + rad * math.cos(a), 50 + rad * math.sin(a) * 0.55 + 6
    p.setPen(Qt.NoPen)
    p.save()
    p.translate(x, y)
    # a barbatana vira para o lado em que está indo
    p.scale(-0.62 if math.sin(a) < 0 else 0.62, 0.62)
    fin = QColor("#e9edf4")
    fin.setAlphaF(0.55 if math.sin(a) < 0 else 0.95)   # some ao passar por trás
    p.setBrush(fin)
    p.drawPath(_fin_path())
    p.restore()


def _post_tide(p: QPainter, ctx: Ctx) -> None:
    """Linha d'água correndo por cima do nível, com espuma."""
    if ctx.body is None:
        return
    p.save()
    p.setClipPath(ctx.body, Qt.IntersectClip)
    y = 100 - 100 * ctx.real_fill
    p.setBrush(Qt.NoBrush)
    for k in range(2):
        c = lighter(ctx.color, 220)
        c.setAlphaF(0.7 - 0.35 * k)
        p.setPen(QPen(c, 2.4 - 0.8 * k, Qt.SolidLine, Qt.RoundCap))
        path = QPainterPath()
        for i in range(31):
            x = -6 + i * (112 / 30)
            yy = (y + k * 4.5
                  + 3.0 * math.sin((x / 26) + ctx.phase * 6.283 * (1 + 0.35 * k)))
            path.lineTo(QPointF(x, yy)) if i else path.moveTo(QPointF(x, yy))
        p.drawPath(path)
    p.restore()
    p.setPen(Qt.NoPen)


@dataclass
class Effect:
    key: str
    label: str
    pre: Callable | None = None
    post: Callable | None = None
    pixel: Callable | None = None      # (QImage, Ctx) -> QImage


def _fx(key, label, pre=None, post=None, pixel=None) -> Effect:
    return Effect(key, label, pre, post, pixel)


EFFECTS: dict[str, Effect] = {e.key: e for e in [
    _fx("none", "None"),
    _fx("pulse", "Pulse", _pre_pulse),
    _fx("breathe", "Breathe", _pre_breathe),
    _fx("glow", "Steady glow", _pre_glow_on),
    _fx("rise", "Fill rise", _pre_rise),
    _fx("wave", "Liquid wave", _pre_wave),
    _fx("wave_rise", "Liquid rise", _pre_wave_rise),
    _fx("comet", "Comet", _pre_sheen, _post_comet),
    _fx("shine", "Shine sweep", _pre_sheen, _post_shine),
    _fx("scan", "Scan line", _pre_sheen, _post_scan),
    _fx("spark", "Rising sparks", _pre_sheen, _post_spark),
    _fx("bolt", "Lightning bolt", None, _post_bolt),
    _fx("electric", "Electric arcs", _pre_sheen, _post_electric),
    _fx("ripple", "Ripple", _pre_sheen, _post_ripple),
    _fx("orbit", "Orbiting dot", None, _post_orbit),
    _fx("blink", "Blink", _pre_blink),
    _fx("strobe", "Strobe", _pre_strobe),
    _fx("flash", "Heartbeat flash", _pre_flash),
    _fx("shake", "Shake", _pre_shake),
    _fx("throb", "Throb", _pre_throb),
    _fx("drain", "Draining", _pre_drain),
    _fx("halo", "Halo rings", None, _post_halo),
    _fx("alert", "Alert badge", _pre_breathe, _post_alert),
    _fx("sparkle", "Sparkle", None, _post_sparkle),
    _fx("pop", "Pop", _pre_pop),
    _fx("check", "Checkmark", None, _post_check),
    # família temática
    _fx("bite", "Shark bite", None, _post_bite),
    _fx("fin", "Passing fin", _pre_sheen, _post_fin),
    _fx("prowl", "Prowling fin", None, _post_prowl),
    _fx("bubbles", "Bubbles", _pre_sheen, _post_bubbles),
    _fx("tide", "Tide line", _pre_sheen, _post_tide),
    _fx("sonar", "Sonar ping", _pre_sheen, _post_sonar),
    _fx("radar", "Radar sweep", None, _post_radar),
    _fx("wireless", "Radio waves", _pre_sheen, _post_wireless),
    _fx("click", "Click", _pre_click, _post_click),
    _fx("dive", "Dive", _pre_dive),
    # arco-íris e glitch
    _fx("rainbow", "Rainbow", _pre_rainbow),
    _fx("rainbow_wave", "More rainbow", _pre_sheen, _post_rainbow_wave),
    _fx("crazy_rainbow", "Crazy rainbow", _pre_crazy_rainbow,
        _post_crazy_rainbow_wave),
    _fx("party", "Party lights", _pre_party),
    _fx("neon", "Neon flicker", _pre_neon),
    _fx("glitch", "Glitch", None, None, _pixel_glitch),
    _fx("crazy_glitch", "Crazy glitch", _pre_shake, None, _pixel_crazy_glitch),
    _fx("vhs", "VHS", _pre_sheen, None, _pixel_vhs),
    _fx("rainbow_glitch", "Rainbow glitch", _pre_rainbow, _post_rainbow_wave,
        _pixel_glitch),
    _fx("crazy_rainbow_glitch", "Crazy rainbow glitch", _pre_crazy_rainbow,
        _post_crazy_rainbow_wave, _pixel_crazy_glitch),
]}

# efeitos de puro espetáculo: valem em qualquer evento, então entram em todas
# as listas de uma vez em vez de serem repetidos à mão em cada uma
SHOWOFF = ["rainbow", "rainbow_wave", "crazy_rainbow", "rainbow_glitch",
           "crazy_rainbow_glitch", "glitch", "crazy_glitch", "vhs", "party",
           "neon"]

# quais efeitos fazem sentido em cada evento (a ordem é a do menu)
FOR_CHARGING = ["wave_rise", "wave", "rise", "tide", "bubbles", "comet",
                "shine", "scan", "spark", "bolt", "electric", "ripple",
                "wireless", "sonar", "orbit", "pulse", "breathe", "throb",
                "glow", "none"]
FOR_LOW = ["breathe", "pulse", "blink", "flash", "throb", "shake", "halo",
           "alert", "drain", "prowl", "sonar", "dive", "glow", "none"]
FOR_CRITICAL = ["flash", "bite", "blink", "strobe", "shake", "alert",
                "pulse", "breathe", "halo", "drain", "throb", "none"]
FOR_FULL = ["halo", "sparkle", "shine", "pop", "check", "breathe", "glow",
            "pulse", "comet", "ripple", "bite", "tide", "none"]
FOR_IDLE = ["none", "breathe", "glow", "pulse", "shine", "comet", "orbit",
            "prowl", "fin", "tide", "radar", "wireless", "click", "dive",
            "bubbles"]

for _list in (FOR_CHARGING, FOR_LOW, FOR_CRITICAL, FOR_FULL, FOR_IDLE):
    # entram antes do "none" final, que é sempre a última opção da lista
    _at = _list.index("none") if "none" in _list else len(_list)
    _list[_at:_at] = SHOWOFF


def options(event: str) -> list[tuple[str, str]]:
    """[(chave, rótulo)] dos efeitos oferecidos para o evento."""
    keys = {"charging": FOR_CHARGING, "low": FOR_LOW, "critical": FOR_CRITICAL,
            "full": FOR_FULL, "idle": FOR_IDLE}.get(event, ["none"])
    return [(k, EFFECTS[k].label) for k in keys if k in EFFECTS]


def get(key: str) -> Effect:
    return EFFECTS.get(key, EFFECTS["none"])


def is_static(key: str) -> bool:
    """Efeitos que não precisam de timer rodando."""
    return key in ("none", "glow")
