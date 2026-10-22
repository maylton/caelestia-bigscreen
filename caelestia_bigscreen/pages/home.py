"""Home page and the library grids."""

from gi.repository import Gtk

from ..i18n import _
from ..widgets import ActionCard, Card, SizedPicture, clear, load_picture, on_focus, pill, scroller, strip

APPS_ON_HOME = 14


def card(app, entry):
    return Card(app, entry, "poster" if entry.is_game else "tile")


class HomePage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["page"])
        self.append(scroller(self.content, horizontal=False))
        self.rebuild()

    def rebuild(self):
        app, library = self.app, self.app.library
        clear(self.content)
        games, recents, favorites = library.games(), library.recents(), library.favorites()
        featured = next((e for e in recents if e.is_game), games[0] if games else None)
        if featured:
            self.content.append(self.hero(featured))
        if recents:
            self.content.append(strip(app, _("Continue"), [card(app, e) for e in recents]))
        if favorites:
            self.content.append(strip(app, _("Favorites"), [card(app, e) for e in favorites]))
        if games:
            self.content.append(strip(app, _("Games"), [Card(app, e, "poster") for e in games]))
        if launchers := library.launchers():
            self.content.append(strip(app, _("Stores and launchers"), [Card(app, e, "tile") for e in launchers]))

        # Apps the user already opened or pinned come first
        seen = {e.id for e in favorites + recents}
        apps = sorted(library.apps(), key=lambda e: e.id not in seen)[:APPS_ON_HOME]
        cards = [Card(app, e, "tile") for e in apps]
        cards.append(ActionCard(app, "view-app-grid-symbolic", _("All apps"), lambda: app.go_tab("apps"), "tile"))
        self.content.append(strip(app, _("Apps"), cards))

        self.content.append(strip(app, _("System"), [
            ActionCard(app, "network-wireless-symbolic", _("Network"), lambda: app.open_settings("network")),
            ActionCard(app, "bluetooth-symbolic", _("Bluetooth"), lambda: app.open_settings("bluetooth")),
            ActionCard(app, "audio-speakers-symbolic", _("Sound"), lambda: app.open_settings("audio")),
            ActionCard(app, "video-display-symbolic", _("Display"), lambda: app.open_settings("display")),
            ActionCard(app, "input-gaming-symbolic", _("Controllers"), lambda: app.open_settings("controllers")),
            ActionCard(app, "system-shutdown-symbolic", _("Power"), app.dialogs.power_menu),
        ]))

    def hero(self, entry):
        app = self.app
        px = app.theme.px
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=px(14), css_classes=["hero"])
        box.set_size_request(-1, px(330))
        box.append(Gtk.Box(vexpand=True))
        if entry.logo:
            logo = SizedPicture(px(460), px(150), Gtk.ContentFit.CONTAIN)
            logo.set_halign(Gtk.Align.START)
            load_picture(logo, entry.logo, px(460) * 2, px(150) * 2)
            box.append(logo)
        else:
            box.append(Gtk.Label(label=entry.name, css_classes=["hero-title"], xalign=0, wrap=True))
        recent = entry.id in app.config["recents"]
        box.append(Gtk.Label(label=_("Recently played") if recent else _("In your library"),
                             css_classes=["hero-sub"], xalign=0))
        buttons = Gtk.Box(spacing=px(16))
        play = pill(_("Play"), lambda: app.launch(entry), icon="media-playback-start-symbolic")
        on_focus(play, lambda: app.on_entry_focus(entry))
        buttons.append(play)
        buttons.append(pill(_("Library"), lambda: app.go_tab("games"), "secondary", icon="view-grid-symbolic"))
        box.append(buttons)
        return box


class GridPage(Gtk.Box):
    """Grid with every game or every app."""

    def __init__(self, app, title, provider, style, empty):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app, self.title, self.provider, self.style, self.empty = app, title, provider, style, empty
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["page"])
        self.append(scroller(self.content, horizontal=False))
        self.rebuild()

    def rebuild(self):
        app = self.app
        px = app.theme.px
        clear(self.content)
        header = Gtk.Box(spacing=px(20))
        header.append(Gtk.Label(label=self.title, css_classes=["page-title"], xalign=0, hexpand=True))
        search = pill(_("Search"), app.dialogs.search, "secondary", "page-action", icon="system-search-symbolic")
        search.set_valign(Gtk.Align.END)
        header.append(search)
        self.content.append(header)

        entries = self.provider()
        if not entries:
            self.content.append(Gtk.Label(label=self.empty, css_classes=["empty"], xalign=0))
            return
        flow = Gtk.FlowBox(css_classes=["grid"], selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           column_spacing=px(30), row_spacing=px(26), max_children_per_line=30,
                           valign=Gtk.Align.START, focusable=False)
        for entry in entries:
            flow.append(Card(app, entry, self.style))
            flow.get_last_child().set_focusable(False)  # only the card button takes focus
        self.content.append(flow)
