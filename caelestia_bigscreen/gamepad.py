"""Gamepad input through evdev, integrated with the GLib main loop.

While Big Screen is hidden or behind a game, devices are read without
exclusivity: games keep receiving everything and only the Guide button is
watched. While the interface is in front, devices are grabbed (EVIOCGRAB) so the
game behind it does not receive the navigation input.
"""

from pathlib import Path

import evdev
from evdev import ecodes as e
from gi.repository import Gio, GLib, GObject

VENDOR_SONY = 0x054C
VENDOR_NINTENDO = 0x057E

REPEAT_DELAY_MS = 380
REPEAT_INTERVAL_MS = 95
STICK_PRESS = 0.6
STICK_RELEASE = 0.35
TRIGGER_PRESS = 0.5
COMBO_WINDOW_MS = 400

DIRECTIONS = ("up", "down", "left", "right")

COMMON_BUTTONS = {
    e.BTN_SOUTH: "a",
    e.BTN_EAST: "b",
    e.BTN_TL: "lb",
    e.BTN_TR: "rb",
    e.BTN_TL2: "lt",
    e.BTN_TR2: "rt",
    e.BTN_SELECT: "select",
    e.BTN_START: "start",
    e.BTN_MODE: "guide",
    e.BTN_DPAD_UP: "up",
    e.BTN_DPAD_DOWN: "down",
    e.BTN_DPAD_LEFT: "left",
    e.BTN_DPAD_RIGHT: "right",
}


def is_gamepad(dev):
    caps = dev.capabilities()
    keys = caps.get(e.EV_KEY, [])
    if e.EV_ABS not in caps or not (e.BTN_SOUTH in keys or e.BTN_MODE in keys):
        return False
    name = dev.name.lower()
    if "motion sensors" in name or "touchpad" in name:
        return False
    # Steam Input virtual pads would duplicate the events of the physical one
    return bool(dev.phys) or not ("steam virtual" in name or name.startswith("microsoft x-box 360 pad"))


def button_map(dev):
    mapping = dict(COMMON_BUTTONS)
    # The kernel defines BTN_NORTH == BTN_X and BTN_WEST == BTN_Y. Sony and
    # Nintendo drivers follow the physical position, xpad (Xbox and clones)
    # follows the label (X on the left, Y on top).
    if dev.info.vendor in (VENDOR_SONY, VENDOR_NINTENDO):
        mapping[e.BTN_NORTH] = "y"
        mapping[e.BTN_WEST] = "x"
    else:
        mapping[e.BTN_X] = "x"
        mapping[e.BTN_Y] = "y"
    return mapping


class Pad:
    def __init__(self, dev):
        self.dev = dev
        self.name = dev.name
        self.buttons = button_map(dev)
        self.axes = dict(dev.capabilities().get(e.EV_ABS, []))
        self.stick = {e.ABS_X: 0.0, e.ABS_Y: 0.0}
        self.stick_dir = None
        self.hat = {e.ABS_HAT0X: 0, e.ABS_HAT0Y: 0}
        self.triggers = {"lt": False, "rt": False}
        self.watch = 0
        self.grabbed = False

    def fraction(self, code, value, centered):
        """Normalizes an axis to -1..1 (centered) or 0..1."""
        info = self.axes.get(code)
        if not info or info.max == info.min:
            return 0.0
        if centered:
            return (value - (info.max + info.min) / 2) / ((info.max - info.min) / 2)
        return (value - info.min) / (info.max - info.min)


