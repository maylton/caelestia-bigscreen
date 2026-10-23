"""Settings: sidebar plus sections (the counterpart of Plasma Bigscreen's KCMs)."""

import os
import platform
import socket

from gi.repository import Adw, GLib, Gtk

from .. import APP_NAME, __version__, artwork, nav
from ..gamepad import controller_batteries
from ..i18n import LANGUAGES, N_, _
from ..m3 import M3Progress, SliderRow
from ..system import Audio, Bluetooth, Hyprland, Network, bt_icon, signal_icon
from ..widgets import SettingRow, SwitchRow, check_icon, clear, group_title, pill, scroller


def battery_widget(theme, percent):
    box = Gtk.Box(spacing=theme.px(10))
    box.append(M3Progress(theme, percent / 100, width=120))
    box.append(Gtk.Label(label=f"{percent}%", css_classes=["battery"], xalign=1))
    return box


def with_spinner(row, busy):
    if busy:
        row.get_child().append(Adw.Spinner())
    return row


class Section(Gtk.Box):
    key = title = icon = subtitle = ""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=app.theme.px(12))
        self.app = app
        self.append(Gtk.Label(label=_(self.title), css_classes=["section-title"], xalign=0))
        if self.subtitle:
            self.append(Gtk.Label(label=_(self.subtitle), css_classes=["section-sub"], xalign=0, wrap=True))
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=app.theme.px(10))
        self.append(self.body)

    def refresh(self):
        """Rebuilds the content keeping the focus on the same item."""
        self.app.preserve_focus(self.body, self.build)

    def build(self):
        clear(self.body)
        self.populate()

    def populate(self):
        raise NotImplementedError

    def add(self, widget):
        self.body.append(widget)

    def refresh_later(self, ms):
        GLib.timeout_add(ms, lambda: self.refresh() or False)

    def on_hide(self):
        pass


# ---- Sound ------------------------------------------------------------------

class AudioSection(Section):
    key, title, icon = "audio", N_("Sound"), "audio-speakers-symbolic"
    subtitle = N_("Volume and output device (TV/HDMI, speakers, headphones).")

    def populate(self):
        if not Audio.available:
            self.add(SettingRow(_("pactl not found"), _("Install pipewire-pulse or pulseaudio-utils.")))
            return
        sinks = Audio.sinks()
        default = next((s for s in sinks if s["default"]), None)
        if default:
            icon = "audio-volume-muted-symbolic" if default["mute"] else "audio-volume-high-symbolic"
            self.add(SliderRow(self.app.theme, icon, _("Volume"), default["volume"], Audio.set_volume,
                               upper=150, key="volume"))
            self.add(SwitchRow(_("Mute"), None, default["mute"], lambda mute: Audio.set_mute(mute, self.refreshed),
                               icon="audio-volume-muted-symbolic"))
        self.add(group_title(_("Output")))
        for sink in sinks:
            if sink["hdmi"]:
                icon = "video-display-symbolic"
            elif sink["bus"] in ("usb", "bluetooth"):
                icon = "audio-headphones-symbolic"
            else:
                icon = "audio-speakers-symbolic"
            self.add(SettingRow(sink["description"], _("In use") if sink["default"] else None, icon,
                                check_icon(sink["default"]), lambda n=sink["name"]: self.select(n), key=sink["name"]))

    def refreshed(self, *_args):
        self.refresh()

    def select(self, name):
        def done(ok, *_args):
            self.refresh()
            if ok:
                self.app.toast(_("Audio output changed"))
        Audio.set_default(name, done)


# ---- Network ----------------------------------------------------------------

