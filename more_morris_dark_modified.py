# pip install pygame PyOpenGL PyOpenGL_accelerate
"""
vMWM (discrete 1-4) — single-file script.

В этой версии добавлено:
1) Probe теперь начинается с обратного отсчёта / look-фазы, как acq.
2) Добавлен mirror_acq: та же конфигурация мира, но вся геометрия зеркалится по оси X.
3) Вместо визуализации платформ цилиндрами рисуются цветы внутри тех же виртуальных границ.
4) Маркеры параллельного порта кодируются разными каналами (битами 0..7), а не длительностью импульса.
"""

import math
import random
import os
import csv
import json
import time
from datetime import datetime
import numpy as np

import traceback

print("HERE")



os.environ["SDL_VIDEODRIVER"] = "windows"

import pygame
from pygame.locals import *
from OpenGL.GL import *





PLOT_MINIMAP = False

# ============================================================
# Defaults
# ============================================================
DEFAULTS = {
    "arena_r": 12.0,
    "wall_h": 4.0,
    "eye_y": 2.0,

    # timing
    "pause_dur": 8.0,
    "look_dur": 6.0,
    "timeout": 30.0,
    "probe_dur": 30.0,
    "hold_on_platform": 10.0,
    "reveal_on_timeout": True,
    "reveal_dur": 15.0,

#"pause_dur": 2.0,
#    "look_dur": 2.0,
#    "timeout": 10.0,
#    "probe_dur": 10.0,
#    "hold_on_platform": 3.0,
#    "reveal_on_timeout": True,
#    "reveal_dur": 8.0,


    # cues
    "markers_n": 4,                 # forced to 4 unique in code
    "markers_fixed": True,
    "marker_y_min": 1.5,
    "marker_y_max": 2.5,
    "marker_sector_frac": 0.55,

    # platforms
    "platform_r": 1.1,
    "platform_fixed": True,
    "platform_wall_margin": 3.0,
    "platform_center_margin": 3.0,
    "platform_min_dist_between": 5.0,

    # start
    "start_near_wall": True,
    "start_wall_radius_frac": 0.92,
    "start_min_dist_to_platform": 6.0,
    "start_jitter_deg": 8.0,

    # change block
    "change_dur": 0.0,
    "change_markers": True,
    "change_platform": True,

    # CONTINUOUS CONTROL (key held)
    "move_step": 0.65,          # units per second
    "turn_step_deg": 12.0,    # deg per second
    "fixed_pitch_deg": 0.0,

    # LOGGING
    "log_sample_hz": 10.0,

    # PARALLEL PORT MARKERS (event identity -> separate bits 0..7)
    "pp_enabled": True,
    "pp_port_name": "LPT",       # informational; kept for PsychoPy-like config parity
    "pp_address_hex": "0xE030",  # string or int OK
    "pp_pulse_dur_ms": 100,       # same duration for all events; identity is in the bit/channel
    "pp_channel_trial_start": 0,
    "pp_channel_nav_start": 1,
    "pp_channel_platform1": 2,
    "pp_channel_platform2": 3,
}

ACQ_LIKE_TYPES = {"acq", "mirror_acq"}


list_inst       = [{"type": "instr"}]
list_pause      = [{"type": "pause"}]
list_visible    = [{"type": "visible"}]
list_acq        = [{"type": "acq"}]
list_mirror_acq = [{"type": "mirror_acq"}]
list_probe      = [{"type": "probe"}]
list_change     = [{"type": "change"}]

mirror_pair = list_pause + list_acq + list_pause + list_mirror_acq
acq_subseq = (
    list_change
    + (list_pause + list_visible * 2)
    + mirror_pair * 5
    + (list_pause + list_probe)
    + mirror_pair * 2
    + (list_pause + list_probe)
    + (list_pause + list_visible * 3)
)
#TRIAL_SEQ = list_inst + acq_subseq * 5

N_seqs = 6
TRIAL_SEQ = list_inst.copy()
for i in range(N_seqs):
    acq_subseq = list_change.copy()
  
    acq_subseq = acq_subseq+ list_pause+list_visible*3

    subsubseq = 4*list_acq+4*list_mirror_acq+2*list_probe

    np.random.shuffle(subsubseq)

    for ele in subsubseq:
        acq_subseq = acq_subseq+ list_pause+[ele]

    acq_subseq = acq_subseq+ list_pause+list_visible*3

    TRIAL_SEQ = TRIAL_SEQ + acq_subseq



    



INSTR_TEXT = (
    "Инструкция\n\n"
    "Управление (НЕПРЕРЫВНО, пока удерживаете):\n"
    "1 — вперёд\n"
    "2 — назад\n"
    "3 — поворот влево\n"
    "4 — поворот вправо\n\n"
    "Задача: найдите ДВЕ платформы как можно быстрее.\n"
    "Порядок не важен.\n\n"
    "Нажмите 1, чтобы начать."
)

CHANGE_TEXT = "Мир меняется.\nНажмите 1, когда будете готовы."

# ============================================================
# Math helpers
# ============================================================
def clamp(x, a, b):
    return max(a, min(b, x))

def dist2(x1, z1, x2, z2):
    dx = x1 - x2
    dz = z1 - z2
    return dx*dx + dz*dz

def dist(x1, z1, x2, z2):
    return math.hypot(x1 - x2, z1 - z2)

def clamp_inside_cylinder(x, z, radius, margin=0.20):
    r = math.hypot(x, z)
    max_r = max(0.0, radius - margin)
    if r > max_r and r > 1e-9:
        k = max_r / r
        return x * k, z * k
    return x, z

def rand_point_in_annulus(min_r, max_r):
    min_r = max(0.0, float(min_r))
    max_r = max(0.0, float(max_r))
    if max_r <= min_r:
        a = 2.0 * math.pi * random.random()
        return min_r * math.cos(a), min_r * math.sin(a)

    a = 2.0 * math.pi * random.random()
    r2 = (min_r * min_r) + (max_r * max_r - min_r * min_r) * random.random()
    r = math.sqrt(r2)
    return r * math.cos(a), r * math.sin(a)

def yaw_look_at_center(x, z, jitter_deg=0.0):
    yaw_rad = math.atan2(-x, z)
    yaw_deg = math.degrees(yaw_rad) + random.uniform(-jitter_deg, jitter_deg)
    return yaw_deg

def rand_start(arena_r, eye_y, start_near_wall=True, frac=0.92):
    if start_near_wall:
        a = 2.0 * math.pi * random.random()
        r = arena_r * frac
        return [r*math.cos(a), eye_y, r*math.sin(a)]
    a = 2.0 * math.pi * random.random()
    r = (arena_r - 1.0) * math.sqrt(random.random())
    return [r*math.cos(a), eye_y, r*math.sin(a)]

# ============================================================
# Grass field (random patches per run) + swaying
# ============================================================
class GrassField:
    def __init__(self, size=80.0, step=2.0, base=(0.4, 0.9, 0.4), patch_amp=0.14, seed=None):
        self.size = float(size)
        self.step = float(step)
        self.seed = int(seed if seed is not None else random.randrange(10**9))
        self.base = base
        self.patch_amp = float(patch_amp)

        self.A1, self.A2 = 0.06, 0.04
        self.k1, self.k2 = 0.35, 0.30
        self.w1, self.w2 = 1.2, 0.9

        self.n = int(self.size / self.step)
        self.colors = self._make_colors()

    def _make_colors(self):
        rng = random.Random(self.seed)
        n = self.n
        colors = [[None]*(n+1) for _ in range(n+1)]
        for i in range(n+1):
            for j in range(n+1):
                x = (i / max(1, n)) * 2.0 * math.pi
                z = (j / max(1, n)) * 2.0 * math.pi
                v = (
                    0.55*math.sin(1.7*x + 0.3)
                    + 0.45*math.sin(1.3*z + 1.1)
                    + 0.35*math.sin(0.9*(x+z) + 2.2)
                )
                v += 0.25*(rng.random() - 0.5)
                v = max(-1.0, min(1.0, v))
                k = 1.0 + self.patch_amp * v
                r = max(0.0, min(1.0, self.base[0]*k))
                g = max(0.0, min(1.0, self.base[1]*k))
                b = max(0.0, min(1.0, self.base[2]*k))
                colors[i][j] = (r, g, b)
        return colors

    def height(self, x, z, y0, t):
        return y0 + self.A1 * math.sin(self.k1 * x + self.w1 * t) + self.A2 * math.sin(self.k2 * z + self.w2 * t)

    def draw(self, y0=0.0, t=0.0):
        half = self.size * 0.5
        step = self.step
        n = self.n
        colors = self.colors

        x0 = -half
        for i in range(n):
            z0 = -half
            for j in range(n):
                xA, zA = x0 + i*step, z0 + j*step
                xB, zB = xA + step, zA + step

                yAA = self.height(xA, zA, y0, t)
                yBA = self.height(xB, zA, y0, t)
                yBB = self.height(xB, zB, y0, t)
                yAB = self.height(xA, zB, y0, t)

                glColor3f(*colors[i][j])
                glBegin(GL_QUADS)
                glVertex3f(xA, yAA, zA)
                glVertex3f(xB, yBA, zA)
                glVertex3f(xB, yBB, zB)
                glVertex3f(xA, yAB, zB)
                glEnd()

