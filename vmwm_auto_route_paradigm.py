# pip install pygame PyOpenGL PyOpenGL_accelerate
"""
Новая версия vMWM с автоматическим прохождением маршрута.
Сохранены базовые OpenGL/pygame настройки из рабочего скрипта.
"""

import math
import random
import os
import time
import json
from datetime import datetime

import pygame
from pygame.locals import *
from OpenGL.GL import *

os.environ.setdefault("SDL_VIDEODRIVER", "windows")

DEFAULTS = {
    "arena_r": 12.0,
    "eye_y": 2.0,
    "look_dur": 4.0,
    "pause_dur": 6.0,

    # объекты
    "objects_n": 3,
    "platform_r": 1.1,
    "platform_center_margin": 3.0,
    "platform_wall_margin": 2.8,
    "platform_min_dist_between": 4.2,

    # маршрут
    "route_segments_min": 4,
    "route_segments_max": 6,
    "route_seg_len_min": 4,
    "route_seg_len_max": 6,
    "route_speed_min": 1.0,
    "route_speed_max": 1.2,
    "turn_base_deg_per_sec": 45.0,
    "non_object_min_dist_mul": 2.5,

    # миникарта
    "show_minimap": False,
    "show_minimap_in_training": True,

    # тренировка free
    "free_move_step": 0.45,
    "free_turn_deg": 8.0,

    # лог
    "log_dir": "logs",
}

TRIAL_SEQ = [
    {"type": "instr"},
    {"type": "train_free"},
    {"type": "pause"},
    {"type": "train_auto_visible"},
    {"type": "pause"},
]
for _ in range(5):
    block = [
        {"type": "acq"}, {"type": "pause"},
        {"type": "mirror_acq"}, {"type": "pause"},
        {"type": "probe"}, {"type": "pause"},
    ]
    random.shuffle(block)
    TRIAL_SEQ.extend(block)

INSTR_TEXT = (
    "Инструкция\n\n"
    "Кнопка 1: вперёд (в тренировке) / отметка прохода через объект (авто-трайалы)\n"
    "Кнопки 2/3: поворот влево/вправо (только в тренировке free)\n"
    "Кнопка 4: завершить тренировочный free-трайал\n\n"
    "В auto-трайалах движение автоматическое: нажимайте 1 в моменты прохода через объекты.\n"
    "Нажмите 1 для старта."
)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def dist(x1, z1, x2, z2):
    return math.hypot(x1 - x2, z1 - z2)


def dist_point_to_segment(px, pz, ax, az, bx, bz):
    abx, abz = bx - ax, bz - az
    apx, apz = px - ax, pz - az
    ab2 = abx * abx + abz * abz
    if ab2 <= 1e-9:
        return math.hypot(px - ax, pz - az)
    t = clamp((apx * abx + apz * abz) / ab2, 0.0, 1.0)
    qx, qz = ax + t * abx, az + t * abz
    return math.hypot(px - qx, pz - qz)


def clamp_inside(x, z, arena_r, margin=0.25):
    r = math.hypot(x, z)
    mr = max(0.01, arena_r - margin)
    if r <= mr:
        return x, z
    k = mr / r
    return x * k, z * k


def rand_in_annulus(min_r, max_r):
    a = random.random() * 2 * math.pi
    rr = math.sqrt(random.uniform(min_r * min_r, max_r * max_r))
    return rr * math.cos(a), rr * math.sin(a)


