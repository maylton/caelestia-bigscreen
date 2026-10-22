"""System integration: audio, network, Bluetooth, power, windows and displays.

Anything that may take a while runs through an async Gio.Subprocess so the UI
never blocks; quick local queries run synchronously with a timeout.
"""

import json
import re
import shutil
import subprocess

from gi.repository import Gio, GLib, GObject


def run(argv, callback=None):
    """Runs without blocking. callback(ok, stdout, stderr)."""
    def finish(ok, out, err):
        if callback:
            callback(ok, out, err)

    try:
        proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as err:
        finish(False, "", err.message)
        return

    def done(p, result):
        try:
            _, out, err = p.communicate_utf8_finish(result)
        except GLib.Error as error:
            finish(False, "", error.message)
            return
        finish(p.get_successful(), out or "", err or "")

    proc.communicate_utf8_async(None, None, done)


def run_sync(argv, timeout=3):
    try:
        res = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return res.returncode == 0, res.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


def have(cmd):
    return shutil.which(cmd) is not None


# ---- Audio (PipeWire/PulseAudio through pactl) ------------------------------

class Audio:
    available = have("pactl")

    @staticmethod
    def sinks():
        ok, out = run_sync(["pactl", "-f", "json", "list", "sinks"])
        try:
            data = json.loads(out) if ok else []
        except ValueError:
            return []
        default = run_sync(["pactl", "get-default-sink"])[1].strip()
        sinks = []
        for s in data:
            levels = [int(v["value_percent"].rstrip("%")) for v in s.get("volume", {}).values()
                      if str(v.get("value_percent", "")).rstrip("%").isdigit()]
            sinks.append({
                "name": s["name"],
                "description": s.get("description") or s["name"],
                "volume": round(sum(levels) / len(levels)) if levels else 0,
                "mute": bool(s.get("mute")),
                "default": s["name"] == default,
                "bus": s.get("properties", {}).get("device.bus", ""),
                "hdmi": "hdmi" in s["name"].lower(),
            })
        return sinks

    @classmethod
    def default(cls):
        return next((s for s in cls.sinks() if s["default"]), None)

    @staticmethod
    def set_default(name, callback=None):
        run(["pactl", "set-default-sink", name], callback)

    @staticmethod
    def set_volume(percent, callback=None):
        run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{int(percent)}%"], callback)

    @staticmethod
    def set_mute(mute, callback=None):
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if mute else "0"], callback)


# ---- Network (NetworkManager through nmcli) ---------------------------------

def split_nmcli(line, fields):
    """Splits an `nmcli -t` line, honoring escaped colons."""
    parts = [p.replace("\\:", ":").replace("\\\\", "\\") for p in re.split(r"(?<!\\):", line)]
    return (parts + [""] * fields)[:fields]


