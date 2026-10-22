"""Dialogs drawn inside the window (a single surface, so they work with layer-shell).

Includes the modal stack, toasts, the launch splash and the common dialogs.
"""

from gi.repository import Adw, GLib, Gtk

from . import nav
from .i18n import _
from .m3 import M3Progress
from .widgets import Card, OnScreenKeyboard, SizedPicture, clear, load_picture, pill, scroller


class Dialogs:
    def __init__(self, app):
        self.app = app
        self.layer = Gtk.Box(css_classes=["modal-scrim"], visible=False)
        self.stack = []

    def __bool__(self):
        return bool(self.stack)

    @property
    def top(self):
        return self.stack[-1] if self.stack else None

    def open(self, widget, on_cancel=None, keyboard=None, focus=None):
        """Shows `widget` on top. `keyboard` is an OnScreenKeyboard that receives shortcuts."""
        if self.stack:
            self.layer.remove(self.stack[-1]["widget"])
        widget.set_hexpand(True)
        widget.set_vexpand(True)
        self.stack.append({"widget": widget, "cancel": on_cancel, "keyboard": keyboard,
                           "focus": self.app.win.get_focus()})
        self.layer.append(widget)
        self.layer.set_visible(True)
        self.app.update_hints()
        GLib.idle_add(lambda: nav.focus(nav.first_candidate(focus or widget)) and False)

    def close(self, cancelled=False):
        if not self.stack:
            return
        modal = self.stack.pop()
        self.layer.remove(modal["widget"])
        if self.stack:
            self.layer.append(self.stack[-1]["widget"])
        else:
            self.layer.set_visible(False)
        self.app.update_hints()
        if modal["focus"] is not None and modal["focus"].get_mapped():
            modal["focus"].grab_focus()
        if cancelled and modal["cancel"]:
            modal["cancel"]()

    def close_all(self):
        while self.stack:
            self.close()

    @property
    def keyboard(self):
        return self.top["keyboard"] if self.top else None

    # ---- Builders ---------------------------------------------------------------

    def frame(self, title=None, text=None, width=None):
        px = self.app.theme.px
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=px(18), css_classes=["modal"],
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        if width:
            box.set_size_request(px(width), -1)
        if title:
            box.append(Gtk.Label(label=title, css_classes=["modal-title"], xalign=0, wrap=True))
        if text:
            box.append(Gtk.Label(label=text, css_classes=["modal-text"], xalign=0, wrap=True))
        return box

    def menu(self, title, items, text=None):
        """Vertical list of actions; items are (label, callback, icon, *css classes)."""
        frame = self.frame(title, text, width=600)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=self.app.theme.px(10))
        for label, callback, icon, *classes in items:
            box.append(pill(label, lambda c=callback: (self.close(), c()), *classes, icon=icon))
        box.append(pill(_("Cancel"), self.close, "secondary"))
        frame.append(box)
        self.open(frame)

    def confirm(self, title, text, ok_label, on_ok, danger=False):
        frame = self.frame(title, text, width=620)
        buttons = Gtk.Box(spacing=self.app.theme.px(14), halign=Gtk.Align.END)
        ok = pill(ok_label, lambda: (self.close(), on_ok()), *(["danger"] if danger else []))
        cancel = pill(_("Cancel"), self.close, "secondary")
        # Destructive actions start focused on Cancel
        for button in (cancel, ok) if danger else (ok, cancel):
            buttons.append(button)
        frame.append(buttons)
        self.open(frame)

    def text_input(self, title, on_submit, submit_label, width, password=False, placeholder=None, extra=None):
        """Text field with the on-screen keyboard. Returns the Gtk.Entry."""
        frame = self.frame(title, width=width)
        entry = Gtk.Entry(css_classes=["osk-entry"], visibility=not password, can_focus=False, can_target=False,
                          placeholder_text=placeholder)
        frame.append(entry)
        if extra:
            frame.append(extra)
        keyboard = OnScreenKeyboard(self.app, entry, on_submit, submit_label)
        frame.append(keyboard)
        self.open(frame, keyboard=keyboard, focus=keyboard)
        return entry

    def prompt_text(self, title, on_done, password=False, submit_label=None):
        self.text_input(title, lambda text: (self.close(), on_done(text)), submit_label or _("OK"), 980, password)

    def search(self, initial=""):
        app = self.app
        px = app.theme.px
        results = Gtk.Box(spacing=px(26), css_classes=["row-strip"])
        results.set_size_request(-1, px(270))
        pending = {"source": 0}

        def pick(entry):
            self.close()
            app.launch(entry)

        def refresh():
            pending["source"] = 0
            clear(results)
            text = entry.get_text()
            hits = app.library.search(text)
            if not hits and text.strip():
                results.append(Gtk.Label(label=_("Nothing found"), css_classes=["empty"]))
            for hit in hits:
                results.append(Card(app, hit, "tile", on_activate=pick))
            return False

        def changed(*_args):
            if pending["source"]:
                GLib.source_remove(pending["source"])
            pending["source"] = GLib.timeout_add(120, refresh)

        def submit(text):
            hits = app.library.search(text)
            if hits:
                pick(hits[0])

        entry = self.text_input(_("Search"), submit, _("Open"), 1240, placeholder=_("Game or app name"),
                                extra=scroller(results, horizontal=True))
        entry.connect("changed", changed)
        entry.set_text(initial)
        refresh()

    def entry_menu(self, entry):
        app = self.app

        def toggle_favorite():
            added = app.config.toggle_in("favorites", entry.id)
            app.toast(_("Added to favorites") if added else _("Removed from favorites"))
            app.library_changed()

        def hide():
            app.config.toggle_in("hidden", entry.id)
            app.toast(_("{name} is hidden (Settings › Library shows it again)").format(name=entry.name))
            app.library_changed()
            GLib.idle_add(app.restore_focus)

        favorite = entry.id in app.config["favorites"]
        self.menu(entry.name, [
            (_("Play") if entry.is_game else _("Open"), lambda: app.launch(entry), "media-playback-start-symbolic"),
            (_("Remove from favorites") if favorite else _("Add to favorites"), toggle_favorite,
             "starred-symbolic", "secondary"),
            (_("Hide from library"), hide, "view-conceal-symbolic", "secondary"),
        ])

    def power_menu(self):
        app = self.app
        first = ((_("Log out"), lambda: app.power_action("logout"), "system-log-out-symbolic", "secondary")
                 if app.session_mode else
                 (_("Back to desktop"), app.hide_ui, "go-previous-symbolic", "secondary"))
        self.menu(_("Power"), [
            first,
            (_("Suspend"), lambda: app.power_action("suspend"), "weather-clear-night-symbolic", "secondary"),
            (_("Restart"), lambda: app.power_action("reboot"), "system-reboot-symbolic", "secondary"),
            (_("Shut down"), lambda: app.power_action("poweroff"), "system-shutdown-symbolic", "secondary"),
        ])