def wood_color(rng):
    cc_low = 1.1
    cc_high = 0.9

    r_min, r_max = cc_low*0x95/0xFF, cc_high*0xCC/0xFF
    g_min, g_max = cc_low*0x59/0xFF, cc_high*0x7A/0xFF
    b_min, b_max = cc_low*0x1D/0xFF, cc_high*0x28/0xFF

    c = rng.random()
    r = r_min + (r_max-r_min)*c
    g = g_min + (g_max-g_min)*c
    b = b_min + (b_max-b_min)*c
    return (r, g, b)

# ============================================================
# Wall + markers
# ============================================================
class ArenaVisuals:
    def __init__(self):
        pass

    @staticmethod
    def draw_wall_fence(radius=12.0, height=4.0, segments=160, y0=0.0, colors=None):
        r = float(radius)
        h = float(height)
        seg = int(segments)

        tip_h = 0.1 * h
        gap_frac = 0.0
        inset = 0.02
        line_outline = False

        for i in range(seg):
            a0 = 2.0 * math.pi * (i / seg)
            a1 = 2.0 * math.pi * ((i + 1) / seg)
            am = 0.5 * (a0 + a1)

            da = (a1 - a0)
            a0p = a0 + da * gap_frac * 0.5
            a1p = a1 - da * gap_frac * 0.5

            x0 = r * math.cos(a0p); z0 = r * math.sin(a0p)
            x1 = r * math.cos(a1p); z1 = r * math.sin(a1p)

            nxm = math.cos(am); nzm = math.sin(am)
            x0i, z0i = x0 - inset * nxm, z0 - inset * nzm
            x1i, z1i = x1 - inset * nxm, z1 - inset * nzm

            xt = r * math.cos(am) - inset * nxm
            zt = r * math.sin(am) - inset * nzm
            y_tip = y0 + h + tip_h

            if colors is None or i >= len(colors):
                col = (0.96, 0.93, 0.86)
            else:
                col = colors[i]

            c_bot = (col[0] * 0.92, col[1] * 0.92, col[2] * 0.92)
            c_top = (min(1.0, col[0] * 1.05), min(1.0, col[1] * 1.05), min(1.0, col[2] * 1.05))

            glBegin(GL_QUADS)
            glColor3f(*c_bot); glVertex3f(x0i, y0,     z0i)
            glColor3f(*c_bot); glVertex3f(x1i, y0,     z1i)
            glColor3f(*c_top); glVertex3f(x1i, y0 + h, z1i)
            glColor3f(*c_top); glVertex3f(x0i, y0 + h, z0i)
            glEnd()

            glBegin(GL_TRIANGLES)
            glColor3f(*c_top); glVertex3f(x0i, y0 + h, z0i)
            glColor3f(*c_top); glVertex3f(x1i, y0 + h, z1i)
            glColor3f(*c_top); glVertex3f(xt,  y_tip,  zt)
            glEnd()

            if line_outline:
                glColor3f(0.0, 0.0, 0.0)
                glLineWidth(1.0)
                glBegin(GL_LINE_LOOP)
                glVertex3f(x0i, y0,     z0i)
                glVertex3f(x1i, y0,     z1i)
                glVertex3f(x1i, y0 + h, z1i)
                glVertex3f(xt,  y_tip,  zt)
                glVertex3f(x0i, y0 + h, z0i)
                glEnd()

    @staticmethod
    def make_markers(y_min, y_max, sector_frac=0.55):
        shapes = ["circle", "triangle", "square", "romb"]
        n = 4
        sector_frac = max(0.0, min(1.0, float(sector_frac)))
        dtheta = 2.0 * math.pi / n
        angles = [i * dtheta + sector_frac * dtheta * random.random() for i in range(n)]
        markers = []
        for i in range(n):
            markers.append({
                "type": shapes[i],
                "angle": angles[i],
                "y": y_min + (y_max - y_min) * random.random(),
            })
        return markers

    @staticmethod
    def _wall_basis(angle_rad):
        ux = -math.sin(angle_rad); uz = math.cos(angle_rad)   # tangent
        nx = math.cos(angle_rad);  nz = math.sin(angle_rad)   # normal
        return ux, uz, nx, nz

    @staticmethod
    def draw_marker_outline(marker_type, radius, angle_rad, y_center, wall_height=4.0):
        y_center = clamp(y_center, 0.7, wall_height - 0.7)

        x = radius * math.cos(angle_rad)
        z = radius * math.sin(angle_rad)
        ux, uz, nx, nz = ArenaVisuals._wall_basis(angle_rad)

        inset = 0.07
        x_in = x - inset * nx
        z_in = z - inset * nz

        scale = 1.4

        c_bot = (0.70, 1.00, 0.98)  # light-cyan
        c_top = (1.00, 0.80, 0.92)  # light-pink

        def set_col(t):
            t = clamp(t, 0.0, 1.0)
            glColor3f(
                c_bot[0] + (c_top[0] - c_bot[0]) * t,
                c_bot[1] + (c_top[1] - c_bot[1]) * t,
                c_bot[2] + (c_top[2] - c_bot[2]) * t,
            )

        if marker_type == "romb":
            r = 0.55 * scale
            top   = (x_in + ux*0.0,  y_center + r,   z_in + uz*0.0)
            right = (x_in + ux*r,    y_center + 0.0, z_in + uz*r)
            bot   = (x_in + ux*0.0,  y_center - r,   z_in + uz*0.0)
            left  = (x_in + ux*(-r), y_center + 0.0, z_in + uz*(-r))
            center = (x_in, y_center, z_in)

            glBegin(GL_TRIANGLES)
            set_col(0.5); glVertex3f(*center); set_col(1.0); glVertex3f(*top);   set_col(0.5); glVertex3f(*right)
            set_col(0.5); glVertex3f(*center); set_col(0.5); glVertex3f(*right); set_col(0.0); glVertex3f(*bot)
            set_col(0.5); glVertex3f(*center); set_col(0.0); glVertex3f(*bot);   set_col(0.5); glVertex3f(*left)
            set_col(0.5); glVertex3f(*center); set_col(0.5); glVertex3f(*left);  set_col(1.0); glVertex3f(*top)
            glEnd()

        elif marker_type == "triangle":
            s = 0.70 * scale
            v_top = (x_in + ux*0.0,  y_center + s*0.8, z_in + uz*0.0)
            v_l   = (x_in + ux*(-s), y_center - s*0.5, z_in + uz*(-s))
            v_r   = (x_in + ux*( s), y_center - s*0.5, z_in + uz*( s))

            glBegin(GL_TRIANGLES)
            set_col(1.0); glVertex3f(*v_top)
            set_col(0.0); glVertex3f(*v_l)
            set_col(0.0); glVertex3f(*v_r)
            glEnd()

        elif marker_type == "circle":
            r0 = 0.55 * scale
            seg = 64
            glBegin(GL_TRIANGLE_FAN)
            set_col(0.5); glVertex3f(x_in, y_center, z_in)
            for i in range(seg + 1):
                a = 2.0 * math.pi * (i / seg)
                du = math.cos(a) * r0
                dv = math.sin(a) * r0
                tcol = (dv / (2.0 * r0)) + 0.5
                set_col(tcol)
                glVertex3f(x_in + ux*du, y_center + dv, z_in + uz*du)
            glEnd()

        elif marker_type == "square":
            half = 0.55 * scale
            v1 = (x_in + ux*(-half), y_center - half, z_in + uz*(-half))
            v2 = (x_in + ux*( half), y_center - half, z_in + uz*( half))
            v3 = (x_in + ux*( half), y_center + half, z_in + uz*( half))
            v4 = (x_in + ux*(-half), y_center + half, z_in + uz*(-half))

            glBegin(GL_TRIANGLES)
            set_col(0.0); glVertex3f(*v1)
            set_col(0.0); glVertex3f(*v2)
            set_col(1.0); glVertex3f(*v3)

            set_col(0.0); glVertex3f(*v1)
            set_col(1.0); glVertex3f(*v3)
            set_col(1.0); glVertex3f(*v4)
            glEnd()

# ============================================================
# Platform drawing + generation
# ============================================================
def draw_flat_disk(x, z, y=0.0, radius=0.3, segments=48, color=(1.0, 1.0, 1.0)):
    glColor3f(*color)
    glBegin(GL_TRIANGLE_FAN)
    glVertex3f(x, y, z)
    for i in range(segments + 1):
        a = 2.0 * math.pi * (i / segments)
        glVertex3f(x + radius * math.cos(a), y, z + radius * math.sin(a))
    glEnd()


def draw_flat_ellipse(x, z, y=0.0, rx=0.4, rz=0.2, yaw_rad=0.0, segments=36, color=(1.0, 1.0, 1.0)):
    c = math.cos(yaw_rad)
    s = math.sin(yaw_rad)
    glColor3f(*color)
    glBegin(GL_TRIANGLE_FAN)
    glVertex3f(x, y, z)
    for i in range(segments + 1):
        a = 2.0 * math.pi * (i / segments)
        ex = rx * math.cos(a)
        ez = rz * math.sin(a)
        wx = x + ex * c - ez * s
        wz = z + ex * s + ez * c
        glVertex3f(wx, y, wz)
    glEnd()