class Network:
    available = have("nmcli")

    @staticmethod
    def status():
        """Wired and Wi-Fi devices: {type, state, connection, device}."""
        ok, out = run_sync(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION,DEVICE", "device"])
        devices = []
        for line in out.splitlines() if ok else []:
            kind, state, connection, device = split_nmcli(line, 4)
            if kind in ("ethernet", "wifi"):
                devices.append({"type": kind, "state": state, "connection": connection, "device": device})
        return devices

    @staticmethod
    def wifi_enabled():
        ok, out = run_sync(["nmcli", "radio", "wifi"])
        return ok and out.strip() == "enabled"

    @staticmethod
    def set_wifi(enabled, callback=None):
        run(["nmcli", "radio", "wifi", "on" if enabled else "off"], callback)

    @staticmethod
    def scan(callback, rescan=True):
        def done(ok, out, _err):
            networks = {}
            for line in out.splitlines() if ok else []:
                in_use, ssid, signal, security = split_nmcli(line, 4)
                if not ssid:
                    continue
                signal = int(signal) if signal.isdigit() else 0
                current = networks.get(ssid)
                if not current or signal > current["signal"] or in_use.strip():
                    networks[ssid] = {
                        "ssid": ssid,
                        "signal": signal,
                        "secure": security.strip() not in ("", "--"),
                        "active": bool(in_use.strip()) or bool(current and current["active"]),
                    }
            callback(sorted(networks.values(), key=lambda n: (not n["active"], -n["signal"])))
        run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
             "--rescan", "yes" if rescan else "no"], done)

    @staticmethod
    def known(ssid):
        ok, out = run_sync(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
        return ok and [ssid, "802-11-wireless"] in (split_nmcli(line, 2) for line in out.splitlines())

    @staticmethod
    def connect(ssid, password=None, callback=None):
        argv = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            argv += ["password", password]
        run(argv, callback)

    @staticmethod
    def disconnect(connection, callback=None):
        run(["nmcli", "connection", "down", "id", connection], callback)


def signal_icon(signal):
    level = "excellent" if signal >= 75 else "good" if signal >= 50 else "ok" if signal >= 25 else "weak"
    return f"network-wireless-signal-{level}-symbolic"


# ---- Bluetooth (bluetoothctl) -----------------------------------------------

DEVICE_RE = re.compile(r"^Device ([0-9A-F:]{17}) (.+)$")
BATTERY_RE = re.compile(r"\((\d+)\)")


class Bluetooth:
    available = have("bluetoothctl")

    @staticmethod
    def powered():
        ok, out = run_sync(["bluetoothctl", "show"])
        return ok and "Powered: yes" in out

    @staticmethod
    def set_powered(on, callback=None):
        run(["bluetoothctl", "power", "on" if on else "off"], callback)

    @staticmethod
    def any_connected():
        ok, out = run_sync(["bluetoothctl", "devices", "Connected"], timeout=1)
        return ok and "Device" in out

    @staticmethod
    def devices():
        ok, out = run_sync(["bluetoothctl", "devices"])
        devices = []
        for line in out.splitlines() if ok else []:
            match = DEVICE_RE.match(line.strip())
            if not match:
                continue
            mac, name = match.groups()
            info = run_sync(["bluetoothctl", "info", mac], timeout=2)[1]
            fields = dict(re.findall(r"^\s*(\w[\w ]*?): (.*)$", info, re.M))
            battery = BATTERY_RE.search(fields.get("Battery Percentage", ""))
            devices.append({
                "mac": mac,
                "name": fields.get("Alias") or name,
                "icon": fields.get("Icon", "bluetooth"),
                "paired": fields.get("Paired") == "yes",
                "connected": fields.get("Connected") == "yes",
                "battery": int(battery.group(1)) if battery else None,
            })
        devices.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].casefold()))
        return devices

    @staticmethod
    def scan(seconds, callback):
        run(["bluetoothctl", "--timeout", str(seconds), "scan", "on"], lambda *_: callback())

    @staticmethod
    def connect(mac, callback=None):
        run(["bluetoothctl", "--timeout", "15", "connect", mac], callback)

    @staticmethod
    def disconnect(mac, callback=None):
        run(["bluetoothctl", "disconnect", mac], callback)

    @staticmethod
    def pair(mac, callback=None):
        """Pairs, trusts and connects (controllers use "Just Works", no PIN)."""
        def after_pair(ok, out, err):
            if not ok and "AlreadyExists" not in out + err:
                if callback:
                    callback(False, out, err)
                return
            run(["bluetoothctl", "trust", mac], lambda *_: Bluetooth.connect(mac, callback))
        run(["bluetoothctl", "--timeout", "20", "pair", mac], after_pair)

    @staticmethod
    def remove(mac, callback=None):
        run(["bluetoothctl", "remove", mac], callback)


BT_ICONS = {
    "input-gaming": "input-gaming-symbolic",
    "audio-headset": "audio-headset-symbolic",
    "audio-headphones": "audio-headphones-symbolic",
    "audio-card": "audio-speakers-symbolic",
    "input-keyboard": "input-keyboard-symbolic",
    "input-mouse": "input-mouse-symbolic",
    "phone": "phone-symbolic",
    "computer": "computer-symbolic",
}


def bt_icon(kind):
    return BT_ICONS.get(kind, "bluetooth-symbolic")


# ---- Power --------------------------------------------------------------------

class Power:
    @staticmethod
    def suspend():
        run(["systemctl", "suspend"])

    @staticmethod
    def reboot():
        run(["systemctl", "reboot"])

    @staticmethod
    def poweroff():
        run(["systemctl", "poweroff"])


