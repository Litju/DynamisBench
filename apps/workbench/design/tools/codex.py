"""Codex design system primitives for the DynamisBench design plates (SVG).

Design tooling, not product code. Tokens here are the same tokens the workbench implements in
``src/styles.css`` (see ``../DESIGN.md``); this module only draws plates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from html import escape

import numpy as np

SERIF = "'EB Garamond', 'Cormorant Garamond', 'Palatino Linotype', Palatino, Georgia, serif"
SANS = "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif"
MONO = "'IBM Plex Mono', 'Cascadia Mono', ui-monospace, monospace"

STUDIOLO = {
    "name": "Studiolo",
    "ground": "#0E0C0A",
    "panel": "#15120F",
    "panel2": "#1B1814",
    "raised": "#221E19",
    "sunk": "#0A0907",
    "stage": "#110F0C",
    "line": "#2C2721",
    "line2": "#3D362C",
    "hair": "#221E19",
    "ink": "#EEE6D6",
    "ink2": "#CDBFA6",
    "ink3": "#9A8C75",
    "ink4": "#6C6150",
    "sanguine": "#D0603F",
    "sanguine_soft": "#3A1D15",
    "lapis": "#7393E3",
    "lapis_soft": "#18213A",
    "verdigris": "#5FB39A",
    "verdigris_soft": "#13302A",
    "gold": "#D9AE55",
    "gold_soft": "#33280F",
    "ochre": "#D99A3E",
    "vermilion": "#E2604B",
    "bone": "#D8C7A6",
    "bone_shade": "#8E7B5C",
    "bone_light": "#F2E6CC",
    "steel": "#AEB2B8",
    "phase_standing": "#7F786C",
    "phase_descent": "#7393E3",
    "phase_bottom": "#D9AE55",
    "phase_ascent": "#5FB39A",
    "phase_return": "#7F786C",
}

VELLUM = {
    "name": "Vellum",
    "ground": "#EDE4D1",
    "panel": "#F8F3E8",
    "panel2": "#F2EADA",
    "raised": "#FFFCF5",
    "sunk": "#E6DCC7",
    "stage": "#F4EDDF",
    "line": "#D6C8AB",
    "line2": "#BFAE8C",
    "hair": "#E6DBC5",
    "ink": "#231C13",
    "ink2": "#4A3F31",
    "ink3": "#75684F",
    "ink4": "#9A8C70",
    "sanguine": "#A4442A",
    "sanguine_soft": "#F2DCD2",
    "lapis": "#2B4C9E",
    "lapis_soft": "#DCE3F3",
    "verdigris": "#2D7A63",
    "verdigris_soft": "#D7EBE3",
    "gold": "#A77A1E",
    "gold_soft": "#F1E4C4",
    "ochre": "#B2721D",
    "vermilion": "#B83A27",
    "bone": "#CDB893",
    "bone_shade": "#8A7453",
    "bone_light": "#EFE3C8",
    "steel": "#7F858D",
    "phase_standing": "#9C9381",
    "phase_descent": "#2B4C9E",
    "phase_bottom": "#A77A1E",
    "phase_ascent": "#2D7A63",
    "phase_return": "#9C9381",
}

PHASES = ("standing", "descent", "bottom", "ascent", "return")
PHASE_LABEL = {
    "standing": "Standing",
    "descent": "Descent",
    "bottom": "Bottom",
    "ascent": "Ascent",
    "return": "Standing",
}


def f(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") if abs(value) < 1e6 else str(value)


@dataclass
class Svg:
    width: int
    height: int
    theme: dict
    parts: list[str] = field(default_factory=list)
    defs: list[str] = field(default_factory=list)
    _id: int = 0

    def uid(self, prefix: str) -> str:
        self._id += 1
        return f"{prefix}{self._id}"

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def rect(self, x, y, w, h, fill="none", stroke="none", sw=1, rx=0, opacity=1.0, extra=""):
        self.add(
            f'<rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="{f(rx)}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{f(sw)}" opacity="{opacity}" {extra}/>'
        )

    def line(self, x1, y1, x2, y2, stroke, sw=1, dash=None, opacity=1.0, cap="butt"):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" stroke="{stroke}" '
            f'stroke-width="{f(sw)}" opacity="{opacity}" stroke-linecap="{cap}"{d}/>'
        )

    def path(self, d, fill="none", stroke="none", sw=1, opacity=1.0, extra=""):
        self.add(
            f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{f(sw)}" '
            f'opacity="{opacity}" {extra}/>'
        )

    def circle(self, cx, cy, r, fill="none", stroke="none", sw=1, opacity=1.0, extra=""):
        self.add(
            f'<circle cx="{f(cx)}" cy="{f(cy)}" r="{f(r)}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{f(sw)}" opacity="{opacity}" {extra}/>'
        )

    def text(
        self,
        x,
        y,
        content,
        size=13,
        fill=None,
        family=SANS,
        weight=400,
        anchor="start",
        spacing=0.0,
        style="",
        caps=False,
        opacity=1.0,
    ):
        fill = fill or self.theme["ink"]
        variant = ' font-variant="small-caps"' if caps else ""
        italic = ' font-style="italic"' if "italic" in style else ""
        self.add(
            f'<text x="{f(x)}" y="{f(y)}" font-family="{family}" font-size="{f(size)}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" '
            f'letter-spacing="{spacing}em" opacity="{opacity}"{variant}{italic}>'
            f"{escape(str(content))}</text>"
        )

    def rubric(self, x, y, content, color=None, size=10.5, anchor="start"):
        """Small-caps section rubric, letterspaced (manuscript rubric in pigment)."""
        self.text(
            x, y, content.upper(), size=size, fill=color or self.theme["gold"], family=SANS,
            weight=600, anchor=anchor, spacing=0.12,
        )

    def render(self) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'height="{self.height}" viewBox="0 0 {self.width} {self.height}">'
            f'<defs>{"".join(self.defs)}</defs>{"".join(self.parts)}</svg>\n'
        )


# ------------------------------------------------------------------------------------------
# Orthographic projection of the real model


@dataclass
class Camera:
    azimuth_deg: float
    elevation_deg: float
    scale: float  # px per metre
    origin: tuple[float, float]  # screen position of the world target
    target: tuple[float, float, float] = (0.05, 0.0, 0.85)

    def basis(self):
        a = math.radians(self.azimuth_deg)
        e = math.radians(self.elevation_deg)
        d = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
        forward = -d
        right = np.cross(forward, np.array([0.0, 0.0, 1.0]))
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        return right, up, d

    def project(self, point):
        right, up, d = self.basis()
        p = np.asarray(point, dtype=float) - np.asarray(self.target)
        return (
            self.origin[0] + self.scale * float(p @ right),
            self.origin[1] - self.scale * float(p @ up),
            float(p @ d),
        )


def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b, strict=True))


def draw_figure(svg: Svg, frame: dict, camera: Camera, *, selected: set[str] = frozenset(),
                ghost: bool = False, opacity: float = 1.0) -> None:
    """Draw every geom of one recorded instant, depth-sorted, engraved-style shading."""
    th = svg.theme
    right, up, d = camera.basis()
    items = []
    for g in frame["geoms"]:
        name = g["name"]
        if name == "floor" or g["type"] == 0:
            continue
        mat = np.array(g["mat"]).reshape(3, 3)
        pos = np.array(g["pos"])
        size = g["size"]
        depth = float((pos - np.asarray(camera.target)) @ d)
        items.append((depth, g, mat, pos, size))
    items.sort(key=lambda item: item[0])
    for depth, g, mat, pos, size in items:
        name = g["name"]
        t = g["type"]
        is_bar = name.startswith("bar")
        is_sole = "heel" in name or "met" in name or "hallux" in name
        is_right = name.endswith("_r") or "_r_" in name
        body_color = th["steel"] if is_bar else th["bone"]
        if is_right and not is_bar:
            body_color = _mix(th["bone"], th["bone_shade"], 0.28)
        if g["body"] in selected:
            body_color = _mix(body_color, th["gold"], 0.55)
        outline = _mix(th["ink4"], th["ground"], 0.2) if svg.theme is STUDIOLO else th["ink3"]
        if ghost:
            body_color = th["ink4"]
        if t in (3, 5):  # capsule, cylinder
            half = size[1]
            axis = mat[:, 2]
            a = camera.project(pos + axis * half)
            b = camera.project(pos - axis * half)
            width = 2 * size[0] * camera.scale
            cap = "round" if t == 3 else "butt"
            svg.add(
                f'<line x1="{f(a[0])}" y1="{f(a[1])}" x2="{f(b[0])}" y2="{f(b[1])}" '
                f'stroke="{outline}" stroke-width="{f(width + 2.2)}" stroke-linecap="{cap}" '
                f'opacity="{opacity}"/>'
            )
            svg.add(
                f'<line x1="{f(a[0])}" y1="{f(a[1])}" x2="{f(b[0])}" y2="{f(b[1])}" '
                f'stroke="{body_color}" stroke-width="{f(width)}" stroke-linecap="{cap}" '
                f'opacity="{opacity}"/>'
            )
            # engraved highlight: a thin lighter line offset toward the light (screen up-left)
            if width > 3 and not ghost:
                nx, ny = b[1] - a[1], a[0] - b[0]
                norm = math.hypot(nx, ny) or 1.0
                nx, ny = nx / norm, ny / norm
                if nx + ny > 0:
                    nx, ny = -nx, -ny
                off = width * 0.22
                light = th["bone_light"] if not is_bar else _mix(th["steel"], "#ffffff", 0.5)
                svg.add(
                    f'<line x1="{f(a[0] + nx * off)}" y1="{f(a[1] + ny * off)}" '
                    f'x2="{f(b[0] + nx * off)}" y2="{f(b[1] + ny * off)}" stroke="{light}" '
                    f'stroke-width="{f(max(1.0, width * 0.22))}" stroke-linecap="{cap}" '
                    f'opacity="{0.55 * opacity}"/>'
                )
        elif t == 4:  # ellipsoid
            A = mat @ np.diag(np.array(size) ** 2) @ mat.T
            P = np.vstack([right, up])
            C = P @ A @ P.T
            vals, vecs = np.linalg.eigh(C)
            rx, ry = (math.sqrt(max(v, 1e-9)) * camera.scale for v in vals)
            angle = math.degrees(math.atan2(-vecs[1, 0], vecs[0, 0]))
            cx, cy, _ = camera.project(pos)
            gid = svg.uid("ell")
            svg.defs.append(
                f'<radialGradient id="{gid}" cx="38%" cy="32%" r="75%">'
                f'<stop offset="0" stop-color="{th["bone_light"] if not ghost else th["ink4"]}"/>'
                f'<stop offset="0.55" stop-color="{body_color}"/>'
                f'<stop offset="1" stop-color="{_mix(body_color, th["ground"], 0.35)}"/>'
                "</radialGradient>"
            )
            svg.add(
                f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{f(rx)}" ry="{f(ry)}" '
                f'transform="rotate({f(angle)} {f(cx)} {f(cy)})" fill="url(#{gid})" '
                f'stroke="{outline}" stroke-width="1.1" opacity="{opacity}"/>'
            )
        elif t == 6:  # box
            corners = []
            for sx in (-1, 1):
                for sy in (-1, 1):
                    for sz in (-1, 1):
                        local = np.array([sx * size[0], sy * size[1], sz * size[2]])
                        corners.append(camera.project(pos + mat @ local)[:2])
            hull = _hull(corners)
            pts = " ".join(f"{f(x)},{f(y)}" for x, y in hull)
            fill = th["ink4"] if "foot" in name else body_color
            svg.add(
                f'<polygon points="{pts}" fill="{fill}" stroke="{outline}" stroke-width="1" '
                f'opacity="{0.9 * opacity}"/>'
            )
        elif t == 2 and is_sole:
            cx, cy, _ = camera.project(pos)
            svg.circle(cx, cy, max(2.0, size[0] * camera.scale), fill=th["ink3"], opacity=opacity)


def _hull(points):
    pts = sorted(set((round(x, 3), round(y, 3)) for x, y in points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def floor_instrument(svg: Svg, camera: Camera, centre=(0.05, 0.0), radii=(0.25, 0.5, 0.75, 1.0)):
    """Vitruvian floor instrument: graduated concentric rings and a measured grid."""
    th = svg.theme
    for gx in np.arange(-1.25, 1.26, 0.25):
        a = camera.project((centre[0] + gx, -1.25, 0))
        b = camera.project((centre[0] + gx, 1.25, 0))
        svg.line(a[0], a[1], b[0], b[1], th["line"], 0.7, opacity=0.7)
    for gy in np.arange(-1.25, 1.26, 0.25):
        a = camera.project((centre[0] - 1.25, gy, 0))
        b = camera.project((centre[0] + 1.25, gy, 0))
        svg.line(a[0], a[1], b[0], b[1], th["line"], 0.7, opacity=0.7)
    for r in radii:
        pts = []
        for k in range(0, 361, 4):
            th_ = math.radians(k)
            p = camera.project((centre[0] + r * math.cos(th_), centre[1] + r * math.sin(th_), 0))
            pts.append(f"{f(p[0])},{f(p[1])}")
        strong = r in (0.5, 1.0)
        svg.add(
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{th["gold"] if strong else th["line2"]}" '
            f'stroke-width="{1.1 if strong else 0.8}" opacity="{0.65 if strong else 0.8}"/>'
        )
    # graduations on the outer ring every 10 degrees, numerals every 30
    r = radii[-1]
    for k in range(0, 360, 10):
        th_ = math.radians(k)
        a = camera.project((centre[0] + r * math.cos(th_), centre[1] + r * math.sin(th_), 0))
        b = camera.project(
            (centre[0] + (r - (0.06 if k % 30 == 0 else 0.03)) * math.cos(th_),
             centre[1] + (r - (0.06 if k % 30 == 0 else 0.03)) * math.sin(th_), 0)
        )
        svg.line(a[0], a[1], b[0], b[1], th["gold"], 1.0, opacity=0.7)
        if k % 30 == 0:
            c = camera.project(
                (centre[0] + (r + 0.09) * math.cos(th_), centre[1] + (r + 0.09) * math.sin(th_), 0)
            )
            svg.text(c[0], c[1] + 3, f"{k}°", size=9.5, fill=th["ink4"], family=MONO,
                     anchor="middle")


def arrow(svg: Svg, x1, y1, x2, y2, color, width=2.4, head=9):
    svg.line(x1, y1, x2, y2, color, width, cap="round")
    ang = math.atan2(y2 - y1, x2 - x1)
    p1 = (x2 - head * math.cos(ang - 0.42), y2 - head * math.sin(ang - 0.42))
    p2 = (x2 - head * math.cos(ang + 0.42), y2 - head * math.sin(ang + 0.42))
    svg.path(f"M{f(x2)},{f(y2)} L{f(p1[0])},{f(p1[1])} L{f(p2[0])},{f(p2[1])} Z", fill=color)


# ------------------------------------------------------------------------------------------
# Plots


def phase_spans(t, phases):
    spans = []
    start = 0
    for i in range(1, len(phases) + 1):
        if i == len(phases) or phases[i] != phases[start]:
            spans.append((phases[start], t[start], t[i - 1]))
            start = i
    return spans


def plot(
    svg: Svg,
    x,
    y,
    w,
    h,
    t,
    series,
    *,
    title,
    unit,
    ylim,
    yticks,
    playhead=None,
    phases=None,
    legend=True,
    xlabel=True,
    tmax=5.5,
):
    """One Codex plot plate: hairline frame, graduated axes, phase wash, playhead cursor."""
    th = svg.theme
    svg.rect(x, y, w, h, fill=th["panel"], stroke=th["line"], sw=1)
    svg.text(x + 12, y + 20, title, size=14, family=SERIF, weight=500, fill=th["ink"])
    svg.text(x + w - 12, y + 19, unit, size=10.5, family=MONO, fill=th["ink4"], anchor="end")
    px0, px1 = x + 46, x + w - 14
    py0, py1 = y + 34, y + h - (26 if xlabel else 12)

    def sx(v):
        return px0 + (v / tmax) * (px1 - px0)

    def sy(v):
        return py1 - (v - ylim[0]) / (ylim[1] - ylim[0]) * (py1 - py0)

    if phases is not None:
        for name, a, b in phase_spans(t, phases):
            if name in ("descent", "bottom", "ascent"):
                svg.rect(sx(a), py0, sx(b) - sx(a), py1 - py0, fill=th[f"phase_{name}"],
                         opacity=0.07)
                svg.rect(sx(a), py0 - 3, sx(b) - sx(a), 2.2, fill=th[f"phase_{name}"], opacity=0.85)
    for v in yticks:
        yy = sy(v)
        svg.line(px0, yy, px1, yy, th["hair"] if svg.theme is STUDIOLO else th["line"], 1)
        svg.text(px0 - 6, yy + 3.5, f(v), size=9.5, family=MONO, fill=th["ink4"], anchor="end")
    for v in np.arange(0, tmax + 0.01, 0.5):
        xx = sx(v)
        svg.line(xx, py1, xx, py1 + (4 if v % 1 == 0 else 2), th["line2"], 1)
        if xlabel and v % 1 == 0:
            svg.text(xx, py1 + 15, f"{v:.0f}", size=9.5, family=MONO, fill=th["ink4"], anchor="middle")
    if xlabel:
        svg.text(px1, py1 + 15, "t  s", size=9.5, family=MONO, fill=th["ink4"], anchor="end")
    svg.line(px0, py1, px1, py1, th["line2"], 1)
    svg.line(px0, py0, px0, py1, th["line2"], 1)
    lx = px0 + 8
    for values, color, dash, label, width in series:
        pts = " ".join(
            f"{f(sx(a))},{f(sy(min(max(b, ylim[0]), ylim[1])))}" for a, b in zip(t, values, strict=True)
        )
        d = f' stroke-dasharray="{dash}"' if dash else ""
        svg.add(
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}" '
            f'stroke-linejoin="round"{d}/>'
        )
        if legend:
            svg.line(lx, py0 + 10, lx + 14, py0 + 10, color, 2, dash=dash)
            svg.text(lx + 18, py0 + 13.5, label, size=10, fill=th["ink2"])
            lx += 24 + 6.3 * len(label)
    if playhead is not None:
        xx = sx(playhead)
        svg.line(xx, py0 - 4, xx, py1, th["gold"], 1.3)
        svg.path(f"M{f(xx - 4)},{f(py0 - 8)} L{f(xx + 4)},{f(py0 - 8)} L{f(xx)},{f(py0 - 3)} Z",
                 fill=th["gold"])
    return sx, sy


def emblem(svg: Svg, cx, cy, r, color):
    """The DynamisBench mark: circle and square (proportion), plumb line and centre of mass."""
    svg.circle(cx, cy, r, stroke=color, sw=1.4)
    s = r * 1.414 / 1.414 * 0.86
    svg.rect(cx - s, cy - s, 2 * s, 2 * s, stroke=color, sw=1.1, opacity=0.85)
    svg.line(cx, cy - r, cx, cy + r, color, 1.0, opacity=0.9)
    svg.circle(cx, cy - r * 0.18, r * 0.2, fill=color)
    svg.line(cx - r * 0.5, cy + r * 0.86, cx + r * 0.5, cy + r * 0.86, color, 1.4)