def draw_flower_platform(x, z, y=0.0, radius=0.9, petal_color=(0.95, 0.85, 0.25), center_color=(0.95, 0.45, 0.05),
                         petal_count=8):
    base_y = y + 0.035
    petal_center_r = radius * 0.42
    petal_rx = radius * 0.30
    petal_rz = radius * 0.16
    for i in range(petal_count):
        a = 2.0 * math.pi * (i / petal_count)
        px = x + petal_center_r * math.cos(a)
        pz = z + petal_center_r * math.sin(a)
        draw_flat_ellipse(px, pz, y=base_y, rx=petal_rx, rz=petal_rz, yaw_rad=a,
                          segments=28, color=petal_color)
    draw_flat_disk(x, z, y=base_y + 0.002, radius=radius * 0.28, segments=40, color=center_color)

def make_two_platforms(arena_r, platform_r, wall_margin, center_margin, min_between):
    max_r = float(arena_r) - float(wall_margin)
    min_r = float(center_margin)

    p1x, p1z = rand_point_in_annulus(min_r=min_r, max_r=max_r)
    p1 = {"x": p1x, "z": p1z, "r": float(platform_r)}

    for _ in range(500):
        p2x, p2z = rand_point_in_annulus(min_r=min_r, max_r=max_r)
        if dist2(p1x, p1z, p2x, p2z) >= (min_between * min_between):
            p2 = {"x": p2x, "z": p2z, "r": float(platform_r)}
            return [p1, p2]

    a = random.random() * 2.0 * math.pi
    p2 = {"x": p1x + min_between*math.cos(a), "z": p1z + min_between*math.sin(a), "r": float(platform_r)}
    p2["x"], p2["z"] = clamp_inside_cylinder(p2["x"], p2["z"], float(arena_r), margin=0.6)
    return [p1, p2]

# ============================================================
# UI overlay (text, pause veil, fixation, minimap)
# ============================================================
class Overlay:
    def __init__(self):
        self._font_cache = {}

    def font(self, size_px):
        size_px = int(size_px)
        if size_px not in self._font_cache:
            self._font_cache[size_px] = pygame.font.SysFont("Arial", size_px, bold=False)
        return self._font_cache[size_px]

    @staticmethod
    def _ortho_begin(w, h):
        glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity(); glOrtho(0, w, 0, h, -1, 1)
        glMatrixMode(GL_MODELVIEW);  glPushMatrix(); glLoadIdentity()

    @staticmethod
    def _ortho_end():
        glPopMatrix(); glMatrixMode(GL_PROJECTION); glPopMatrix(); glMatrixMode(GL_MODELVIEW)

    def draw_white_screen(self, w, h):
        self._ortho_begin(w, h)
        glDisable(GL_DEPTH_TEST)
        glColor3f(0.5, 0.5, 0.5)
        glBegin(GL_QUADS)
        glVertex2f(0, 0); glVertex2f(w, 0); glVertex2f(w, h); glVertex2f(0, h)
        glEnd()
        glEnable(GL_DEPTH_TEST)
        self._ortho_end()

    def draw_fixation_cross(self, w, h, size_px=18, thickness=2):
        self._ortho_begin(w, h)
        glDisable(GL_DEPTH_TEST)
        glLineWidth(thickness)
        glColor3f(1.0, 1.0, 1.0)
        cx, cy = w*0.5, h*0.5
        glBegin(GL_LINES)
        glVertex2f(cx - size_px, cy); glVertex2f(cx + size_px, cy)
        glVertex2f(cx, cy - size_px); glVertex2f(cx, cy + size_px)
        glEnd()
        glEnable(GL_DEPTH_TEST)
        self._ortho_end()

    def draw_pause_veil_blur(self, w, h, alpha=0.5):
        self._ortho_begin(w, h)
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        glColor4f(0.5, 0.5, 0.5, alpha)
        glBegin(GL_QUADS)
        glVertex2f(0, 0); glVertex2f(w, 0); glVertex2f(w, h); glVertex2f(0, h)
        glEnd()

        for _ in range(10):
            dx = random.uniform(-6, 6)
            dy = random.uniform(-6, 6)

            if alpha < 0.99:
                a = alpha * 0.06
                glColor4f(1.0, 1.0, 1.0, a)
            glBegin(GL_QUADS)
            glVertex2f(0+dx, 0+dy); glVertex2f(w+dx, 0+dy); glVertex2f(w+dx, h+dy); glVertex2f(0+dx, h+dy)
            glEnd()

        glDisable(GL_BLEND)
        glEnable(GL_DEPTH_TEST)
        self._ortho_end()

    def draw_text(self, w, h, text, x, y_from_top, size_px=24, color=(0,0,0), anchor="topleft"):
        if not text:
            return

        font = self.font(size_px)
        col = (int(color[0]*255), int(color[1]*255), int(color[2]*255))
        surf = font.render(str(text), True, col).convert_alpha()
        tw, th = surf.get_width(), surf.get_height()

        y_gl = h - y_from_top - th
        if anchor == "topright":
            x0 = x - tw
        elif anchor == "topmiddle":
            x0 = x - tw//2
        else:
            x0 = x
        y0 = y_gl

        data = pygame.image.tostring(surf, "RGBA", True)
        tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, tw, th, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)

        self._ortho_begin(w, h)
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_TEXTURE_2D)

        glColor4f(1,1,1,1)
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex2f(x0,     y0)
        glTexCoord2f(1, 0); glVertex2f(x0+tw,  y0)
        glTexCoord2f(1, 1); glVertex2f(x0+tw,  y0+th)
        glTexCoord2f(0, 1); glVertex2f(x0,     y0+th)
        glEnd()

        glDisable(GL_TEXTURE_2D)
        glDisable(GL_BLEND)
        glEnable(GL_DEPTH_TEST)
        self._ortho_end()

        glDeleteTextures([tex_id])

    def draw_minimap(self, w, h, exp, x_from_left=18, y_from_top=18, size_px=190,
                     show_markers=True, show_platforms=True, show_direction=True,
                     bg_alpha=0.45):
        s = int(size_px)
        pad = 10
        x0 = int(x_from_left)
        y0_top = int(y_from_top)
        y0 = h - y0_top - s

        arena_r = float(exp.p["arena_r"])
        if arena_r <= 1e-6:
            return

        def world_to_map(wx, wz):
            nx = (wx / arena_r) * 0.5 + 0.5
            nz = (wz / arena_r) * 0.5 + 0.5
            mx = x0 + pad + nx * (s - 2*pad)
            my = y0 + pad + nz * (s - 2*pad)
            return mx, my

        self._ortho_begin(w, h)
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        glColor4f(1.0, 1.0, 1.0, bg_alpha)
        glBegin(GL_QUADS)
        glVertex2f(x0,   y0)
        glVertex2f(x0+s, y0)
        glVertex2f(x0+s, y0+s)
        glVertex2f(x0,   y0+s)
        glEnd()

        cx = x0 + s*0.5
        cy = y0 + s*0.5
        R  = (s - 2*pad) * 0.5

        glColor4f(0.0, 0.0, 0.0, 0.9)
        glLineWidth(2.0)
        seg = 72
        glBegin(GL_LINE_LOOP)
        for i in range(seg):
            a = 2.0 * math.pi * (i / seg)
            glVertex2f(cx + math.cos(a)*R, cy + math.sin(a)*R)
        glEnd()

        if show_markers and exp.exp.get("markers") is not None:
            glLineWidth(3.0)
            for m in exp.exp["markers"]:
                a = float(m["angle"])
                tx = cx + math.cos(a)*R
                ty = cy + math.sin(a)*R
                tx2 = cx + math.cos(a)*(R - 10)
                ty2 = cy + math.sin(a)*(R - 10)
                glColor4f(0.0, 0.55, 0.95, 0.95)
                glBegin(GL_LINES)
                glVertex2f(tx, ty)
                glVertex2f(tx2, ty2)
                glEnd()

        if show_platforms and exp.exp.get("platforms") is not None:
            for i, p in enumerate(exp.exp["platforms"]):
                visible_now = (exp.platforms_visible or exp.found[i] or (exp.phase == "hold"))
                if not (exp.platforms_present and visible_now):
                    continue

                mx, my = world_to_map(p["x"], p["z"])
                pr = (p["r"] / arena_r) * R
                if i == 0:
                    col = (0.95, 0.85, 0.25, 0.95)
                else:
                    col = (0.85, 0.75, 0.95, 0.95)

                glColor4f(*col)
                glBegin(GL_TRIANGLE_FAN)
                glVertex2f(mx, my)
                for k in range(seg + 1):
                    a = 2.0 * math.pi * (k / seg)
                    glVertex2f(mx + math.cos(a)*pr, my + math.sin(a)*pr)
                glEnd()

                glColor4f(0.0, 0.0, 0.0, 0.9)
                glLineWidth(1.5)
                glBegin(GL_LINE_LOOP)
                for k in range(seg):
                    a = 2.0 * math.pi * (k / seg)
                    glVertex2f(mx + math.cos(a)*pr, my + math.sin(a)*pr)
                glEnd()

        px, pz = exp.cam_pos[0], exp.cam_pos[2]
        mx, my = world_to_map(px, pz)
        glColor4f(0.0, 0.0, 0.0, 1.0)
        glPointSize(7.0)
        glBegin(GL_POINTS)
        glVertex2f(mx, my)
        glEnd()

        if show_direction:
            yaw = math.radians(exp.yaw)
            fx, fz = math.sin(yaw), -math.cos(yaw)
            ax, ay = world_to_map(px + fx*1.2, pz + fz*1.2)
            glLineWidth(2.0)
            glBegin(GL_LINES)
            glVertex2f(mx, my)
            glVertex2f(ax, ay)
            glEnd()

        glDisable(GL_BLEND)
        glEnable(GL_DEPTH_TEST)
        self._ortho_end()

