import sys
import math
import random
import argparse
import psutil
import time
import subprocess
from PIL import Image
import os

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QPainter, QColor, QPen, QPolygon
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QImage, QPixmap

from Xlib import display, X

def capture_window_image(win):
    try:
        win_id = win["window"].id
        path = "/tmp/frogy_capture.xwd"
        out = "/tmp/frogy_capture.png"

        # capture X11 window
        subprocess.run([
            "xwd", "-id", str(win_id), "-out", path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # convert to png
        subprocess.run([
            "convert", path, out
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return Image.open(out)

    except Exception as e:
        print("capture failed:", e)
        return None

def move_window(win_id, x, y, w, h):
    try:
        cmd = [
            "wmctrl",
            "-ir", hex(win_id),
            "-e", f"0,{int(x)},{int(y)},{int(w)},{int(h)}"
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print("Move failed:", e)

# ----------------------------
# murder the children
# ----------------------------

def kill_tree(pid, kill_children=False):
    try:
        parent = psutil.Process(pid)

        children = parent.children(recursive=True)

        if kill_children:
            print(f"Killing {len(children)} child processes")

            for child in children:
                try:
                    print(f"   child {child.pid} {child.name()}")
                    child.terminate()
                except:
                    pass

        # kill parent last
        print(f"Killing parent {parent.pid} {parent.name()}")
        parent.terminate()

    except psutil.NoSuchProcess:
        print("Process already gone")
    except Exception as e:
        print("Kill tree failed:", e)

# ----------------------------
# X11 helpers
# ----------------------------
def get_windows():
    d = display.Display()
    root = d.screen().root
    windows = []

    def recurse(win):
        try:
            children = win.query_tree().children
        except:
            return

        for w in children:
            try:
                geom = w.get_geometry()
                attrs = w.get_attributes()

                if attrs.map_state == X.IsViewable:
                    name = w.get_wm_name()
                    if name:
                        windows.append({
                            "window": w,
                            "id": w.id,
                            "title": name,
                            "x": geom.x,
                            "y": geom.y,
                            "w": geom.width,
                            "h": geom.height
                        })
            except:
                pass
            recurse(w)

    recurse(root)
    return windows

import fnmatch

def find_target(pattern):
    pattern = pattern.lower()

    for w in get_windows():
        title = w["title"].lower()

        # wildcard match
        if fnmatch.fnmatch(title, pattern):
            return w

    return None

def kill_window(win_data):
    try:
        win = win_data["window"]

        pid_atom = win.get_full_property(
            win.display.get_atom("_NET_WM_PID"),
            X.AnyPropertyType
        )

        if not pid_atom:
            return

        pid = pid_atom.value[0]
        p = psutil.Process(pid)

        print(f"Eating {p.name()} (PID {pid})")
        p.terminate()

    except Exception as e:
        print("Kill failed:", e)

# ----------------------------
# Creature
# ----------------------------
class Creature(QWidget):
    def __init__(self, args):
        super().__init__()

        self.args = args

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.fragments = []

        self.screen = QApplication.primaryScreen().geometry()

        self.resize(self.screen.width(), self.screen.height())

        # position
        self.x = self.screen.width() // 2
        self.y = self.screen.height() // 2

        # tongue state
        self.tongue_active = False
        self.tongue_progress = 0.0
        self.tongue_target = None

        self.target = None

        # animation state
        self.mouth_open = 0.0   # 0 = closed, 1 = fully open
        self.mouth_speed = 0.15
        self.mouth_target_size = 20
        self.mouth_current_size = 20

        # yum mode states
        self.yum_mode = bool(getattr(self.args, "yum", False))
        self.eating_state = None   # can be "idle", "targeting", "pulling", "mouth_opening", "fading", "mouth_closing"
        self.active_fragment = None
        self.mouth_anim = 0.0  # used for mouth open/close in eat animation
        self.fragment_start_pos = None

        # timer loop
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_logic)
        self.timer.start(16)

    # ----------------------------
    # DRAW
    # ----------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        breath = math.sin(time.time() * 3) * 3

        body_w = 110
        body_h = 80 + breath

        painter.setBrush(QColor(50, 220, 80))
        painter.setPen(Qt.PenStyle.NoPen)

        painter.drawEllipse(
            int(self.x - body_w/2),
            int(self.y - body_h/2),
            int(body_w),
            int(body_h)
        )

        # EYES (frog style, on top)
        eye_offset_x = 30
        eye_offset_y = -30
        eye_radius = 18

        for side in [-1, 1]:
            ex = self.x + side * eye_offset_x
            ey = self.y + eye_offset_y

            # white eye
            painter.setBrush(QColor(255, 255, 255))
            painter.drawEllipse(int(ex-eye_radius), int(ey-eye_radius), eye_radius*2, eye_radius*2)

            # pupil follows target (or mouse fallback)
            px, py = ex, ey

            if self.target:
                tx = self.target["x"]
                ty = self.target["y"]
            else:
                tx = self.x
                ty = self.y

            dx = tx - ex
            dy = ty - ey
            dist = math.hypot(dx, dy) + 0.001

            px += (dx / dist) * 6
            py += (dy / dist) * 6

            painter.setBrush(QColor(0, 0, 0))
            painter.drawEllipse(int(px-5), int(py-5), 10, 10)

        # MOUTH (animated frog mouth)
        mouth_w = int(self.mouth_current_size * self.mouth_open)
        mouth_h = int(20 + 60 * self.mouth_open)

        # In yum mode, mouth may animate size based on fragment
        if self.yum_mode and self.eating_state in ("mouth_opening", "fading", "mouth_closing") and self.active_fragment:
            frag_w = self.active_fragment["img"].width
            frag_h = self.active_fragment["img"].height
            extra_w = frag_w // 2
            extra_h = frag_h // 2
            open_amt = self.mouth_anim
            mouth_w = int(self.mouth_target_size * (1-open_amt) + (extra_w + 20) * open_amt)
            mouth_h = int(20 * (1-open_amt) + (extra_h + 40) * open_amt)

        painter.setBrush(QColor(20, 20, 20))
        painter.drawEllipse(
            int(self.x - mouth_w/2),
            int(self.y + 10),
            mouth_w,
            mouth_h
        )

        # TONGUE EFFECT (when very open)
        if self.mouth_open > 0.7 and self.target:
            painter.setBrush(QColor(255, 100, 120))

            tx = self.target["x"] + self.target["w"]//2
            ty = self.target["y"] + self.target["h"]//2

            painter.drawLine(
                int(self.x),
                int(self.y + 20),
                int(tx),
                int(ty)
            )

        if self.tongue_active and self.tongue_target:
            painter.setPen(QPen(QColor(255, 120, 140), 6))

            tx, ty = self.tongue_target

            # interpolate tongue tip
            tip_x = self.x + (tx - self.x) * self.tongue_progress
            tip_y = self.y + (ty - self.y) * self.tongue_progress

            painter.drawLine(
                int(self.x),
                int(self.y + 10),
                int(tip_x),
                int(tip_y)
            )

        # draw fragments
        for f in self.fragments:
            img = f["img"].convert("RGBA")
            w, h = img.size
            ptr = img.tobytes("raw", "RGBA")
            bytes_per_line = w * 4  # 4 bytes per pixel for RGBA

            pix = QImage(ptr, w, h, bytes_per_line, QImage.Format.Format_RGBA8888)

            painter.save()
            if self.yum_mode:
                # apply alpha if fading
                alpha = int(f.get("alpha", 255))
                painter.setOpacity(alpha/255.0)
            painter.drawImage(int(f["x"]), int(f["y"]), pix)
            painter.restore()

    # ----------------------------
    # CLICK (eye = exit)
    # ----------------------------
    def mousePressEvent(self, event):
        ex = event.position().x()
        ey = event.position().y()

        # eye center
        cx = self.x + 24
        cy = self.y - 6

        if math.hypot(ex - cx, ey - cy) < 15:
            print("Eye poked → exiting")
            QApplication.quit()

    #----------------------------
    #SMASH
    #----------------------------
    def shatter_window(self, win):
        img = capture_window_image(win)

        if img is None:
            return

        x, y = win["x"], win["y"]
        w, h = win["w"], win["h"]

        # Get fragment count from args, choose cols and rows
        fragment_count = getattr(self.args, "fragments", 80)
        # Prefer a shape close to the window aspect ratio
        aspect = w / h if h else 1
        rows = max(1, int((fragment_count / aspect) ** 0.5))
        cols = max(1, int(fragment_count / rows))
        # Clamp cols, rows to be at least 1
        cols = max(1, cols)
        rows = max(1, rows)

        tile_w = w // cols
        tile_h = h // rows

        self.fragments.clear()
        for i in range(cols):
            for j in range(rows):
                box = (
                    i * tile_w,
                    j * tile_h,
                    min((i + 1) * tile_w, w),
                    min((j + 1) * tile_h, h)
                )

                piece = img.crop(box)

                fragment = {
                    "img": piece,
                    "x": x + i * tile_w,
                    "y": y + j * tile_h,
                    "vx": random.uniform(-4, 4),
                    "vy": random.uniform(-10, -3),
                    "rot": random.uniform(-8, 8),
                    "eaten": False,  # for yum
                    "alpha": 255
                }
                self.fragments.append(fragment)

    # ----------------------------
    # LOGIC
    # ----------------------------
    def update_logic(self):
        if self.yum_mode:
            self.update_logic_yum()
        else:
            self.update_logic_default()

        self.update()

    def update_logic_default(self):
        # original fragment gravity logic
        for f in self.fragments:
            f["x"] += f["vx"]
            f["y"] += f["vy"]
            f["vy"] += 0.5  # gravity
        # find target
        if self.args.eat:
            self.target = find_target(self.args.eat)
        if self.target:
            tx = self.target["x"] + self.target["w"] // 2
            ty = self.target["y"] + self.target["h"] // 2

            dx = tx - self.x
            dy = ty - self.y
            dist = math.hypot(dx, dy)

            # SMASH (very close)
            if dist < 60:
                print(f" SMASH {self.target['title']}")
                self.shatter_window(self.target)

                # remove off-screen fragments
                self.fragments = [
                    f for f in self.fragments
                    if f["y"] < self.screen.height() + 200
                ]

                if self.args.auto:
                    kill_window(self.target)
                else:
                    ans = input(f"Eat '{self.target['title']}'? (y/n): ")
                    if ans.lower() == "y":
                        kill_window(self.target)

                self.target = None
                self.tongue_active = False
                self.mouth_open = 1.0

            # TONGUE MODE (mid range)
            elif dist < 300:
                self.tongue_active = True
                self.tongue_target = (tx, ty)

                # extend tongue
                self.tongue_progress = min(1.0, self.tongue_progress + 0.1)

                win = self.target

                wx = win["x"]
                wy = win["y"]
                ww = win["w"]
                wh = win["h"]

                # target position = near frog mouth
                target_x = self.x - ww // 2
                target_y = self.y - wh // 2

                # interpolate movement
                new_x = wx + (target_x - wx) * 0.2
                new_y = wy + (target_y - wy) * 0.2

                move_window(win["id"], new_x, new_y, ww, wh)

                # update stored position (important!)
                win["x"] = new_x
                win["y"] = new_y

                # move frog slightly toward target too
                self.x += dx * 0.03
                self.y += dy * 0.03

                self.mouth_open = min(1.0, self.mouth_open + 0.1)

            #FAR: move normally
            else:
                self.tongue_active = False
                self.tongue_progress = 0.0

                self.x += dx * self.args.speed
                self.y += dy * self.args.speed

                self.mouth_open = max(0.0, self.mouth_open - 0.05)
        else:
            self.tongue_active = False
            self.tongue_progress = 0.0
            self.mouth_open = max(0.0, self.mouth_open - self.mouth_speed)

    # YUM LOGIC
    def update_logic_yum(self):
        # fragments stay on screen, use state machine to eat them one by one
        # states: idle → targeting(next fragment) → pulling → mouth_opening → fading → mouth_closing → done

        # If no fragments, do normal behavior (wait for shatter)
        if not self.fragments:
            # seek window as in default mode
            if self.args.eat:
                self.target = find_target(self.args.eat)
            if self.target:
                tx = self.target["x"] + self.target["w"] // 2
                ty = self.target["y"] + self.target["h"] // 2
                dx = tx - self.x
                dy = ty - self.y
                dist = math.hypot(dx, dy)
                if dist < 60:
                    self.shatter_window(self.target)
                    kill_window(self.target)
                    self.target = None
                    # start yum eating
                    self.eating_state = "idle"
                else:
                    self.x += dx * self.args.speed
                    self.y += dy * self.args.speed
            return

        # initialize state machine if needed
        if self.eating_state is None or self.eating_state == "idle":
            # find next uneaten fragment
            frag = next((f for f in self.fragments if not f.get("eaten", False)), None)
            if frag is None:
                self.eating_state = "done"
                return
            self.active_fragment = frag
            self.eating_state = "targeting"
            self.tongue_progress = 0.0
            self.mouth_anim = 0.0
            self.fragment_start_pos = (frag["x"], frag["y"])
            return

        if self.eating_state == "targeting":
            # tongue extends to fragment
            frag = self.active_fragment
            fx = frag["x"] + frag["img"].width // 2
            fy = frag["y"] + frag["img"].height // 2
            self.tongue_active = True
            self.tongue_target = (fx, fy)
            # move frog mouth slightly toward fragment (optional)
            dx = fx - self.x
            dy = fy - self.y
            self.x += dx * 0.015
            self.y += dy * 0.015
            # tongue progresses
            self.tongue_progress = min(1.0, self.tongue_progress + 0.06)
            if self.tongue_progress >= 1.0:
                self.eating_state = "pulling"
                self.pull_progress = 0.0

        elif self.eating_state == "pulling":
            # pull fragment toward frog mouth using tongue
            frag = self.active_fragment
            fx, fy = self.fragment_start_pos
            mouth_x = self.x
            mouth_y = self.y + 40
            # progress toward frog
            prog = getattr(self, "pull_progress", 0.0)
            prog = min(1.0, prog + 0.09)
            frag["x"] = fx + (mouth_x - fx) * prog
            frag["y"] = fy + (mouth_y - fy) * prog
            self.tongue_progress = 1.0 - prog  # tongue retracts as fragment gets close
            self.tongue_target = (frag["x"] + frag["img"].width // 2, frag["y"] + frag["img"].height // 2)
            setattr(self, "pull_progress", prog)
            if prog >= 1.0:
                self.eating_state = "mouth_opening"
                self.mouth_anim = 0.0

        elif self.eating_state == "mouth_opening":
            # mouth grows to surround the fragment
            self.mouth_anim = min(1.0, self.mouth_anim + 0.14)
            if self.mouth_anim >= 1.0:
                self.eating_state = "fading"

        elif self.eating_state == "fading":
            frag = self.active_fragment
            frag["alpha"] = max(0, frag.get("alpha", 255) - 19)
            if frag["alpha"] <= 0:
                frag["eaten"] = True
                self.eating_state = "mouth_closing"
                self.mouth_anim = 1.0

        elif self.eating_state == "mouth_closing":
            self.mouth_anim = max(0.0, self.mouth_anim - 0.14)
            if self.mouth_anim <= 0.0:
                self.eating_state = "idle"
                self.tongue_active = False
                # start next fragment on next tick

    # ----------------------------
    # CLI
    # ----------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eat", help="window title keyword")
    parser.add_argument("--auto", action="store_true", help="auto kill")
    parser.add_argument("--speed", type=float, default=0.05)
    parser.add_argument("--wander", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--kill-children", action="store_true")
    parser.add_argument("--yum", action="store_true", help="frog eats fragments with tongue after shatter, one by one")
    parser.add_argument("--fragments", type=int, default=80, help="number of fragments for shattering")
    args = parser.parse_args()

    if args.list:
        for w in get_windows():
            print(w["title"])
        return  # Only list windows, do not launch GUI

    app = QApplication(sys.argv)
    c = Creature(args)
    c.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
