"""
Formas dos icones.

Cada estilo devolve um `Geom` puramente geometrico (espaco 100x100, sem cor e
sem nivel), entao da pra cachear: a geometria so muda quando o estilo ou a
espessura mudam, nunca a cada quadro de animacao.

O contrato e estreito de proposito, porque e ele que deixa QUALQUER efeito
funcionar com QUALQUER forma:

    body   silhueta preenchivel - serve de traco apagado, de recorte pros
           efeitos (brilho, faisca, varredura) e de fonte do glow
    route  linha de centro, quando existe - o cometa corre por ela e o modo
           "progress" preenche por ela
    axis   'v' enche de baixo pra cima, 'h' da esquerda pra direita
    over   detalhes desenhados por cima (numero, marca), ja com o nivel

As formas de tubarao sao desenho proprio, inspirado na marca do mouse - nao
sao o logotipo da Attack Shark, que e deles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath,
                           QPainterPathStroker, QPen)

# chave -> rotulo no menu (interface toda em ingles)
STYLES: dict[str, str] = {
    # o aparelho
    "mouse":          "Mouse",
    "mouse_outline":  "Mouse (outline)",
    "mouse_gaming":   "Gaming mouse",
    "mouse_side":     "Mouse (side view)",
    "wheel":          "Scroll wheel",
    "sensor":         "Optical sensor",
    "dongle":         "USB receiver",
    "cursor":         "Pointer",
    # a marca
    "shark":          "Shark",
    "shark_badge":    "Shark badge",
    "shark_ring":     "Shark ring",
    "shark_shield":   "Shark shield",
    "fin":            "Dorsal fin",
    "jaws":           "Jaws",
    "tooth":          "Shark tooth",
    "monogram":       "AS monogram",
    # medidores
    "battery":        "Battery",
    "battery_vert":   "Battery (upright)",
    "bolt_battery":   "Battery with bolt",
    "ring":           "Ring gauge",
    "dual_ring":      "Double ring",
    "arc_gauge":      "Arc gauge",
    "bars":           "Bars",
    "dots":           "Dots",
    "ticks":          "Segmented ring",
    "capsule":        "Capsule",
    "hex":            "Hexagon",
    "shield":         "Shield",
    "droplet":        "Tank",
    "badge":          "Number badge",
    "chip":           "Cell",
}

# estilos onde cabe o numero sobreposto
NUMBER_STYLES = {"ring", "dual_ring", "badge", "droplet", "hex", "shield",
                 "arc_gauge", "ticks", "chip", "shark_badge", "shark_ring",
                 "shark_shield", "mouse", "mouse_outline", "monogram"}

WEIGHTS = {"thin": 0.72, "normal": 1.0, "bold": 1.34}


@dataclass
class Geom:
    body: QPainterPath                      # silhueta preenchivel
    route: QPainterPath | None = None       # linha de centro (cometa/progress)
    axis: str = "v"                         # 'v' | 'h'
    stroke_w: float = 10.0                  # espessura usada no modo progress
    prefer: str = "liquid"                  # liquid | progress
    detail: Callable | None = None          # tracos da forma, sempre visiveis
    over: Callable | None = None            # numero, que o usuario pode desligar
    custom: Callable | None = None          # desenho proprio (barras, pontos)
    parts: list = field(default_factory=list)   # partes que sempre enchem por regiao


# -- utilidades de caminho -----------------------------------

def _stroke(path: QPainterPath, width: float,
            cap=Qt.RoundCap, join=Qt.RoundJoin) -> QPainterPath:
    """Converte uma linha em silhueta preenchivel."""
    st = QPainterPathStroker()
    st.setWidth(width)
    st.setCapStyle(cap)
    st.setJoinStyle(join)
    return st.createStroke(path).simplified()


def _rrect(rect: QRectF, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, r, r)
    return path


def _arc_route(rect: QRectF, start_deg: float, span_deg: float) -> QPainterPath:
    path = QPainterPath()
    path.arcMoveTo(rect, start_deg)
    path.arcTo(rect, start_deg, span_deg)
    return path


def _poly(points: list[tuple[float, float]]) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for pt in points[1:]:
        path.lineTo(QPointF(*pt))
    path.closeSubpath()
    return path


def _hexagon(cx: float, cy: float, r: float) -> QPainterPath:
    pts = [(cx + r * math.cos(math.radians(a - 90)),
            cy + r * math.sin(math.radians(a - 90))) for a in range(0, 360, 60)]
    return _poly(pts)


def _shield_path() -> QPainterPath:
    path = QPainterPath(QPointF(50, 8))
    path.lineTo(88, 22)
    path.cubicTo(88, 62, 74, 82, 50, 94)
    path.cubicTo(26, 82, 12, 62, 12, 22)
    path.closeSubpath()
    return path


def draw_number(p: QPainter, rect: QRectF, level: int, color: QColor,
                filled_frac: float, size: int, px: int = 40) -> None:
    """Numero legivel: vazado quando o preenchimento ja cobriu a area."""
    if size < 30:
        return
    txt = str(level)
    font = QFont()
    font.setPixelSize(px if len(txt) < 3 else int(px * 0.74))
    font.setBold(True)
    p.setFont(font)
    covered = filled_frac > 1.0 - (rect.center().y() / 100.0) - 0.04
    p.setPen(QPen(QColor("#101014") if covered else color))
    p.drawText(rect, Qt.AlignCenter, txt)


# -- a marca -------------------------------------------------

def shark_path() -> QPainterPath:
    """Tubarao de perfil, nadando para a direita.

    Desenhado como uma silhueta unica e fechada porque ela precisa servir de
    recorte para os efeitos: se as barbatanas fossem sub-caminhos separados, a
    varredura e o brilho vazariam entre elas.

    Proporcoes que decidem se o olho ve tubarao ou peixe generico: a dorsal
    tem que nascer no meio do dorso e ser estreita (uma dorsal larga e adiantada
    vira asa de golfinho), a peitoral tem que ser pequena e adiantada (grande
    demais e o desenho ganha duas caudas), e a cauda precisa do lobo superior
    bem mais longo que o inferior."""
    p = QPainterPath(QPointF(98, 55))              # focinho, pontudo
    # dorso ate a base da dorsal
    p.cubicTo(QPointF(86, 44), QPointF(72, 39), QPointF(58, 38))
    # barbatana dorsal: estreita e inclinada para tras
    p.lineTo(QPointF(48, 12))
    p.cubicTo(QPointF(46, 26), QPointF(43, 34), QPointF(38, 39))
    # dorso ate o pedunculo
    p.cubicTo(QPointF(30, 41), QPointF(22, 44), QPointF(16, 48))
    # cauda: lobo superior longo, entalhe, lobo inferior curto
    p.lineTo(QPointF(3, 20))
    p.cubicTo(QPointF(7, 40), QPointF(10, 50), QPointF(14, 56))
    p.cubicTo(QPointF(11, 63), QPointF(9, 70), QPointF(8, 78))
    p.cubicTo(QPointF(13, 71), QPointF(18, 65), QPointF(22, 61))
    # barriga ate a base da peitoral
    p.cubicTo(QPointF(32, 65), QPointF(42, 67), QPointF(52, 68))
    # barbatana peitoral: curta, apontando para tras e para baixo
    p.lineTo(QPointF(50, 84))
    p.cubicTo(QPointF(58, 76), QPointF(63, 72), QPointF(68, 70))
    # barriga ate o focinho
    p.cubicTo(QPointF(80, 68), QPointF(92, 63), QPointF(98, 55))
    p.closeSubpath()
    return p


def _shark_eye(p: QPainter, color: QColor, frac: float) -> None:
    """Olho vazado. Escurece junto com o corpo quando o nivel cobre a altura."""
    p.setBrush(QColor("#101014") if frac > 0.52 else color.darker(220))
    p.drawEllipse(QPointF(84, 53), 3.2, 3.2)


def fin_path() -> QPainterPath:
    """Barbatana dorsal isolada, grande."""
    p = QPainterPath(QPointF(10, 88))
    p.cubicTo(QPointF(26, 60), QPointF(52, 26), QPointF(84, 8))
    p.cubicTo(QPointF(70, 40), QPointF(66, 66), QPointF(66, 88))
    p.closeSubpath()
    return p


def tooth_path() -> QPainterPath:
    """Dente com a ponta curva e um entalhe raso na raiz.

    O entalhe tem que ser RASO: fundo demais e o dente vira tenda, que foi o
    que aconteceu na primeira versao."""
    p = QPainterPath(QPointF(50, 5))
    p.cubicTo(QPointF(64, 34), QPointF(76, 62), QPointF(80, 88))
    p.lineTo(QPointF(62, 88))
    p.cubicTo(QPointF(59, 82), QPointF(55, 79), QPointF(50, 79))
    p.cubicTo(QPointF(45, 79), QPointF(41, 82), QPointF(38, 88))
    p.lineTo(QPointF(20, 88))
    p.cubicTo(QPointF(24, 62), QPointF(36, 34), QPointF(50, 5))
    p.closeSubpath()
    return p


def jaws_path(w: float) -> QPainterPath:
    """Duas arcadas encaradas, com a boca aberta entre elas.

    A versao anterior punha as gengivas curvando PARA DENTRO e os dentes
    saindo do mesmo lado: as duas arcadas se cruzavam no meio e o desenho lia
    como ampulheta. Aqui cada gengiva curva para fora e os dentes apontam para
    o vao central, que e o que faz parecer boca."""
    body = QPainterPath()
    for upper in (True, False):
        sign = 1.0 if upper else -1.0
        y = 50 - sign * 16            # borda da gengiva, virada para o centro
        arc = QPainterPath(QPointF(6, y - sign * 26))
        arc.cubicTo(QPointF(6, y - sign * 4), QPointF(94, y - sign * 4),
                    QPointF(94, y - sign * 26))
        gums = _stroke(arc, 10 * w)
        teeth = QPainterPath()
        n = 7
        for i in range(n):
            x0 = 10 + i * (80 / n)
            x1 = x0 + (80 / n)
            # dente menor nas pontas: acompanha a curva da arcada
            edge = abs((i + 0.5) / n - 0.5) * 2
            depth = 17 * (1.0 - 0.45 * edge)
            teeth = teeth.united(_poly([(x0, y - sign * 5), (x1, y - sign * 5),
                                        ((x0 + x1) / 2, y + sign * depth)]))
        body = body.united(gums.united(teeth))
    return body


def monogram_path(w: float) -> QPainterPath:
    """Monograma AS: o A vira barbatana, o S vira o corpo do tubarao."""
    a = QPainterPath(QPointF(6, 84))
    a.lineTo(QPointF(28, 16))
    a.lineTo(QPointF(50, 84))
    stroke_a = _stroke(a, 11 * w, Qt.FlatCap, Qt.MiterJoin)
    crossbar = QPainterPath(QPointF(16, 62))
    crossbar.lineTo(QPointF(40, 62))
    bar = _stroke(crossbar, 9 * w, Qt.FlatCap)

    s = QPainterPath(QPointF(92, 28))
    s.cubicTo(QPointF(92, 14), QPointF(62, 14), QPointF(62, 32))
    s.cubicTo(QPointF(62, 48), QPointF(92, 46), QPointF(92, 64))
    s.cubicTo(QPointF(92, 84), QPointF(62, 84), QPointF(62, 70))
    return stroke_a.united(bar).united(_stroke(s, 11 * w))


# -- o aparelho ----------------------------------------------

def mouse_path() -> QPainterPath:
    """Mouse visto de cima: ombros largos, traseira arredondada."""
    p = QPainterPath(QPointF(50, 6))
    p.cubicTo(QPointF(72, 6), QPointF(84, 22), QPointF(85, 46))
    p.cubicTo(QPointF(86, 70), QPointF(74, 94), QPointF(50, 94))
    p.cubicTo(QPointF(26, 94), QPointF(14, 70), QPointF(15, 46))
    p.cubicTo(QPointF(16, 22), QPointF(28, 6), QPointF(50, 6))
    p.closeSubpath()
    return p


def _mouse_split(w: float) -> QPainterPath:
    """Fenda entre os botoes + roda: e o que faz a silhueta virar mouse."""
    split = QPainterPath(QPointF(50, 8))
    split.lineTo(QPointF(50, 40))
    out = _stroke(split, 3.4 * w, Qt.FlatCap)
    wheel = _rrect(QRectF(45.5, 14, 9, 17), 4.5)
    return out.united(wheel)


def mouse_side_path() -> QPainterPath:
    """Perfil lateral: base reta, bico baixo na frente, corcova atras.

    Duas coisas quebram esse desenho: base curva (vira sapato) e corcova no
    meio (vira pedra). A corcova fica nos ultimos 30% do comprimento."""
    p = QPainterPath(QPointF(12, 78))
    p.cubicTo(QPointF(10, 66), QPointF(15, 57), QPointF(28, 52))
    p.cubicTo(QPointF(46, 45), QPointF(62, 32), QPointF(76, 32))
    p.cubicTo(QPointF(87, 32), QPointF(92, 41), QPointF(92, 56))
    p.lineTo(QPointF(92, 74))
    p.cubicTo(QPointF(92, 78), QPointF(89, 79), QPointF(84, 79))
    p.lineTo(QPointF(12, 78))
    p.closeSubpath()
    return p


# -- estilos# -- estilos -------------------------------------------------

def _mouse_detail(w: float):
    """Fenda dos botoes e roda, desenhadas POR CIMA do preenchimento.

    Como parte de `parts` elas sumiam: `parts` e pintado antes do liquido, e
    aqui os tracos ficam dentro da silhueta, entao o proprio nivel os cobria."""
    split = _mouse_split(w)

    def detail(p: QPainter, level: int, color: QColor, dim: QColor,
               frac: float, size: int) -> None:
        p.setPen(Qt.NoPen)
        # escuro sobre a parte cheia, claro sobre a vazia: legivel nos dois lados
        p.setBrush(QColor(16, 16, 20, 210) if frac > 0.62 else dim.darker(150))
        p.drawPath(split)

    return detail


def _g_mouse(w: float) -> Geom:
    body = mouse_path()

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        draw_number(p, QRectF(20, 46, 60, 38), level, color, frac, size, 30)

    return Geom(body=body, axis="v", over=over, detail=_mouse_detail(w))


def _g_mouse_outline(w: float) -> Geom:
    outer = mouse_path()
    inner = _stroke(outer, 9 * w)
    body = outer.intersected(inner)          # so a casca

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        draw_number(p, QRectF(20, 40, 60, 40), level, color, 0.0, size, 32)

    return Geom(body=body, axis="v", over=over)


def _g_mouse_gaming(w: float) -> Geom:
    body = mouse_path()
    side = _rrect(QRectF(4, 38, 12, 22), 5)      # botoes laterais
    return Geom(body=body.united(side), axis="v", detail=_mouse_detail(w))


def _g_mouse_side(w: float) -> Geom:
    body = mouse_side_path()
    # cabo curto saindo do bico: longo demais vira alca de bolsa
    cable = QPainterPath(QPointF(12, 62))
    cable.cubicTo(QPointF(4, 58), QPointF(2, 48), QPointF(6, 40))

    def detail(p: QPainter, level: int, color: QColor, dim: QColor,
               frac: float, size: int) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(dim.darker(120))
        p.drawPath(_stroke(cable, 5 * w))

    return Geom(body=body, axis="h", detail=detail)


def _g_wheel(w: float) -> Geom:
    body = _rrect(QRectF(36, 12, 28, 76), 14)
    ridges = QPainterPath()
    for i in range(5):
        ridges = ridges.united(_rrect(QRectF(41, 25 + i * 13, 18, 4), 2))

    def detail(p: QPainter, level: int, color: QColor, dim: QColor,
               frac: float, size: int) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(16, 16, 20, 180))
        p.drawPath(ridges)

    return Geom(body=body, axis="v", detail=detail)


def _g_sensor(w: float) -> Geom:
    body = QPainterPath()
    body.addEllipse(QPointF(50, 50), 30, 30)
    ring = QPainterPath()
    ring.addEllipse(QPointF(50, 50), 42, 42)
    hole = QPainterPath()
    hole.addEllipse(QPointF(50, 50), 42 - 7 * w, 42 - 7 * w)
    beams = QPainterPath()
    for a in range(0, 360, 45):
        r = math.radians(a)
        line = QPainterPath(QPointF(50 + 46 * math.cos(r), 50 + 46 * math.sin(r)))
        line.lineTo(QPointF(50 + 54 * math.cos(r), 50 + 54 * math.sin(r)))
        beams = beams.united(_stroke(line, 5 * w))
    return Geom(body=body, parts=[("frame", ring.subtracted(hole)),
                                  ("frame_dim", beams)])


def _g_dongle(w: float) -> Geom:
    body = _rrect(QRectF(24, 26, 52, 48), 10)
    plug = _rrect(QRectF(36, 6, 28, 22), 4)
    pins = _rrect(QRectF(41, 10, 18, 8), 2)
    return Geom(body=body, axis="v",
                parts=[("frame", plug.subtracted(pins))])


def _g_cursor(w: float) -> Geom:
    body = _poly([(22, 8), (22, 78), (39, 62), (50, 88), (62, 82),
                  (51, 57), (72, 55)])
    return Geom(body=body, axis="v")


def _g_shark(w: float) -> Geom:
    body = shark_path()

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        if size >= 22:
            p.setPen(Qt.NoPen)
            _shark_eye(p, color, frac)

    return Geom(body=body, axis="h", over=over)


def _g_shark_badge(w: float) -> Geom:
    body = _rrect(QRectF(8, 8, 84, 84), 20)

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        p.save()
        p.translate(50, 52)
        p.scale(0.66, 0.66)
        p.translate(-50, -50)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#101014") if frac > 0.5 else color)
        p.drawPath(shark_path())
        p.restore()

    return Geom(body=body, over=over)


def _g_shark_ring(w: float) -> Geom:
    rect = QRectF(9, 9, 82, 82)
    route = _arc_route(rect, 225, -270)

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        p.save()
        p.translate(50, 52)
        p.scale(0.56, 0.56)
        p.translate(-50, -50)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPath(shark_path())
        p.restore()

    return Geom(body=_stroke(route, 9 * w), route=route, stroke_w=9 * w,
                prefer="progress", over=over)


def _g_shark_shield(w: float) -> Geom:
    body = _shield_path()

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        p.save()
        p.translate(50, 50)
        p.scale(0.58, 0.58)
        p.translate(-50, -50)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#101014") if frac > 0.5 else color)
        p.drawPath(shark_path())
        p.restore()

    return Geom(body=body, over=over)


def _g_fin(w: float) -> Geom:
    body = fin_path()
    line = QPainterPath(QPointF(2, 90))
    for i in range(1, 13):
        x = 2 + i * 8.2
        line.lineTo(QPointF(x, 90 + (3.5 if i % 2 else -3.5)))
    water = _stroke(line, 4.5 * w)

    def detail(p: QPainter, level: int, color: QColor, dim: QColor,
               frac: float, size: int) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPath(water)

    return Geom(body=body, axis="v", detail=detail)


def _g_jaws(w: float) -> Geom:
    return Geom(body=jaws_path(w), axis="h")


def _g_tooth(w: float) -> Geom:
    return Geom(body=tooth_path(), axis="v")


def _g_monogram(w: float) -> Geom:
    return Geom(body=monogram_path(w), axis="h")


def _g_battery(w: float) -> Geom:
    shell = _rrect(QRectF(8, 30, 74, 40), 9)
    inner = _rrect(QRectF(8 + 6 * w, 30 + 6 * w, 74 - 12 * w, 40 - 12 * w), 4)
    nub = _rrect(QRectF(83, 41, 9, 18), 3)
    body = _rrect(QRectF(14, 36, 62, 28), 5)
    return Geom(body=body, axis="h",
                parts=[("frame", shell.subtracted(inner).united(nub))])


def _g_battery_vert(w: float) -> Geom:
    shell = _rrect(QRectF(30, 14, 40, 76), 9)
    inner = _rrect(QRectF(30 + 6 * w, 14 + 6 * w, 40 - 12 * w, 76 - 12 * w), 4)
    nub = _rrect(QRectF(41, 5, 18, 9), 3)
    body = _rrect(QRectF(36, 20, 28, 64), 5)
    return Geom(body=body, axis="v",
                parts=[("frame", shell.subtracted(inner).united(nub))])


def _g_bolt_battery(w: float) -> Geom:
    shell = _rrect(QRectF(8, 28, 74, 44), 10)
    inner = _rrect(QRectF(8 + 6 * w, 28 + 6 * w, 74 - 12 * w, 44 - 12 * w), 5)
    nub = _rrect(QRectF(83, 40, 9, 20), 3)
    bolt = _poly([(52, 33), (33, 55), (44, 55), (39, 71), (58, 47), (47, 47)])
    body = _rrect(QRectF(14, 34, 62, 32), 6).subtracted(
        _stroke(bolt, 6).united(bolt))
    return Geom(body=body, axis="h",
                parts=[("frame", shell.subtracted(inner).united(nub))])


def _g_ring(w: float) -> Geom:
    rect = QRectF(14, 14, 72, 72)
    route = _arc_route(rect, 225, -270)

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        draw_number(p, QRectF(14, 26, 72, 48), level, color, 0.0, size, 36)

    return Geom(body=_stroke(route, 11 * w), route=route, stroke_w=11 * w,
                prefer="progress", over=over)


def _g_dual_ring(w: float) -> Geom:
    outer = QRectF(10, 10, 80, 80)
    inner = QRectF(24, 24, 52, 52)
    route = _arc_route(outer, 225, -270)
    ring2 = _stroke(_arc_route(inner, 225, -270), 4 * w)

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        draw_number(p, QRectF(24, 32, 52, 40), level, color, 0.0, size, 30)

    return Geom(body=_stroke(route, 9 * w), route=route, stroke_w=9 * w,
                prefer="progress", over=over, parts=[("frame", ring2)])


def _g_arc_gauge(w: float) -> Geom:
    rect = QRectF(10, 18, 80, 80)
    route = _arc_route(rect, 200, -220)

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        draw_number(p, QRectF(20, 40, 60, 34), level, color, 0.0, size, 30)

    return Geom(body=_stroke(route, 13 * w), route=route, stroke_w=13 * w,
                prefer="progress", over=over)


def _bar_rects() -> list[QRectF]:
    return [QRectF(11 + i * 17, 92 - (24 + i * 14), 12, 24 + i * 14)
            for i in range(5)]


def _g_bars(w: float) -> Geom:
    rects = _bar_rects()
    body = QPainterPath()
    for r in rects:
        body = body.united(_rrect(r, 3))

    def custom(p: QPainter, level: int, color: QColor, dim: QColor,
               frac: float, size: int) -> None:
        lit = frac * len(rects)
        p.setPen(Qt.NoPen)
        for i, r in enumerate(rects):
            p.setBrush(dim)
            p.drawRoundedRect(r, 3, 3)
            take = max(0.0, min(1.0, lit - i))
            if take > 0:
                h = r.height() * take
                p.setBrush(color)
                p.drawRoundedRect(QRectF(r.x(), r.bottom() - h, r.width(), h), 3, 3)

    return Geom(body=body, custom=custom)


def _dot_points() -> list[QPointF]:
    return [QPointF(50 + 34 * math.cos(math.radians(-90 + i * 72)),
                    50 + 34 * math.sin(math.radians(-90 + i * 72)))
            for i in range(5)]


def _g_dots(w: float) -> Geom:
    pts = _dot_points()
    r = 11 * w
    body = QPainterPath()
    for pt in pts:
        d = QPainterPath()
        d.addEllipse(pt, r, r)
        body = body.united(d)

    def custom(p: QPainter, level: int, color: QColor, dim: QColor,
               frac: float, size: int) -> None:
        lit = frac * len(pts)
        p.setPen(Qt.NoPen)
        for i, pt in enumerate(pts):
            take = max(0.0, min(1.0, lit - i))
            p.setBrush(dim)
            p.drawEllipse(pt, r, r)
            if take > 0:
                c = QColor(color)
                c.setAlphaF(c.alphaF() * (0.35 + 0.65 * take))
                p.setBrush(c)
                p.drawEllipse(pt, r * (0.55 + 0.45 * take), r * (0.55 + 0.45 * take))

    return Geom(body=body, custom=custom)


def _tick_paths(w: float) -> list[QPainterPath]:
    out = []
    n = 12
    for i in range(n):
        a = math.radians(-215 + i * (250 / (n - 1)))
        c, s = math.cos(a), math.sin(a)
        p1 = QPointF(50 + 29 * c, 50 + 29 * s)
        p2 = QPointF(50 + 43 * c, 50 + 43 * s)
        line = QPainterPath(p1)
        line.lineTo(p2)
        out.append(_stroke(line, 8 * w))
    return out


def _g_ticks(w: float) -> Geom:
    ticks = _tick_paths(w)
    body = QPainterPath()
    for t in ticks:
        body = body.united(t)

    def custom(p: QPainter, level: int, color: QColor, dim: QColor,
               frac: float, size: int) -> None:
        lit = frac * len(ticks)
        p.setPen(Qt.NoPen)
        for i, t in enumerate(ticks):
            take = max(0.0, min(1.0, lit - i))
            if take <= 0:
                p.setBrush(dim)
            else:
                c = QColor(color)
                c.setAlphaF(c.alphaF() * (0.4 + 0.6 * take))
                p.setBrush(c)
            p.drawPath(t)

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        draw_number(p, QRectF(25, 32, 50, 38), level, color, 0.0, size, 30)

    return Geom(body=body, custom=custom, over=over)


def _g_capsule(w: float) -> Geom:
    outer = QRectF(32, 8, 36, 84)
    body = _rrect(QRectF(38, 14, 24, 72), 12)
    frame = _rrect(outer, 18).subtracted(_rrect(
        QRectF(32 + 5 * w, 8 + 5 * w, 36 - 10 * w, 84 - 10 * w), 14))
    return Geom(body=body, parts=[("frame", frame)])


def _g_hex(w: float) -> Geom:
    body = _hexagon(50, 50, 38)
    frame = _hexagon(50, 50, 45).subtracted(_hexagon(50, 50, 45 - 6 * w))

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        draw_number(p, QRectF(20, 32, 60, 36), level, color, frac, size, 34)

    return Geom(body=body, parts=[("frame", frame)], over=over)


def _g_shield(w: float) -> Geom:
    body = _shield_path()

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        draw_number(p, QRectF(20, 34, 60, 36), level, color, frac, size, 32)

    return Geom(body=body, over=over)


def _g_droplet(w: float) -> Geom:
    body = QPainterPath()
    body.addEllipse(QPointF(50, 52), 36, 36)
    ring = QPainterPath()
    ring.addEllipse(QPointF(50, 52), 44, 44)
    hole = QPainterPath()
    hole.addEllipse(QPointF(50, 52), 44 - 6 * w, 44 - 6 * w)

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        draw_number(p, QRectF(20, 34, 60, 36), level, color, frac, size, 34)

    return Geom(body=body, parts=[("frame", ring.subtracted(hole))], over=over)


def _g_badge(w: float) -> Geom:
    body = _rrect(QRectF(6, 18, 88, 60), 16)
    under_bg = _rrect(QRectF(10, 84, 80, 8), 4)

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        rect = QRectF(6, 18, 88, 60)
        draw_number(p, rect, level, color, frac, size, 44)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(10, 84, max(5.0, 80 * frac), 8), 4, 4)

    return Geom(body=body, over=over, parts=[("frame_dim", under_bg)])


def _g_chip(w: float) -> Geom:
    body = _rrect(QRectF(18, 22, 64, 56), 8)
    frame = _rrect(QRectF(12, 16, 76, 68), 12).subtracted(
        _rrect(QRectF(12 + 5 * w, 16 + 5 * w, 76 - 10 * w, 68 - 10 * w), 8))
    pins = QPainterPath()
    for x in (26, 46, 66):
        pins = pins.united(_rrect(QRectF(x, 84, 12, 8), 3))
        pins = pins.united(_rrect(QRectF(x, 8, 12, 8), 3))

    def over(p: QPainter, level: int, color: QColor, frac: float, size: int) -> None:
        draw_number(p, QRectF(18, 24, 64, 52), level, color, frac, size, 32)

    return Geom(body=body, over=over, parts=[("frame", frame.united(pins))])


_BUILDERS = {
    "mouse": _g_mouse,
    "mouse_outline": _g_mouse_outline,
    "mouse_gaming": _g_mouse_gaming,
    "mouse_side": _g_mouse_side,
    "wheel": _g_wheel,
    "sensor": _g_sensor,
    "dongle": _g_dongle,
    "cursor": _g_cursor,
    "shark": _g_shark,
    "shark_badge": _g_shark_badge,
    "shark_ring": _g_shark_ring,
    "shark_shield": _g_shark_shield,
    "fin": _g_fin,
    "jaws": _g_jaws,
    "tooth": _g_tooth,
    "monogram": _g_monogram,
    "battery": _g_battery,
    "battery_vert": _g_battery_vert,
    "bolt_battery": _g_bolt_battery,
    "ring": _g_ring,
    "dual_ring": _g_dual_ring,
    "arc_gauge": _g_arc_gauge,
    "bars": _g_bars,
    "dots": _g_dots,
    "ticks": _g_ticks,
    "capsule": _g_capsule,
    "hex": _g_hex,
    "shield": _g_shield,
    "droplet": _g_droplet,
    "badge": _g_badge,
    "chip": _g_chip,
}


@lru_cache(maxsize=128)
def geometry(style: str, weight: str = "normal") -> Geom:
    """Geometria do estilo. Cacheada: nao depende do nivel nem da fase."""
    build = _BUILDERS.get(style, _g_mouse)
    return build(WEIGHTS.get(weight, 1.0))
