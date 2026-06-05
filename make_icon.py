#!/usr/bin/env python3
"""Generate the LAMMPS Dashboard icon — refined atom symbol with glow effects."""

import sys
import math
import os
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import (
    QPainter, QPixmap, QColor, QPen, QBrush,
    QRadialGradient, QLinearGradient, QConicalGradient,
    QFont, QFontMetrics, QIcon, QPainterPath,
)
from PyQt5.QtWidgets import QApplication


def draw_icon(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setRenderHint(QPainter.TextAntialiasing)

    s  = float(size)
    c  = s / 2
    r  = s / 2 - s * 0.03   # usable radius

    # ── 1. Outer glow ring ───────────────────────────────────────────────
    outer_glow = QRadialGradient(c, c, r + s * 0.04)
    outer_glow.setColorAt(0.80, QColor(30, 120, 200, 0))
    outer_glow.setColorAt(0.92, QColor(50, 160, 230, 55))
    outer_glow.setColorAt(1.00, QColor(30, 100, 180, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(outer_glow))
    p.drawEllipse(QRectF(0, 0, s, s))

    # ── 2. Background circle — deep navy gradient ────────────────────────
    bg = QRadialGradient(c, c * 0.75, r)
    bg.setColorAt(0.00, QColor("#1e2c45"))
    bg.setColorAt(0.45, QColor("#141a28"))
    bg.setColorAt(0.80, QColor("#0d1018"))
    bg.setColorAt(1.00, QColor("#080a10"))
    p.setBrush(QBrush(bg))
    circ_rect = QRectF(c - r, c - r, r * 2, r * 2)
    p.drawEllipse(circ_rect)

    # ── 3. Subtle dot texture ────────────────────────────────────────────
    if size >= 64:
        dot_pen = QPen(QColor(255, 255, 255, 18))
        dot_pen.setWidthF(max(1.0, s * 0.008))
        p.setPen(dot_pen)
        p.setBrush(Qt.NoBrush)
        step = s * 0.095
        cx0  = c - r + step
        while cx0 < c + r:
            cy0 = c - r + step
            while cy0 < c + r:
                dist = math.hypot(cx0 - c, cy0 - c)
                if dist < r - s * 0.04:
                    rr = max(0.8, s * 0.007)
                    p.drawEllipse(QRectF(cx0 - rr, cy0 - rr, rr * 2, rr * 2))
                cy0 += step
            cx0 += step

    # ── 4. Orbital rings ─────────────────────────────────────────────────
    orb_rx = r * 0.76
    orb_ry = r * 0.27
    lw     = max(1.5, s * 0.013)

    for i, (angle, col_bright, col_dim) in enumerate([
        (  0, "#62d6f8", "#1a6090"),
        ( 60, "#50c8f0", "#155585"),
        (120, "#40bae8", "#104a78"),
    ]):
        p.save()
        p.translate(c, c)
        p.rotate(angle)

        # Glow shadow behind ring
        glow_pen = QPen(QColor(col_bright))
        glow_pen.setWidthF(lw * 3.5)
        glow_c = QColor(col_bright)
        glow_c.setAlpha(30)
        glow_pen.setColor(glow_c)
        p.setPen(glow_pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(-orb_rx, -orb_ry, orb_rx * 2, orb_ry * 2))

        # Medium glow
        mid_pen = QPen()
        mid_pen.setWidthF(lw * 1.8)
        mid_c = QColor(col_bright)
        mid_c.setAlpha(60)
        mid_pen.setColor(mid_c)
        p.setPen(mid_pen)
        p.drawEllipse(QRectF(-orb_rx, -orb_ry, orb_rx * 2, orb_ry * 2))

        # Main ring
        ring_pen = QPen(QColor(col_bright))
        ring_pen.setWidthF(lw)
        ring_pen.setCapStyle(Qt.RoundCap)
        p.setPen(ring_pen)
        p.drawEllipse(QRectF(-orb_rx, -orb_ry, orb_rx * 2, orb_ry * 2))

        p.restore()

    # ── 5. Nucleus ───────────────────────────────────────────────────────
    nr = r * 0.115   # nucleus radius

    # Outermost halo
    h3 = QRadialGradient(c, c, nr * 5)
    h3.setColorAt(0.00, QColor(80, 200, 255, 50))
    h3.setColorAt(1.00, QColor(80, 200, 255, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(h3))
    p.drawEllipse(QRectF(c - nr * 5, c - nr * 5, nr * 10, nr * 10))

    # Middle halo
    h2 = QRadialGradient(c, c, nr * 2.8)
    h2.setColorAt(0.00, QColor(100, 210, 255, 90))
    h2.setColorAt(1.00, QColor(50, 160, 230, 0))
    p.setBrush(QBrush(h2))
    p.drawEllipse(QRectF(c - nr * 2.8, c - nr * 2.8, nr * 5.6, nr * 5.6))

    # Core sphere
    core = QRadialGradient(c - nr * 0.28, c - nr * 0.28, nr * 1.1)
    core.setColorAt(0.00, QColor("#ffffff"))
    core.setColorAt(0.20, QColor("#d0f0ff"))
    core.setColorAt(0.50, QColor("#62d6f8"))
    core.setColorAt(0.80, QColor("#1a8fc8"))
    core.setColorAt(1.00, QColor("#0a5590"))
    p.setBrush(QBrush(core))
    p.drawEllipse(QRectF(c - nr, c - nr, nr * 2, nr * 2))

    # Specular highlight
    hl_r = nr * 0.32
    hl   = QRadialGradient(c - nr * 0.4, c - nr * 0.4, hl_r)
    hl.setColorAt(0.0, QColor(255, 255, 255, 200))
    hl.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(hl))
    p.drawEllipse(QRectF(c - nr * 0.4 - hl_r, c - nr * 0.4 - hl_r, hl_r * 2, hl_r * 2))

    # ── 6. Electron dots ─────────────────────────────────────────────────
    er = max(2.5, s * 0.050)
    electrons = [
        (  0, math.radians( 45)),
        ( 60, math.radians(165)),
        (120, math.radians(285)),
    ]
    for orb_deg, elec_rad in electrons:
        orb_r = math.radians(orb_deg)
        x =  orb_rx * math.cos(elec_rad)
        y =  orb_ry * math.sin(elec_rad)
        co, so = math.cos(orb_r), math.sin(orb_r)
        ex = c + x * co - y * so
        ey = c + x * so + y * co

        # Glow halo
        eg = QRadialGradient(ex, ey, er * 2.6)
        eg.setColorAt(0.0, QColor(80, 200, 255, 80))
        eg.setColorAt(1.0, QColor(80, 200, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(eg))
        p.drawEllipse(QRectF(ex - er * 2.6, ey - er * 2.6, er * 5.2, er * 5.2))

        # Core
        ec = QRadialGradient(ex - er * 0.3, ey - er * 0.3, er * 1.1)
        ec.setColorAt(0.0, QColor("#ffffff"))
        ec.setColorAt(0.3, QColor("#c8f0ff"))
        ec.setColorAt(0.7, QColor("#40b8e8"))
        ec.setColorAt(1.0, QColor("#1070b0"))
        p.setBrush(QBrush(ec))
        p.drawEllipse(QRectF(ex - er, ey - er, er * 2, er * 2))

    # ── 7. Border ring ───────────────────────────────────────────────────
    p.setBrush(Qt.NoBrush)
    brd_pen = QPen()
    brd_pen.setWidthF(max(1.0, s * 0.012))
    brd_c = QColor(80, 180, 230, 70)
    brd_pen.setColor(brd_c)
    p.setPen(brd_pen)
    pad = s * 0.016
    p.drawEllipse(QRectF(c - r + pad, c - r + pad, (r - pad) * 2, (r - pad) * 2))

    # ── 8. "LAMMPS" text badge ───────────────────────────────────────────
    if size >= 48:
        font_sz = max(6, int(s * 0.13))
        font = QFont("Segoe UI", font_sz, QFont.Bold)
        fm   = QFontMetrics(font)
        label = "LAMMPS"
        tw = fm.horizontalAdvance(label)
        th = fm.ascent()
        tx = c - tw / 2
        ty = c + r * 0.66 + th / 2

        # Shadow
        p.setFont(font)
        p.setPen(QColor(0, 0, 0, 160))
        p.drawText(QPointF(tx + 1.2, ty + 1.2), label)

        # Gradient text (simulate with two-pass)
        p.setPen(QColor("#a8e8ff"))
        p.drawText(QPointF(tx, ty), label)

    p.end()
    return pix


def build_icon() -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(draw_icon(sz))
    return icon


def save_png(path: str, size: int = 256):
    pix = draw_icon(size)
    pix.save(path, "PNG")
    print(f"Saved {size}×{size} → {path}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
    save_png(out, 256)
