"""Game session: the windows opened from Big Screen, followed through Hyprland events.

After a launch, the next window that appears is the game ("started"). When every
window of the session closes, or nothing is focused any more, the game is over
("ended") and Big Screen comes back to the front.
"""

from gi.repository import GLib, GObject

from .system import Hyprland, HyprlandEvents

# A new window still counts as "the game that was just launched" for this long
LAUNCH_WINDOW_SECONDS = 180
# Launcher clients stay open after the game exits, so their windows are not part of it
LAUNCHER_CLASSES = {"steam", "steamwebhelper", "heroic", "net.lutris.lutris", "epicgameslauncher",
                    "com.usebottles.bottles"}
# Windows closing this soon after the first one opened are a launcher handing over to the game
HANDOFF_SECONDS = 60
# An already open app gets focused right after the launch, not minutes later
ACTIVATION_SECONDS = 10


class GameSession(GObject.Object):
    __gsignals__ = {
        "started": (GObject.SignalFlags.RUN_FIRST, None, (str,)),  # window address
        "ended": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Some window entered fullscreen (address), launched from here or not
        "fullscreen": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self.tracked = set()
        self.pending = None  # {"entry", "active"} while waiting for the game window
        self.pending_source = 0
        self.first_window_at = 0
        self.handed_off = False
        self.ignored = set()
        self.active_class = ""
        # True while Big Screen sits behind the session windows
        self.background = False
        self.events = HyprlandEvents()
        self.events.connect("event", self.on_event)

    @property
    def available(self):
        return self.events.stream is not None

    def launched(self, entry):
        active = Hyprland.active_window() if Hyprland.available else {}
        self.pending = {"entry": entry, "active": (active.get("address") or "").removeprefix("0x"),
                        "at": GLib.get_monotonic_time()}
        # Opening a launcher itself (Heroic, Lutris…) still follows its window
        self.ignored = LAUNCHER_CLASSES if entry.is_game else set()
        self.first_window_at = 0
        self.handed_off = False
        if self.pending_source:
            GLib.source_remove(self.pending_source)
        self.pending_source = GLib.timeout_add_seconds(LAUNCH_WINDOW_SECONDS, self.stop_waiting)

    def follow(self, address):
        self.tracked.add(address.removeprefix("0x"))

    def reset(self):
        if self.pending_source:
            GLib.source_remove(self.pending_source)
        self.stop_waiting()
        self.tracked.clear()

    def stop_waiting(self):
        self.pending_source = 0
        self.pending = None
        self.first_window_at = 0
        return False

    def track(self, address):
        self.tracked.add(address)
        if self.pending and not self.first_window_at:
            self.first_window_at = GLib.get_monotonic_time()

    @staticmethod
    def fullscreen_window():
        active = Hyprland.active_window()
        if active.get("fullscreen"):
            return active.get("address", "")
        clients = sorted((c for c in Hyprland.clients() if c.get("fullscreen")),
                         key=lambda c: c.get("focusHistoryID", 99))
        return clients[0]["address"] if clients else ""

    def on_event(self, _events, name, data):
        if name == "openwindow":
            address, _workspace, window_class = (data.split(",", 3) + ["", ""])[:3]
            if window_class.lower() in self.ignored:
                return
            if self.pending or self.background:
                self.track(address)
            if self.pending and not self.background:
                self.emit("started", address)
        elif name == "activewindow":
            # Comes right before activewindowv2, which only has the address
            self.active_class = data.split(",", 1)[0].lower()
        elif name == "activewindowv2":
            address = "" if data.strip() in ("", ",", "0", "0x0") else data.strip()
            if not address:
                if self.background:
                    GLib.timeout_add(400, self.check_ended, False)
            elif (self.pending and not self.background and address != self.pending["active"]
                  and self.active_class not in self.ignored
                  and GLib.get_monotonic_time() - self.pending["at"] < ACTIVATION_SECONDS * 1e6):
                # The app was already open and only got activated (no new window)
                self.track(address)
                self.emit("started", address)
        elif name == "fullscreen" and data.strip() == "1" and not self.background:
            if address := self.fullscreen_window():
                self.emit("fullscreen", address.removeprefix("0x"))
        elif name == "closewindow" and data.strip() in self.tracked:
            self.tracked.discard(data.strip())
            if not self.tracked and self.background:
                GLib.timeout_add(500, self.check_ended, True)

    def check_ended(self, all_closed):
        if not self.background:
            return False
        ended = not self.tracked if all_closed else not Hyprland.active_window().get("address")
        if ended:
            # A launcher that closed right after opening is handing over to the game:
            # keep waiting for the game window (once per launch) instead of forgetting it
            handoff = (self.pending and not self.handed_off
                       and GLib.get_monotonic_time() - self.first_window_at < HANDOFF_SECONDS * 1e6)
            if handoff:
                self.handed_off = True
                self.tracked.clear()
            else:
                self.reset()
            self.emit("ended")
        return False