# ============================================================
# Parallel port marker output (Psychopy-like)
# ============================================================
def _parse_addr(addr_hex_or_int):
    if isinstance(addr_hex_or_int, int):
        return addr_hex_or_int
    s = str(addr_hex_or_int).strip().lower()
    if s.startswith("0x"):
        return int(s, 16)
    return int(s)

def _quantize_ms(ms, q=100):
    q = max(1, int(q))
    ms = int(round(float(ms)))
    if ms <= 0:
        ms = q
    # enforce multiple of q (round to nearest, but never 0)
    ms = int(round(ms / q)) * q
    if ms <= 0:
        ms = q
    return ms

class ParallelPortLike:
    """
    Best-effort parallel-port writer.
    Tries:
      1) psychopy.parallel.ParallelPort (if installed)
      2) Windows InpOut32/InpOutx64 DLL via ctypes (if present on PATH)
      3) fallback dummy (does nothing)
    Uses DATA register write: out(address, value).
    """
    def __init__(self, address, enabled=True):
        self.address = int(address)
        self.enabled = bool(enabled)
        self.mode = "dummy"
        self._pp = None
        self._out32 = None
        self._dll = None

        if not self.enabled:
            return

        # 1) PsychoPy
        try:
            from psychopy import parallel  # type: ignore
            self._pp = parallel.ParallelPort(address=self.address)
            self.mode = "psychopy"
            return
        except Exception:
            self._pp = None

        # 2) InpOut32/InpOutx64 (Windows)
        try:
            import ctypes
            for dllname in ("inpoutx64.dll", "inpout32.dll"):
                try:
                    dll = ctypes.WinDLL(dllname)
                    out32 = dll.Out32
                    out32.argtypes = [ctypes.c_short, ctypes.c_short]
                    out32.restype = None
                    self._dll = dll
                    self._out32 = out32
                    self.mode = f"inpout({dllname})"
                    return
                except Exception:
                    continue
        except Exception:
            pass

        # 3) fallback dummy
        self.mode = "dummy"

    def set_data(self, value_byte):
        if not self.enabled:
            return
        v = int(value_byte) & 0xFF
        if self.mode == "psychopy" and self._pp is not None:
            try:
                self._pp.setData(v)
            except Exception:
                pass
        elif self._out32 is not None:
            try:
                self._out32(self.address, v)
            except Exception:
                pass
        else:
            # dummy: do nothing
            pass

class MarkerPulseScheduler:
    """
    Parallel-port pulse scheduler with event identity encoded by bit index.
    Only one bit is active at a time; pulses are queued without overlap.
    """
    def __init__(self, port: ParallelPortLike):
        self.port = port
        self.queue = []  # list of (bit_idx, dur_s)
        self.active_until = 0.0
        self.active = False
        self.active_bit = None
        self._off()

    def _on(self, bit_idx):
        bit_idx = max(0, min(7, int(bit_idx)))
        self.port.set_data(1 << bit_idx)
        self.active = True
        self.active_bit = bit_idx

    def _off(self):
        self.port.set_data(0)
        self.active = False
        self.active_bit = None

    def pulse(self, bit_idx, ms, now_s):
        dur_s = max(1, int(round(ms))) / 1000.0
        item = (max(0, min(7, int(bit_idx))), dur_s)
        if not self.active and not self.queue:
            self._on(item[0])
            self.active_until = now_s + item[1]
        else:
            self.queue.append(item)

    def update(self, now_s):
        if self.active and now_s >= self.active_until:
            self._off()
            self.active_until = 0.0

        if (not self.active) and self.queue:
            bit_idx, dur_s = self.queue.pop(0)
            self._on(bit_idx)
            self.active_until = now_s + dur_s

