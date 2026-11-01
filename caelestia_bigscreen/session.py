"""Game session: the windows opened from Big Screen, followed through Hyprland events.

After a launch, the next window that appears is the game ("started"). When every
window of the session closes, or nothing is focused any more, the game is over
("ended") and Big Screen comes back to the front.

Games that drop out of fullscreen by themselves right after entering it are put back.
Wuthering Waves does it after its login screen, and Hyprland makes it worse with
misc:on_focus_under_fullscreen = 2 (Caelestia's default), which takes the fullscreen
window out whenever one of the game's short-lived helper windows gets focus.
"""

import re

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
# Steam/Proton (and umu, used by Lutris and Heroic) game windows, launched from here or not
GAME_CLASSES = re.compile(r"steam_app_\w+|gamescope")
# A game leaving fullscreen this soon after entering it is put back; later it is the player's choice
KEEP_FULLSCREEN_SECONDS = 120
# A closing window also leaves fullscreen: by the time of the check it is gone and left alone
KEEP_FULLSCREEN_DELAY_MS = 800
# Gives up on a game that keeps leaving anyway
KEEP_FULLSCREEN_MAX_RESTORES = 20


class GameSession(GObject.Object):
    __gsignals__ = {
        "started": (GObject.SignalFlags.RUN_FIRST, None, (str,)),  # window address
        "ended": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Some window entered fullscreen (address), launched from here or not
        "fullscreen": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, keep_fullscreen=lambda: True):
        super().__init__()
        self.keep_fullscreen = keep_fullscreen
        self.kept = {}  # game windows that went fullscreen: address -> {"since", "restores"}
        self.keep_source = 0
        self.launched_game = False
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
        self.launched_game = entry.is_game
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
        elif name == "fullscreen":
            if data.strip() == "1":
                self.remember_fullscreen_games()
                if not self.background and (address := self.fullscreen_window()):
                    self.emit("fullscreen", address.removeprefix("0x"))
            elif self.kept and not self.keep_source:
                self.keep_source = GLib.timeout_add(KEEP_FULLSCREEN_DELAY_MS, self.restore_fullscreen)
        elif name == "closewindow":
            address = data.strip()
            self.kept.pop(address, None)
            if address in self.tracked:
                self.tracked.discard(address)
                if not self.tracked and self.background:
                    GLib.timeout_add(500, self.check_ended, True)

    # ---- Keeping games in fullscreen -----------------------------------------------

    def is_game(self, address, window_class):
        return bool(GAME_CLASSES.fullmatch(window_class)) or (self.launched_game and address in self.tracked)

    def remember_fullscreen_games(self):
        if not self.keep_fullscreen():
            return
        now = GLib.get_monotonic_time()
        for client in Hyprland.clients():
            address = client.get("address", "").removeprefix("0x")
            if client.get("fullscreen") and address not in self.kept and self.is_game(address, client["class"]):
                self.kept[address] = {"since": now, "restores": 0}

    def restore_fullscreen(self):
        self.keep_source = 0
        if not self.keep_fullscreen():
            self.kept.clear()
            return False
        # Only mapped, visible windows: a window that is closing has already gone from this list
        clients = {c.get("address", "").removeprefix("0x"): c for c in Hyprland.clients()}
        now = GLib.get_monotonic_time()
        for address, state in list(self.kept.items()):
            client = clients.get(address)
            if (not client or now - state["since"] > KEEP_FULLSCREEN_SECONDS * 1e6
                    or state["restores"] >= KEEP_FULLSCREEN_MAX_RESTORES):
                del self.kept[address]
            elif not client.get("fullscreen"):
                state["restores"] += 1
                Hyprland.set_fullscreen("0x" + address)
        return False

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