class NetworkSection(Section):
    key, title, icon = "network", N_("Network"), "network-wireless-symbolic"
    subtitle = N_("Wired and Wi-Fi connections.")

    def __init__(self, app):
        super().__init__(app)
        self.networks = None
        self.scanning = False

    def populate(self):
        if not Network.available:
            self.add(SettingRow(_("nmcli not found"), _("Networks are managed through NetworkManager.")))
            return
        devices = Network.status()
        for dev in (d for d in devices if d["type"] == "ethernet"):
            connected = dev["state"].startswith("connected")
            self.add(SettingRow(_("Wired"), dev["connection"] if connected else _("Disconnected"),
                                "network-wired-symbolic", key="eth:" + dev["device"]))
        if not any(d["type"] == "wifi" for d in devices):
            return
        enabled = Network.wifi_enabled()
        self.add(SwitchRow(_("Wi-Fi"), None, enabled, self.set_wifi, icon="network-wireless-symbolic"))
        if not enabled:
            return
        self.add(with_spinner(SettingRow(_("Scan for networks"), _("Scanning…") if self.scanning else None,
                                         "view-refresh-symbolic", callback=self.scan, key="scan"), self.scanning))
        if self.networks is None and not self.scanning:
            GLib.idle_add(self.scan, False)
        self.add(group_title(_("Available networks")))
        for net in self.networks or []:
            if net["active"]:
                status = _("Connected")
            else:
                status = _("Secured") if net["secure"] else _("Open")
            lock = Gtk.Image(icon_name="channel-secure-symbolic" if net["secure"] else "channel-insecure-symbolic",
                             css_classes=["lead"])
            self.add(SettingRow(net["ssid"], status, signal_icon(net["signal"]), lock,
                                lambda n=net: self.choose(n), key="ssid:" + net["ssid"]))

    def set_wifi(self, enabled):
        Network.set_wifi(enabled, lambda *_args: self.refresh_later(800))

    def scan(self, rescan=True):
        if not self.scanning:
            self.scanning = True
            self.refresh()

            def done(networks):
                self.scanning = False
                self.networks = networks
                self.refresh()
            Network.scan(done, rescan)
        return False

    def choose(self, net):
        if net["active"]:
            connection = next((d["connection"] for d in Network.status() if d["type"] == "wifi" and d["connection"]),
                              net["ssid"])
            self.app.dialogs.confirm(net["ssid"], _("Disconnect from this network?"), _("Disconnect"),
                                     lambda: Network.disconnect(connection, lambda *_args: self.scan(False)))
        elif not net["secure"] or Network.known(net["ssid"]):
            self.connect(net["ssid"], None)
        else:
            self.app.dialogs.prompt_text(_("Password for “{ssid}”").format(ssid=net["ssid"]),
                                         lambda password: self.connect(net["ssid"], password),
                                         password=True, submit_label=_("Connect"))

    def connect(self, ssid, password):
        self.app.toast(_("Connecting to {ssid}…").format(ssid=ssid))

        def done(ok, _out, err):
            self.app.toast(_("Connected to {ssid}").format(ssid=ssid) if ok
                           else _("Could not connect: {error}").format(error=err.strip()[:80]))
            self.scan(False)
        Network.connect(ssid, password, done)


# ---- Bluetooth ----------------------------------------------------------------

class BluetoothSection(Section):
    key, title, icon = "bluetooth", N_("Bluetooth"), "bluetooth-symbolic"
    subtitle = N_("Controllers, headphones and speakers. To pair a controller, put it in pairing mode.")

    def __init__(self, app):
        super().__init__(app)
        self.scanning = False
        self.poll = 0

    def populate(self):
        if not Bluetooth.available:
            self.add(SettingRow(_("bluetoothctl not found"), _("Install bluez-utils.")))
            return
        powered = Bluetooth.powered()
        self.add(SwitchRow(_("Bluetooth"), None, powered,
                           lambda on: Bluetooth.set_powered(on, lambda *_args: self.refresh_later(600)),
                           icon="bluetooth-symbolic"))
        if not powered:
            return
        self.add(with_spinner(SettingRow(_("Scan for devices"), _("Scanning…") if self.scanning else None,
                                         "view-refresh-symbolic", callback=self.scan, key="scan"), self.scanning))
        devices = Bluetooth.devices()
        if devices:
            self.add(group_title(_("Devices")))
        for dev in devices:
            battery = dev["connected"] and dev["battery"] is not None
            if dev["connected"]:
                status = _("Connected")
            else:
                status = _("Paired") if dev["paired"] else _("Ready to pair")
            self.add(SettingRow(dev["name"], status, bt_icon(dev["icon"]),
                                battery_widget(self.app.theme, dev["battery"]) if battery else None,
                                callback=lambda d=dev: self.actions(d), key=dev["mac"]))

    def scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.refresh()
        self.poll = GLib.timeout_add_seconds(3, lambda: self.refresh() or True)

        def done():
            self.scanning = False
            self.on_hide()
            self.refresh()
        Bluetooth.scan(12, done)

    def actions(self, dev):
        app = self.app

        def run(action, message):
            def done(ok, out, err):
                app.toast(_("Done") if ok else _("Failed: {error}").format(error=(err or out).strip()[-80:]))
                self.refresh()
            app.toast(message)
            action(dev["mac"], done)

        items = []
        if dev["connected"]:
            items.append((_("Disconnect"), lambda: run(Bluetooth.disconnect, _("Disconnecting…")), None))
        elif dev["paired"]:
            items.append((_("Connect"), lambda: run(Bluetooth.connect, _("Connecting…")), None))
        else:
            items.append((_("Pair and connect"), lambda: run(Bluetooth.pair, _("Pairing…")), None))
        if dev["paired"]:
            items.append((_("Forget device"), lambda: run(Bluetooth.remove, _("Removing…")), None, "secondary"))
        app.dialogs.menu(dev["name"], items, text=dev["mac"])

    def on_hide(self):
        if self.poll:
            GLib.source_remove(self.poll)
            self.poll = 0


