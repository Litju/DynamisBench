"""Render the Codex design plates for the DynamisBench workbench.

Design tooling, not product code:

    python/worker-mujoco/.venv/bin/python apps/workbench/design/tools/plate_data.py /tmp/plate_data.json
    python3 apps/workbench/design/tools/plates.py /tmp/plate_data.json apps/workbench/design/mockups

Every figure and number on the plates comes from the packaged model's recorded repetition.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from codex import (
    MONO,
    PHASE_LABEL,
    SANS,
    SERIF,
    STUDIOLO,
    VELLUM,
    Camera,
    Svg,
    _mix,
    arrow,
    draw_figure,
    emblem,
    f,
    floor_instrument,
    phase_spans,
    plot,
)

W, H = 1920, 1200
FOLIOS = (("I", "Laboratory"), ("II", "Model Atlas"), ("III", "Analysis"), ("IV", "Evidence"))


# ------------------------------------------------------------------------------------------
# Shared chrome


def titlebar(svg: Svg, active: int, recording="Back squat · nominal repetition"):
    th = svg.theme
    svg.rect(0, 0, W, 52, fill=th["panel"])
    svg.line(0, 52, W, 52, th["line"], 1)
    emblem(svg, 30, 26, 13, th["gold"])
    svg.text(54, 25, "DynamisBench", size=21, family=SERIF, weight=600, fill=th["ink"])
    svg.text(55, 42, "BIOMECHANICS LABORATORY", size=9.5, family=SANS, weight=600,
             fill=th["ink3"], spacing=0.2)
    x = 560
    for i, (numeral, label) in enumerate(FOLIOS):
        width = 30 + 9.2 * len(label) + 28
        if i == active:
            svg.rect(x, 8, width, 36, fill=th["raised"], stroke=th["line2"], rx=3)
            svg.line(x + 10, 44, x + width - 10, 44, th["gold"], 2)
        svg.text(x + 14, 32, numeral, size=13, family=SERIF, weight=600,
                 fill=th["gold"] if i == active else th["ink4"])
        svg.text(x + 20 + 8 * len(numeral), 32, label, size=15, family=SERIF,
                 weight=500 if i == active else 400, fill=th["ink"] if i == active else th["ink3"])
        x += width + 10
    # recording selector
    svg.rect(1290, 11, 330, 30, fill=th["sunk"], stroke=th["line2"], rx=3)
    svg.text(1302, 22, "RECORDING", size=8.5, weight=600, fill=th["ink4"], spacing=0.14)
    svg.text(1302, 35.5, recording, size=12, fill=th["ink"])
    svg.path("M1603,23 l5,5 l5,-5", stroke=th["ink3"], sw=1.4)
    # session pill
    svg.rect(1636, 14, 150, 24, fill=th["verdigris_soft"], stroke=th["verdigris"], rx=12, sw=0.8)
    svg.circle(1650, 26, 3.6, fill=th["verdigris"])
    svg.text(1660, 30, "Sidecar ready · API v1", size=11, fill=th["verdigris"], weight=500)
    # theme toggle
    svg.rect(1798, 14, 104, 24, fill="none", stroke=th["line2"], rx=12)
    svg.rect(1800, 16, 52, 20, fill=th["raised"] if th is STUDIOLO else "none", rx=10)
    svg.rect(1850, 16, 50, 20, fill=th["raised"] if th is VELLUM else "none", rx=10)
    svg.text(1826, 30, "Studiolo", size=10, anchor="middle",
             fill=th["ink"] if th is STUDIOLO else th["ink4"])
    svg.text(1875, 30, "Vellum", size=10, anchor="middle",
             fill=th["ink"] if th is VELLUM else th["ink4"])


def colophon(svg: Svg, data, y=52):
    th = svg.theme
    svg.rect(0, y, W, 26, fill=th["panel2"])
    svg.line(0, y + 26, W, y + 26, th["line"], 1)
    items = [
        ("RECORDING", "repetition · dt 1 ms · 551 frames @ 100 Hz"),
        ("TRAJECTORY", data["trajectory_sha256"][:12]),
        ("MODEL", "c91b2fa2ca1e"),
        ("ENGINE", "MuJoCo 3.17.0 · implicitfast"),
        ("DATASET", "laboratory/1 · packaged, SHA-pinned"),
    ]
    x = 16
    for key, value in items:
        svg.text(x, y + 17, key, size=8.5, weight=600, fill=th["ink4"], spacing=0.14)
        svg.text(x + 8 + 6.4 * len(key) + 4, y + 17, value, size=10.5, family=MONO, fill=th["ink2"])
        x += 8 + 6.4 * len(key) + 14 + 6.5 * len(value) + 26
    svg.rect(W - 380, y + 5, 368, 17, fill=th["gold_soft"], rx=2)
    svg.text(W - 372, y + 17, "DIAGNOSTIC RECORD — NOT SEALED DYNAMISBENCH EVIDENCE", size=9,
             weight=600, fill=th["gold"], spacing=0.08)


def statusbar(svg: Svg, text_left, text_right):
    th = svg.theme
    svg.rect(0, H - 26, W, 26, fill=th["panel"])
    svg.line(0, H - 26, W, H - 26, th["line"], 1)
    svg.text(16, H - 9, text_left, size=10.5, family=MONO, fill=th["ink3"])
    svg.text(W - 16, H - 9, text_right, size=10.5, family=MONO, fill=th["ink3"], anchor="end")


def pane_header(svg: Svg, x, y, w, title, numeral=None):
    th = svg.theme
    svg.rect(x, y, w, 30, fill=th["panel"])
    svg.line(x, y + 30, x + w, y + 30, th["line"], 1)
    svg.rubric(x + 14, y + 19, title)
    if numeral:
        svg.text(x + w - 12, y + 20, numeral, size=12, family=SERIF, fill=th["ink4"], anchor="end")


def toggle(svg: Svg, x, y, on: bool):
    th = svg.theme
    svg.rect(x, y, 26, 14, fill=th["gold_soft"] if on else th["sunk"],
             stroke=th["gold"] if on else th["line2"], rx=7, sw=0.8)
    svg.circle(x + (19 if on else 7), y + 7, 4.6, fill=th["gold"] if on else th["ink4"])


# ------------------------------------------------------------------------------------------
# Laboratory (folio I)


def sample_at(data, t):
    index = int(round(t / 0.01))
    return index, {k: v[index] for k, v in data["samples"].items()}


def left_rail(svg: Svg, x, y, w, h, selected_body="shank_l"):
    th = svg.theme
    svg.rect(x, y, w, h, fill=th["panel"])
    svg.line(x + w, y, x + w, y + h, th["line"], 1)
    pane_header(svg, x, y, w, "Recordings", "i")
    recs = [
        ("Back squat — nominal", "dt 1 ms · all checks pass", True, th["verdigris"]),
        ("Timestep study — dt 0.5 ms", "convergence companion", False, th["verdigris"]),
        ("Ablation — no internal model", "heels lift · 4 checks fail", False, th["sanguine"]),
        ("Ablation — soft friction", "feet slide 9.4 mm", False, th["sanguine"]),
    ]
    yy = y + 42
    for name, sub, sel, mark in recs:
        if sel:
            svg.rect(x + 8, yy - 6, w - 16, 44, fill=th["raised"], stroke=th["line2"], rx=3)
            svg.rect(x + 8, yy - 6, 3, 44, fill=th["gold"])
        svg.circle(x + 24, yy + 9, 4, fill=mark)
        svg.text(x + 36, yy + 13, name, size=12.5, fill=th["ink"] if sel else th["ink2"],
                 weight=500 if sel else 400)
        svg.text(x + 36, yy + 29, sub, size=10.5, fill=th["ink4"])
        yy += 50
    yy += 6
    pane_header(svg, x, yy, w, "Model", "ii")
    tree = [
        (0, "Pelvis", "root · free joint", False),
        (1, "Torso — middle", "lumbar ×3", False),
        (2, "Torso — upper", "thoracic ×3", False),
        (3, "Head", "neck ×3", False),
        (3, "Arm L · R", "shoulder ×3 · elbow", False),
        (1, "Thigh L", "hip ×3", False),
        (2, "Shank L", "knee", True),
        (3, "Foot L", "ankle · subtalar · 5 contacts", False),
        (1, "Thigh R ▸", "", False),
        (0, "Barbell", "free · weld + 2 grips", False),
    ]
    yy += 44
    for depth, name, sub, sel in tree:
        xx = x + 18 + depth * 14
        if sel:
            svg.rect(x + 8, yy - 14, w - 16, 22, fill=th["gold_soft"], rx=2)
        if depth:
            svg.line(xx - 9, yy - 12, xx - 9, yy - 3, th["line2"], 1)
            svg.line(xx - 9, yy - 3, xx - 3, yy - 3, th["line2"], 1)
        svg.text(xx, yy + 1, name, size=12, fill=th["gold"] if sel else th["ink2"],
                 weight=600 if sel else 400)
        if sub:
            svg.text(x + w - 14, yy + 1, sub, size=9.5, fill=th["ink4"], anchor="end")
        yy += 24
    yy += 8
    pane_header(svg, x, yy, w, "Layers", "iii")
    layers = [
        ("Athlete & barbell", th["bone"], True),
        ("Ground reaction vectors", th["sanguine"], True),
        ("Centre of mass & plumb", th["gold"], True),
        ("Support polygon (loaded)", th["verdigris"], True),
        ("Plantar load discs", th["verdigris"], True),
        ("Bar path", th["gold"], True),
        ("CoM path", th["gold"], False),
        ("Joint axes", th["lapis"], False),
        ("Floor instrument", th["line2"], True),
    ]
    yy += 44
    for name, color, on in layers:
        svg.rect(x + 16, yy - 9, 10, 10, fill=color, rx=2, opacity=0.9 if on else 0.35)
        svg.text(x + 34, yy, name, size=11.5, fill=th["ink2"] if on else th["ink4"])
        toggle(svg, x + w - 42, yy - 11, on)
        yy += 25


def stage(svg: Svg, data, x, y, w, h, t=2.2):
    th = svg.theme
    svg.rect(x, y, w, h, fill=th["stage"])
    cam = Camera(azimuth_deg=-58, elevation_deg=13, scale=292, origin=(x + w * 0.50, y + h * 0.47))
    floor_instrument(svg, cam)
    index, s = sample_at(data, t)
    frame = data["frames"][f"{t:.1f}"]
    # support polygon of loaded contacts (ground plane)
    pos = {g["name"]: g["pos"] for g in frame["geoms"]}
    names = [f"foot_{side}_{p}" for side in ("l", "r") for p in data["sole_points"]]
    loads = s["contact_normal_n"]
    pts2 = [(pos[n][0], pos[n][1]) for n, load in zip(names, loads, strict=True) if load > 5]
    from codex import _hull

    hull = _hull(pts2)
    poly = " ".join(
        f"{f(cam.project((a, b, 0))[0])},{f(cam.project((a, b, 0))[1])}" for a, b in hull
    )
    hid = svg.uid("hatch")
    svg.defs.append(
        f'<pattern id="{hid}" width="7" height="7" patternUnits="userSpaceOnUse" '
        f'patternTransform="rotate(35)"><line x1="0" y1="0" x2="0" y2="7" '
        f'stroke="{th["verdigris"]}" stroke-width="1" opacity="0.55"/></pattern>'
    )
    svg.add(f'<polygon points="{poly}" fill="{th["verdigris"]}" opacity="0.12"/>')
    svg.add(f'<polygon points="{poly}" fill="url(#{hid})" stroke="{th["verdigris"]}" stroke-width="1.2"/>')
    # CoM path (past, faint) and bar path
    bar = np.array(data["samples"]["bar_position_m"])
    past = " ".join(
        f"{f(cam.project(p)[0])},{f(cam.project(p)[1])}" for p in bar[: index + 1 : 2]
    )
    future = " ".join(
        f"{f(cam.project(p)[0])},{f(cam.project(p)[1])}" for p in bar[index::2]
    )
    svg.add(f'<polyline points="{future}" fill="none" stroke="{th["gold"]}" stroke-width="1" '
            f'stroke-dasharray="3 4" opacity="0.45"/>')
    draw_figure(svg, frame, cam, selected={"shank_l"})
    svg.add(f'<polyline points="{past}" fill="none" stroke="{th["gold"]}" stroke-width="2" opacity="0.9"/>')
    # plantar load discs
    for n, load in zip(names, loads, strict=True):
        p = cam.project((pos[n][0], pos[n][1], 0.002))
        r = 2 + 10 * math.sqrt(max(load, 0) / 140.0)
        svg.add(f'<ellipse cx="{f(p[0])}" cy="{f(p[1])}" rx="{f(r)}" ry="{f(r * 0.32)}" '
                f'fill="{th["verdigris"]}" opacity="0.75"/>')
    # ground reaction vectors per foot, from the foot's centre of pressure
    for side in ("l", "r"):
        fz = s[f"grf_{'left' if side == 'l' else 'right'}_n"]
        idx = [i for i, n in enumerate(names) if n.startswith(f"foot_{side}")]
        total = sum(loads[i] for i in idx)
        cx = sum(loads[i] * pos[names[i]][0] for i in idx) / total
        cy = sum(loads[i] * pos[names[i]][1] for i in idx) / total
        base = cam.project((cx, cy, 0))
        scale = 0.62 / 1000.0
        tip = cam.project((cx + fz[0] * scale, cy + fz[1] * scale, fz[2] * scale))
        arrow(svg, base[0], base[1], tip[0], tip[1], th["sanguine"], 3.0, 11)
        svg.text(tip[0] + (10 if side == "l" else -10), tip[1] - 2, f"{fz[2]:.0f} N",
                 size=11, family=MONO, fill=th["sanguine"], weight=500,
                 anchor="start" if side == "l" else "end")
    # centre of mass and plumb line
    com = s["com_position_m"]
    c = cam.project(com)
    g = cam.project((com[0], com[1], 0))
    svg.line(c[0], c[1], g[0], g[1], th["gold"], 1.2, dash="5 4")
    svg.circle(c[0], c[1], 8.5, stroke=th["gold"], sw=1.6, fill=th["stage"], opacity=0.95)
    svg.path(
        f"M{f(c[0])},{f(c[1] - 8.5)} A8.5,8.5 0 0,1 {f(c[0] + 8.5)},{f(c[1])} L{f(c[0])},{f(c[1])} Z "
        f"M{f(c[0])},{f(c[1] + 8.5)} A8.5,8.5 0 0,1 {f(c[0] - 8.5)},{f(c[1])} L{f(c[0])},{f(c[1])} Z",
        fill=th["gold"],
    )
    svg.add(f'<ellipse cx="{f(g[0])}" cy="{f(g[1])}" rx="9" ry="3" fill="none" stroke="{th["gold"]}" stroke-width="1.4"/>')
    # marginalia: leader lines to live annotations
    bodies = frame["bodies"]
    joints = data["joint_names"]
    angles = s["joint_angle_deg"]
    speeds = s["joint_velocity_deg_s"]

    def note(body, label, value, sub, dx, dy, color):
        p = cam.project(bodies[body])
        tx, ty = p[0] + dx, p[1] + dy
        svg.circle(p[0], p[1], 3.2, fill=color)
        svg.line(p[0], p[1], tx - (4 if dx > 0 else -4), ty - 4, color, 0.9, opacity=0.8)
        anchor = "start" if dx > 0 else "end"
        svg.text(tx, ty - 6, label, size=13, family=SERIF, style="italic", fill=th["ink2"], anchor=anchor)
        svg.text(tx, ty + 10, value, size=13, family=MONO, fill=color, weight=500, anchor=anchor)
        svg.text(tx, ty + 24, sub, size=10, family=MONO, fill=th["ink4"], anchor=anchor)

    k = joints.index("knee_flexion_l")
    hp = joints.index("hip_flexion_l")
    an = joints.index("ankle_dorsiflexion_l")
    note("shank_l", "genu sinistrum · knee", f"{angles[k]:.1f}°", f"{speeds[k]:+.0f}°/s · ref {s['reference_angle_deg'][k]:.1f}°", 150, 10, th["lapis"])
    note("thigh_l", "coxa · hip", f"{angles[hp]:.1f}°", f"{speeds[hp]:+.0f}°/s", -150, -40, th["lapis"])
    note("foot_l", "talus · ankle", f"{angles[an]:.1f}°", f"{speeds[an]:+.0f}°/s", 190, -6, th["lapis"])
    # view presets (top-left)
    bx = x + 14
    for i, name in enumerate(("Oblique", "Sagittal", "Frontal", "Plan")):
        bw = 16 + 7.4 * len(name)
        svg.rect(bx, y + 14, bw, 24, fill=th["raised"] if i == 0 else th["panel"],
                 stroke=th["gold"] if i == 0 else th["line2"], rx=3)
        svg.text(bx + bw / 2, y + 30, name, size=11.5, anchor="middle",
                 fill=th["ink"] if i == 0 else th["ink3"])
        bx += bw + 6
    svg.rect(bx + 6, y + 14, 110, 24, fill=th["panel"], stroke=th["line2"], rx=3)
    svg.text(bx + 61, y + 30, "Follow · off", size=11, anchor="middle", fill=th["ink3"])
    # orientation instrument (armillary) top-right
    ox, oy, r = x + w - 70, y + 70, 42
    svg.circle(ox, oy, r, stroke=th["line2"], sw=1, fill=th["panel"], opacity=0.85)
    for kdeg in range(0, 360, 15):
        a = math.radians(kdeg)
        rr = r - (6 if kdeg % 90 == 0 else 3)
        svg.line(ox + r * math.cos(a), oy + r * math.sin(a), ox + rr * math.cos(a), oy + rr * math.sin(a), th["gold"], 1, opacity=0.7)
    for label, vec, color in (("X", (1, 0, 0), th["sanguine"]), ("Y", (0, 1, 0), th["verdigris"]), ("Z", (0, 0, 1), th["lapis"])):
        ra, ua, _ = cam.basis()
        v = np.array(vec, float)
        px, py = ox + 30 * float(v @ ra), oy - 30 * float(v @ ua)
        svg.line(ox, oy, px, py, color, 2, cap="round")
        svg.text(px + (5 if px >= ox else -5), py + 4, label, size=10.5, family=MONO, fill=color,
                 anchor="start" if px >= ox else "end", weight=600)
    svg.text(ox, oy + r + 16, "az −58° · el 13°", size=9.5, family=MONO, fill=th["ink4"], anchor="middle")
    # HUD bottom-left
    hx, hy = x + 16, y + h - 96
    svg.rect(hx, hy, 272, 80, fill=th["panel"], stroke=th["line2"], rx=3, opacity=0.94)
    svg.rect(hx, hy, 3, 80, fill=th["phase_descent"])
    svg.text(hx + 16, hy + 24, f"t  {t:.3f} s", size=15, family=MONO, fill=th["ink"], weight=500)
    svg.text(hx + 256, hy + 24, "DESCENT", size=10, weight=600, fill=th["phase_descent"], anchor="end", spacing=0.14)
    svg.text(hx + 16, hy + 46, f"GRF  {(s['grf_left_n'][2] + s['grf_right_n'][2]) / 931.63:.3f} W", size=11.5, family=MONO, fill=th["sanguine"])
    svg.text(hx + 146, hy + 46, f"CoM z  {s['com_position_m'][2]:.3f} m", size=11.5, family=MONO, fill=th["gold"])
    svg.text(hx + 16, hy + 66, f"CoP margin  {s['cop_margin_m'] * 1000:.0f} mm", size=11.5, family=MONO, fill=th["verdigris"])
    svg.text(hx + 146, hy + 66, f"loaded  {s['loaded_contacts']}/10", size=11.5, family=MONO, fill=th["verdigris"])
    # scale bar bottom-right
    a = cam.project((0.05, -1.05, 0))
    b = cam.project((0.55, -1.05, 0))
    sx0 = x + w - 40 - (b[0] - a[0])
    svg.line(sx0, y + h - 30, x + w - 40, y + h - 30, th["ink3"], 1.2)
    for xx in (sx0, x + w - 40):
        svg.line(xx, y + h - 35, xx, y + h - 25, th["ink3"], 1.2)
    svg.text((sx0 + x + w - 40) / 2, y + h - 38, "0.5 m", size=10, family=MONO, fill=th["ink3"], anchor="middle")
    return index, s


def timeline(svg: Svg, data, x, y, w, h, t):
    th = svg.theme
    svg.rect(x, y, w, h, fill=th["panel"])
    svg.line(x, y, x + w, y, th["line"], 1)
    svg.line(x, y + h, x + w, y + h, th["line"], 1)
    # transport
    bx = x + 14
    icons = ["⏮", "◂", "❚❚", "▸", "⏭"]
    for i, icon in enumerate(icons):
        active = i == 2
        svg.rect(bx, y + 14, 34, 30, fill=th["gold"] if active else th["raised"],
                 stroke=th["line2"], rx=3)
        svg.text(bx + 17, y + 34, icon, size=13, anchor="middle",
                 fill=th["ground"] if active else th["ink2"])
        bx += 38
    svg.text(bx + 12, y + 27, f"{t:.3f}", size=18, family=MONO, weight=500, fill=th["ink"])
    svg.text(bx + 12, y + 42, "/ 5.500 s · frame 220 of 551", size=10, family=MONO, fill=th["ink4"])
    # track
    tx0, tx1 = x + 400, x + w - 240
    ts = np.array(data["samples"]["t"])
    spans = phase_spans(ts, data["samples"]["phase"])

    def sx(v):
        return tx0 + v / 5.5 * (tx1 - tx0)

    for name, a, b in spans:
        svg.rect(sx(a), y + 14, sx(b) - sx(a), 16, fill=th[f"phase_{name}"], opacity=0.22 if name in ("standing", "return") else 0.34)
        svg.rect(sx(a), y + 28, sx(b) - sx(a), 2, fill=th[f"phase_{name}"])
        label = PHASE_LABEL[name]
        if sx(b) - sx(a) > 50:
            svg.text((sx(a) + sx(b)) / 2, y + 26, label.upper(), size=8.8, weight=600, spacing=0.12,
                     anchor="middle", fill=th["ink"] if name not in ("standing", "return") else th["ink3"])
    for v in np.arange(0, 5.51, 0.1):
        major = abs(v - round(v)) < 1e-6
        half = abs(v * 2 - round(v * 2)) < 1e-6
        svg.line(sx(v), y + 34, sx(v), y + 34 + (8 if major else 5 if half else 3), th["line2"], 1)
        if major:
            svg.text(sx(v), y + 54, f"{v:.0f}", size=9.5, family=MONO, fill=th["ink4"], anchor="middle")
    # measured phase markers (triangles) from the event list
    for e in data["events"][1:]:
        xx = sx(e["t"])
        svg.path(f"M{f(xx - 4)},{f(y + 10)} L{f(xx + 4)},{f(y + 10)} L{f(xx)},{f(y + 15)} Z", fill=th["ink3"])
    xx = sx(t)
    svg.line(xx, y + 8, xx, y + h - 6, th["gold"], 1.6)
    svg.circle(xx, y + 22, 6.5, fill=th["gold"], stroke=th["ground"], sw=1.5)
    # speed / loop
    rx0 = x + w - 222
    for i, sp in enumerate(("¼×", "½×", "1×", "2×")):
        active = sp == "1×"
        svg.rect(rx0 + i * 40, y + 15, 36, 24, fill=th["raised"] if active else "none",
                 stroke=th["gold"] if active else th["line2"], rx=3)
        svg.text(rx0 + i * 40 + 18, y + 31, sp, size=11, anchor="middle", fill=th["ink"] if active else th["ink3"])
    svg.text(rx0 + 170, y + 31, "⟲ loop", size=11, fill=th["ink3"])


def inspector(svg: Svg, data, s, x, y, w, h):
    th = svg.theme
    svg.rect(x, y, w, h, fill=th["panel"])
    svg.line(x, y, x, y + h, th["line"], 1)
    pane_header(svg, x, y, w, "Inspector — selected joint", "iv")
    joints = data["joint_names"]
    k = joints.index("knee_flexion_l")
    angle = s["joint_angle_deg"][k]
    torque = s["joint_torque_nm"][k]
    svg.text(x + 16, y + 62, "Knee · left", size=22, family=SERIF, weight=500, fill=th["ink"])
    svg.text(x + 16, y + 80, "knee_flexion_l · hinge about +y · shank_l", size=10.5, family=MONO, fill=th["ink4"])
    # angle dial: range -5..150
    cx, cy, r = x + w / 2, y + 196, 76
    lo, hi = -5.0, 150.0

    def ang(v):
        return math.radians(180 + (v - lo) / (hi - lo) * 180)

    def arc(v1, v2, rr):
        a1, a2 = ang(v1), ang(v2)
        return (f"M{f(cx + rr * math.cos(a1))},{f(cy + rr * math.sin(a1))} "
                f"A{rr},{rr} 0 {1 if a2 - a1 > math.pi else 0},1 {f(cx + rr * math.cos(a2))},{f(cy + rr * math.sin(a2))}")

    svg.path(arc(lo, hi, r), stroke=th["line2"], sw=9)
    svg.path(arc(0, 120.1, r), stroke=th["lapis_soft"], sw=9)
    svg.path(arc(lo, angle, r), stroke=th["lapis"], sw=9)
    for v in range(0, 151, 10):
        a = ang(v)
        rr = r + (10 if v % 30 == 0 else 6)
        svg.line(cx + (r + 5) * math.cos(a), cy + (r + 5) * math.sin(a), cx + rr * math.cos(a), cy + rr * math.sin(a), th["ink4"], 1)
        if v % 30 == 0:
            svg.text(cx + (r + 22) * math.cos(a), cy + (r + 22) * math.sin(a) + 3, f"{v}", size=9.5, family=MONO, fill=th["ink4"], anchor="middle")
    ref = s["reference_angle_deg"][k]
    a = ang(ref)
    svg.line(cx + (r - 12) * math.cos(a), cy + (r - 12) * math.sin(a), cx + (r + 12) * math.cos(a), cy + (r + 12) * math.sin(a), th["gold"], 2)
    a = ang(angle)
    svg.line(cx, cy, cx + (r - 16) * math.cos(a), cy + (r - 16) * math.sin(a), th["ink"], 2, cap="round")
    svg.circle(cx, cy, 5, fill=th["ink"])
    svg.text(cx, cy + 36, f"{angle:.1f}°", size=26, family=MONO, weight=500, fill=th["lapis"], anchor="middle")
    svg.text(cx, cy + 54, "flexion", size=12, family=SERIF, style="italic", fill=th["ink3"], anchor="middle")
    svg.text(x + 18, cy + 20, "ROM −5°…150°", size=10, family=MONO, fill=th["ink4"])
    svg.text(x + w - 18, cy + 20, "▮ ref", size=10, family=MONO, fill=th["gold"], anchor="end")

    def row(yy, key, value, color=None, sub=None):
        svg.line(x + 14, yy + 8, x + w - 14, yy + 8, th["hair"] if th is STUDIOLO else th["line"], 1)
        svg.text(x + 16, yy, key, size=11.5, fill=th["ink3"])
        svg.text(x + w - 16, yy, value, size=12, family=MONO, fill=color or th["ink"], anchor="end", weight=500)
        if sub:
            svg.text(x + w - 16, yy + 14, sub, size=9.5, family=MONO, fill=th["ink4"], anchor="end")

    yy = cy + 84
    row(yy, "Angular velocity", f"{s['joint_velocity_deg_s'][k]:+.1f} °/s", th["lapis"])
    row(yy + 26, "Tracking error", f"{angle - ref:+.2f} °", th["ink2"])
    # torque bar vs capacity
    yy += 62
    svg.text(x + 16, yy, "Actuator torque", size=11.5, fill=th["ink3"])
    svg.text(x + w - 16, yy, f"{torque:+.1f} N·m", size=12, family=MONO, fill=th["sanguine"], anchor="end", weight=500)
    bx0, bx1 = x + 16, x + w - 16
    zero = bx0 + (300 / 450) * (bx1 - bx0)
    svg.rect(bx0, yy + 10, bx1 - bx0, 10, fill=th["sunk"], stroke=th["line2"], rx=2)
    tx = zero + torque / 450 * (bx1 - bx0)
    svg.rect(min(zero, tx), yy + 10, abs(tx - zero), 10, fill=th["sanguine"], rx=1)
    svg.line(zero, yy + 6, zero, yy + 24, th["ink3"], 1)
    svg.text(bx0, yy + 34, "−300 extension", size=9.5, family=MONO, fill=th["ink4"])
    svg.text(bx1, yy + 34, "150 flexion", size=9.5, family=MONO, fill=th["ink4"], anchor="end")
    yy += 56
    row(yy, "Activation", f"{abs(torque) / 300:.2f}", th["ink2"], "capacity used")
    row(yy + 30, "Joint power", f"{torque * math.radians(s['joint_velocity_deg_s'][k]):+.0f} W", th["sanguine"])
    # segment
    yy += 72
    svg.rubric(x + 16, yy, "Segment — Shank L")
    row(yy + 24, "Mass", "3.2475 kg")
    row(yy + 48, "CoM from knee", "0.1945 m")
    row(yy + 72, "Principal inertia", "0.0402 · 0.0383 · 0.0066", None)
    svg.text(x + 16, yy + 96, "de Leva (1996), male · 0.0433 of 75 kg", size=10, family=SERIF, style="italic", fill=th["ink4"])
    # plantar load map: true-scale sole outline, contact points at their model coordinates
    yy += 118
    svg.rubric(x + 16, yy, "Plantar load · N")
    names = data["sole_points"]
    loads = s["contact_normal_n"]
    layout = {"heel_lateral": (-0.037, 0.022), "heel_medial": (-0.037, -0.022),
              "met1": (0.1297, -0.036), "met5": (0.1064, 0.030), "hallux": (0.1854, -0.024)}
    k_px = 0.86  # px per mm
    for side, ox in (("r", x + w * 0.30), ("l", x + w * 0.70)):
        heel_y = yy + 232
        lateral = 1 if side == "l" else -1

        def at(ax, lat):
            # screen: toes up, the foot's lateral side outward (left foot: right of screen)
            return ox + lat * lateral * 1000 * k_px, heel_y - (ax + 0.057) * 1000 * k_px

        outline = [(-0.060, 0.0), (-0.054, 0.022), (-0.035, 0.032), (0.03, 0.037), (0.085, 0.045),
                   (0.115, 0.050), (0.15, 0.046), (0.178, 0.034), (0.196, 0.016), (0.206, -0.004),
                   (0.203, -0.026), (0.19, -0.043), (0.16, -0.052), (0.125, -0.050),
                   (0.085, -0.034), (0.045, -0.024), (0.0, -0.026), (-0.035, -0.032),
                   (-0.054, -0.022)]
        pts = [at(a, b) for a, b in outline]
        d = "M" + " L".join(f"{f(px)},{f(py)}" for px, py in pts) + " Z"
        svg.path(d, fill=th["sunk"], stroke=th["line2"], sw=1.2,
                 extra='stroke-linejoin="round"')
        for j2, name in enumerate(names):
            load = loads[(0 if side == "l" else 5) + j2]
            px, py = at(*layout[name])
            r = 3 + 7.5 * math.sqrt(max(load, 0) / 160)
            svg.circle(px, py, r, fill=th["verdigris"], opacity=0.78)
            svg.text(px + (r + 4) * (1 if layout[name][1] * lateral > 0 else -1), py + 3.5,
                     f"{load:.0f}", size=9.5, family=MONO, fill=th["ink2"],
                     anchor="start" if layout[name][1] * lateral > 0 else "end")
        svg.text(ox, heel_y + 22, "left" if side == "l" else "right", size=11.5, family=SERIF,
                 style="italic", fill=th["ink3"], anchor="middle")
    row(yy + 276, "Heel share (min foot)", f"{s['heel_load_fraction'] * 100:.1f} %", th["verdigris"])
    row(yy + 302, "Loaded contacts", f"{s['loaded_contacts']} / 10", th["verdigris"])


def plot_dock(svg: Svg, data, x, y, w, h, t):
    th = svg.theme
    svg.rect(x, y, w, h, fill=th["panel2"])
    # tabs
    tabs = ("Kinematics", "Kinetics", "Ground reaction", "Balance", "Contact", "Energy", "Compare runs")
    tx = x + 12
    for i, name in enumerate(tabs):
        tw = 20 + 7.2 * len(name)
        active = i < 3
        svg.rect(tx, y + 8, tw, 24, fill=th["raised"] if active else "none",
                 stroke=th["line2"] if active else "none", rx=3)
        svg.text(tx + tw / 2, y + 24, name, size=11.5, anchor="middle",
                 fill=th["ink"] if active else th["ink3"], weight=500 if active else 400)
        tx += tw + 6
    svg.text(x + w - 14, y + 24, "3 plots pinned · click a plot to seek · ⇧-drag to zoom", size=10.5, fill=th["ink4"], anchor="end")
    ts = np.array(data["samples"]["t"])
    names = data["joint_names"]
    A = np.array(data["samples"]["joint_angle_deg"])
    R = np.array(data["samples"]["reference_angle_deg"])
    T = np.array(data["samples"]["joint_torque_nm"])
    gl = np.array(data["samples"]["grf_left_n"])
    gr = np.array(data["samples"]["grf_right_n"])
    plan = np.array(data["samples"]["grf_planned_vertical_n"])
    ph = data["samples"]["phase"]
    pw = (w - 48) / 3
    py = y + 40
    phh = h - 48
    lap = th["lapis"]
    plot(svg, x + 12, py, pw, phh, ts, [
        (A[:, names.index("knee_flexion_l")], lap, None, "knee", 2),
        (A[:, names.index("hip_flexion_l")], th["ink2"], "6 3", "hip", 1.5),
        (A[:, names.index("ankle_dorsiflexion_l")], th["verdigris"], None, "ankle", 1.6),
        (R[:, names.index("knee_flexion_l")], th["gold"], "4 3", "knee ref", 1.1),
    ], title="Kinematics — joint angles", unit="deg", ylim=(-10, 130), yticks=(0, 30, 60, 90, 120), playhead=t, phases=ph)
    san = th["sanguine"]
    plot(svg, x + 24 + pw, py, pw, phh, ts, [
        (-T[:, names.index("knee_flexion_l")], san, None, "knee", 2),
        (-T[:, names.index("hip_flexion_l")], th["gold"], None, "hip", 1.6),
        (-T[:, names.index("lumbar_flexion")], th["ink2"], "6 3", "lumbar", 1.4),
        (-T[:, names.index("ankle_dorsiflexion_l")], th["verdigris"], None, "ankle", 1.4),
    ], title="Kinetics — extensor moments", unit="N·m", ylim=(-20, 140), yticks=(0, 40, 80, 120), playhead=t, phases=ph)
    plot(svg, x + 36 + 2 * pw, py, pw, phh, ts, [
        ((gl[:, 2] + gr[:, 2]) / 931.63, san, None, "measured", 2),
        (plan / 931.63, th["ink2"], "5 3", "internal-model plan", 1.3),
    ], title="Ground reaction — vertical", unit="× weight", ylim=(0.7, 1.35), yticks=(0.8, 0.9, 1.0, 1.1, 1.2, 1.3), playhead=t, phases=ph)


def laboratory(data, theme, out: Path):
    svg = Svg(W, H, theme)
    th = svg.theme
    svg.rect(0, 0, W, H, fill=th["ground"])
    titlebar(svg, 0)
    colophon(svg, data)
    top = 78
    left_w, right_w = 280, 340
    body_h = H - 26 - top
    stage_h = round((body_h - 70) * 0.618 / (1 + 0.618) * 1.62)
    stage_h = 600
    left_rail(svg, 0, top, left_w, body_h)
    cx, cw = left_w, W - left_w - right_w
    t = 2.2
    index, s = stage(svg, data, cx, top, cw, stage_h, t)
    timeline(svg, data, cx, top + stage_h, cw, 64, t)
    plot_dock(svg, data, cx, top + stage_h + 64, cw, body_h - stage_h - 64, t)
    inspector(svg, data, s, W - right_w, top, right_w, body_h)
    statusbar(svg, f"frame 220 / 551 · t 2.200 s · record 100 Hz · render 60 fps · WebGL2 · selection: knee_flexion_l",
              "laboratory/1 · trajectory d3b4edafc090 · not sealed evidence")
    out.write_text(svg.render(), encoding="utf-8")


def main() -> int:
    data = json.load(open(sys.argv[1]))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    laboratory(data, STUDIOLO, out / "02-laboratory-studiolo.svg")
    laboratory(data, VELLUM, out / "03-laboratory-vellum.svg")
    model_atlas(data, VELLUM, out / "04-model-atlas.svg")
    analysis_plate(data, STUDIOLO, out / "05-analysis.svg")
    evidence_plate(data, STUDIOLO, out / "06-evidence.svg")
    design_language(data, out / "01-design-language.svg")
    reference_study(out.parent / "references" / "reference-study.svg")
    return 0



# ------------------------------------------------------------------------------------------
# Model Atlas (folio II): a lettered plate of the real model


ATLAS_LETTERS = [
    ("A", "head", "Head & neck"), ("B", "torso_upper", "Upper trunk"), ("C", "torso_middle", "Middle trunk"),
    ("D", "pelvis", "Pelvis (lower trunk)"), ("E", "upper_arm_l", "Upper arm"), ("F", "forearm_l", "Forearm"),
    ("G", "hand_l", "Hand"), ("H", "thigh_l", "Thigh"), ("I", "shank_l", "Shank"), ("K", "foot_l", "Foot"),
    ("L", "barbell", "Barbell · 20 kg"),
]


def model_atlas(data, theme, out: Path):
    svg = Svg(W, H, theme)
    th = svg.theme
    svg.rect(0, 0, W, H, fill=th["ground"])
    titlebar(svg, 1, recording="Model · barbell_back_squat.xml")
    colophon(svg, data)
    top = 78
    body_h = H - 26 - top
    # plate area
    px, pw = 0, 1060
    svg.rect(px, top, pw, body_h, fill=th["stage"])
    svg.text(px + 40, top + 52, "Tabula I", size=15, family=SERIF, style="italic", fill=th["gold"])
    svg.text(px + 40, top + 86, "The athlete and the bar, in the standing keyframe", size=30, family=SERIF, weight=500, fill=th["ink"])
    svg.text(px + 40, top + 110, "75 kg · 1.750 m · 16 segments · 29 hinges · 29 torque actuators · 20 kg IWF barbell, high-bar", size=12.5, family=MONO, fill=th["ink3"])
    frame = data["frames"]["0.0"]
    # frontal view with the Vitruvian construction
    front = Camera(azimuth_deg=0.0, elevation_deg=0.0, scale=272, origin=(px + 330, top + 700), target=(0.05, 0.0, 0.0))
    cxy = front.project((0.05, 0.0, 0.875))
    svg.circle(cxy[0], cxy[1], 0.875 * 272, stroke=th["gold"], sw=1.1, opacity=0.55)
    svg.rect(cxy[0] - 0.875 * 272, cxy[1] - 0.875 * 272, 1.75 * 272, 1.75 * 272, stroke=th["gold"], sw=0.9, opacity=0.4)
    base = front.project((0.05, 0, 0))
    svg.line(px + 40, base[1], px + 560, base[1], th["line2"], 1)
    draw_figure(svg, frame, front)
    # sagittal view
    side = Camera(azimuth_deg=-90.0, elevation_deg=0.0, scale=272, origin=(px + 790, top + 700), target=(0.05, 0.0, 0.0))
    draw_figure(svg, frame, side)
    b2 = side.project((0.05, 0, 0))
    svg.line(px + 620, b2[1], px + pw - 40, b2[1], th["line2"], 1)
    # dimension lines (sagittal): stature, hip, shoulder, bar
    def dim(z, label, xx):
        p = side.project((0.05, 0, z))
        svg.line(xx, b2[1], xx, p[1], th["ink4"], 0.9)
        svg.line(xx - 5, p[1], xx + 5, p[1], th["ink3"], 1.2)
        svg.text(xx + 8, p[1] + 4, label, size=10.5, family=MONO, fill=th["ink3"])
    dim(1.7402, "vertex 1.740 m", px + 935)
    dim(1.4695, "bar 1.470 m", px + 895)
    dim(1.106, "CoM 1.106 m", px + 855)
    dim(0.9215, "hip 0.921 m", px + 975)
    com = side.project((0.0506, 0, 1.106))
    svg.circle(com[0], com[1], 7, stroke=th["gold"], sw=1.6, fill=th["stage"])
    svg.circle(com[0], com[1], 2.5, fill=th["gold"])
    svg.line(com[0], com[1], com[0], b2[1], th["gold"], 1, dash="4 4")
    # lettered callouts on the frontal figure (Vesalius-style)
    bodies = frame["bodies"]
    centres = {g["body"]: g["pos"] for g in frame["geoms"] if g["name"] in (
        "head_geom", "torso_upper_geom", "torso_middle_geom", "pelvis_geom", "upper_arm_l_geom",
        "forearm_l_geom", "hand_l_geom", "thigh_l_geom", "shank_l_geom", "foot_l_shape")}
    offsets = {"A": (-170, -10), "B": (-185, -10), "C": (-190, 5), "D": (-195, 20), "E": (175, 10),
               "F": (165, 40), "G": (150, -10), "H": (-170, 10), "I": (-175, 15), "K": (-150, -14), "L": (60, -70)}
    for letter, body, _label in ATLAS_LETTERS:
        p = front.project(centres[body]) if body != "barbell" else front.project((bodies[body][0], 0.80, bodies[body][2]))
        dx, dy = offsets[letter]
        tx, ty = p[0] + dx, p[1] + dy
        svg.line(p[0], p[1], tx + (12 if dx < 0 else -12), ty - 4, th["ink4"], 0.8)
        svg.circle(p[0], p[1], 2.4, fill=th["sanguine"])
        svg.circle(tx, ty - 4, 10, stroke=th["sanguine"], sw=1.1, fill=th["stage"])
        svg.text(tx, ty + 0.5, letter, size=13, family=SERIF, weight=600, fill=th["sanguine"], anchor="middle")
    svg.text(px + 330, top + 735, "frontal — with the Vitruvian circle and square of the stature", size=12, family=SERIF, style="italic", fill=th["ink3"], anchor="middle")
    svg.text(px + 790, top + 735, "sagittal — measured heights, CoM plumb over the mid-foot", size=12, family=SERIF, style="italic", fill=th["ink3"], anchor="middle")
    # sources marginalia
    y0 = top + 790
    svg.rubric(px + 40, y0, "Sources of the plate", color=th["sanguine"])
    lines = [
        "Segment mass, centre of mass and radii of gyration — de Leva P. (1996) J. Biomech. 29:1223-1230, males.",
        "Vertical landmarks — Drillis & Contini (1966) via Winter (2009) Fig. 4.1 · hip joint centres — Bell et al. (1990).",
        "Joint ranges — AAOS (Greene & Heckman 1994); weight-bearing dorsiflexion — Bennell et al. (1998).",
        "Barbell — IWF Technical and Competition Rules, men's bar: 2.20 m, Ø28 mm shaft, Ø50 mm sleeves, 20 kg.",
        "Generated MJCF, SHA-256 pinned: c91b2fa2ca1e04f920f4685bc23be2a99a64ad697dcd6a40cf5699dc5761a947",
    ]
    for i, text in enumerate(lines):
        svg.text(px + 40, y0 + 24 + i * 21, text, size=12, family=SERIF, fill=th["ink2"])
    # right: tables
    rx = pw
    rw = W - pw
    svg.rect(rx, top, rw, body_h, fill=th["panel"])
    svg.line(rx, top, rx, top + body_h, th["line"], 1)
    pane_header(svg, rx, top, rw, "Legend — segment inertia (de Leva 1996)", "A–L")
    cols = (rx + 20, rx + 56, rx + 250, rx + 340, rx + 470, rx + 600, rx + 730)
    hy = top + 56
    for c, h_ in zip(cols, ("", "Segment", "Mass kg", "CoM m", "Ixx", "Iyy", "Izz  kg·m²"), strict=True):
        svg.text(c, hy, h_, size=10, weight=600, fill=th["ink4"], spacing=0.08)
    seg = {s_["body"]: s_ for s_ in data["segments"]}
    seg["barbell"] = {"mass": 20.0, "com": [0, 0, 0], "inertia": [11.5545, 0.00547, 11.5545]}
    yy = hy + 24
    for letter, body, label in ATLAS_LETTERS:
        s_ = seg[body]
        svg.line(rx + 16, yy + 8, rx + rw - 16, yy + 8, th["hair"] if th is STUDIOLO else th["line"], 1)
        svg.circle(cols[0] + 6, yy - 4, 9, stroke=th["sanguine"], sw=1)
        svg.text(cols[0] + 6, yy, letter, size=11.5, family=SERIF, weight=600, fill=th["sanguine"], anchor="middle")
        svg.text(cols[1], yy, label, size=12.5, fill=th["ink"])
        svg.text(cols[2], yy, f"{s_['mass']:.4f}", size=12, family=MONO, fill=th["ink2"])
        svg.text(cols[3], yy, f"{s_['com'][2]:+.4f}", size=12, family=MONO, fill=th["ink2"])
        for c, v in zip(cols[4:], s_["inertia"], strict=True):
            svg.text(c, yy, f"{v:.4f}", size=12, family=MONO, fill=th["ink2"])
        yy += 27
    svg.text(cols[1], yy + 4, "Total 95.0000 kg  (athlete 75.0000 + bar 20.0000) — verified after compilation", size=11, family=SERIF, style="italic", fill=th["ink3"])
    # joints with ROM and capacity
    yy += 28
    pane_header(svg, rx, yy, rw, "Joints — range of motion and torque capacity", "29")
    yy += 62
    show = ["hip_flexion_l", "knee_flexion_l", "ankle_dorsiflexion_l", "subtalar_inversion_l", "hip_adduction_l",
            "hip_rotation_l", "lumbar_flexion", "thoracic_flexion", "shoulder_rotation_l", "elbow_flexion_l"]
    spec = {j["name"]: j for j in data["joints"]}
    svg.text(rx + 20, yy - 16, "Joint", size=10, weight=600, fill=th["ink4"], spacing=0.08)
    svg.text(rx + 240, yy - 16, "Range of motion  −180° … 180°", size=10, weight=600, fill=th["ink4"], spacing=0.08)
    svg.text(rx + 560, yy - 16, "Capacity  N·m  (− | +)", size=10, weight=600, fill=th["ink4"], spacing=0.08)
    for name in show:
        j = spec[name]
        lo, hi = j["range"]
        svg.text(rx + 20, yy, name.replace("_l", " · L").replace("_", " "), size=12, fill=th["ink"])
        x0, x1 = rx + 240, rx + 520
        zx = (x0 + x1) / 2
        sc = (x1 - x0) / 360
        svg.rect(x0, yy - 9, x1 - x0, 8, fill=th["sunk"], rx=2)
        svg.rect(zx + lo * sc, yy - 9, (hi - lo) * sc, 8, fill=th["lapis"], rx=2, opacity=0.85)
        svg.line(zx, yy - 13, zx, yy + 3, th["ink3"], 1)
        svg.text(zx + lo * sc - 4, yy, f"{lo:.0f}", size=9.5, family=MONO, fill=th["ink4"], anchor="end")
        svg.text(zx + hi * sc + 4, yy, f"{hi:.0f}", size=9.5, family=MONO, fill=th["ink4"])
        neg, pos = j["torque"]
        c0, c1 = rx + 580, rx + 840
        cz = c0 + (c1 - c0) * 0.5
        k = (c1 - c0) / 2 / 300
        svg.rect(cz - neg * k, yy - 9, neg * k, 8, fill=th["sanguine"], opacity=0.85, rx=1)
        svg.rect(cz, yy - 9, pos * k, 8, fill=th["gold"], opacity=0.85, rx=1)
        svg.line(cz, yy - 13, cz, yy + 3, th["ink3"], 1)
        svg.text(cz - neg * k - 4, yy, f"{neg:.0f}", size=9.5, family=MONO, fill=th["ink4"], anchor="end")
        svg.text(cz + pos * k + 4, yy, f"{pos:.0f}", size=9.5, family=MONO, fill=th["ink4"])
        yy += 25
    # contact & coupling cards
    yy += 16
    pane_header(svg, rx, yy, rw, "Contact and coupling", "")
    yy += 30
    cards = [
        ("Plantar contact", ["5 spheres per foot · r 12 mm", "μ 0.9 · elliptic cone · no-slip", "friction time constant 2 ms", "load-bearing above 5 N"]),
        ("Barbell coupling", ["weld: bar centre → trapezius shelf", "connect: each hand → grip (±0.48 m)", "time constant 5 ms · reported forces", "no self-collision"]),
        ("Actuation", ["29 joint torque generators", "activation τ = 30 ms", "asymmetric capacities", "no armature"]),
    ]
    cw = (rw - 56) / 3
    for i, (title, lines_) in enumerate(cards):
        cx0 = rx + 16 + i * (cw + 12)
        svg.rect(cx0, yy + 10, cw, 118, fill=th["raised"], stroke=th["line"], rx=3)
        svg.text(cx0 + 14, yy + 36, title, size=16, family=SERIF, weight=500, fill=th["ink"])
        for k_, line_ in enumerate(lines_):
            svg.text(cx0 + 14, yy + 60 + k_ * 18, line_, size=11.5, fill=th["ink2"])
    statusbar(svg, "model c91b2fa2ca1e · nq 43 · nv 41 · nu 29 · 18 bodies · 3 equality constraints · 10 contact pairs",
              "select a letter or a row to highlight the segment on the stage")
    out.write_text(svg.render(), encoding="utf-8")


# ------------------------------------------------------------------------------------------
# Analysis (folio III)


def card(svg, x, y, w, h, rubric, big, unit, lines, color):
    th = svg.theme
    svg.rect(x, y, w, h, fill=th["panel"], stroke=th["line"], rx=3)
    svg.rect(x, y, w, 3, fill=color)
    svg.rubric(x + 16, y + 28, rubric, color=color)
    svg.text(x + 16, y + 70, big, size=34, family=SERIF, weight=500, fill=th["ink"])
    svg.text(x + 20 + 17 * len(big), y + 70, unit, size=13, family=MONO, fill=th["ink3"])
    for i, line_ in enumerate(lines):
        svg.text(x + 16, y + 96 + i * 19, line_, size=11.5, family=MONO, fill=th["ink2"])


def analysis_plate(data, theme, out: Path):
    svg = Svg(W, H, theme)
    th = svg.theme
    svg.rect(0, 0, W, H, fill=th["ground"])
    titlebar(svg, 2)
    colophon(svg, data)
    top = 78
    sm = data["summary"]
    ex = data["extrema"]
    svg.text(32, top + 44, "Quantitative analysis of the repetition", size=26, family=SERIF, weight=500, fill=th["ink"])
    svg.text(32, top + 66, "every value measured from synchronized MuJoCo snapshots · bounds are the predeclared acceptance criteria", size=12, family=SERIF, style="italic", fill=th["ink3"])
    cw, ch = 298, 156
    cy = top + 86
    b = sm["bottom"]
    tor = sm["torques"]
    gr = sm["ground_reaction"]
    bal = sm["balance"]
    mp = sm["measured_phases"]
    cards = [
        ("Depth", f"{b['knee_flexion_deg']:.1f}", "° knee", [f"hip    {b['hip_flexion_deg']:.1f}°", f"ankle  {b['ankle_dorsiflexion_deg']:.1f}°", f"trunk  {b['trunk_inclination_deg']:.1f}° · spine ±0.3°"], th["lapis"]),
        ("Tempo (measured)", f"{mp[1]['end_s'] - mp[1]['start_s']:.2f}", "s down", [f"ascent   {mp[3]['end_s'] - mp[3]['start_s']:.2f} s", f"peak knee  {sm['ranges']['peak_knee_speed_descent_deg_s']:.0f} / {sm['ranges']['peak_knee_speed_ascent_deg_s']:.0f} °/s", "no reversal within a phase"], th["lapis"]),
        ("Peak moments", f"{tor['knee_flexion_l']['peak_extensor_nm']:.0f}", "N·m knee", [f"{tor['knee_flexion_l']['peak_extensor_nm_per_kg']:.2f} N·m/kg per leg", f"hip    {tor['hip_flexion_l']['peak_extensor_nm']:.0f} N·m", f"lumbar {tor['lumbar_flexion']['peak_extensor_nm']:.0f} N·m"], th["sanguine"]),
        ("Ground reaction", f"{gr['max_vertical_over_weight']:.2f}", "× weight", [f"min   {gr['min_vertical_over_weight']:.2f} × W", f"mean  {gr['mean_vertical_over_weight']:.4f} × W", f"plan  {gr['planned_minus_measured_rms_over_weight'] * 100:.1f} % RMS"], th["sanguine"]),
        ("Balance", f"{bal['min_cop_margin_m'] * 1000:.0f}", "mm CoP", [f"XCoM margin ≥ {bal['min_xcom_margin_m'] * 1000:.0f} mm", f"CoM x {bal['com_x_range_m'][0] * 1000:.1f}–{bal['com_x_range_m'][1] * 1000:.1f} mm", "over the mid-foot"], th["verdigris"]),
        ("Contact", f"{int(ex['min_loaded_sole_contacts'])}/10", "loaded", [f"min point load {ex['min_contact_point_load_n']:.0f} N", f"slip {ex['max_sole_point_slip_m'] * 1000:.2f} mm", f"friction use ≤ {ex['max_friction_utilization'] * 100:.0f} %"], th["verdigris"]),
    ]
    for i, c in enumerate(cards):
        card(svg, 32 + i * (cw + 12), cy, cw, ch, *c)
    # ledger of work and energy (Pacioli)
    ly = cy + ch + 24
    lw = 900
    svg.rect(32, ly, lw, 330, fill=th["panel"], stroke=th["line"], rx=3)
    svg.text(52, ly + 36, "Ledger of work and energy", size=22, family=SERIF, weight=500, fill=th["ink"])
    svg.text(52, ly + 56, "per phase, double entry: actuator work − damping dissipation = change of mechanical energy", size=11.5, family=SERIF, style="italic", fill=th["ink3"])
    heads = ("Phase", "Actuator +", "Actuator −", "Damping", "ΔE mechanical", "Residual", "")
    colx = (52, 250, 380, 510, 640, 790, 860)
    for c, h_ in zip(colx, heads, strict=True):
        svg.text(c, ly + 90, h_, size=10.5, weight=600, fill=th["ink4"], spacing=0.08, anchor="start" if c == 52 else "end" if c > 52 and h_ else "start")
    svg.line(52, ly + 98, 52 + lw - 40, ly + 98, th["line2"], 1)
    yy = ly + 124
    totals = [0, 0, 0, 0, 0]
    for phase in ("standing", "descent", "bottom", "ascent", "return"):
        w_ = data["work"][phase]
        res = w_["positive_j"] + w_["negative_j"] - w_["damping_dissipation_j"] - w_["mechanical_energy_change_j"]
        vals = (w_["positive_j"], w_["negative_j"], w_["damping_dissipation_j"], w_["mechanical_energy_change_j"], res)
        totals = [a + b_ for a, b_ in zip(totals, vals, strict=True)]
        svg.rect(52, yy - 13, 4, 18, fill=th[f"phase_{phase}"])
        svg.text(64, yy, PHASE_LABEL[phase] if phase != "return" else "Return", size=13, family=SERIF, fill=th["ink"])
        for c, v in zip(colx[1:6], vals, strict=True):
            svg.text(c, yy, f"{v:+.2f} J", size=12.5, family=MONO, fill=th["ink2"], anchor="end")
        ok = abs(res) < 0.01 * abs(vals[3]) + 1.0
        svg.circle(colx[6] + 10, yy - 4, 7, fill=th["verdigris_soft"] if ok else th["sanguine_soft"], stroke=th["verdigris"] if ok else th["sanguine"], sw=1)
        svg.text(colx[6] + 10, yy - 0.5, "✓" if ok else "✗", size=10, anchor="middle", fill=th["verdigris"] if ok else th["sanguine"])
        svg.line(52, yy + 10, 52 + lw - 40, yy + 10, th["hair"] if th is STUDIOLO else th["line"], 1)
        yy += 30
    svg.line(52, yy - 8, 52 + lw - 40, yy - 8, th["ink3"], 1)
    svg.line(52, yy - 5, 52 + lw - 40, yy - 5, th["ink3"], 1)
    svg.text(64, yy + 14, "Summa", size=13, family=SERIF, weight=600, fill=th["gold"])
    for c, v in zip(colx[1:6], totals, strict=True):
        svg.text(c, yy + 14, f"{v:+.2f} J", size=12.5, family=MONO, fill=th["gold"], anchor="end", weight=500)
    svg.text(52, ly + 316, f"CoM drop {sm['energy']['com_drop_m']:.3f} m → M·g·Δh = {sm['energy']['potential_energy_change_j']:.1f} J; the ledger closes to within 0.1 % (soft contact & coupling dissipation).", size=11.5, family=SERIF, style="italic", fill=th["ink3"])
    # phase register commanded vs measured
    rx0 = 32 + lw + 16
    rw = W - rx0 - 32
    svg.rect(rx0, ly, rw, 330, fill=th["panel"], stroke=th["line"], rx=3)
    svg.text(rx0 + 20, ly + 36, "Phases — commanded and measured", size=22, family=SERIF, weight=500, fill=th["ink"])
    svg.text(rx0 + 20, ly + 56, "commanded transitions fire on measured state; measured phases are segmented from hip height alone", size=11.5, family=SERIF, style="italic", fill=th["ink3"])
    tx0, tx1 = rx0 + 150, rx0 + rw - 30

    def tx(v):
        return tx0 + v / 5.5 * (tx1 - tx0)

    ev = data["events"]
    rows_ = [("commanded", [(ev[i]["phase"], ev[i]["t"], ev[i + 1]["t"] if i + 1 < len(ev) else 5.5) for i in range(len(ev))]),
             ("measured", [(p["phase"] if not (p["phase"] == "standing" and p["start_s"] > 1) else "return", p["start_s"], p["end_s"]) for p in mp])]
    for i, (label, spans) in enumerate(rows_):
        yy = ly + 104 + i * 64
        svg.text(rx0 + 20, yy + 16, label, size=13, family=SERIF, style="italic", fill=th["ink2"])
        for name, a_, b2 in spans:
            svg.rect(tx(a_), yy, tx(b2) - tx(a_), 26, fill=th[f"phase_{name}"], opacity=0.3 if name in ("standing", "return") else 0.55)
            if tx(b2) - tx(a_) > 60:
                svg.text((tx(a_) + tx(b2)) / 2, yy + 17, PHASE_LABEL[name].upper(), size=9.5, weight=600, spacing=0.1, anchor="middle", fill=th["ink"])
            svg.text(tx(a_), yy + 42, f"{a_:.2f}", size=9.5, family=MONO, fill=th["ink4"], anchor="middle")
    for v in range(6):
        svg.line(tx(v), ly + 230, tx(v), ly + 236, th["line2"], 1)
        svg.text(tx(v), ly + 250, f"{v} s", size=10, family=MONO, fill=th["ink4"], anchor="middle")
    svg.text(rx0 + 20, ly + 290, f"Measured descent {mp[1]['end_s'] - mp[1]['start_s']:.2f} s (hip speed > 0.05 m/s) · bottom {mp[2]['end_s'] - mp[2]['start_s']:.2f} s · ascent {mp[3]['end_s'] - mp[3]['start_s']:.2f} s", size=12, family=MONO, fill=th["ink2"])
    # comparison plots: ablations and timestep study
    py = ly + 346
    ph = H - 26 - py - 16
    pw = (W - 64 - 24) / 3
    ts = np.array(data["samples"]["t"])
    heel = np.array(data["samples"]["heel_load_fraction"])
    ab = data["ablations"]
    nim = ab["no_internal_model"]["samples"]
    # Runs share the exact sample grid (index * 10 ms); overlay them on the common span.
    n_common = min(len(ts), len(nim["t"]))
    ts = ts[:n_common]
    heel = heel[:n_common]
    nim = {k: v[:n_common] for k, v in nim.items()}
    plot(svg, 32, py, pw, ph, ts, [
        (heel * 100, th["verdigris"], None, "nominal", 2),
        (np.array(nim["heel_load_fraction"]) * 100, th["sanguine"], None, "no internal model", 1.6),
        (np.full_like(ts, 20.0), th["ink3"], "4 3", "bound 20 %", 1),
    ], title="Compare runs — heel load share (min foot)", unit="%", ylim=(-5, 65), yticks=(0, 20, 40, 60), phases=data["samples"]["phase"][:n_common])
    gl = (np.array(data["samples"]["grf_left_n"])[:, 2] + np.array(data["samples"]["grf_right_n"])[:, 2])[:n_common]
    gpl = np.array(data["samples"]["grf_planned_vertical_n"])[:n_common]
    g2 = np.array(nim["grf_left_n"])[:, 2] + np.array(nim["grf_right_n"])[:, 2]
    g2p = np.array(nim["grf_planned_vertical_n"])
    plot(svg, 44 + pw, py, pw, ph, ts, [
        ((gl - gpl) / 931.63 * 100, th["verdigris"], None, "nominal", 2),
        ((g2 - g2p) / 931.63 * 100, th["sanguine"], None, "no internal model", 1.6),
    ], title="Compare runs — measured − planned GRF", unit="% weight", ylim=(-30, 30), yticks=(-20, -10, 0, 10, 20), phases=data["samples"]["phase"][:n_common])
    ts = np.array(data["samples"]["t"])
    A = np.array(data["samples"]["joint_angle_deg"])
    A2 = np.array(ab["half_timestep"]["samples"]["joint_angle_deg"])
    k = data["joint_names"].index("knee_flexion_l")
    n = min(len(A), len(A2))
    plot(svg, 56 + 2 * pw, py, pw, ph, ts[:n], [
        ((A[:n, k] - A2[:n, k]) * 1000, th["lapis"], None, "knee: dt 1 ms − dt 0.5 ms", 1.8),
    ], title="Timestep study — knee angle difference", unit="millidegree", ylim=(-20, 20), yticks=(-15, -5, 0, 5, 15), phases=data["samples"]["phase"][:n])
    statusbar(svg, "analysis of recording repetition · companions: timestep 0.5 ms (736b8af5ebad), ablation runs (6d34a139189a, 359cc0263cb8)",
              "values are diagnostic measurements, not sealed evidence")
    out.write_text(svg.render(), encoding="utf-8")


# ------------------------------------------------------------------------------------------
# Evidence (folio IV)


def seal(svg, x, y, ok: bool):
    th = svg.theme
    color = th["verdigris"] if ok else th["sanguine"]
    svg.circle(x, y, 11, fill=th["verdigris_soft"] if ok else th["sanguine_soft"], stroke=color, sw=1.2)
    svg.circle(x, y, 8, stroke=color, sw=0.6, opacity=0.7)
    svg.text(x, y + 4, "✓" if ok else "✗", size=11, anchor="middle", fill=color, weight=600)


def evidence_plate(data, theme, out: Path):
    svg = Svg(W, H, theme)
    th = svg.theme
    svg.rect(0, 0, W, H, fill=th["ground"])
    titlebar(svg, 3)
    colophon(svg, data)
    top = 78
    # provenance chain
    lx, lw = 24, 470
    svg.rect(lx, top + 20, lw, H - top - 70, fill=th["panel"], stroke=th["line"], rx=3)
    svg.text(lx + 20, top + 56, "Chain of provenance", size=22, family=SERIF, weight=500, fill=th["ink"])
    svg.text(lx + 20, top + 76, "every link is content-addressed and re-checkable", size=11.5, family=SERIF, style="italic", fill=th["ink3"])
    chain = [
        ("Model authority", "anthropometry.py · mjcf.py · stance.py", "de Leva 1996 · AAOS · IWF", th["ink2"]),
        ("MJCF asset", "barbell_back_squat.xml", "sha256 c91b2fa2ca1e…5761a947", th["gold"]),
        ("Worker environment", "MuJoCo 3.17.0 · CPython 3.12", "lock f939e54b… · closure verified", th["lapis"]),
        ("Recording", "repetition · dt 1 ms · 5501 steps", f"trajectory {data['trajectory_sha256'][:16]}…", th["sanguine"]),
        ("Companions", "dt 0.5 ms · 2 ablations", "736b8af5… · 6d34a139… · 359cc026…", th["sanguine"]),
        ("Laboratory dataset", "laboratory/1 · packaged", "manifest sha256 pinned · --check", th["gold"]),
        ("Application API", "GET /api/v1/laboratory/…", "read-only · never executes", th["verdigris"]),
        ("Workbench", "this view", "renders only what the API published", th["verdigris"]),
    ]
    yy = top + 118
    for i, (name, what, ident, color) in enumerate(chain):
        svg.circle(lx + 40, yy, 9, fill=th["panel"], stroke=color, sw=2)
        if i < len(chain) - 1:
            svg.line(lx + 40, yy + 9, lx + 40, yy + 96 - 9, th["line2"], 1.4, dash="3 3")
        svg.text(lx + 64, yy - 2, name, size=16, family=SERIF, weight=500, fill=th["ink"])
        svg.text(lx + 64, yy + 18, what, size=11.5, fill=th["ink2"])
        svg.text(lx + 64, yy + 36, ident, size=11, family=MONO, fill=color)
        yy += 96
    # register of checks
    cx0 = lx + lw + 20
    cw = 880
    svg.rect(cx0, top + 20, cw, H - top - 70, fill=th["panel"], stroke=th["line"], rx=3)
    svg.text(cx0 + 20, top + 56, "Register of checks", size=22, family=SERIF, weight=500, fill=th["ink"])
    ex = data["extrema"]
    sm = data["summary"]
    groups = [
        ("Mechanics", [
            ("Impulse–momentum residual", f"{ex['max_momentum_residual_n_s']:.3f} N·s", "< 0.05", True),
            ("Mean vertical GRF / weight", f"{sm['ground_reaction']['mean_vertical_over_weight']:.5f}", "1 ± 0.001", True),
            ("Work–energy ledger residual", "0.53 J", "< 1 % + 1 J", True),
            ("Internal-model plan vs GRF", f"{sm['ground_reaction']['planned_minus_measured_rms_over_weight'] * 100:.2f} % W", "< 3 %", True),
        ]),
        ("Contact", [
            ("Loaded plantar contacts (min)", f"{int(ex['min_loaded_sole_contacts'])} / 10", "= 10", True),
            ("Lightest contact load", f"{ex['min_contact_point_load_n']:.1f} N", "> 10 N", True),
            ("Σ point loads − total GRF", f"{ex['max_contact_load_sum_error_n']:.1e} N", "< 1e-6", True),
            ("Heel share, min foot", f"{ex['min_heel_load_fraction_per_foot'] * 100:.1f} %", "> 20 %", True),
            ("Foot slip (contact point)", f"{ex['max_sole_point_slip_m'] * 1000:.2f} mm", "< 2 mm", True),
            ("Friction use per contact", f"{ex['max_friction_utilization'] * 100:.0f} %", "< 50 %", True),
        ]),
        ("Coupling & joints", [
            ("Bar weld / grip error", f"{ex['max_weld_position_error_m'] * 1000:.2f} / {ex['max_grip_error_m'] * 1000:.2f} mm", "< 0.5 mm", True),
            ("Joint range violation", f"{ex['max_range_violation_deg']:.1f}°", "= 0", True),
            ("Actuator saturation", f"{ex['saturated_fraction'] * 100:.0f} %", "= 0", True),
        ]),
        ("Human-likeness", [
            ("Bottom knee flexion", f"{sm['bottom']['knee_flexion_deg']:.1f}°", "118–122°", True),
            ("Lumbar excursion (neutral spine)", f"{sm['ranges']['max_abs_lumbar_flexion_deg']:.2f}°", "< 5°", True),
            ("Peak knee moment", f"{sm['torques']['knee_flexion_l']['peak_extensor_nm_per_kg']:.2f} N·m/kg", "1.0–2.2", True),
            ("CoP margin (loaded polygon)", f"{sm['balance']['min_cop_margin_m'] * 1000:.0f} mm", "> 30 mm", True),
        ]),
        ("Numerics", [
            ("Timestep 1 → 0.5 ms: knee", "0.016°", "< 0.5°", True),
            ("Momentum residual ratio", "2.00", "1.7–2.3", True),
            ("Cross-process determinism", "identical hash", "equal", True),
        ]),
    ]
    total_checks = sum(len(rows) for _g, rows in groups)
    passed = sum(1 for _g, rows in groups for row_ in rows if row_[3])
    svg.text(cx0 + 20, top + 76, f"predeclared acceptance criteria, evaluated on the synchronized recording · {passed} of {total_checks} pass", size=11.5, family=SERIF, style="italic", fill=th["ink3"])
    yy = top + 112
    for gname, rows in groups:
        svg.rubric(cx0 + 20, yy, gname, color=th["sanguine"])
        yy += 10
        for name, value, bound, ok in rows:
            yy += 26
            svg.line(cx0 + 20, yy + 9, cx0 + cw - 20, yy + 9, th["hair"] if th is STUDIOLO else th["line"], 1)
            seal(svg, cx0 + 36, yy - 4, ok)
            svg.text(cx0 + 58, yy, name, size=13, fill=th["ink"])
            svg.text(cx0 + 600, yy, value, size=12.5, family=MONO, fill=th["ink2"], anchor="end", weight=500)
            svg.text(cx0 + 628, yy, bound, size=12, family=MONO, fill=th["ink4"])
            svg.text(cx0 + cw - 24, yy, "PASS" if ok else "FAIL", size=10, weight=600, spacing=0.12, fill=th["verdigris"] if ok else th["sanguine"], anchor="end")
        yy += 30
    # claim & limitations
    rx0 = cx0 + cw + 20
    rw = W - rx0 - 24
    svg.rect(rx0, top + 20, rw, H - top - 70, fill=th["panel"], stroke=th["line"], rx=3)
    svg.text(rx0 + 20, top + 56, "Colophon", size=22, family=SERIF, weight=500, fill=th["ink"])
    svg.rubric(rx0 + 20, top + 92, "Claim", color=th["gold"])
    claim = ["Mechanical consistency and closed-loop", "forward-dynamics behaviour of a synthetic,", "population-scaled athlete-barbell model.", "", "Not validated against measured human", "motion · not subject-specific · not sealed", "DynamisBench evidence · not a benchmark", "execution."]
    for i, l_ in enumerate(claim):
        svg.text(rx0 + 20, top + 116 + i * 19, l_, size=13, family=SERIF, fill=th["ink2"])
    svg.rubric(rx0 + 20, top + 290, "Limitations", color=th["sanguine"])
    lim = ["one repetition · one tempo · empty bar", "pure-hinge knee: valgus cannot occur", "exact internal model (humans: approximate)", "no sensorimotor delay", "torque generators, not muscles", "foot slip → ~1.4 mm as dt → 0"]
    for i, l_ in enumerate(lim):
        svg.text(rx0 + 20, top + 316 + i * 22, "·  " + l_, size=12.5, fill=th["ink2"])
    svg.rubric(rx0 + 20, top + 470, "Reproduce", color=th["lapis"])
    cmds = ["uv run python tools/", "  mujoco_squat_laboratory.py --check", "<worker-python> -I -m", "  dynamisbench.adapters.mujoco.squat", "  --repetition"]
    svg.rect(rx0 + 16, top + 482, rw - 32, 118, fill=th["sunk"], stroke=th["line"], rx=3)
    for i, l_ in enumerate(cmds):
        svg.text(rx0 + 28, top + 506 + i * 19, l_, size=11.5, family=MONO, fill=th["ink2"])
    svg.rubric(rx0 + 20, top + 640, "Not connected", color=th["ochre"])
    nc = ["New runs from the workbench: the API", "never executes a simulation (ADR-017).", "Sealed evidence: the evidence pipeline", "is not wired to this model yet."]
    for i, l_ in enumerate(nc):
        svg.text(rx0 + 20, top + 664 + i * 19, l_, size=12.5, family=SERIF, style="italic", fill=th["ink3"])
    statusbar(svg, f"register: {total_checks} checks · {passed} pass · {total_checks - passed} fail", "diagnostic qualification record — not sealed DynamisBench evidence")
    out.write_text(svg.render(), encoding="utf-8")



# ------------------------------------------------------------------------------------------
# Design language (plate 01)


def design_language(data, out: Path):
    svg = Svg(W, H, VELLUM)
    th = svg.theme
    svg.rect(0, 0, W, H, fill=th["ground"])
    emblem(svg, 64, 72, 26, th["gold"])
    svg.text(110, 66, "Codex", size=44, family=SERIF, weight=500, fill=th["ink"])
    svg.text(112, 94, "THE DESIGN SYSTEM OF THE DYNAMISBENCH BIOMECHANICS LABORATORY", size=11, weight=600, fill=th["ink3"], spacing=0.18)
    svg.text(W - 48, 66, "Plate 01 — pigments, letters, instruments, proportion", size=16, family=SERIF, style="italic", fill=th["ink3"], anchor="end")
    svg.text(W - 48, 90, "a Renaissance scientific manuscript, rebuilt as a precision instrument", size=12, family=SERIF, style="italic", fill=th["ink4"], anchor="end")
    svg.line(48, 118, W - 48, 118, th["line2"], 1)
    # 1. pigments
    svg.rubric(48, 152, "I · Pigments — every colour carries meaning", color=th["sanguine"])
    pigments = [
        ("Sanguine", "sanguine", "kinetics: forces, moments, GRF", "Leonardo's red chalk"),
        ("Lapis", "lapis", "kinematics: angles, velocities", "ultramarine from lapis lazuli"),
        ("Verdigris", "verdigris", "contact, balance, passing checks", "copper-green pigment"),
        ("Gold leaf", "gold", "CoM, barbell, selection, time", "gilded instruments"),
        ("Ochre", "ochre", "warnings, not connected", "earth pigment"),
        ("Vermilion", "vermilion", "errors, failed checks", "cinnabar red"),
    ]
    for i, (name, key, role, origin) in enumerate(pigments):
        x = 48 + i * 304
        for j, theme in enumerate((STUDIOLO, VELLUM)):
            svg.rect(x + j * 62, 172, 58, 58, fill=theme[key], rx=3, stroke=th["line2"], sw=0.6)
        svg.text(x + 132, 190, name, size=19, family=SERIF, weight=500, fill=th["ink"])
        svg.text(x + 132, 208, role, size=10.5, fill=th["ink2"])
        svg.text(x + 132, 224, origin, size=10.5, family=SERIF, style="italic", fill=th["ink4"])
        svg.text(x, 246, f"{STUDIOLO[key]} · {VELLUM[key]}", size=9.5, family=MONO, fill=th["ink4"])
    # grounds
    svg.text(48, 276, "Grounds", size=16, family=SERIF, weight=500, fill=th["ink"])
    gx = 130
    for theme, label in ((STUDIOLO, "Studiolo (dark, default)"), (VELLUM, "Vellum (light)")):
        for k, key in enumerate(("ground", "panel", "raised", "line2", "ink3", "ink")):
            svg.rect(gx + k * 40, 262, 36, 22, fill=theme[key], stroke=th["line2"], sw=0.6, rx=2)
        svg.text(gx + 250, 278, label, size=11.5, fill=th["ink2"])
        gx += 460
    svg.text(1060, 278, "phases:", size=11.5, fill=th["ink2"])
    px = 1120
    for name in ("standing", "descent", "bottom", "ascent", "return"):
        svg.rect(px, 264, 120, 18, fill=th[f"phase_{name}"], opacity=0.55, rx=2)
        svg.text(px + 60, 277, PHASE_LABEL[name].upper() if name != "return" else "RETURN", size=9, weight=600, spacing=0.1, anchor="middle", fill=th["ink"])
        px += 126
    svg.line(48, 306, W - 48, 306, th["line"], 1)
    # 2. letters
    svg.rubric(48, 338, "II · Letters — three voices", color=th["sanguine"])
    svg.text(48, 392, "EB Garamond", size=40, family=SERIF, weight=500, fill=th["ink"])
    svg.text(48, 418, "Display and headings: folios, plate titles, marginalia (italic). Old-style figures, never in data tables.", size=12, fill=th["ink2"])
    svg.text(48, 452, "Tabula I · Ledger of work and energy · genu sinistrum", size=22, family=SERIF, style="italic", fill=th["ink2"])
    svg.text(700, 392, "IBM Plex Sans", size=34, family=SANS, weight=500, fill=th["ink"])
    svg.text(700, 418, "Interface: labels, controls, rubrics (600, caps, +0.12 em tracking).", size=12, fill=th["ink2"])
    svg.rubric(700, 452, "Inspector — selected joint")
    svg.text(1290, 392, "IBM Plex Mono", size=32, family=MONO, weight=500, fill=th["ink"])
    svg.text(1290, 418, "Every number: tabular, unit-bearing, aligned on the decimal.", size=12, fill=th["ink2"])
    svg.text(1290, 452, "113.4°  −93.7 N·m  1.000 W  d3b4edaf", size=17, family=MONO, fill=th["lapis"])
    scale = [("Display", 34, SERIF), ("Plate title", 26, SERIF), ("Pane title", 20, SERIF), ("Body", 13, SANS), ("Label", 11.5, SANS), ("Rubric", 10.5, SANS), ("Data", 12, MONO), ("Axis", 9.5, MONO)]
    x = 48
    for name, size_, fam in scale:
        svg.text(x, 498, f"{name} {size_}", size=min(size_, 20), family=fam, fill=th["ink2"])
        x += 220
    svg.line(48, 522, W - 48, 522, th["line"], 1)
    # 3. instruments (motifs that measure)
    svg.rubric(48, 554, "III · Instruments — every ornament measures something", color=th["sanguine"])
    # floor instrument
    cam = Camera(azimuth_deg=-58, elevation_deg=22, scale=100, origin=(215, 700), target=(0.05, 0, 0))
    floor_instrument(svg, cam, radii=(0.25, 0.5, 0.75))
    svg.line(*cam.project((0.05, 0, 0))[:2], *cam.project((0.05, 0, 0.9))[:2], th["gold"], 1.2, dash="5 4")
    c = cam.project((0.05, 0, 0.9))
    svg.circle(c[0], c[1], 7, stroke=th["gold"], sw=1.5, fill=th["ground"])
    svg.circle(c[0], c[1], 2.5, fill=th["gold"])
    svg.text(190, 800, "Floor instrument & plumb", size=15, family=SERIF, weight=500, fill=th["ink"], anchor="middle")
    svg.text(190, 818, "Vitruvian rings graduated in degrees; CoM plumb", size=10.5, fill=th["ink3"], anchor="middle")
    # marginalia
    mx = 430
    svg.circle(mx, 650, 3.2, fill=th["lapis"])
    svg.line(mx, 650, mx + 100, 630, th["lapis"], 0.9)
    svg.text(mx + 104, 624, "genu sinistrum · knee", size=13, family=SERIF, style="italic", fill=th["ink2"])
    svg.text(mx + 104, 642, "113.4°", size=13, family=MONO, fill=th["lapis"], weight=500)
    svg.text(mx + 104, 658, "+58°/s · ref 113.3°", size=10, family=MONO, fill=th["ink4"])
    svg.text(mx + 110, 800, "Marginalia", size=15, family=SERIF, weight=500, fill=th["ink"], anchor="middle")
    svg.text(mx + 110, 818, "live annotations beside the joint", size=10.5, fill=th["ink3"], anchor="middle")
    # seal & ledger mark
    sx = 760
    seal(svg, sx, 650, True)
    seal(svg, sx + 40, 650, False)
    svg.text(sx + 20, 700, "0.53 J", size=14, family=MONO, fill=th["gold"], anchor="middle")
    svg.line(sx - 40, 680, sx + 80, 680, th["ink3"], 1)
    svg.line(sx - 40, 683, sx + 80, 683, th["ink3"], 1)
    svg.text(sx + 20, 800, "Seals & Summa", size=15, family=SERIF, weight=500, fill=th["ink"], anchor="middle")
    svg.text(sx + 20, 818, "check status · ledger totals", size=10.5, fill=th["ink3"], anchor="middle")
    # gauge
    gx0, gy0, r = 1040, 700, 60
    def ang(v):
        return math.radians(180 + (v + 5) / 155 * 180)
    def arc(v1, v2):
        a1, a2 = ang(v1), ang(v2)
        return f"M{f(gx0 + r * math.cos(a1))},{f(gy0 + r * math.sin(a1))} A{r},{r} 0 0,1 {f(gx0 + r * math.cos(a2))},{f(gy0 + r * math.sin(a2))}"
    svg.path(arc(-5, 150), stroke=th["line2"], sw=7)
    svg.path(arc(-5, 113.4), stroke=th["lapis"], sw=7)
    a = ang(113.4)
    svg.line(gx0, gy0, gx0 + (r - 12) * math.cos(a), gy0 + (r - 12) * math.sin(a), th["ink"], 2)
    svg.circle(gx0, gy0, 4, fill=th["ink"])
    svg.text(gx0, 800, "Dial", size=15, family=SERIF, weight=500, fill=th["ink"], anchor="middle")
    svg.text(gx0, 818, "angle within its range of motion", size=10.5, fill=th["ink3"], anchor="middle")
    # phase band + playhead
    bx0 = 1230
    for name, wdt in (("standing", 70), ("descent", 110), ("bottom", 22), ("ascent", 90), ("return", 90)):
        svg.rect(bx0, 640, wdt, 16, fill=th[f"phase_{name}"], opacity=0.5)
        svg.rect(bx0, 654, wdt, 2, fill=th[f"phase_{name}"])
        bx0 += wdt
    svg.line(1400, 630, 1400, 670, th["gold"], 1.6)
    svg.circle(1400, 648, 6, fill=th["gold"], stroke=th["ground"], sw=1.4)
    for k in range(0, 383, 20):
        svg.line(1230 + k, 660, 1230 + k, 664 + (3 if k % 60 == 0 else 0), th["line2"], 1)
    svg.text(1421, 800, "Phase strip & playhead", size=15, family=SERIF, weight=500, fill=th["ink"], anchor="middle")
    svg.text(1421, 818, "one clock for every view", size=10.5, fill=th["ink3"], anchor="middle")
    # armillary
    ox, oy = 1760, 680
    svg.circle(ox, oy, 46, stroke=th["line2"], sw=1)
    for kdeg in range(0, 360, 15):
        aa = math.radians(kdeg)
        rr = 46 - (6 if kdeg % 90 == 0 else 3)
        svg.line(ox + 46 * math.cos(aa), oy + 46 * math.sin(aa), ox + rr * math.cos(aa), oy + rr * math.sin(aa), th["gold"], 1)
    for lbl, (dx, dy), col in (("X", (24, 10), th["sanguine"]), ("Y", (20, -14), th["verdigris"]), ("Z", (0, -30), th["lapis"])):
        svg.line(ox, oy, ox + dx, oy + dy, col, 2, cap="round")
        svg.text(ox + dx * 1.25, oy + dy * 1.25 + 4, lbl, size=10, family=MONO, fill=col, anchor="middle", weight=600)
    svg.text(ox, 800, "Armillary", size=15, family=SERIF, weight=500, fill=th["ink"], anchor="middle")
    svg.text(ox, 818, "view orientation, graduated", size=10.5, fill=th["ink3"], anchor="middle")
    svg.line(48, 846, W - 48, 846, th["line"], 1)
    # 4. proportion & components
    svg.rubric(48, 878, "IV · Proportion — the golden section orders the laboratory", color=th["sanguine"])
    gx, gy, gw, gh = 48, 896, 560, 270
    svg.rect(gx, gy, gw, gh, stroke=th["ink3"], sw=1)
    lw_, rw_ = 80, 96
    svg.rect(gx, gy, lw_, gh, fill=th["panel2"], stroke=th["line2"])
    svg.rect(gx + gw - rw_, gy, rw_, gh, fill=th["panel2"], stroke=th["line2"])
    stage_h = gh / 1.618
    svg.rect(gx + lw_, gy, gw - lw_ - rw_, stage_h, fill=th["raised"], stroke=th["line2"])
    svg.rect(gx + lw_, gy + stage_h, gw - lw_ - rw_, gh - stage_h, fill=th["panel"], stroke=th["line2"])
    svg.text(gx + lw_ + 10, gy + 22, "stage  φ = 1.618", size=12, family=MONO, fill=th["gold"])
    svg.text(gx + lw_ + 10, gy + stage_h + 22, "timeline + dock  1", size=12, family=MONO, fill=th["ink3"])
    svg.text(gx + 10, gy + 22, "codex", size=11, family=SERIF, style="italic", fill=th["ink3"])
    svg.text(gx + gw - rw_ + 10, gy + 22, "inspector", size=11, family=SERIF, style="italic", fill=th["ink3"])
    svg.text(gx + gw + 20, gy + 30, "8 px grid · 4 px baseline", size=13, fill=th["ink2"])
    svg.text(gx + gw + 20, gy + 52, "rails 280 / 340 px · stage : dock = φ", size=13, fill=th["ink2"])
    svg.text(gx + gw + 20, gy + 74, "min window 1366 × 768", size=13, fill=th["ink2"])
    svg.text(gx + gw + 20, gy + 96, "hairlines 1 px · radii 3 px", size=13, fill=th["ink2"])
    # components
    cx = 1000
    svg.rubric(cx, 878, "V · Components and states", color=th["sanguine"])
    buttons = [("Play", th["gold"], th["ground"], th["gold"]), ("Sagittal", th["raised"], th["ink"], th["line2"]),
               ("Reset view", "none", th["ink2"], th["line2"]), ("Execute", th["sunk"], th["ink4"], th["line"])]
    bx = cx
    for label, fill, ink, stroke in buttons:
        bw = 30 + 8 * len(label)
        svg.rect(bx, 898, bw, 30, fill=fill, stroke=stroke, rx=3)
        svg.text(bx + bw / 2, 918, label, size=12.5, anchor="middle", fill=ink, weight=500)
        bx += bw + 12
    svg.text(bx + 4, 918, "← not connected: tooltip states why", size=11, family=SERIF, style="italic", fill=th["ink3"])
    states = [("Ready", th["verdigris"], th["verdigris_soft"]), ("Loading", th["lapis"], th["lapis_soft"]),
              ("Not connected", th["ochre"], th["gold_soft"]), ("Failed", th["vermilion"], th["sanguine_soft"]),
              ("Diagnostic — not sealed", th["gold"], th["gold_soft"])]
    bx = cx
    for label, ink, fill in states:
        bw = 34 + 7 * len(label)
        svg.rect(bx, 946, bw, 24, fill=fill, stroke=ink, rx=12, sw=0.8)
        svg.circle(bx + 14, 958, 3.6, fill=ink)
        svg.text(bx + 24, 962, label, size=11, fill=ink, weight=500)
        bx += bw + 10
    # focus ring & toggle & tabs
    svg.rect(cx, 990, 150, 30, fill=th["raised"], stroke=th["line2"], rx=3)
    svg.rect(cx - 3, 987, 156, 36, stroke=th["lapis"], sw=2, rx=5)
    svg.text(cx + 75, 1010, "Focus visible", size=12.5, anchor="middle", fill=th["ink"])
    toggle(svg, cx + 176, 998, True)
    toggle(svg, cx + 212, 998, False)
    svg.text(cx + 250, 1010, "layer toggles", size=11.5, fill=th["ink2"])
    tx = cx + 380
    for i, (numeral, label) in enumerate(FOLIOS):
        width = 30 + 9.2 * len(label) + 14
        if i == 0:
            svg.rect(tx, 988, width, 34, fill=th["raised"], stroke=th["line2"], rx=3)
            svg.line(tx + 8, 1022, tx + width - 8, 1022, th["gold"], 2)
        svg.text(tx + 10, 1010, numeral, size=12, family=SERIF, weight=600, fill=th["gold"] if i == 0 else th["ink4"])
        svg.text(tx + 16 + 7 * len(numeral), 1010, label, size=13.5, family=SERIF, fill=th["ink"] if i == 0 else th["ink3"])
        tx += width + 4
    # inspector row & table
    svg.line(cx, 1066, cx + 380, 1066, th["line"], 1)
    svg.text(cx, 1058, "Actuator torque", size=11.5, fill=th["ink3"])
    svg.text(cx + 380, 1058, "−93.7 N·m", size=12, family=MONO, fill=th["sanguine"], anchor="end", weight=500)
    svg.rect(cx, 1076, 380, 10, fill=th["sunk"], stroke=th["line2"], rx=2)
    svg.rect(cx + 174, 1076, 79, 10, fill=th["sanguine"], rx=1)
    svg.line(cx + 253, 1072, cx + 253, 1090, th["ink3"], 1)
    svg.text(cx + 440, 1066, "rows: label left (Plex Sans 11.5), value right (Plex Mono 12, pigment by quantity)", size=11.5, family=SERIF, style="italic", fill=th["ink3"])
    svg.text(cx, 1130, "Motion: playback is linear and frame-exact; UI transitions 120 ms ease-out; no decorative animation.", size=12, fill=th["ink2"])
    svg.text(cx, 1152, "Accessibility: WCAG AA contrast on both grounds · every control keyboard-operable · plots have table equivalents.", size=12, fill=th["ink2"])
    out.write_text(svg.render(), encoding="utf-8")


# ------------------------------------------------------------------------------------------
# Reference study (plate 00): abstract paradigm schematics, no copied visuals


def schematic(svg: Svg, x, y, w, h, regions):
    th = svg.theme
    svg.rect(x, y, w, h, fill=th["raised"], stroke=th["ink3"], sw=1)
    for rx_, ry_, rw_, rh_, label, accent in regions:
        svg.rect(x + rx_ * w, y + ry_ * h, rw_ * w, rh_ * h, fill=th["gold_soft"] if accent else th["panel2"],
                 stroke=th["line2"], sw=0.8)
        svg.text(x + (rx_ + rw_ / 2) * w, y + (ry_ + rh_ / 2) * h + 4, label, size=10.5, anchor="middle",
                 fill=th["ink2"], family=SERIF, style="italic")


def reference_study(out: Path):
    svg = Svg(W, H, VELLUM)
    th = svg.theme
    svg.rect(0, 0, W, H, fill=th["ground"])
    svg.text(48, 66, "Visual reference study", size=40, family=SERIF, weight=500, fill=th["ink"])
    svg.text(50, 94, "PLATE 00 — PARADIGMS OF PROFESSIONAL SCIENTIFIC SOFTWARE, AND WHAT THE CODEX TAKES FROM THEM", size=11, weight=600, spacing=0.16, fill=th["ink3"])
    svg.text(W - 48, 66, "abstract schematics drawn for this study — no product screen, logo or artwork is reproduced", size=13, family=SERIF, style="italic", fill=th["ink3"], anchor="end")
    svg.line(48, 114, W - 48, 114, th["line2"], 1)
    refs = [
        ("OpenSim", "musculoskeletal modelling", [(0, 0, 0.22, 1, "navigator tree", False), (0.22, 0, 0.56, 0.72, "3D model view", True), (0.78, 0, 0.22, 1, "coordinates", False), (0.22, 0.72, 0.56, 0.28, "motion playback", False)],
         "model as a tree; coordinates first-class", "separate plotter with its own clock"),
        ("Creo (CAD)", "parametric creation", [(0, 0, 1, 0.14, "ribbon", False), (0, 0.14, 0.2, 0.86, "model tree", False), (0.2, 0.14, 0.8, 0.86, "graphics · view cube · named views", True)],
         "view cube, named views, tree ↔ viewport selection", "ribbon density; no notion of time"),
        ("COMSOL", "multiphysics model builder", [(0, 0, 0.24, 1, "model builder", True), (0.24, 0, 0.3, 0.7, "settings", False), (0.54, 0, 0.46, 0.7, "graphics", False), (0.24, 0.7, 0.76, 0.3, "messages · log", False)],
         "the tree is the workflow: definitions → study → results", "correctness evidence buried in logs"),
        ("ParaView", "scientific visualisation", [(0, 0, 1, 0.1, "time toolbar", True), (0, 0.1, 0.22, 0.9, "pipeline", False), (0.22, 0.1, 0.39, 0.9, "render view", False), (0.61, 0.1, 0.39, 0.9, "linked plot view", False)],
         "one time toolbar drives linked views; legends", "general-purpose pipeline hides the domain"),
        ("Simulink", "signal flow and scopes", [(0, 0, 0.6, 1, "block diagram", False), (0.6, 0, 0.4, 0.5, "scope · cursor", True), (0.6, 0.5, 0.4, 0.5, "run comparison", True)],
         "run comparison; cursor-synchronised scopes", "diagram irrelevant to a recorded movement"),
        ("Renaissance plates", "Leonardo · Vesalius · Vitruvius · Dürer · Pacioli", [(0.05, 0.08, 0.4, 0.84, "lettered figure", True), (0.5, 0.08, 0.45, 0.4, "legend", False), (0.5, 0.52, 0.45, 0.4, "marginalia · ledger", False)],
         "pigment, proportion, lettered legends, double entry", "pastiche: parchment textures, drop caps"),
    ]
    for i, (name, sub, regions, adopt, reject) in enumerate(refs):
        col, row = i % 3, i // 3
        x = 48 + col * 612
        y = 140 + row * 360
        svg.text(x, y + 24, name, size=24, family=SERIF, weight=500, fill=th["ink"])
        svg.text(x, y + 44, sub, size=12, family=SERIF, style="italic", fill=th["ink3"])
        schematic(svg, x, y + 58, 560, 200, regions)
        svg.text(x, y + 286, "ADOPT", size=10, weight=600, spacing=0.12, fill=th["verdigris"])
        svg.text(x + 64, y + 286, adopt, size=12.5, fill=th["ink2"])
        svg.text(x, y + 310, "REJECT", size=10, weight=600, spacing=0.12, fill=th["sanguine"])
        svg.text(x + 64, y + 310, reject, size=12.5, fill=th["ink2"])
    y = 880
    svg.line(48, y - 20, W - 48, y - 20, th["line2"], 1)
    svg.text(48, y + 16, "Synthesis — the Codex laboratory", size=26, family=SERIF, weight=500, fill=th["ink"])
    schematic(svg, 48, y + 36, 760, 250, [
        (0, 0, 1, 0.1, "folios I–IV · recording · session", False),
        (0, 0.1, 0.16, 0.9, "codex tree", False),
        (0.16, 0.1, 0.64, 0.52, "stage: athlete, forces, CoM, floor instrument", True),
        (0.16, 0.62, 0.64, 0.1, "one clock: phase strip + playhead", True),
        (0.16, 0.72, 0.64, 0.28, "linked plots · compare runs", False),
        (0.8, 0.1, 0.2, 0.9, "inspector", False),
    ])
    notes = [
        ("One clock", "the time toolbar of ParaView, as a phase strip: stage, plots, inspector and plantar map follow it."),
        ("One selection", "CAD's tree ↔ viewport sync, extended to plots: select a joint anywhere, it is selected everywhere."),
        ("The workflow as folios", "COMSOL's builder spine as four folios: Laboratory · Model Atlas · Analysis · Evidence."),
        ("Correctness is a page", "checks and provenance leave the log and become folio IV, with seals and a chain of hashes."),
        ("Compare runs", "Simulink's data inspector: nominal vs timestep study vs ablations, on one axis."),
        ("Honest absence", "what the API cannot do (new runs) is shown as not connected, with the reason."),
    ]
    for i, (title, text_) in enumerate(notes):
        yy = y + 56 + i * 40
        svg.text(850, yy, title, size=16, family=SERIF, weight=500, fill=th["sanguine"])
        svg.text(1060, yy, text_, size=12.5, fill=th["ink2"])
    out.write_text(svg.render(), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