# ============================================================
# Logger
# ============================================================
class Logger:
    def __init__(self, base_dir="logs", run_name=None):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if run_name is None:
            run_name = f"vmwm_{ts}"
        self.run_dir = os.path.join(base_dir, run_name)
        os.makedirs(self.run_dir, exist_ok=True)
        self.t0 = time.perf_counter()

        self.f_events  = open(os.path.join(self.run_dir, "events.csv"),  "w", newline="", encoding="utf-8")
        self.f_actions = open(os.path.join(self.run_dir, "actions.csv"), "w", newline="", encoding="utf-8")
        self.f_samples = open(os.path.join(self.run_dir, "samples.csv"), "w", newline="", encoding="utf-8")
        self.f_trials  = open(os.path.join(self.run_dir, "trials.jsonl"), "w", encoding="utf-8")

        self.w_events = csv.DictWriter(self.f_events, fieldnames=[
            "t_exp", "trial_index", "trial_type", "phase", "event", "nav_time",
            "x", "z", "yaw_deg",
            "p1_x", "p1_z", "p1_r", "p1_found",
            "p2_x", "p2_z", "p2_r", "p2_found",
            "platforms_present", "platforms_visible",
            "details_json"
        ])
        self.w_actions = csv.DictWriter(self.f_actions, fieldnames=[
            "t_exp", "trial_index", "trial_type", "phase",
            "key", "action", "accepted",
            "x_before", "z_before", "yaw_before",
            "x_after",  "z_after",  "yaw_after",
            "p1_x", "p1_z", "p1_r", "p1_found", "dist_p1_before", "dist_p1_after",
            "p2_x", "p2_z", "p2_r", "p2_found", "dist_p2_before", "dist_p2_after",
        ])
        self.w_samples = csv.DictWriter(self.f_samples, fieldnames=[
            "t_exp", "trial_index", "trial_type", "phase", "nav_time",
            "x", "z", "yaw_deg",
            "p1_x", "p1_z", "p1_r", "p1_found", "dist_p1",
            "p2_x", "p2_z", "p2_r", "p2_found", "dist_p2",
            "platforms_present", "platforms_visible",
        ])

        self.w_events.writeheader()
        self.w_actions.writeheader()
        self.w_samples.writeheader()

    def now(self):
        return time.perf_counter() - self.t0

    def close(self):
        for f in (self.f_events, self.f_actions, self.f_samples, self.f_trials):
            try:
                f.flush()
                f.close()
            except Exception:
                pass

    def write_run_json(self, defaults, extra=None):
        payload = {"created_at": datetime.now().isoformat(), "defaults": defaults}
        if extra:
            payload.update(extra)
        with open(os.path.join(self.run_dir, "run.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def log_trial_config(self, trial_index, trial_type, params, platforms, markers, start_pose):
        obj = {
            "trial_index": trial_index,
            "trial_type": trial_type,
            "params": params,
            "platforms": platforms,
            "markers": markers,
            "start_pose": start_pose,
        }
        self.f_trials.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.f_trials.flush()

    @staticmethod
    def _pinfo(platforms, found_flags):
        if not platforms:
            return (None, None, None, 0, None, None, None, 0)
        p1, p2 = platforms[0], platforms[1]
        f1, f2 = found_flags
        return (p1["x"], p1["z"], p1["r"], int(bool(f1)),
                p2["x"], p2["z"], p2["r"], int(bool(f2)))

    def log_event(self, trial_index, trial_type, phase, event, nav_time,
                  pose, platforms, found_flags, platforms_present, platforms_visible, details=None):
        details_json = json.dumps(details or {}, ensure_ascii=False)
        p1x, p1z, p1r, f1, p2x, p2z, p2r, f2 = self._pinfo(platforms, found_flags)

        row = {
            "t_exp": f"{self.now():.6f}",
            "trial_index": trial_index,
            "trial_type": trial_type,
            "phase": phase,
            "event": event,
            "nav_time": f"{nav_time:.6f}" if nav_time is not None else "",
            "x": f"{pose[0]:.6f}" if pose else "",
            "z": f"{pose[2]:.6f}" if pose else "",
            "yaw_deg": f"{pose[3]:.6f}" if pose else "",
            "p1_x": f"{p1x:.6f}" if p1x is not None else "",
            "p1_z": f"{p1z:.6f}" if p1z is not None else "",
            "p1_r": f"{p1r:.6f}" if p1r is not None else "",
            "p1_found": f1,
            "p2_x": f"{p2x:.6f}" if p2x is not None else "",
            "p2_z": f"{p2z:.6f}" if p2z is not None else "",
            "p2_r": f"{p2r:.6f}" if p2r is not None else "",
            "p2_found": f2,
            "platforms_present": int(bool(platforms_present)),
            "platforms_visible": int(bool(platforms_visible)),
            "details_json": details_json
        }
        self.w_events.writerow(row)
        self.f_events.flush()

    def log_action(self, trial_index, trial_type, phase, key, action, accepted,
                   before_pose, after_pose, platforms, found_flags):
        if not platforms:
            return
        p1, p2 = platforms[0], platforms[1]
        f1, f2 = found_flags

        d1_0 = dist(before_pose[0], before_pose[2], p1["x"], p1["z"])
        d1_1 = dist(after_pose[0],  after_pose[2],  p1["x"], p1["z"])
        d2_0 = dist(before_pose[0], before_pose[2], p2["x"], p2["z"])
        d2_1 = dist(after_pose[0],  after_pose[2],  p2["x"], p2["z"])

        row = {
            "t_exp": f"{self.now():.6f}",
            "trial_index": trial_index,
            "trial_type": trial_type,
            "phase": phase,
            "key": key,
            "action": action,
            "accepted": int(bool(accepted)),
            "x_before": f"{before_pose[0]:.6f}",
            "z_before": f"{before_pose[2]:.6f}",
            "yaw_before": f"{before_pose[3]:.6f}",
            "x_after": f"{after_pose[0]:.6f}",
            "z_after": f"{after_pose[2]:.6f}",
            "yaw_after": f"{after_pose[3]:.6f}",

            "p1_x": f"{p1['x']:.6f}", "p1_z": f"{p1['z']:.6f}", "p1_r": f"{p1['r']:.6f}",
            "p1_found": int(bool(f1)),
            "dist_p1_before": f"{d1_0:.6f}", "dist_p1_after": f"{d1_1:.6f}",

            "p2_x": f"{p2['x']:.6f}", "p2_z": f"{p2['z']:.6f}", "p2_r": f"{p2['r']:.6f}",
            "p2_found": int(bool(f2)),
            "dist_p2_before": f"{d2_0:.6f}", "dist_p2_after": f"{d2_1:.6f}",
        }
        self.w_actions.writerow(row)
        self.f_actions.flush()

    def log_sample(self, trial_index, trial_type, phase, nav_time,
                   pose, platforms, found_flags, platforms_present, platforms_visible):
        if not platforms:
            return
        p1, p2 = platforms[0], platforms[1]
        f1, f2 = found_flags
        d1 = dist(pose[0], pose[2], p1["x"], p1["z"])
        d2 = dist(pose[0], pose[2], p2["x"], p2["z"])

        row = {
            "t_exp": f"{self.now():.6f}",
            "trial_index": trial_index,
            "trial_type": trial_type,
            "phase": phase,
            "nav_time": f"{nav_time:.6f}" if nav_time is not None else "",
            "x": f"{pose[0]:.6f}",
            "z": f"{pose[2]:.6f}",
            "yaw_deg": f"{pose[3]:.6f}",

            "p1_x": f"{p1['x']:.6f}", "p1_z": f"{p1['z']:.6f}", "p1_r": f"{p1['r']:.6f}",
            "p1_found": int(bool(f1)),
            "dist_p1": f"{d1:.6f}",

            "p2_x": f"{p2['x']:.6f}", "p2_z": f"{p2['z']:.6f}", "p2_r": f"{p2['r']:.6f}",
            "p2_found": int(bool(f2)),
            "dist_p2": f"{d2:.6f}",

            "platforms_present": int(bool(platforms_present)),
            "platforms_visible": int(bool(platforms_visible)),
        }
        self.w_samples.writerow(row)

# ============================================================
# Experiment / State machine
# ============================================================
class Experiment:
    def __init__(self, defaults):
        self.p = defaults
        self.visuals = ArenaVisuals()
        self.grass = GrassField(size=80.0, step=2.0)
        self.overlay = Overlay()

        self.fence_seed = random.randrange(10**9)
        self.fence_rng = random.Random(self.fence_seed)
        self.fence_colors = None

        self.exp = {"platforms": None, "markers": None}
        self.found = [False, False]
        self.world_is_mirrored = False

        self.phase = "init"
        self.prev_phase = None
        self.trial_i = 0
        self.trial_type = None

        self.platforms_present = True
        self.platforms_visible = True

        self.trial_time = 0.0
        self.nav_elapsed = 0.0
        self.nav_start_banner = 0.0
        self.first_found_banner = 0.0
        self.both_found_banner = 0.0

        self.path_len = 0.0
        self.n_fwd = 0
        self.n_bwd = 0
        self.n_left = 0
        self.n_right = 0

        self.cam_pos = [0.0, float(defaults["eye_y"]), 0.0]
        self.yaw = 0.0
        self.pitch = float(defaults["fixed_pitch_deg"])

        self.sample_hz = float(self.p.get("log_sample_hz", 10.0))
        self.sample_dt = 1.0 / max(1e-6, self.sample_hz)
        self.sample_accum = 0.0

        # continuous key state
        #self.key_held = {"F": False, "B": False, "L": False, "R": False}
        self.pending_actions = []

    def pose(self):
        return (self.cam_pos[0], self.cam_pos[1], self.cam_pos[2], self.yaw)

    def reset_trial_stats(self):
        self.trial_time = 0.0
        self.nav_elapsed = 0.0
        self.nav_start_banner = 0.0
        self.sample_accum = 0.0
        self.path_len = 0.0
        self.n_fwd = self.n_bwd = self.n_left = self.n_right = 0
        self.first_found_banner = 0.0
        self.both_found_banner = 0.0

    def ensure_world(self):
        ARENA_R = float(self.p["arena_r"])
        EYE_Y = float(self.p["eye_y"])

        if self.exp["markers"] is None or (not self.p["markers_fixed"]):
            self.exp["markers"] = self.visuals.make_markers(
                y_min=float(self.p["marker_y_min"]),
                y_max=float(self.p["marker_y_max"]),
                sector_frac=float(self.p.get("marker_sector_frac", 0.55)),
            )
            self.world_is_mirrored = False

        if self.exp["platforms"] is None or (not self.p["platform_fixed"]):
            self.exp["platforms"] = make_two_platforms(
                arena_r=ARENA_R,
                platform_r=float(self.p["platform_r"]),
                wall_margin=float(self.p["platform_wall_margin"]),
                center_margin=float(self.p["platform_center_margin"]),
                min_between=float(self.p["platform_min_dist_between"]),
            )
            self.world_is_mirrored = False

        self.cam_pos[:] = rand_start(
            arena_r=ARENA_R,
            eye_y=EYE_Y,
            start_near_wall=bool(self.p["start_near_wall"]),
            frac=float(self.p["start_wall_radius_frac"]),
        )

        min_d = float(self.p["start_min_dist_to_platform"])
        for _ in range(80):
            dmin2 = min(
                dist2(self.cam_pos[0], self.cam_pos[2], self.exp["platforms"][0]["x"], self.exp["platforms"][0]["z"]),
                dist2(self.cam_pos[0], self.cam_pos[2], self.exp["platforms"][1]["x"], self.exp["platforms"][1]["z"]),
            )
            if dmin2 >= (min_d * min_d):
                break
            self.cam_pos[:] = rand_start(ARENA_R, EYE_Y, bool(self.p["start_near_wall"]), float(self.p["start_wall_radius_frac"]))

        self.yaw = yaw_look_at_center(self.cam_pos[0], self.cam_pos[2], jitter_deg=float(self.p.get("start_jitter_deg", 0.0)))
        self.pitch = float(self.p.get("fixed_pitch_deg", 0.0))

    def toggle_world_mirror(self):
        if self.exp.get("platforms") is not None:
            for p in self.exp["platforms"]:
                p["x"] = -float(p["x"])
        if self.exp.get("markers") is not None:
            for m in self.exp["markers"]:
                m["angle"] = (math.pi - float(m["angle"])) % (2.0 * math.pi)
        self.world_is_mirrored = not self.world_is_mirrored

    def mirror_pose(self):
        self.cam_pos[0] = -float(self.cam_pos[0])
        self.yaw = -float(self.yaw)

    def set_trial_phase_from_type(self, trial_type):
        if trial_type == "instr":
            self.platforms_present = False
            self.platforms_visible = False
            return "instr"

        if trial_type == "change":
            if bool(self.p.get("change_markers", True)):
                self.exp["markers"] = self.visuals.make_markers(
                    y_min=float(self.p["marker_y_min"]),
                    y_max=float(self.p["marker_y_max"]),
                    sector_frac=float(self.p.get("marker_sector_frac", 0.55)),
                )
            if bool(self.p.get("change_platform", True)):
                self.exp["platforms"] = make_two_platforms(
                    arena_r=float(self.p["arena_r"]),
                    platform_r=float(self.p["platform_r"]),
                    wall_margin=float(self.p["platform_wall_margin"]),
                    center_margin=float(self.p["platform_center_margin"]),
                    min_between=float(self.p["platform_min_dist_between"]),
                )
            self.platforms_present = True
            self.platforms_visible = False
            return "change"

        if trial_type == "pause":
            self.platforms_present = False
            self.platforms_visible = False
            return "pause"

        if trial_type == "visible":
            self.platforms_present = True
            self.platforms_visible = True
            return "look"

        if trial_type in ACQ_LIKE_TYPES:
            self.platforms_present = True
            self.platforms_visible = False
            return "look"

        if trial_type == "probe":
            self.platforms_present = False
            self.platforms_visible = False
            return "look"

        self.platforms_present = True
        self.platforms_visible = False
        return "look"

# ============================================================
# GL init (manual perspective)
# ============================================================
def setup_gl(w, h, fovy_deg=75.0, z_near=0.05, z_far=300.0):
    glEnable(GL_DEPTH_TEST)
    glDisable(GL_LIGHTING)
    glDisable(GL_CULL_FACE)
    glClearColor(0.55, 0.75, 0.95, 1.0)

    glMatrixMode(GL_PROJECTION); glLoadIdentity()
    fovy = math.radians(float(fovy_deg))
    aspect = w / h
    f = 1.0 / math.tan(fovy / 2.0)
    proj = [
        [f/aspect, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, (z_far+z_near)/(z_near-z_far), (2*z_far*z_near)/(z_near-z_far)],
        [0, 0, -1, 0],
    ]
    glLoadMatrixf([
        proj[0][0], proj[1][0], proj[2][0], proj[3][0],
        proj[0][1], proj[1][1], proj[2][1], proj[3][1],
        proj[0][2], proj[1][2], proj[2][2], proj[3][2],
        proj[0][3], proj[1][3], proj[2][3], proj[3][3],
    ])
    glMatrixMode(GL_MODELVIEW)

# ============================================================
# Main loop
# ============================================================

pygame.init()
pygame.font.init()

pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 2)
pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_COMPATIBILITY)
pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)