class ArenaVisuals:
    @staticmethod
    def make_markers(n=5):
        # 5 ориентиров на периметре
        shapes = ["circle", "triangle", "square", "crescent_up", "star4"]
        step = 2 * math.pi / n
        out = []
        for i in range(n):
            out.append({"type": shapes[i % len(shapes)], "angle": i * step + random.uniform(-0.16, 0.16), "y": random.uniform(1.4, 2.6)})
        return out

    @staticmethod
    def _basis(angle):
        ux, uz = -math.sin(angle), math.cos(angle)
        nx, nz = math.cos(angle), math.sin(angle)
        return ux, uz, nx, nz

    @staticmethod
    def draw_marker(shape, radius, angle, y):
        x = radius * math.cos(angle)
        z = radius * math.sin(angle)
        ux, uz, nx, nz = ArenaVisuals._basis(angle)
        x -= nx * 0.15
        z -= nz * 0.15

        def c(t):
            glColor3f(0.6 + 0.4 * t, 0.8 - 0.2 * t, 1.0 - 0.3 * t)

        if shape == "circle":
            glBegin(GL_TRIANGLE_FAN)
            c(0.4); glVertex3f(x, y, z)
            for i in range(49):
                a = 2 * math.pi * i / 48
                glVertex3f(x + 0.65 * math.cos(a) * ux, y + 0.65 * math.sin(a), z + 0.65 * math.cos(a) * uz)
            glEnd()
        elif shape == "triangle":
            glBegin(GL_TRIANGLES)
            c(0.9); glVertex3f(x, y + 0.7, z)
            c(0.1); glVertex3f(x - 0.6 * ux, y - 0.5, z - 0.6 * uz)
            c(0.1); glVertex3f(x + 0.6 * ux, y - 0.5, z + 0.6 * uz)
            glEnd()
        elif shape == "square":
            glBegin(GL_QUADS)
            c(0.2); glVertex3f(x - 0.55 * ux, y - 0.55, z - 0.55 * uz)
            c(0.2); glVertex3f(x + 0.55 * ux, y - 0.55, z + 0.55 * uz)
            c(0.9); glVertex3f(x + 0.55 * ux, y + 0.55, z + 0.55 * uz)
            c(0.9); glVertex3f(x - 0.55 * ux, y + 0.55, z - 0.55 * uz)
            glEnd()
        elif shape == "crescent_up":
            # полумесяц "рожками вверх"
            glColor3f(1.0, 0.95, 0.7)
            glBegin(GL_TRIANGLE_FAN)
            glVertex3f(x, y, z)
            for i in range(60):
                a = math.pi * i / 59.0
                glVertex3f(x + 0.75 * math.cos(a) * ux, y + 0.75 * math.sin(a), z + 0.75 * math.cos(a) * uz)
            glEnd()
            glColor3f(0.55, 0.75, 0.95)
            glBegin(GL_TRIANGLE_FAN)
            glVertex3f(x + 0.15 * ux, y + 0.05, z + 0.15 * uz)
            for i in range(60):
                a = math.pi * i / 59.0
                glVertex3f(x + 0.52 * math.cos(a) * ux + 0.15 * ux, y + 0.52 * math.sin(a) + 0.05, z + 0.52 * math.cos(a) * uz + 0.15 * uz)
            glEnd()
        else:  # star4
            pts = []
            for i in range(8):
                a = i * (math.pi / 4)
                r = 0.72 if i % 2 == 0 else 0.28
                pts.append((x + r * math.cos(a) * ux, y + r * math.sin(a), z + r * math.cos(a) * uz))
            glColor3f(1.0, 0.9, 0.45)
            glBegin(GL_TRIANGLE_FAN)
            glVertex3f(x, y, z)
            for p in pts + [pts[0]]:
                glVertex3f(*p)
            glEnd()

    @staticmethod
    def draw_panorama(arena_r):
        rr = arena_r * 2.8
        # горы
        for i in range(10):
            a = i * (2 * math.pi / 10.0)
            x = rr * math.cos(a)
            z = rr * math.sin(a)
            h = 4.0 + 2.6 * math.sin(i)
            glBegin(GL_TRIANGLES)
            glColor3f(0.45, 0.44, 0.48); glVertex3f(x - 4, 0.0, z - 2)
            glColor3f(0.38, 0.37, 0.42); glVertex3f(x + 4, 0.0, z + 2)
            glColor3f(0.6, 0.6, 0.66); glVertex3f(x, h, z)
            glEnd()
        # кусты/деревья: овалы + коричневые линии
        for i in range(24):
            a = i * (2 * math.pi / 24.0) + random.uniform(-0.08, 0.08)
            x = rr * math.cos(a)
            z = rr * math.sin(a)
            glColor3f(0.40, 0.23, 0.12)
            glBegin(GL_LINES)
            glVertex3f(x, 0.0, z)
            glVertex3f(x, 1.0, z)
            glEnd()
            for k in range(2):
                rad = 0.9 - 0.25 * k
                glColor3f(0.2 + 0.2 * random.random(), 0.45 + 0.25 * random.random(), 0.2)
                glBegin(GL_TRIANGLE_FAN)
                glVertex3f(x, 1.0 + 0.2 * k, z)
                for j in range(24):
                    aa = 2 * math.pi * j / 23
                    glVertex3f(x + rad * math.cos(aa), 1.0 + 0.2 * k + 0.45 * math.sin(aa), z + 0.5 * rad * math.sin(aa))
                glEnd()
        # река - несколько голубых полос
        glColor3f(0.38, 0.56, 0.92)
        for k in range(3):
            glBegin(GL_LINE_STRIP)
            for i in range(140):
                a = i / 139.0 * 2 * math.pi
                r = rr - 6.0 - 0.8 * k + 0.7 * math.sin(5 * a + k)
                glVertex3f(r * math.cos(a), 0.04, r * math.sin(a))
            glEnd()