# ---- Display ------------------------------------------------------------------

SCALES = [0, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5]
REVERT_SECONDS = 15


class DisplaySection(Section):
    key, title, icon = "display", N_("Display"), "video-display-symbolic"
    subtitle = N_("Which screen Big Screen opens on, interface size and resolution.")

    def populate(self):
        app = self.app
        self.add(group_title(_("Open Big Screen on")))
        current = app.config["monitor"]
        self.add(SettingRow(_("Automatic"), _("The focused screen"), "video-display-symbolic",
                            check_icon(current == "auto"), lambda: self.set_monitor("auto"), key="mon:auto"))
        for mon in app.list_monitors():
            name = mon.get_connector() or "?"
            geo = mon.get_geometry()
            description = " · ".join(filter(None, [mon.get_description() or mon.get_model(),
                                                    f"{geo.width}×{geo.height}"]))
            self.add(SettingRow(name, description, "video-display-symbolic", check_icon(current == name),
                                lambda n=name: self.set_monitor(n), key="mon:" + name))

        self.add(group_title(_("Interface size")))
        for scale in SCALES:
            if scale:
                label = f"{round(scale * 100)}%"
            else:
                label = _("Automatic ({percent}%)").format(percent=round(app.theme.auto_scale(app.monitor) * 100))
            self.add(SettingRow(label, None, "zoom-in-symbolic", check_icon(app.config["ui_scale"] == scale),
                                lambda s=scale: self.set_scale(s), key=f"scale:{scale}"))

        if Hyprland.available:
            self.add(group_title(_("Resolution (Hyprland)")))
            for mon in Hyprland.monitors():
                mode = f"{mon['width']}x{mon['height']}@{mon['refreshRate']:.2f}Hz"
                self.add(SettingRow(mon["name"], mode, "preferences-desktop-display-symbolic",
                                    callback=lambda m=mon: self.choose_mode(m), key="res:" + mon["name"]))

    def set_monitor(self, name):
        self.app.config["monitor"] = name
        self.app.toast(_("Applies the next time Big Screen opens"))
        self.refresh()

    def set_scale(self, scale):
        self.app.config["ui_scale"] = scale
        self.app.rebuild_ui(self.key)

    def choose_mode(self, mon):
        dialogs = self.app.dialogs
        modes = {}
        for mode in mon.get("availableModes", []):
            resolution, _sep, hz = mode.partition("@")
            modes.setdefault(f"{resolution} · {float(hz.rstrip('Hz') or 0):.0f} Hz", mode.replace("Hz", ""))
        frame = dialogs.frame(_("Resolution of {name}").format(name=mon["name"]), width=620)
        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=self.app.theme.px(8))
        for label, mode in list(modes.items())[:30]:
            listing.append(SettingRow(label, callback=lambda m=mode: self.apply_mode(mon, m)))
        sw = scroller(listing, horizontal=False)
        sw.set_size_request(-1, self.app.theme.px(520))
        frame.append(sw)
        frame.append(pill(_("Cancel"), dialogs.close, "secondary"))
        dialogs.open(frame)

    def apply_mode(self, mon, mode):
        """Applies the mode and reverts it unless the user confirms in time, like any TV."""
        dialogs = self.app.dialogs
        dialogs.close()
        previous = f"{mon['width']}x{mon['height']}@{mon['refreshRate']:.3f}"
        Hyprland.set_mode(mon, mode)
        state = {"left": REVERT_SECONDS, "source": 0}
        frame = dialogs.frame(_("Keep this resolution?"))
        countdown = Gtk.Label(css_classes=["modal-text"], xalign=0)
        frame.append(countdown)

        def finish(keep):
            if state["source"]:
                GLib.source_remove(state["source"])
                state["source"] = 0
            dialogs.close()
            if keep:
                self.app.toast(_("Resolution kept until Hyprland restarts"))
            else:
                Hyprland.set_mode(mon, previous)
            self.refresh_later(1200)

        def tick():
            countdown.set_label(_("Reverting in {seconds} s.").format(seconds=state["left"]))
            state["left"] -= 1
            if state["left"] < 0:
                state["source"] = 0
                finish(False)
                return False
            return True

        tick()
        buttons = Gtk.Box(spacing=self.app.theme.px(12))
        buttons.append(pill(_("Keep"), lambda: finish(True)))
        buttons.append(pill(_("Revert"), lambda: finish(False), "secondary"))
        frame.append(buttons)
        state["source"] = GLib.timeout_add_seconds(1, tick)
        dialogs.open(frame, on_cancel=lambda: finish(False))


