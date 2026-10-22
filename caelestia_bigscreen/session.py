"""Game session: the windows opened from Big Screen, followed through Hyprland events.

After a launch, the next window that appears is the game ("started"). When every
window of the session closes, or nothing is focused any more, the game is over
("ended") and Big Screen comes back to the front.
"""

from gi.repository import GLib, GObject

from .system import Hyprland, HyprlandEvents

# A new window still counts as "the game that was just launched" for this long
LAUNCH_WINDOW_SECONDS = 180
# The Steam client stays open after the game exits, so it is not part of it
STEAM_CLIENT_CLASSES = {"steam", "steamwebhelper"}


class GameSession(GObject.Object):
    __gsignals__ = {
        "started": (GObject.SignalFlags.RUN_FIRST, None, (str,)),  # window address
        "ended": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.tracked = set()
        self.pending = None  # {"entry", "active"} while waiting for the game window
        self.pending_source = 0
        self.ignored = set()
        # True while Big Screen sits behind the session windows
        self.background = False
        self.events = HyprlandEvents()
        self.events.connect("event", self.on_event)

    @property
    def available(self):
        return self.events.stream is not None

    def launched(self, entry):
        active = Hyprland.active_window() if Hyprland.available else {}
        self.pending = {"entry": entry, "active": (active.get("address") or "").removeprefix("0x")}
        self.ignored = STEAM_CLIENT_CLASSES if entry.source == "steam" else set()
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
        return False

    def on_event(self, _events, name, data):
        if name == "openwindow":
            address, _workspace, window_class = (data.split(",", 3) + ["", ""])[:3]
            if window_class.lower() in self.ignored:
                return
            if self.pending or self.background:
                self.tracked.add(address)
            if self.pending and not self.background:
                self.emit("started", address)
        elif name == "activewindowv2":
            address = "" if data.strip() in ("", ",", "0", "0x0") else data.strip()
            if not address:
                if self.background:
                    GLib.timeout_add(400, self.check_ended, False)
            elif self.pending and not self.background and address != self.pending["active"]:
                # The app was already open and only got activated (no new window)
                self.tracked.add(address)
                self.emit("started", address)
        elif name == "closewindow" and data.strip() in self.tracked:
            self.tracked.discard(data.strip())
            if not self.tracked and self.background:
                GLib.timeout_add(500, self.check_ended, True)

    def check_ended(self, all_closed):
        if not self.background:
            return False
        ended = not self.tracked if all_closed else not Hyprland.active_window().get("address")
        if ended:
            self.reset()
            self.emit("ended")
        return False