def draw_ground(size=84.0, step=2.0, t=0.0):
    half = size * 0.5
    n = int(size / step)
    for i in range(n):
        for j in range(n):
            x0, z0 = -half + i * step, -half + j * step
            x1, z1 = x0 + step, z0 + step
            c = 0.52 + 0.07 * math.sin(0.17 * x0 + 0.23 * z0 + 0.7 * t)
            glColor3f(0.36 * c, 0.84 * c, 0.35 * c)
            glBegin(GL_QUADS)
            glVertex3f(x0, 0.0, z0)
            glVertex3f(x1, 0.0, z0)
            glVertex3f(x1, 0.0, z1)
            glVertex3f(x0, 0.0, z1)
            glEnd()


def draw_flower(x, z, r):
    for i in range(8):
        a = i * (2 * math.pi / 8)
        px, pz = x + 0.42 * r * math.cos(a), z + 0.42 * r * math.sin(a)
        glColor3f(0.95, 0.83, 0.27)
        glBegin(GL_TRIANGLE_FAN)
        glVertex3f(px, 0.035, pz)
        for j in range(28):
            aa = 2 * math.pi * j / 27
            glVertex3f(px + 0.28 * r * math.cos(aa), 0.035, pz + 0.16 * r * math.sin(aa))
        glEnd()
    glColor3f(0.95, 0.45, 0.06)
    glBegin(GL_TRIANGLE_FAN)
    glVertex3f(x, 0.04, z)
    for j in range(36):
        aa = 2 * math.pi * j / 35
        glVertex3f(x + 0.26 * r * math.cos(aa), 0.04, z + 0.26 * r * math.sin(aa))
    glEnd()