# ---- Hyprland (windows and displays) ------------------------------------------

class Hyprland:
    available = bool(GLib.getenv("HYPRLAND_INSTANCE_SIGNATURE")) and have("hyprctl")
    _lua = None

    @classmethod
    def lua(cls):
        """Hyprland >= 0.55 with a Lua config uses a different dispatch syntax."""
        if cls._lua is None:
            ok, out = run_sync(["hyprctl", "eval", "return 1"])
            cls._lua = ok and "error" not in out.lower() and "invalid" not in out.lower()
        return cls._lua

    @staticmethod
    def query(what):
        ok, out = run_sync(["hyprctl", what, "-j"])
        try:
            return json.loads(out) if ok else None
        except ValueError:
            return None

    @classmethod
    def clients(cls):
        return [c for c in cls.query("clients") or [] if c.get("mapped") and not c.get("hidden") and c.get("class")]

    @classmethod
    def active_window(cls):
        return cls.query("activewindow") or {}

    @classmethod
    def monitors(cls):
        return cls.query("monitors") or []

    @classmethod
    def dispatch(cls, lua, legacy):
        run(["hyprctl", "dispatch", lua] if cls.lua() else ["hyprctl", "dispatch", *legacy])

    @classmethod
    def focus(cls, address):
        cls.dispatch(f'hl.dsp.focus({{ window = "address:{address}" }})', ["focuswindow", f"address:{address}"])

    @classmethod
    def close(cls, address):
        cls.dispatch(f'hl.dsp.window.close({{ window = "address:{address}" }})', ["closewindow", f"address:{address}"])

    @classmethod
    def exit(cls):
        cls.dispatch("hl.dsp.exit()", ["exit"])

    @classmethod
    def set_mode(cls, monitor, mode):
        """Applies 'WIDTHxHEIGHT@HZ' at runtime, keeping position and scale."""
        name, scale = monitor["name"], monitor.get("scale", 1)
        position = f'{monitor.get("x", 0)}x{monitor.get("y", 0)}'
        if cls.lua():
            run(["hyprctl", "eval",
                 f'hl.monitor({{ output = "{name}", mode = "{mode}", position = "{position}", scale = {scale} }})'])
        else:
            run(["hyprctl", "keyword", "monitor", f"{name},{mode},{position},{scale}"])


class HyprlandEvents(GObject.Object):
    """Hyprland event socket (socket2). Emits 'event'(name, data); addresses come without 0x."""

    __gsignals__ = {"event": (GObject.SignalFlags.RUN_FIRST, None, (str, str))}

    def __init__(self):
        super().__init__()
        self.stream = None
        self.connection = None
        if Hyprland.available:
            self.open()

    def open(self):
        path = f"{GLib.get_user_runtime_dir()}/hypr/{GLib.getenv('HYPRLAND_INSTANCE_SIGNATURE')}/.socket2.sock"
        try:
            self.connection = Gio.SocketClient().connect(Gio.UnixSocketAddress.new(path), None)
        except GLib.Error:
            GLib.timeout_add_seconds(3, self.open)
            return False
        self.stream = Gio.DataInputStream.new(self.connection.get_input_stream())
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.on_line)
        return False

    def on_line(self, stream, result):
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is None:
            self.stream = None
            GLib.timeout_add_seconds(2, self.open)
            return
        name, _, data = line.partition(">>")
        self.emit("event", name, data)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.on_line)


def window_icon(window_class):
    """Finds an app icon from a window class."""
    if not window_class:
        return None
    for app_id in (window_class, window_class.lower()):
        info = Gio.DesktopAppInfo.new(f"{app_id}.desktop")
        if info:
            return info.get_icon()
    for info in Gio.AppInfo.get_all():
        if isinstance(info, Gio.DesktopAppInfo) and (info.get_startup_wm_class() or "").lower() == window_class.lower():
            return info.get_icon()
    if window_class.startswith("steam_app_"):
        return Gio.ThemedIcon.new_from_names([f"steam_icon_{window_class[10:]}", "applications-games"])
    return Gio.ThemedIcon.new_from_names([window_class.lower(), "application-x-executable"])