class Toast(Gtk.Revealer):
    """Short message at the bottom, optionally with a progress bar (volume)."""

    def __init__(self, theme):
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.END, can_target=False,
                         transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=theme.px(10), css_classes=["toast"])
        self.label = Gtk.Label()
        self.progress = M3Progress(theme, width=260)
        box.append(self.label)
        box.append(self.progress)
        self.set_child(box)
        self.source = 0

    def post(self, message, fraction=None):
        self.label.set_label(message)
        self.progress.set_visible(fraction is not None)
        if fraction is not None:
            self.progress.set_fraction(fraction)
        self.set_reveal_child(True)
        if self.source:
            GLib.source_remove(self.source)
        self.source = GLib.timeout_add(2600, self.dismiss)

    def dismiss(self):
        self.source = 0
        self.set_reveal_child(False)
        return False


class Splash(Gtk.Box):
    """"Opening <game>…" screen shown right after a launch."""

    def __init__(self):
        super().__init__(css_classes=["modal-scrim"], visible=False)
        self.source = 0

    def start(self, theme, entry, duration, on_done):
        px = theme.px
        clear(self)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=px(24), css_classes=["splash"],
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=True)
        if entry.poster:
            picture = SizedPicture(px(240), px(360))
            picture.set_halign(Gtk.Align.CENTER)
            load_picture(picture, entry.poster, px(240), px(360))
            box.append(picture)
        else:
            box.append(Gtk.Image(gicon=entry.icon))
        box.append(Gtk.Label(label=_("Opening {name}…").format(name=entry.name), css_classes=["splash-title"]))
        box.append(Adw.Spinner(halign=Gtk.Align.CENTER))
        self.append(box)
        self.set_visible(True)

        def done():
            self.source = 0
            self.set_visible(False)
            on_done()
            return False
        self.source = GLib.timeout_add(duration, done)

    def stop(self):
        if self.source:
            GLib.source_remove(self.source)
            self.source = 0
        self.set_visible(False)