class Overlay:
    def __init__(self):
        self.cache = {}

    def font(self, s):
        if s not in self.cache:
            self.cache[s] = pygame.font.SysFont("Arial", s)
        return self.cache[s]

    def ortho_begin(self, w, h):
        glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity(); glOrtho(0, w, 0, h, -1, 1)
        glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()

    def ortho_end(self):
        glPopMatrix(); glMatrixMode(GL_PROJECTION); glPopMatrix(); glMatrixMode(GL_MODELVIEW)

    def text(self, w, h, txt, x, y_top, size=24, color=(0, 0, 0), anchor="topleft"):
        surf = self.font(size).render(str(txt), True, tuple(int(255 * c) for c in color)).convert_alpha()
        tw, th = surf.get_width(), surf.get_height()
        y = h - y_top - th
        if anchor == "topmiddle":
            x -= tw // 2
        elif anchor == "topright":
            x -= tw
        data = pygame.image.tostring(surf, "RGBA", True)
        tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, tw, th, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        self.ortho_begin(w, h)
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_TEXTURE_2D)
        glColor4f(1, 1, 1, 1)
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex2f(x, y)
        glTexCoord2f(1, 0); glVertex2f(x + tw, y)
        glTexCoord2f(1, 1); glVertex2f(x + tw, y + th)
        glTexCoord2f(0, 1); glVertex2f(x, y + th)
        glEnd()
        glDisable(GL_TEXTURE_2D); glDisable(GL_BLEND)
        glEnable(GL_DEPTH_TEST)
        self.ortho_end()
        glDeleteTextures([tex])

    def minimap(self, w, h, exp, show_feedback=False):
        s, pad = 260, 14
        x0, y0 = 20, h - 20 - s
        ar = exp.p["arena_r"]

        def w2m(x, z):
            return x0 + pad + (x / ar * 0.5 + 0.5) * (s - 2 * pad), y0 + pad + (z / ar * 0.5 + 0.5) * (s - 2 * pad)

        self.ortho_begin(w, h)
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glColor4f(1, 1, 1, 0.58)
        glBegin(GL_QUADS)
        glVertex2f(x0, y0); glVertex2f(x0 + s, y0); glVertex2f(x0 + s, y0 + s); glVertex2f(x0, y0 + s)
        glEnd()

        cx, cy = x0 + s * 0.5, y0 + s * 0.5
        R = (s - 2 * pad) * 0.5
        glColor4f(0, 0, 0, 0.9)
        glBegin(GL_LINE_LOOP)
        for i in range(80):
            a = 2 * math.pi * i / 79
            glVertex2f(cx + R * math.cos(a), cy + R * math.sin(a))
        glEnd()

        # маршрут
        if exp.route_polyline:
            glColor4f(0.15, 0.18, 0.2, 0.9)
            glLineWidth(2.0)
            glBegin(GL_LINE_STRIP)
            for p in exp.route_polyline:
                mx, my = w2m(p[0], p[1])
                glVertex2f(mx, my)
            glEnd()

        for m in exp.markers:
            a = m["angle"]
            glColor4f(0.0, 0.5, 0.95, 0.9)
            glBegin(GL_LINES)
            glVertex2f(cx + R * math.cos(a), cy + R * math.sin(a))
            glVertex2f(cx + (R - 11) * math.cos(a), cy + (R - 11) * math.sin(a))
            glEnd()

        for o in exp.objects:
            mx, my = w2m(o["x"], o["z"])
            pr = o["r"] / ar * R
            glColor4f(1.0, 0.72, 0.15, 0.95)
            glBegin(GL_TRIANGLE_FAN)
            glVertex2f(mx, my)
            for i in range(35):
                a = 2 * math.pi * i / 34
                glVertex2f(mx + pr * math.cos(a), my + pr * math.sin(a))
            glEnd()

        if show_feedback:
            for px, pz in exp.responses:
                mx, my = w2m(px, pz)
                glColor4f(0.9, 0.1, 0.1, 0.95)
                glPointSize(7)
                glBegin(GL_POINTS); glVertex2f(mx, my); glEnd()

        mx, my = w2m(exp.cam_x, exp.cam_z)
        glColor4f(0, 0, 0, 1)
        glPointSize(6)
        glBegin(GL_POINTS); glVertex2f(mx, my); glEnd()

        glDisable(GL_BLEND)
        glEnable(GL_DEPTH_TEST)
        self.ortho_end()


