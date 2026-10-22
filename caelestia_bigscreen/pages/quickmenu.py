"""Side quick menu shown over a game when the Guide button is pressed."""

from gi.repository import GLib, Gtk

from ..i18n import _
from ..m3 import SliderRow
from ..system import Audio, Hyprland, window_icon
from ..widgets import SettingRow, clear, group_title, scroller, set_context


class QuickMenu(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["quick-panel"],
                         halign=Gtk.Align.START, vexpand=True)
        self.app = app
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=app.theme.px(10))
        self.append(scroller(self.content, horizontal=False))

    def add(self, widget):
        self.content.append(widget)

    def rebuild(self):
        app = self.app
        clear(self.content)
        now = GLib.DateTime.new_now_local()
        self.add(Gtk.Label(label=now.format("%H:%M"), css_classes=["clock"], xalign=0))
        # Translators: strftime date format of the quick menu
        self.add(Gtk.Label(label=now.format(_("%A, %B %d")), css_classes=["date"], xalign=0))

        active = Hyprland.active_window() if Hyprland.available else {}
        if active.get("title"):
            self.add(group_title(_("Now")))
            self.add(SettingRow(active["title"], _("Resume"), gicon=window_icon(active.get("class")),
                                callback=app.leave, key="resume"))
        self.add(SettingRow(_("Home"), icon="go-home-symbolic", callback=app.show_home))
        self.add(SettingRow(_("Search"), icon="system-search-symbolic", callback=app.dialogs.search))
        self.add(SettingRow(_("Settings"), icon="emblem-system-symbolic", callback=lambda: app.open_settings("audio")))

        default = Audio.default() if Audio.available else None
        if default:
            self.add(SliderRow(app.theme, "audio-volume-high-symbolic", _("Volume"), default["volume"],
                               Audio.set_volume, upper=150, key="volume"))

        if Hyprland.available:
            clients = [c for c in Hyprland.clients() if c.get("address") != active.get("address")]
            if clients:
                self.add(group_title(_("Open windows  ·  X closes")))
            for client in clients:
                row = SettingRow(client.get("title") or client["class"], client["class"],
                                 gicon=window_icon(client["class"]), callback=lambda c=client: self.focus(c),
                                 key=client["address"])
                set_context(row, lambda c=client: self.close(c))
                self.add(row)
            if active.get("address"):
                self.add(group_title(_("Current game")))
                self.add(SettingRow(_("Close current window"), active.get("title"), "window-close-symbolic",
                                    callback=lambda: self.close(active)))

        self.add(SettingRow(_("Power"), icon="system-shutdown-symbolic", callback=app.dialogs.power_menu))

    def focus(self, client):
        # The chosen window joins the session: when it closes, Big Screen comes back
        self.app.session.follow(client["address"])
        self.app.go_background()
        Hyprland.focus(client["address"])

    def close(self, client):
        title = client.get("title") or client.get("class")

        def do_close():
            Hyprland.close(client["address"])
            self.app.toast(_("Closing {title}").format(title=title))
            GLib.timeout_add(700, lambda: self.app.preserve_focus(self.content, self.rebuild))
        self.app.dialogs.confirm(_("Close “{title}”?").format(title=title), _("Unsaved progress may be lost."),
                                 _("Close"), do_close, True)