# ---- Controllers ----------------------------------------------------------------

BUTTON_LEGEND = [
    ("PS / Xbox", N_("Show or hide Big Screen")), ("A / ✕", N_("Select")), ("B / ○", N_("Back")),
    ("X / □", N_("Item options")), ("Y / △", N_("Search")), ("LB / RB", N_("Switch tabs")),
    ("LT / RT", N_("Volume")), ("Start", N_("Quick menu")),
]


class ControllersSection(Section):
    key, title, icon = "controllers", N_("Controllers"), "input-gaming-symbolic"
    subtitle = N_("Connected controllers and how Big Screen responds to them.")

    def populate(self):
        app = self.app
        names = app.gamepads.names()
        batteries = controller_batteries()
        self.add(group_title(_("Connected")))
        if not names:
            self.add(SettingRow(_("No controller detected"), _("Connect one over USB or pair it over Bluetooth."),
                                "input-gaming-symbolic", key="none"))
        for name in names:
            battery = next((b for b in batteries if b["name"] and (b["name"] in name or name in b["name"])),
                           batteries[0] if len(batteries) == len(names) == 1 else None)
            subtitle, end = None, None
            if battery and battery["capacity"] is not None:
                subtitle = _("Charging") if battery["status"] == "Charging" else _("Battery")
                end = battery_widget(app.theme, battery["capacity"])
            elif battery:
                subtitle = _("Battery: {level}").format(level=battery["level"])
            self.add(SettingRow(name, subtitle, "input-gaming-symbolic", end, key="pad:" + name))
        self.add(SettingRow(_("Pair a new controller"), _("Opens Bluetooth and scans for devices"),
                            "list-add-symbolic", callback=self.pair, key="pair"))

        self.add(group_title(_("Behavior")))
        self.add(SwitchRow(_("PS / Xbox button opens Big Screen"),
                           _("Pressing it again goes back to the game"), app.config["guide_button"],
                           self.set_guide_button, icon="go-home-symbolic"))
        self.add(SwitchRow(_("Select + Start also opens it"), _("For controllers without a center button"),
                           app.config["select_start_combo"], self.set_combo, icon="input-gaming-symbolic"))

        self.add(group_title(_("Buttons")))
        for button, action in BUTTON_LEGEND:
            row = Gtk.Box(spacing=18, css_classes=["setting-static"])
            row.append(Gtk.Label(label=button, css_classes=["setting-title"], xalign=0, width_chars=12))
            row.append(Gtk.Label(label=_(action), css_classes=["setting-sub"], xalign=0))
            self.add(row)

    def set_guide_button(self, value):
        self.app.config["guide_button"] = value

    def set_combo(self, value):
        self.app.config["select_start_combo"] = value
        self.app.gamepads.combo = value

    def pair(self):
        self.app.open_settings("bluetooth")
        self.app.settings.sections["bluetooth"].scan()


# ---- Appearance -------------------------------------------------------------------