class Experiment:
    def __init__(self, p):
        self.p = p
        self.ov = Overlay()
        self.visuals = ArenaVisuals()

        self.trial_i = 0
        self.phase = "init"
        self.trial_type = None
        self.t_in_phase = 0.0
        self.nav_t = 0.0

        self.cam_x = 0.0
        self.cam_z = 0.0
        self.cam_y = p["eye_y"]
        self.yaw = 0.0

        self.markers = []
        self.objects = []
        self.route = []
        self.route_polyline = []
        self.route_seg_i = 0
        self.seg_progress = 0.0
        self.responses = []
        self.feedback_text = ""
        self.feedback_timer = 0.0

        self.mirror_mode = False
        self.log = []

    def new_world(self):
        self.markers = self.visuals.make_markers(5)
        self.objects = self.make_objects(self.p["objects_n"])

    def make_objects(self, n):
        out = []
        ar = self.p["arena_r"]
        for _ in range(max(1, int(n))):
            for _ in range(300):
                x, z = rand_in_annulus(self.p["platform_center_margin"], ar - self.p["platform_wall_margin"])
                ok = True
                for q in out:
                    if dist(x, z, q["x"], q["z"]) < self.p["platform_min_dist_between"]:
                        ok = False
                        break
                if ok:
                    out.append({"x": x, "z": z, "r": self.p["platform_r"]})
                    break
        return out

    def _random_anchor(self):
        x, z = rand_in_annulus(2.0, self.p["arena_r"] - 0.7)
        return [x, z]

    def _segment_is_safe(self, a, b, used_object_indices):
        safe_d = self.p["non_object_min_dist_mul"] * self.p["platform_r"]
        for i, o in enumerate(self.objects):
            d = dist_point_to_segment(o["x"], o["z"], a[0], a[1], b[0], b[1])
            if i in used_object_indices:
                continue
            if d < safe_d:
                return False
        return True

    def plan_route(self, pass_through_all=True):
        seg_min = int(self.p["route_segments_min"])
        seg_max = int(self.p["route_segments_max"])
        n_segments = random.randint(seg_min, seg_max)

        points = [self._random_anchor()]
        used_object_segments = {}

        # распределяем объекты по случайным отрезкам
        obj_indices = list(range(len(self.objects)))
        random.shuffle(obj_indices)
        tgt_segments = [random.randrange(n_segments) for _ in obj_indices]

        used_objects_on_seg = {i: [] for i in range(n_segments)}
        if pass_through_all:
            for oi, si in zip(obj_indices, tgt_segments):
                used_objects_on_seg[si].append(oi)

        for si in range(n_segments):
            prev = points[-1]
            placed = False
            for _ in range(400):
                length = random.uniform(self.p["route_seg_len_min"], self.p["route_seg_len_max"])
                angle = random.uniform(0, 2 * math.pi)
                nx = prev[0] + length * math.cos(angle)
                nz = prev[1] + length * math.sin(angle)
                nx, nz = clamp_inside(nx, nz, self.p["arena_r"], margin=0.7)
                cand = [nx, nz]

                if used_objects_on_seg[si]:
                    # делаем отрезок через объект: точка-объект и далее в том же направлении
                    oi = random.choice(used_objects_on_seg[si])
                    ox, oz = self.objects[oi]["x"], self.objects[oi]["z"]
                    vx, vz = ox - prev[0], oz - prev[1]
                    vv = math.hypot(vx, vz)
                    if vv < 0.8:
                        continue
                    vx, vz = vx / vv, vz / vv
                    ext = random.uniform(1.0, self.p["route_seg_len_max"])
                    p_obj = [ox, oz]
                    p_after = [ox + vx * ext, oz + vz * ext]
                    p_after[0], p_after[1] = clamp_inside(p_after[0], p_after[1], self.p["arena_r"], margin=0.7)
                    # до объекта и после объекта проверяем безопасность относительно ДРУГИХ объектов
                    if self._segment_is_safe(prev, p_obj, {oi}) and self._segment_is_safe(p_obj, p_after, {oi}):
                        points.append(p_obj)
                        points.append(p_after)
                        used_object_segments[oi] = (len(points) - 3, len(points) - 2)
                        placed = True
                        break
                else:
                    if self._segment_is_safe(prev, cand, set()):
                        points.append(cand)
                        placed = True
                        break
            if not placed:
                points.append(self._random_anchor())

        # превращаем полилинию в сегменты с независимой скоростью
        route = []
        for i in range(len(points) - 1):
            a, b = points[i], points[i + 1]
            ln = dist(a[0], a[1], b[0], b[1])
            if ln < 1e-4:
                continue
            route.append({
                "a": a,
                "b": b,
                "len": ln,
                "speed": random.uniform(self.p["route_speed_min"], self.p["route_speed_max"]),
            })
        self.route_polyline = points
        return route

    def start_trial(self, tt):
        self.trial_type = tt
        self.phase = "look" if tt not in ("instr", "pause") else tt
        self.t_in_phase = 0.0
        self.nav_t = 0.0
        self.responses = []
        self.feedback_text = ""
        self.feedback_timer = 0.0

        if tt == "instr":
            return
        if tt == "pause":
            return

        self.new_world()
        self.route_seg_i = 0
        self.seg_progress = 0.0

        pass_through = tt in ("acq", "mirror_acq", "train_auto_visible")
        if tt == "probe":
            pass_through = False
        self.route = self.plan_route(pass_through_all=pass_through)
        if not self.route:
            self.route = [{"a": [0, 0], "b": [1, 0], "len": 1.0, "speed": 1.0}]
            self.route_polyline = [[0, 0], [1, 0]]

        self.cam_x, self.cam_z = self.route[0]["a"]
        d = self.route[0]
        self.yaw = math.degrees(math.atan2(d["b"][0] - d["a"][0], -(d["b"][1] - d["a"][1])))

        self.mirror_mode = (tt == "mirror_acq")
        if self.mirror_mode:
            self.cam_x = -self.cam_x
            self.route_polyline = [[-p[0], p[1]] for p in self.route_polyline]
            for seg in self.route:
                seg["a"][0] *= -1
                seg["b"][0] *= -1
            for o in self.objects:
                o["x"] *= -1
            for m in self.markers:
                m["angle"] = (math.pi - m["angle"]) % (2 * math.pi)

    def should_show_minimap(self):
        if self.p["show_minimap"]:
            return True
        if self.trial_type == "train_free" and self.p["show_minimap_in_training"]:
            return True
        return False

    def process_key(self, key):
        if self.phase == "instr" and key in (K_1, K_KP1):
            self.trial_i += 1
            self.phase = "init"
            return

        if self.phase == "pause":
            return

        if self.trial_type == "train_free" and self.phase == "nav":
            if key in (K_4, K_KP4):
                self.finish_trial()
                return
            if key in (K_1, K_KP1):
                a = math.radians(self.yaw)
                nx = self.cam_x + self.p["free_move_step"] * math.sin(a)
                nz = self.cam_z - self.p["free_move_step"] * math.cos(a)
                self.cam_x, self.cam_z = clamp_inside(nx, nz, self.p["arena_r"], margin=0.2)
            elif key in (K_2, K_KP2):
                self.yaw -= self.p["free_turn_deg"]
            elif key in (K_3, K_KP3):
                self.yaw += self.p["free_turn_deg"]
            return

        if self.phase == "nav" and self.trial_type in ("acq", "mirror_acq", "probe", "train_auto_visible"):
            if key in (K_1, K_KP1):
                self.responses.append((self.cam_x, self.cam_z))

    def update(self, dt):
        self.t_in_phase += dt

        if self.phase == "pause":
            if self.t_in_phase >= self.p["pause_dur"]:
                self.trial_i += 1
                self.phase = "init"
            return

        if self.trial_type == "train_free":
            if self.phase == "look" and self.t_in_phase >= self.p["look_dur"]:
                self.phase = "nav"; self.t_in_phase = 0.0
            return

        if self.phase == "look":
            if self.t_in_phase >= self.p["look_dur"]:
                self.phase = "nav"
                self.t_in_phase = 0.0
            return

        if self.phase == "feedback":
            self.feedback_timer -= dt
            if self.feedback_timer <= 0:
                self.trial_i += 1
                self.phase = "init"
            return

        if self.phase != "nav":
            return

        # автоматическое прохождение маршрута
        self.nav_t += dt
        if self.route_seg_i >= len(self.route):
            self.finish_trial()
            return

        seg = self.route[self.route_seg_i]
        self.seg_progress += seg["speed"] * dt

        t = clamp(self.seg_progress / seg["len"], 0.0, 1.0)
        self.cam_x = seg["a"][0] + (seg["b"][0] - seg["a"][0]) * t
        self.cam_z = seg["a"][1] + (seg["b"][1] - seg["a"][1]) * t

        # плавный поворот в сторону следующего сегмента
        if self.route_seg_i + 1 < len(self.route):
            cur_vec = (seg["b"][0] - seg["a"][0], seg["b"][1] - seg["a"][1])
            nxt = self.route[self.route_seg_i + 1]
            nxt_vec = (nxt["b"][0] - nxt["a"][0], nxt["b"][1] - nxt["a"][1])
            yaw_target = math.degrees(math.atan2(cur_vec[0], -cur_vec[1]))
            yaw_next = math.degrees(math.atan2(nxt_vec[0], -nxt_vec[1]))
            blend = clamp((self.seg_progress / seg["len"] - 0.75) / 0.25, 0.0, 1.0)
            targ = yaw_target * (1 - blend) + yaw_next * blend
        else:
            cur_vec = (seg["b"][0] - seg["a"][0], seg["b"][1] - seg["a"][1])
            targ = math.degrees(math.atan2(cur_vec[0], -cur_vec[1]))

        max_turn = self.p["turn_base_deg_per_sec"] * (seg["speed"] / max(0.01, self.p["route_speed_max"]))
        dy = ((targ - self.yaw + 180) % 360) - 180
        dy = clamp(dy, -max_turn * dt, max_turn * dt)
        self.yaw += dy

        if self.seg_progress >= seg["len"]:
            self.route_seg_i += 1
            self.seg_progress = 0.0

    def finish_trial(self):
        # фидбек: ближайшая нажатая точка к каждому объекту
        if self.trial_type in ("acq", "mirror_acq", "probe", "train_auto_visible"):
            if len(self.responses) == 0:
                self.feedback_text = "Плохо: не было ни одного нажатия."
            else:
                errs = []
                for o in self.objects:
                    best = min(dist(o["x"], o["z"], r[0], r[1]) for r in self.responses)
                    errs.append(best)
                total_err = sum(errs)
                self.feedback_text = f"Суммарная ошибка: {total_err:0.2f}."
                if len(self.responses) > len(self.objects) + 2:
                    self.feedback_text += " Предупреждение: слишком много нажатий."
                elif len(self.responses) < len(self.objects):
                    self.feedback_text += " Предупреждение: нажатий меньше, чем объектов."

            self.phase = "feedback"
            self.feedback_timer = 6.0
            return

        self.trial_i += 1
        self.phase = "init"