class GamepadManager(GObject.Object):
    __gsignals__ = {
        # Logical button name: a, b, x, y, lb, rb, lt, rt, select, start
        "button": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # Navigation direction, with auto-repeat: up, down, left, right
        "nav": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # Guide button (or Select + Start), emitted even while inactive
        "home": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "devices-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, combo=True):
        super().__init__()
        self.pads = {}
        self.active = False
        self.combo = combo
        self.held = set()
        self.held_since = {}
        self.repeat_source = 0
        self.repeat_dir = None
        self.last_home = 0
        self.monitor = Gio.File.new_for_path("/dev/input").monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self.on_dir_changed)
        for path in evdev.list_devices():
            self.try_add(path)

    # ---- Devices ------------------------------------------------------------

    def try_add(self, path, attempts=0):
        if path in self.pads:
            return False
        try:
            dev = evdev.InputDevice(path)
        except PermissionError:
            # udev may apply the uaccess ACL right after the node is created
            if attempts < 6:
                GLib.timeout_add(500, self.try_add, path, attempts + 1)
            return False
        except OSError:
            return False
        if not is_gamepad(dev):
            dev.close()
            return False
        pad = Pad(dev)
        pad.watch = GLib.io_add_watch(dev.fd, GLib.PRIORITY_DEFAULT,
                                      GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                                      self.on_readable, path)
        self.pads[path] = pad
        if self.active:
            self.grab(pad, True)
        self.emit("devices-changed")
        return False

    def remove(self, path):
        pad = self.pads.pop(path, None)
        if not pad:
            return
        if pad.watch:
            GLib.source_remove(pad.watch)
        try:
            pad.dev.close()
        except OSError:
            pass
        self.stop_repeat()
        self.held.clear()
        self.emit("devices-changed")

    def on_dir_changed(self, _monitor, file, _other, event):
        if not (file.get_basename() or "").startswith("event"):
            return
        if event == Gio.FileMonitorEvent.CREATED:
            GLib.timeout_add(300, self.try_add, file.get_path())
        elif event == Gio.FileMonitorEvent.DELETED:
            self.remove(file.get_path())

    @staticmethod
    def grab(pad, grabbed):
        if pad.grabbed == grabbed:
            return
        try:
            pad.dev.grab() if grabbed else pad.dev.ungrab()
        except OSError:
            pass
        pad.grabbed = grabbed

    def set_active(self, active):
        """Active = the interface is in front and consumes navigation."""
        if self.active == active:
            return
        self.active = active
        self.stop_repeat()
        self.held.clear()
        for pad in self.pads.values():
            self.grab(pad, active)

    def names(self):
        return [pad.name for pad in self.pads.values()]

    # ---- Events -------------------------------------------------------------

    def on_readable(self, _fd, condition, path):
        pad = self.pads.get(path)
        if not pad:
            return False
        try:
            if condition & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
                raise OSError
            for event in pad.dev.read():
                if event.type == e.EV_KEY and event.code in pad.buttons and event.value != 2:
                    self.on_button(pad.buttons[event.code], event.value != 0)
                elif event.type == e.EV_ABS:
                    self.on_axis(pad, event.code, event.value)
        except BlockingIOError:
            pass
        except OSError:
            pad.watch = 0
            self.remove(path)
            return False
        return True

    def on_axis(self, pad, code, value):
        if code in (e.ABS_HAT0X, e.ABS_HAT0Y):
            old, pad.hat[code] = pad.hat[code], value
            negative, positive = ("left", "right") if code == e.ABS_HAT0X else ("up", "down")
            if old != value:
                if old:
                    self.on_button(negative if old < 0 else positive, False)
                if value:
                    self.on_button(negative if value < 0 else positive, True)
        elif code in (e.ABS_X, e.ABS_Y):
            pad.stick[code] = pad.fraction(code, value, centered=True)
            self.on_stick(pad, pad.stick[e.ABS_X], pad.stick[e.ABS_Y])
        elif code in (e.ABS_Z, e.ABS_RZ) and code in pad.axes:
            # Analog triggers (xpad and hid-playstation report them as Z/RZ)
            name = "lt" if code == e.ABS_Z else "rt"
            pressed = pad.fraction(code, value, centered=False) > TRIGGER_PRESS
            if pressed != pad.triggers[name]:
                pad.triggers[name] = pressed
                self.on_button(name, pressed)

    def on_stick(self, pad, x, y):
        magnitude = max(abs(x), abs(y))
        current = pad.stick_dir
        if current and magnitude < STICK_RELEASE:
            pad.stick_dir = None
            self.on_button(current, False)
            return
        if magnitude < STICK_PRESS:
            return
        if abs(x) > abs(y):
            direction = "right" if x > 0 else "left"
        else:
            direction = "down" if y > 0 else "up"
        if direction != current:
            if current:
                self.on_button(current, False)
            pad.stick_dir = direction
            self.on_button(direction, True)

    def on_button(self, name, pressed):
        now = GLib.get_monotonic_time() // 1000
        if pressed:
            self.held.add(name)
            self.held_since[name] = now
        else:
            self.held.discard(name)

        if pressed and self.is_home_press(name, now):
            # Several devices (physical + virtual) may report the same press
            if now - self.last_home > 250:
                self.last_home = now
                self.emit("home")
            return
        if not self.active:
            return
        if name in DIRECTIONS:
            if pressed:
                self.start_repeat(name)
            elif self.repeat_dir == name:
                self.stop_repeat()
        elif pressed:
            self.emit("button", name)

    def is_home_press(self, name, now):
        if name == "guide":
            return True
        if self.combo and name in ("select", "start"):
            other = "start" if name == "select" else "select"
            return other in self.held and now - self.held_since.get(other, 0) < COMBO_WINDOW_MS
        return False

    def start_repeat(self, direction):
        self.stop_repeat()
        self.repeat_dir = direction
        self.emit("nav", direction)
        self.repeat_source = GLib.timeout_add(REPEAT_DELAY_MS, self.on_repeat_delay)

    def on_repeat_delay(self):
        self.repeat_source = GLib.timeout_add(REPEAT_INTERVAL_MS, self.on_repeat)
        return False

    def on_repeat(self):
        if self.repeat_dir in self.held:
            self.emit("nav", self.repeat_dir)
            return True
        self.repeat_source = 0
        self.repeat_dir = None
        return False

    def stop_repeat(self):
        if self.repeat_source:
            GLib.source_remove(self.repeat_source)
        self.repeat_source = 0
        self.repeat_dir = None


def controller_batteries():
    """Batteries of connected controllers (power_supply entries with scope "Device")."""
    result = []
    base = Path("/sys/class/power_supply")
    for entry in sorted(base.iterdir()) if base.exists() else []:
        def read(name, entry=entry):
            try:
                return (entry / name).read_text().strip()
            except OSError:
                return ""
        if read("scope") != "Device":
            continue
        capacity = read("capacity")
        result.append({
            "name": read("model_name") or entry.name,
            "capacity": int(capacity) if capacity.isdigit() else None,
            "level": read("capacity_level"),
            "status": read("status"),
        })
    return result