class AppearanceSection(Section):
    key, title, icon = "appearance", N_("Appearance"), "preferences-desktop-appearance-symbolic"

    def populate(self):
        for key, title, subtitle, icon in (
            ("use_shell_colors", _("Use Caelestia colors"), _("Follows the Material You scheme of the wallpaper"),
             "applications-graphics-symbolic"),
            ("show_wallpaper", _("Wallpaper in the background"), None, "preferences-desktop-wallpaper-symbolic"),
            ("game_backdrop", _("Game artwork in the background"),
             _("Shows the artwork of the selected game"), "image-x-generic-symbolic"),
            ("return_on_exit", _("Come back when the game closes"),
             _("Big Screen stays behind the game and returns when it ends"), "view-restore-symbolic"),
        ):
            self.add(SwitchRow(title, subtitle, self.app.config[key], lambda v, k=key: self.set(k, v), icon=icon))

        self.add(group_title(_("Language")))
        current = self.app.config["language"]
        for code, name in LANGUAGES.items():
            self.add(SettingRow(_(name), None, "preferences-desktop-locale-symbolic", check_icon(current == code),
                                lambda c=code: self.set_language(c), key="lang:" + code))

    def set(self, key, value):
        self.app.config[key] = value
        self.app.apply_theme()

    def set_language(self, code):
        self.app.config["language"] = code
        self.app.rebuild_ui(self.key)


# ---- Library ----------------------------------------------------------------------

class LibrarySection(Section):
    key, title, icon = "library", N_("Library"), "applications-games-symbolic"
    subtitle = N_("Game and app sources. Heroic, Lutris and similar launchers show up through the shortcuts "
                  "they create. Apps hidden in the Caelestia launcher are hidden here too.")

    def populate(self):
        sources = self.app.config["sources"]
        self.add(SwitchRow(_("Steam games"), _("With artwork from the local library"), sources.get("steam", True),
                           lambda v: self.set_source("steam", v), icon="applications-games-symbolic"))
        self.add(SwitchRow(_("System apps"), _(".desktop shortcuts"), sources.get("desktop", True),
                           lambda v: self.set_source("desktop", v), icon="view-app-grid-symbolic"))
        self.add(SettingRow(_("Reload library"), None, "view-refresh-symbolic", callback=self.reload))

        self.add(group_title(_("Game artwork (SteamGridDB)")))
        self.add(Gtk.Label(label=_("Covers, backgrounds and logos for games outside Steam come from SteamGridDB, a "
                                   "community database. It needs a free personal API key: sign in at "
                                   "steamgriddb.com, open Preferences › API, generate a key and paste it below."),
                           css_classes=["setting-sub"], xalign=0, wrap=True))
        key = self.app.config["steamgriddb_key"]
        self.add(SettingRow(_("API key"), _("Set, ends in {end}").format(end=key[-4:]) if key
                            else _("Not set: needed to download artwork"),
                            "dialog-password-symbolic", callback=self.edit_key, key="sgdb-key"))
        if key:
            self.add(SettingRow(_("Download missing artwork"), _("Only games without artwork are looked up"),
                                "folder-download-symbolic", callback=self.download, key="sgdb-download"))
            self.add(SettingRow(_("Download all artwork again"), None, "view-refresh-symbolic",
                                callback=self.redownload, key="sgdb-redownload"))
            self.add(SettingRow(_("Remove API key"), None, "edit-delete-symbolic", callback=self.remove_key,
                                key="sgdb-remove"))

        hidden = self.app.library.hidden()
        if hidden:
            self.add(group_title(_("Hidden (select to show again)")))
        for entry in hidden:
            self.add(SettingRow(entry.name, gicon=entry.icon, callback=lambda e=entry: self.unhide(e), key=entry.id))

    def set_source(self, source, value):
        self.app.config["sources"][source] = value
        self.app.config.save()
        self.reload()

    def reload(self):
        self.app.reload_library()
        self.app.toast(_("Library reloaded"))
        self.refresh()

    def unhide(self, entry):
        self.app.config.toggle_in("hidden", entry.id)
        self.app.library_changed()
        self.refresh()

    def edit_key(self):
        self.app.dialogs.prompt_text(_("SteamGridDB API key"), self.save_key, password=True,
                                     submit_label=_("Save"))

    def save_key(self, key):
        self.app.config["steamgriddb_key"] = key.strip()
        self.refresh()
        if key.strip():
            self.download()

    def download(self):
        count = self.app.fetch_artwork(notify=True)
        if count:
            self.app.toast(_("Looking up artwork for {count} games…").format(count=count))

    def redownload(self):
        artwork.clear_cache()
        self.app.library.reload()
        self.app.library_changed()
        self.download()

    def remove_key(self):
        self.app.config["steamgriddb_key"] = ""
        self.refresh()