w, h = 1000, 700
pygame.display.set_mode((w, h), DOUBLEBUF | OPENGL)
pygame.display.set_caption("vMWM — continuous + parallel markers")

setup_gl(w, h)

pygame.event.set_grab(False)
pygame.mouse.set_visible(True)

exp = Experiment(DEFAULTS)
ov = exp.overlay

# per-run fence palette
WALL_SEGMENTS = 160
exp.fence_colors = [wood_color(exp.fence_rng) for _ in range(WALL_SEGMENTS)]

# parallel marker output
pp_addr = _parse_addr(exp.p.get("pp_address_hex", "0xE030"))
pp = ParallelPortLike(address=pp_addr, enabled=bool(exp.p.get("pp_enabled", True)))
marker = MarkerPulseScheduler(port=pp)



logger = Logger(base_dir="logs")
logger.write_run_json(DEFAULTS, extra={
    "window": {"w": w, "h": h},
    "fovy_deg": 75.0,
    "script_version": "vmwm_mirror_flowers_parallel_bits_v2",
    "grass_seed": exp.grass.seed,
    "fence_seed": exp.fence_seed,
    "parallel": {
        "enabled": bool(exp.p.get("pp_enabled", True)),
        "port_name": exp.p.get("pp_port_name", "LPT"),
        "address": hex(pp_addr),
        "pulse_dur_ms": int(exp.p.get("pp_pulse_dur_ms", 100)),
        "channels": {
            "trial_start": int(exp.p.get("pp_channel_trial_start", 0)),
            "nav_start": int(exp.p.get("pp_channel_nav_start", 1)),
            "platform1": int(exp.p.get("pp_channel_platform1", 2)),
            "platform2": int(exp.p.get("pp_channel_platform2", 3)),
        },
        "backend_mode": pp.mode
    }
})
logger.log_event(
    trial_index=-1, trial_type="run", phase="init", event="RUN_START",
    nav_time=None, pose=None, platforms=None, found_flags=(False, False),
    platforms_present=False, platforms_visible=False, details={}
)

clock = pygame.time.Clock()
running = True
t = 0.0

# ------------------------------------------------------------111112333333333333333333333
# Universal waiting text screen (ends on key "1")
# ------------------------------------------------------------
def wait_screen(text, size_px=28, x=60, y_from_top=60,
                bg="white", anchor="topleft",
                line_step=None, key_accept=(K_1, K_KP1)):
    global running
    if line_step is None:
        line_step = int(size_px * 1.25)

    # ensure no "held" state leaks into start
    #exp.key_held = {"F": False, "B": False, "L": False, "R": False}
    exp.pending_actions.clear()
    while running:
        for e in pygame.event.get():
            if e.type == QUIT:
                running = False
                return False
            if e.type == KEYDOWN:
                if e.key == K_ESCAPE:
                    running = False
                    return False
                if e.key in key_accept:
                    return True

        if bg == "white":
            ov.draw_white_screen(w, h)
        elif bg == "veil":
            ov.draw_pause_veil_blur(w, h, alpha=1.0)
        else:
            ov.draw_white_screen(w, h)

        yy = y_from_top
        for ln in str(text).splitlines():
            ov.draw_text(w, h, ln, x=x, y_from_top=yy, size_px=size_px, color=(0,0,0), anchor=anchor)
            yy += line_step

        pygame.display.flip()
        clock.tick(60)

    return False

def log_phase_enter():
    if exp.prev_phase != exp.phase:
        logger.log_event(
            trial_index=exp.trial_i,
            trial_type=exp.trial_type,
            phase=exp.phase,
            event="PHASE_ENTER",
            nav_time=exp.nav_elapsed if exp.phase in ("nav", "hold", "reveal") else None,
            pose=exp.pose(),
            platforms=exp.exp.get("platforms"),
            found_flags=(exp.found[0], exp.found[1]),
            platforms_present=exp.platforms_present,
            platforms_visible=exp.platforms_visible,
            details={"from": exp.prev_phase}
        )
        exp.prev_phase = exp.phase

def end_trial(result_details):
    logger.log_event(
        trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
        event="TRIAL_END",
        nav_time=exp.nav_elapsed if exp.phase in ("nav", "hold", "reveal") else None,
        pose=exp.pose(),
        platforms=exp.exp.get("platforms"),
        found_flags=(exp.found[0], exp.found[1]),
        platforms_present=exp.platforms_present,
        platforms_visible=exp.platforms_visible,
        details=result_details
    )
    exp.trial_i += 1
    exp.phase = "init"

def restart_run():
    logger.log_event(
        trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
        event="RUN_RESTART",
        nav_time=exp.nav_elapsed if exp.phase in ("nav","hold","reveal") else None,
        pose=exp.pose(),
        platforms=exp.exp.get("platforms"),
        found_flags=(exp.found[0], exp.found[1]),
        platforms_present=exp.platforms_present,
        platforms_visible=exp.platforms_visible,
        details={}
    )
    exp.trial_i = 0
    exp.phase = "init"
    exp.exp["platforms"] = None
    exp.exp["markers"] = None
    exp.nav_elapsed = 0.0
    exp.nav_start_banner = 0.0
    exp.found[:] = [False, False]
    #exp.key_held = {"F": False, "B": False, "L": False, "R": False}
    exp.pending_actions.clear()
    # make sure port is low
    marker.queue.clear()
    marker._off()

def send_marker(event_name, now_s):
    if not bool(exp.p.get("pp_enabled", True)):
        return None

    channel_map = {
        "TRIAL_START": int(exp.p.get("pp_channel_trial_start", 0)),
        "NAV_START": int(exp.p.get("pp_channel_nav_start", 1)),
        "PLATFORM1": int(exp.p.get("pp_channel_platform1", 2)),
        "PLATFORM2": int(exp.p.get("pp_channel_platform2", 3)),
    }
    bit_idx = channel_map.get(event_name, 0)
    dur_ms = int(exp.p.get("pp_pulse_dur_ms", 100))
    marker.pulse(bit_idx, dur_ms, now_s=now_s)
    return {"pp_channel": bit_idx, "pp_pulse_ms": dur_ms}