def setup_gl(w, h):
    glEnable(GL_DEPTH_TEST)
    glDisable(GL_LIGHTING)
    glDisable(GL_CULL_FACE)
    glClearColor(0.55, 0.75, 0.95, 1.0)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    fovy, z_near, z_far = math.radians(75.0), 0.05, 300.0
    aspect = w / h
    f = 1.0 / math.tan(fovy / 2.0)
    M = [
        [f / aspect, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, (z_far + z_near) / (z_near - z_far), (2 * z_far * z_near) / (z_near - z_far)],
        [0, 0, -1, 0],
    ]
    glLoadMatrixf([
        M[0][0], M[1][0], M[2][0], M[3][0],
        M[0][1], M[1][1], M[2][1], M[3][1],
        M[0][2], M[1][2], M[2][2], M[3][2],
        M[0][3], M[1][3], M[2][3], M[3][3],
    ])
    glMatrixMode(GL_MODELVIEW)


def wait_instr(exp, w, h, clock):
    while True:
        for e in pygame.event.get():
            if e.type == QUIT:
                return False
            if e.type == KEYDOWN and e.key in (K_1, K_KP1):
                return True
            if e.type == KEYDOWN and e.key == K_ESCAPE:
                return False
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        exp.ov.text(w, h, INSTR_TEXT.split("\n")[0], 40, 40, 28)
        y = 90
        for ln in INSTR_TEXT.split("\n")[2:]:
            exp.ov.text(w, h, ln, 40, y, 22)
            y += 30
        pygame.display.flip()
        clock.tick(60)