# ---- Power and About ----------------------------------------------------------------

class PowerSection(Section):
    key, title, icon = "power", N_("Power"), "system-shutdown-symbolic"

    def populate(self):
        app = self.app
        if app.session_mode:
            self.add(SettingRow(_("Log out"), _("Back to the login screen"), "system-log-out-symbolic",
                                callback=lambda: app.power_action("logout")))
        else:
            self.add(SettingRow(_("Back to desktop"), _("Hides Big Screen (the PS / Xbox button opens it again)"),
                                "go-previous-symbolic", callback=app.hide_ui))
        for action, label, icon in (("suspend", _("Suspend"), "weather-clear-night-symbolic"),
                                    ("reboot", _("Restart"), "system-reboot-symbolic"),
                                    ("poweroff", _("Shut down"), "system-shutdown-symbolic")):
            self.add(SettingRow(label, None, icon, callback=lambda a=action: app.power_action(a)))
        if not app.session_mode:
            self.add(SettingRow(_("Quit Big Screen"), _("The gamepad button stops working until it starts again"),
                                "application-exit-symbolic",
                                callback=lambda: app.dialogs.confirm(_("Quit Big Screen?"), None, _("Quit"),
                                                                     app.quit, True)))


def os_name():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "Linux"


class AboutSection(Section):
    key, title, icon = "about", N_("About"), "help-about-symbolic"

    def populate(self):
        try:
            with open("/proc/uptime") as f:
                seconds = int(float(f.read().split()[0]))
            uptime = _("{hours} h {minutes} min").format(hours=seconds // 3600, minutes=seconds % 3600 // 60)
        except OSError:
            uptime = "?"
        session = f"{os.environ.get('XDG_CURRENT_DESKTOP', '?')} · {os.environ.get('XDG_SESSION_TYPE', '?')}"
        for title, subtitle, icon in (
            (APP_NAME, _("Version {version}").format(version=__version__), "video-display-symbolic"),
            (_("Computer"), socket.gethostname(), "computer-symbolic"),
            (_("System"), os_name(), "distributor-logo-symbolic"),
            (_("Kernel"), platform.release(), "application-x-firmware-symbolic"),
            (_("Session"), session, "preferences-system-symbolic"),
            (_("Uptime"), uptime, "alarm-symbolic"),
        ):
            self.add(SettingRow(title, subtitle, icon))


SECTIONS = [AudioSection, NetworkSection, BluetoothSection, DisplaySection, ControllersSection,
            AppearanceSection, LibrarySection, PowerSection, AboutSection]


class SettingsPage(Gtk.Box):
    def __init__(self, app):
        super().__init__()
        px = app.theme.px
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=px(6), css_classes=["sidebar"])
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=150,
                               hexpand=True)
        self.sections, self.items = {}, {}
        for cls in SECTIONS:
            section = cls(app)
            self.sections[cls.key] = section
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["settings-content"])
            content.append(section)
            self.stack.add_named(scroller(content, horizontal=False), cls.key)
            item = Gtk.Button(css_classes=["side-item"])
            box = Gtk.Box(spacing=px(14))
            box.append(Gtk.Image(icon_name=cls.icon))
            box.append(Gtk.Label(label=_(cls.title), xalign=0))
            item.set_child(box)
            item.section_key = cls.key
            item.connect("clicked", lambda _b, k=cls.key: self.show(k, focus_content=True))
            self.items[cls.key] = item
            self.sidebar.append(item)
        sidebar_scroller = scroller(self.sidebar, horizontal=False)
        sidebar_scroller.set_hexpand(False)
        self.append(sidebar_scroller)
        self.append(self.stack)
        self.current = None
        self.show("audio")

    def show(self, key, focus_content=False):
        if key != self.current:
            if self.current:
                self.sections[self.current].on_hide()
                self.items[self.current].remove_css_class("active")
            self.current = key
            self.items[key].add_css_class("active")
            self.sections[key].build()
            self.stack.set_visible_child_name(key)
        if focus_content:
            GLib.idle_add(self.focus_content)

    def focus_content(self):
        nav.focus(nav.first_candidate(self.sections[self.current].body))
        return False

    def focus_sidebar(self):
        self.items[self.current].grab_focus()

    def in_content(self, widget):
        return widget is not None and widget.is_ancestor(self.stack)

    def refresh_current(self):
        if self.current:
            self.sections[self.current].refresh()
