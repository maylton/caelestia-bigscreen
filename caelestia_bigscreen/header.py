"""Top bar: tabs, status indicators, clock and the search/power buttons."""

from gi.repository import GLib, Gtk

from .i18n import N_, _
from .system import Audio, Bluetooth, Network

TABS = [("home", N_("Home")), ("games", N_("Games")), ("apps", N_("Apps")), ("settings", N_("Settings"))]


class Header(Gtk.Box):
    def __init__(self, app):
        px = app.theme.px
        super().__init__(spacing=px(10), css_classes=["header"])
        self.app = app
        self.append(Gtk.Label(label="BIG SCREEN", css_classes=["brand"]))
        self.tabs = {}
        for key, label in TABS:
            button = Gtk.Button(label=_(label), css_classes=["tab"])
            button.tab_key = key
            button.connect("clicked", lambda _b, k=key: app.go_tab(k))
            self.tabs[key] = button
            self.append(button)
        self.append(Gtk.Box(hexpand=True))

        status = Gtk.Box(spacing=px(16), css_classes=["status"], valign=Gtk.Align.CENTER)
        self.pads = Gtk.Box(spacing=px(6))
        self.pads.append(Gtk.Image(icon_name="input-gaming-symbolic"))
        self.pads_count = Gtk.Label()
        self.pads.append(self.pads_count)
        self.bluetooth = Gtk.Image(icon_name="bluetooth-active-symbolic")
        self.network = Gtk.Image(icon_name="network-offline-symbolic")
        self.volume = Gtk.Box(spacing=px(6))
        self.volume_icon = Gtk.Image(icon_name="audio-volume-high-symbolic")
        self.volume_label = Gtk.Label()
        self.volume.append(self.volume_icon)
        self.volume.append(self.volume_label)
        for widget in (self.pads, self.bluetooth, self.network, self.volume):
            status.append(widget)
        self.append(status)

        clock = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, css_classes=["clock-box"])
        self.clock = Gtk.Label(css_classes=["clock"], xalign=1)
        self.date = Gtk.Label(css_classes=["date"], xalign=1)
        clock.append(self.clock)
        clock.append(self.date)
        self.append(clock)

        for icon, callback in (("system-search-symbolic", lambda: app.dialogs.search()),
                               ("system-shutdown-symbolic", lambda: app.dialogs.power_menu())):
            button = Gtk.Button(icon_name=icon, css_classes=["icon-button"], valign=Gtk.Align.CENTER)
            button.connect("clicked", lambda *_args, c=callback: c())
            self.append(button)

    def set_active(self, key):
        for k, button in self.tabs.items():
            (button.add_css_class if k == key else button.remove_css_class)("active")

    def update(self):
        now = GLib.DateTime.new_now_local()
        self.clock.set_label(now.format("%H:%M"))
        # Translators: strftime date format of the header clock
        self.date.set_label(now.format(_("%a, %b %d")))
        pads = len(self.app.gamepads.pads)
        self.pads.set_visible(pads > 0)
        self.pads_count.set_label(str(pads) if pads > 1 else "")

        if Network.available:
            connected = {d["type"] for d in Network.status() if d["state"] == "connected"}
            icon = ("network-wired-symbolic" if "ethernet" in connected else
                    "network-wireless-signal-good-symbolic" if "wifi" in connected else "network-offline-symbolic")
            self.network.set_from_icon_name(icon)
        self.bluetooth.set_visible(Bluetooth.available and Bluetooth.any_connected())
        default = Audio.default() if Audio.available else None
        self.volume.set_visible(default is not None)
        if default:
            self.set_volume(default["volume"], default["mute"])

    def set_volume(self, value, mute=False):
        self.volume_icon.set_from_icon_name("audio-volume-muted-symbolic" if mute else "audio-volume-high-symbolic")
        self.volume_label.set_label(f"{value}%")