def main():
    pygame.init(); pygame.font.init()
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 2)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_COMPATIBILITY)
    pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
    pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)

    w, h = 1000, 700
    pygame.display.set_mode((w, h), DOUBLEBUF | OPENGL)
    pygame.display.set_caption("vMWM auto-route paradigm")
    setup_gl(w, h)

    exp = Experiment(DEFAULTS)

    log_dir = os.path.join(DEFAULTS["log_dir"], "vmwm_auto_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(log_dir, exist_ok=True)
    run_meta = {
        "defaults": DEFAULTS,
        "created": datetime.now().isoformat(),
        "trial_seq": TRIAL_SEQ,
    }
    with open(os.path.join(log_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(run_meta, f, ensure_ascii=False, indent=2)

    if not wait_instr(exp, w, h, pygame.time.Clock()):
        pygame.quit(); return

    clock = pygame.time.Clock()
    running = True
    t = 0.0

    while running:
        dt = clock.tick(60) / 1000.0
        t += dt

        if exp.phase == "init":
            if exp.trial_i >= len(TRIAL_SEQ):
                break
            tt = TRIAL_SEQ[exp.trial_i]["type"]
            exp.start_trial(tt)
            if tt == "instr":
                exp.trial_i += 1
                exp.phase = "init"
                continue

        for e in pygame.event.get():
            if e.type == QUIT:
                running = False
            elif e.type == KEYDOWN:
                if e.key == K_ESCAPE:
                    running = False
                else:
                    exp.process_key(e.key)

        exp.update(dt)

        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        glRotatef(0.0, 1, 0, 0)
        glRotatef(exp.yaw, 0, 1, 0)
        glTranslatef(-exp.cam_x, -exp.cam_y, -exp.cam_z)

        draw_ground(t=t)
        exp.visuals.draw_panorama(exp.p["arena_r"])
        for m in exp.markers:
            exp.visuals.draw_marker(m["type"], exp.p["arena_r"], m["angle"], m["y"])

        platforms_visible = exp.trial_type in ("train_free", "train_auto_visible", "feedback")
        if platforms_visible:
            for o in exp.objects:
                draw_flower(o["x"], o["z"], o["r"])

        if exp.should_show_minimap() or exp.phase == "feedback":
            exp.ov.minimap(w, h, exp, show_feedback=(exp.phase == "feedback"))

        pad = 18
        if exp.phase == "look":
            exp.ov.text(w, h, f"Осмотр: {max(0, int(exp.p['look_dur'] - exp.t_in_phase))} c", w // 2, pad, 24, anchor="topmiddle")
        if exp.phase == "nav" and exp.trial_type in ("acq", "mirror_acq", "probe", "train_auto_visible"):
            exp.ov.text(w, h, f"Нажатий: {len(exp.responses)}", w - pad, pad, 24, anchor="topright")
            exp.ov.text(w, h, f"{exp.nav_t:0.1f} c", w - pad, pad + 28, 24, anchor="topright")
        if exp.phase == "nav" and exp.trial_type == "train_free":
            exp.ov.text(w, h, "Тренировка: 1-вперёд, 2/3-поворот, 4-завершить", w // 2, pad, 24, anchor="topmiddle")
        if exp.phase == "feedback":
            exp.ov.text(w, h, "Фидбек", w // 2, pad, 28, anchor="topmiddle")
            exp.ov.text(w, h, exp.feedback_text, w // 2, pad + 34, 22, anchor="topmiddle")

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