try:
    while running:
        dt = clock.tick(60) / 1000.0
        t += dt
        exp.sample_accum += dt

        # update marker pulses
        marker.update(now_s=t)

        # ----------------------------
        # Start next trial
        # ----------------------------
        if exp.phase == "init":
            if exp.trial_i >= len(TRIAL_SEQ):
                break

            item = TRIAL_SEQ[exp.trial_i]
            exp.trial_type = item.get("type", "acq")

            if exp.trial_type != "mirror_acq" and exp.world_is_mirrored:
                exp.toggle_world_mirror()

            exp.ensure_world()
            exp.found[:] = [False, False]
            #exp.key_held = {"F": False, "B": False, "L": False, "R": False}
            exp.pending_actions.clear()
            exp.reset_trial_stats()

            exp.phase = exp.set_trial_phase_from_type(exp.trial_type)

            if exp.trial_type == "mirror_acq" and not exp.world_is_mirrored:
                exp.toggle_world_mirror()
                exp.mirror_pose()

            logger.log_trial_config(
                trial_index=exp.trial_i,
                trial_type=exp.trial_type,
                params=exp.p,
                platforms=exp.exp.get("platforms"),
                markers=exp.exp.get("markers"),
                start_pose={"x": exp.cam_pos[0], "z": exp.cam_pos[2], "yaw_deg": exp.yaw}
            )

            # IMPORTANT EVENT: TRIAL_START marker
            ms_sent = send_marker("TRIAL_START", now_s=t)

            logger.log_event(
                trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                event="TRIAL_START",
                nav_time=None,
                pose=exp.pose(),
                platforms=exp.exp.get("platforms"),
                found_flags=(exp.found[0], exp.found[1]),
                platforms_present=exp.platforms_present,
                platforms_visible=exp.platforms_visible,
                details={"trial_start_t_exp": logger.now(), **(ms_sent or {})}
            )

            exp.prev_phase = None
            log_phase_enter()

            # INSTR wait screen
            if exp.phase == "instr":
                logger.log_event(
                    trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                    event="WAITSCREEN_SHOWN",
                    nav_time=None, pose=exp.pose(),
                    platforms=exp.exp.get("platforms"),
                    found_flags=(exp.found[0], exp.found[1]),
                    platforms_present=exp.platforms_present,
                    platforms_visible=exp.platforms_visible,
                    details={"kind": "instr"}
                )
                ok = wait_screen(INSTR_TEXT, size_px=28, x=60, y_from_top=60, bg="white", anchor="topleft")
                if not ok:
                    break

                logger.log_event(
                    trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                    event="WAITSCREEN_ACK",
                    nav_time=None, pose=exp.pose(),
                    platforms=exp.exp.get("platforms"),
                    found_flags=(exp.found[0], exp.found[1]),
                    platforms_present=exp.platforms_present,
                    platforms_visible=exp.platforms_visible,
                    details={"kind": "instr"}
                )
                exp.trial_i += 1
                exp.phase = "init"
                continue

            # CHANGE wait screen (no physical time)
            if exp.phase == "change":
                logger.log_event(
                    trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                    event="WAITSCREEN_SHOWN",
                    nav_time=None, pose=exp.pose(),
                    platforms=exp.exp.get("platforms"),
                    found_flags=(exp.found[0], exp.found[1]),
                    platforms_present=exp.platforms_present,
                    platforms_visible=exp.platforms_visible,
                    details={"kind": "change"}
                )

                ok = wait_screen(CHANGE_TEXT, size_px=30, x=w//2, y_from_top=h//2 - 40,
                                    bg="white", anchor="topmiddle")
                if not ok:
                    break

                logger.log_event(
                    trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                    event="WAITSCREEN_ACK",
                    nav_time=None, pose=exp.pose(),
                    platforms=exp.exp.get("platforms"),
                    found_flags=(exp.found[0], exp.found[1]),
                    platforms_present=exp.platforms_present,
                    platforms_visible=exp.platforms_visible,
                    details={"kind": "change"}
                )
                end_trial({"result": "change_done"})
                continue

        # ----------------------------
        # Events (keydown/keyup set held state)
        # ----------------------------
        for e in pygame.event.get():
            if e.type == QUIT:
                running = False

            elif e.type == KEYDOWN:
                if e.key == K_ESCAPE:
                    running = False
                elif e.key == K_r:
                    restart_run()
                else:
                    if e.key in (K_1, K_KP1):
                        exp.pending_actions.append(("1", "F"))
                        #exp.key_held["F"] = True
                        #logger.log_action(exp.trial_i, exp.trial_type, exp.phase, "1", "F_DOWN", True,
                        #                    exp.pose(), exp.pose(), exp.exp.get("platforms"), (exp.found[0], exp.found[1]))
                    elif e.key in (K_2, K_KP2):
                        exp.pending_actions.append(("12", "B"))
                        #exp.key_held["B"] = True
                        #logger.log_action(exp.trial_i, exp.trial_type, exp.phase, "2", "B_DOWN", True,
                        #                    exp.pose(), exp.pose(), exp.exp.get("platforms"), (exp.found[0], exp.found[1]))
                    elif e.key in (K_3, K_KP3):
                        exp.pending_actions.append(("3", "L"))
                        #exp.key_held["L"] = True
                        #logger.log_action(exp.trial_i, exp.trial_type, exp.phase, "3", "L_DOWN", True,
                        #                    exp.pose(), exp.pose(), exp.exp.get("platforms"), (exp.found[0], exp.found[1]))
                    elif e.key in (K_4, K_KP4):
                        exp.pending_actions.append(("4", "R"))
                        #exp.key_held["R"] = True
                        #logger.log_action(exp.trial_i, exp.trial_type, exp.phase, "4", "R_DOWN", True,
                        #                    exp.pose(), exp.pose(), exp.exp.get("platforms"), (exp.found[0], exp.found[1]))

                    


        if not running:
            break

        # ----------------------------
        # Time
        # ----------------------------
        exp.trial_time += dt
        if exp.phase in ("nav", "hold", "reveal"):
            exp.nav_elapsed += dt

        if exp.nav_start_banner > 0.0:
            exp.nav_start_banner = max(0.0, exp.nav_start_banner - dt)
        if exp.first_found_banner > 0.0:
            exp.first_found_banner = max(0.0, exp.first_found_banner - dt)
        if exp.both_found_banner > 0.0:
            exp.both_found_banner = max(0.0, exp.both_found_banner - dt)

        # ----------------------------
        # Phase transitions
        # ----------------------------
        if exp.phase == "pause":
            if exp.trial_time >= float(exp.p["pause_dur"]):
                end_trial({"result": "pause_done"})

        elif exp.phase == "look":
            if exp.trial_time >= float(exp.p["look_dur"]):
                logger.log_event(
                    trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                    event="LOOK_END",
                    nav_time=None,
                    pose=exp.pose(),
                    platforms=exp.exp.get("platforms"),
                    found_flags=(exp.found[0], exp.found[1]),
                    platforms_present=exp.platforms_present,
                    platforms_visible=exp.platforms_visible,
                    details={}
                )
                exp.phase = "nav"
                exp.trial_time = 0.0
                exp.nav_elapsed = 0.0
                exp.nav_start_banner = 1.0

                # IMPORTANT EVENT: NAV_START marker
                ms_sent = send_marker("NAV_START", now_s=t)

                logger.log_event(
                    trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                    event="NAV_START",
                    nav_time=0.0,
                    pose=exp.pose(),
                    platforms=exp.exp.get("platforms"),
                    found_flags=(exp.found[0], exp.found[1]),
                    platforms_present=exp.platforms_present,
                    platforms_visible=exp.platforms_visible,
                    details=(ms_sent or {})
                )

        elif exp.phase == "nav":
            if (exp.phase in ("nav", "reveal")) and exp.platforms_present and exp.exp.get("platforms") is not None:
                for idx in (0, 1):
                    if exp.found[idx]:
                        continue
                    p = exp.exp["platforms"][idx]
                    if dist2(exp.cam_pos[0], exp.cam_pos[2], p["x"], p["z"]) <= (p["r"] ** 2):
                        exp.found[idx] = True

                        # IMPORTANT EVENT: platform markers
                        ms_sent = send_marker("PLATFORM1" if idx == 0 else "PLATFORM2", now_s=t)

                        logger.log_event(
                            trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                            event="PLATFORM_FOUND",
                            nav_time=exp.nav_elapsed,
                            pose=exp.pose(),
                            platforms=exp.exp.get("platforms"),
                            found_flags=(exp.found[0], exp.found[1]),
                            platforms_present=exp.platforms_present,
                            platforms_visible=exp.platforms_visible,
                            details={
                                "which": idx + 1,
                                **(ms_sent or {}),
                                "path_len": exp.path_len,
                                "n_fwd": exp.n_fwd, "n_bwd": exp.n_bwd, "n_left": exp.n_left, "n_right": exp.n_right
                            }
                        )

                        if exp.found[0] and exp.found[1]:
                            # IMPORTANT: "visible" must end ONLY by timeout, not by "both found"
                            if exp.trial_type != "visible":
                                exp.phase = "hold"
                                exp.trial_time = 0.0
                            else:
                                exp.both_found_banner = 3.0
                        else:
                            exp.first_found_banner = 3.0
                        break

            if exp.phase == "nav":
                if exp.trial_type == "probe":
                    if exp.trial_time >= float(exp.p["probe_dur"]):
                        end_trial({
                            "result": "probe_end",
                            "found1": exp.found[0], "found2": exp.found[1],
                            "path_len": exp.path_len,
                            "n_fwd": exp.n_fwd, "n_bwd": exp.n_bwd, "n_left": exp.n_left, "n_right": exp.n_right
                        })
                else:
                    if exp.trial_time >= float(exp.p["timeout"]):
                        logger.log_event(
                            trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                            event="TIMEOUT",
                            nav_time=exp.nav_elapsed,
                            pose=exp.pose(),
                            platforms=exp.exp.get("platforms"),
                            found_flags=(exp.found[0], exp.found[1]),
                            platforms_present=exp.platforms_present,
                            platforms_visible=exp.platforms_visible,
                            details={
                                "found1": exp.found[0], "found2": exp.found[1],
                                "path_len": exp.path_len,
                                "n_fwd": exp.n_fwd, "n_bwd": exp.n_bwd, "n_left": exp.n_left, "n_right": exp.n_right
                            }
                        )
                        if (exp.trial_type in ACQ_LIKE_TYPES) and bool(exp.p.get("reveal_on_timeout", True)):
                            exp.platforms_present = True
                            exp.platforms_visible = True
                            exp.phase = "reveal"
                            exp.trial_time = 0.0
                            logger.log_event(
                                trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                                event="REVEAL_START",
                                nav_time=exp.nav_elapsed,
                                pose=exp.pose(),
                                platforms=exp.exp.get("platforms"),
                                found_flags=(exp.found[0], exp.found[1]),
                                platforms_present=exp.platforms_present,
                                platforms_visible=exp.platforms_visible,
                                details={}
                            )
                        else:
                            end_trial({"result": "timeout_end"})

        elif exp.phase == "hold":
            if exp.trial_time >= float(exp.p["hold_on_platform"]):
                end_trial({
                    "result": "both_found",
                    "path_len": exp.path_len,
                    "n_fwd": exp.n_fwd, "n_bwd": exp.n_bwd, "n_left": exp.n_left, "n_right": exp.n_right
                })

        elif exp.phase == "reveal":
            exp.platforms_visible = True
            if exp.trial_time >= float(exp.p["reveal_dur"]):
                logger.log_event(
                    trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                    event="REVEAL_END",
                    nav_time=exp.nav_elapsed,
                    pose=exp.pose(),
                    platforms=exp.exp.get("platforms"),
                    found_flags=(exp.found[0], exp.found[1]),
                    platforms_present=exp.platforms_present,
                    platforms_visible=exp.platforms_visible,
                    details={}
                )
                end_trial({"result": "reveal_done"})

        log_phase_enter()

        # ----------------------------
        # Apply DISCRETE actions (keypress queue)
        # ----------------------------
        allow_turn = (exp.phase in ("look", "nav", "hold", "reveal"))
        allow_move = (exp.phase in ("nav", "reveal"))
        move_step = float(exp.p.get("move_step", 0.65))
        turn_step = float(exp.p.get("turn_step_deg", 12.0))
        ARENA_R = float(exp.p["arena_r"])

        while exp.pending_actions:
            key_str, act = exp.pending_actions.pop(0)
            before = exp.pose()
            accepted = False

            if act == "L" and allow_turn:
                exp.yaw -= turn_step
                exp.n_left += 1
                accepted = True
            elif act == "R" and allow_turn:
                exp.yaw += turn_step
                exp.n_right += 1
                accepted = True
            elif act == "F" and allow_move:
                yaw_rad = math.radians(exp.yaw)
                fx, fz = math.sin(yaw_rad), -math.cos(yaw_rad)
                nx = exp.cam_pos[0] + fx * move_step
                nz = exp.cam_pos[2] + fz * move_step
                nx, nz = clamp_inside_cylinder(nx, nz, ARENA_R, margin=0.25)
                exp.path_len += dist(exp.cam_pos[0], exp.cam_pos[2], nx, nz)
                exp.cam_pos[0], exp.cam_pos[2] = nx, nz
                exp.n_fwd += 1
                accepted = True
            elif act == "B" and allow_move:
                yaw_rad = math.radians(exp.yaw)
                fx, fz = math.sin(yaw_rad), -math.cos(yaw_rad)
                nx = exp.cam_pos[0] - fx * move_step
                nz = exp.cam_pos[2] - fz * move_step
                nx, nz = clamp_inside_cylinder(nx, nz, ARENA_R, margin=0.25)
                exp.path_len += dist(exp.cam_pos[0], exp.cam_pos[2], nx, nz)
                exp.cam_pos[0], exp.cam_pos[2] = nx, nz
                exp.n_bwd += 1
                accepted = True

            after = exp.pose()

            logger.log_action(
                trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                key=key_str, action=act, accepted=accepted,
                before_pose=before, after_pose=after,
                platforms=exp.exp.get("platforms"),
                found_flags=(exp.found[0], exp.found[1])
            )

            # optional immediate sample on each action (как было раньше)
            logger.log_sample(
                trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                nav_time=exp.nav_elapsed if exp.phase in ("nav","hold","reveal") else None,
                pose=exp.pose(),
                platforms=exp.exp.get("platforms"),
                found_flags=(exp.found[0], exp.found[1]),
                platforms_present=exp.platforms_present,
                platforms_visible=exp.platforms_visible
            )
                
        # sample at fixed Hz
        if exp.phase in ("look", "nav", "hold", "reveal"):
            while exp.sample_accum >= exp.sample_dt:
                exp.sample_accum -= exp.sample_dt
                logger.log_sample(
                    trial_index=exp.trial_i, trial_type=exp.trial_type, phase=exp.phase,
                    nav_time=exp.nav_elapsed if exp.phase in ("nav","hold","reveal") else None,
                    pose=exp.pose(),
                    platforms=exp.exp.get("platforms"),
                    found_flags=(exp.found[0], exp.found[1]),
                    platforms_present=exp.platforms_present,
                    platforms_visible=exp.platforms_visible
                )

        exp.cam_pos[1] = float(exp.p["eye_y"])
        exp.pitch = float(exp.p.get("fixed_pitch_deg", 0.0))

        # ----------------------------
        # HARD PAUSE SCREEN (no 3D render => no arena flicker)
        # ----------------------------
        if exp.phase == "pause":
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            ov.draw_white_screen(w, h)
            ov.draw_fixation_cross(w, h, size_px=30, thickness=10)
            pygame.display.flip()
            continue

        # ============================================================
        # Render 3D
        # ============================================================
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glRotatef(exp.pitch, 1, 0, 0)
        glRotatef(exp.yaw,   0, 1, 0)
        glTranslatef(-exp.cam_pos[0], -exp.cam_pos[1], -exp.cam_pos[2])

        exp.grass.draw(y0=0.0, t=t)
        exp.visuals.draw_wall_fence(
            radius=float(exp.p["arena_r"]),
            height=float(exp.p["wall_h"]),
            segments=WALL_SEGMENTS,
            y0=0.0,
            colors=exp.fence_colors
        )

        if exp.exp["markers"] is not None:
            for m in exp.exp["markers"]:
                exp.visuals.draw_marker_outline(
                    m["type"],
                    radius=float(exp.p["arena_r"]),
                    angle_rad=m["angle"],
                    y_center=m["y"],
                    wall_height=float(exp.p["wall_h"])
                )

        if exp.platforms_present and exp.exp.get("platforms") is not None:
            for i, p in enumerate(exp.exp["platforms"]):
                if exp.platforms_visible or exp.found[i] or (exp.phase == "hold"):
                    if i == 0:
                        petal_color = (0.98, 0.90, 0.22)
                        center_color = (0.95, 0.42, 0.06)
                    else:
                        petal_color = (0.78, 0.62, 0.95)
                        center_color = (0.08, 0.16, 0.55)
                    draw_flower_platform(p["x"], p["z"], y=0.0, radius=p["r"],
                                         petal_color=petal_color, center_color=center_color)

        # ============================================================
        # Render UI overlays
        # ============================================================
        pad = 18

        if exp.phase == "look":
            remain = max(0.0, float(exp.p["look_dur"]) - exp.trial_time)
            look_label = "Осмотр"
            if exp.trial_type == "visible":
                look_label = "Осмотр (обучение)"
            elif exp.trial_type in ACQ_LIKE_TYPES or exp.trial_type == "probe":
                look_label = "Осмотр"
            ov.draw_text(w, h, f"{look_label}: {int(remain):d} c", x=w//2, y_from_top=pad,
                            size_px=26, color=(0,0,0), anchor="topmiddle")

        if exp.phase == "nav" and exp.nav_start_banner > 0.0:
            ov.draw_text(w, h, "СТАРТ", x=w//2, y_from_top=pad+34,
                            size_px=28, color=(0,0,0), anchor="topmiddle")

        if exp.phase == "reveal":
            ov.draw_text(w, h, "Платформы показаны. Убедитесь, что вы запомнили расположение", x=w//2, y_from_top=pad,
                            size_px=26, color=(0,0,0), anchor="topmiddle")

        if exp.phase == "nav":
            ov.draw_text(w, h, f"{exp.nav_elapsed:0.1f} c", x=w-pad, y_from_top=pad,
                            size_px=26, color=(0,0,0), anchor="topright")
            ov.draw_text(w, h, f"Найдено: {int(exp.found[0]) + int(exp.found[1])}/2", x=pad, y_from_top=pad,
                            size_px=24, color=(0,0,0), anchor="topleft")
            if exp.first_found_banner > 0.0:
                ov.draw_text(w, h, "Первая платформа найдена — идите ко второй!", x=w//2, y_from_top=pad+34,
                                size_px=26, color=(0,0,0), anchor="topmiddle")
            if exp.trial_type == "visible" and exp.both_found_banner > 0.0:
                ov.draw_text(w, h, "Вы нашли ОБЕ платформы!", x=w//2, y_from_top=pad+68,
                                size_px=28, color=(0,0,0), anchor="topmiddle")

        if exp.phase == "hold":
            ov.draw_text(w, h, "Вы нашли ОБЕ платформы!", x=w//2, y_from_top=pad,
                            size_px=28, color=(0,0,0), anchor="topmiddle")
        if PLOT_MINIMAP:
            ov.draw_minimap(w, h, exp, x_from_left=18, y_from_top=18, size_px=190,
                            show_markers=True, show_platforms=True, show_direction=True)

        pygame.display.flip()

finally:
    try:
        logger.log_event(
            trial_index=exp.trial_i,
            trial_type=exp.trial_type if exp.trial_type else "run",
            phase=exp.phase,
            event="RUN_END",
            nav_time=exp.nav_elapsed if exp.phase in ("nav","hold","reveal") else None,
            pose=exp.pose(),
            platforms=exp.exp.get("platforms"),
            found_flags=(exp.found[0], exp.found[1]),
            platforms_present=exp.platforms_present,
            platforms_visible=exp.platforms_visible,
            details={}
        )
    except Exception:
        pass
    # ensure port low
    try:
        marker.queue.clear()
        marker._off()
    except Exception:
        pass
    logger.close()
    pygame.quit()

