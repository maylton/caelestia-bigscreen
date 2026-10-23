"""Application: window, states (hidden, front, behind games), input routing and launching."""

import os

import gi
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import APP_ID, APP_NAME, i18n, nav
from .backdrop import Backdrop
from .config import Config
from .dialogs import Dialogs, Splash, Toast
from .gamepad import GamepadManager
from .header import TABS, Header
from .i18n import _
from .library import SHELL_CONFIG, Library, launch
from .pages.home import GridPage, HomePage
from .pages.quickmenu import QuickMenu
from .pages.settings import SettingsPage
from .session import GameSession
from .system import Audio, Hyprland, Power
from .theme import Theme, shell_wallpaper
from .widgets import clear

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LayerShell
except (ValueError, ImportError):
    LayerShell = None

OPTIONS = [
    ("daemon", "Stay in the background waiting for the gamepad Guide button"),
    ("session", "Run as the main interface of the Big Screen session (never hides)"),
    ("toggle", "Show or hide Big Screen"),
    ("quick", "Open the quick menu"),
    ("settings", "Open the settings"),
    ("hide", "Hide Big Screen"),
    ("quit", "Quit Big Screen"),
]

HINT_GLYPHS = {
    "xbox": {"a": "A", "b": "B", "x": "X", "y": "Y"},
    "ps": {"a": "✕", "b": "○", "x": "□", "y": "△"},
}

ARROWS = {Gdk.KEY_Up: "up", Gdk.KEY_Down: "down", Gdk.KEY_Left: "left", Gdk.KEY_Right: "right"}


class BigScreenApp(Adw.Application):
    def __init__(self):
        # Automated tests use another ID so they never talk to the real daemon
        test = bool(os.environ.get("BIGSCREEN_TEST"))
        super().__init__(application_id=APP_ID + (".Test" if test else ""),
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        for name, description in OPTIONS:
            self.add_main_option(name, 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, description, None)
        self.add_main_option("launch", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Launch a library entry, e.g. steam:35700 or desktop:firefox.desktop", "ID")
        self.test = test
        self.win = None
        self.visible = False  # in front and receiving input
        self.state = "hidden"  # hidden | front | back
        self.mode = "home"  # home | quick (quick menu over a game)
        self.session_mode = False
        self.quick_open = False
        self.home_dirty = False
        self.library_dirty = False
        self.built_scale = None
        self.monitor = None
        self.status_source = 0
        self.last_focus = {}
        self.current_tab = "home"

    # ---- Lifecycle ----------------------------------------------------------

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        self.config = Config()
        i18n.setup(self.config["language"])
        self.library = Library(self.config)
        self.theme = Theme(self.config, on_change=self.show_default_backdrop)
        self.gamepads = GamepadManager(combo=self.config["select_start_combo"])
        self.gamepads.connect("nav", lambda _m, direction: self.navigate(direction))
        self.gamepads.connect("button", self.on_pad_button)
        self.gamepads.connect("home", lambda _m: self.config["guide_button"] and self.toggle())
        self.gamepads.connect("devices-changed", self.on_pads_changed)
        self.session = GameSession()
        self.session.connect("started", self.on_game_started)
        self.session.connect("ended", self.on_game_ended)
        self.session.connect("fullscreen", self.on_fullscreen_window)
        # Apps hidden in the Caelestia launcher are hidden here too
        self.shell_monitor = Gio.File.new_for_path(str(SHELL_CONFIG)).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.shell_monitor.connect("changed", self.on_shell_config_changed)
        self.hold()
        self.monitor = self.pick_monitor()
        self.theme.apply(self.monitor)
        self.build_window()

    def do_command_line(self, command_line):
        options = command_line.get_options_dict().end().unpack()
        if options.get("session"):
            self.session_mode = True
            self.show_home()
        elif options.get("quit"):
            self.quit()
        elif options.get("launch"):
            entry = self.library.get(options["launch"])
            if entry is None:
                command_line.printerr(f"Not in the library: {options['launch']}\n")
                return 1
            self.show_home()
            self.launch(entry)
        elif options.get("hide"):
            self.hide_ui()
        elif options.get("toggle"):
            self.toggle()
        elif options.get("quick"):
            self.show_quick()
        elif options.get("settings"):
            self.open_settings("audio")
        elif not options.get("daemon"):
            self.show_home()
        return 0

    # ---- Window ---------------------------------------------------------------

    def build_window(self):
        win = Gtk.ApplicationWindow(application=self, title=APP_NAME, css_classes=["bigscreen"], decorated=False)
        win.connect("close-request", lambda *_: self.hide_ui() or True)
        self.layer = bool(LayerShell and LayerShell.is_supported())
        if self.layer:
            LayerShell.init_for_window(win)
            LayerShell.set_namespace(win, "caelestia-bigscreen")
            for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
                LayerShell.set_anchor(win, edge, True)
            LayerShell.set_exclusive_zone(win, -1)
            # Tests must not steal the keyboard from whoever is using the computer
            self.front_keyboard = (LayerShell.KeyboardMode.ON_DEMAND if self.test
                                   else LayerShell.KeyboardMode.EXCLUSIVE)
        self.win = win

        root = Gtk.Overlay()
        win.set_child(root)
        self.backdrop = Backdrop()
        root.set_child(self.backdrop)

        self.main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_overlay(self.main)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=180,
                               vexpand=True)
        self.hints = Gtk.Box(spacing=18, css_classes=["hints"], halign=Gtk.Align.END)

        self.quick_scrim = Gtk.Box(css_classes=["quick-scrim"], visible=False)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_: self.back())
        self.quick_scrim.add_controller(click)
        root.add_overlay(self.quick_scrim)
        self.quick_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT,
                                           transition_duration=220, halign=Gtk.Align.START)
        self.quick_revealer.connect("notify::child-revealed", self.on_quick_revealed)
        root.add_overlay(self.quick_revealer)

        self.dialogs = Dialogs(self)
        root.add_overlay(self.dialogs.layer)
        self.splash = Splash()
        root.add_overlay(self.splash)
        self.toast_widget = Toast(self.theme)
        root.add_overlay(self.toast_widget)

        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)
        win.connect("notify::focus-widget", self.on_focus_changed)

        self.build_ui()
        self.show_default_backdrop()

    def build_ui(self):
        """(Re)creates everything that depends on the scale or the language."""
        clear(self.main)
        self.header = Header(self)
        for widget in (self.header, self.stack, self.hints):
            self.main.append(widget)
        while child := self.stack.get_first_child():
            self.stack.remove(child)
        self.home = HomePage(self)
        self.games = GridPage(self, _("Games"), lambda: self.library.games() + self.library.launchers(), "poster",
                              _("No games found."))
        self.apps = GridPage(self, _("Apps"), self.library.apps, "tile", _("No apps found."))
        self.settings = SettingsPage(self)
        for key, page in zip((k for k, _label in TABS), (self.home, self.games, self.apps, self.settings)):
            self.stack.add_named(page, key)
        self.quick = QuickMenu(self)
        self.quick_revealer.set_child(self.quick)
        self.last_focus.clear()
        self.built_scale = self.theme.scale
        self.home_dirty = False
        self.go_tab(self.current_tab, focus=False)
        self.update_hints()

    def rebuild_ui(self, settings_section=None):
        i18n.setup(self.config["language"])
        self.theme.apply(self.monitor)
        self.build_ui()
        self.header.update()
        if settings_section:
            self.open_settings(settings_section)

    # ---- Monitors -------------------------------------------------------------

    def list_monitors(self):
        monitors = Gdk.Display.get_default().get_monitors()
        return [monitors.get_item(i) for i in range(monitors.get_n_items())]

    def pick_monitor(self):
        monitors = self.list_monitors()
        wanted = self.config["monitor"]
        if wanted == "auto" and Hyprland.available:
            wanted = next((m["name"] for m in Hyprland.monitors() if m.get("focused")), wanted)
        return next((m for m in monitors if m.get_connector() == wanted), monitors[0] if monitors else None)

    # ---- States: hidden, in front (interactive) and behind the windows ---------

    def set_front(self, front):
        """Front: overlay layer with the keyboard. Back: bottom layer, below games."""
        if not self.layer:
            return
        LayerShell.set_layer(self.win, LayerShell.Layer.OVERLAY if front else LayerShell.Layer.BOTTOM)
        LayerShell.set_keyboard_mode(self.win, self.front_keyboard if front else LayerShell.KeyboardMode.NONE)
        self.session.background = not front

    def set_content_visible(self, visible):
        self.main.set_visible(visible)
        self.backdrop.set_visible(visible)

    def prepare_map(self):
        """Picks the monitor and scale before the window is mapped."""
        self.monitor = self.pick_monitor()
        self.theme.apply(self.monitor)
        if self.monitor:
            self.backdrop.width = self.monitor.get_geometry().width
        if self.built_scale != self.theme.scale:
            self.build_ui()
        if self.layer:
            LayerShell.set_monitor(self.win, self.monitor)

    def bring_front(self):
        if not self.win.get_visible():
            self.prepare_map()
        if self.library_dirty:
            self.library_changed()
        elif self.home_dirty:
            self.home.rebuild()
        self.home_dirty = self.library_dirty = False
        self.set_front(True)
        self.header.update()
        if not self.status_source:
            self.status_source = GLib.timeout_add_seconds(10, self.on_status_tick)
        self.gamepads.set_active(True)
        self.visible = True
        self.state = "front"
        if self.win.get_visible():
            return
        if not self.layer and self.monitor:
            self.win.fullscreen_on_monitor(self.monitor)
        self.win.present()

    def show_home(self):
        self.bring_front()
        self.mode = "home"
        self.close_quick(animate=False)
        self.set_content_visible(True)
        GLib.idle_add(self.restore_focus)

    def show_quick(self):
        if not self.visible:
            self.bring_front()
            self.mode = "quick"
            self.set_content_visible(False)
        self.open_quick()

    def leave_front(self):
        """Closes dialogs and the quick menu and stops taking input."""
        self.splash.stop()
        self.dialogs.close_all()
        self.close_quick(animate=False)
        self.visible = False
        self.gamepads.set_active(False)
        if self.status_source:
            GLib.source_remove(self.status_source)
            self.status_source = 0

    def hide_ui(self):
        """Hides completely (desktop use). The Big Screen session never hides: it goes behind the windows."""
        if self.session_mode:
            if self.session.tracked or Hyprland.clients():
                self.go_background()
            return
        self.leave_front()
        self.state = "hidden"
        self.session.reset()
        self.session.background = False
        self.win.set_visible(False)

    def go_background(self):
        """Sits behind the windows showing Home, like a console home screen."""
        if not self.layer:
            self.hide_ui()
            return
        self.leave_front()
        self.mode = "home"
        self.set_content_visible(True)
        self.state = "back"
        self.set_front(False)
        if not self.win.get_visible():
            self.prepare_map()
            self.win.present()

    def leave(self):
        """Guide/Back: returns to the game (Big Screen stays behind) or hides on the desktop."""
        if self.session.tracked:
            self.go_background()
        else:
            self.hide_ui()

    def toggle(self):
        if self.visible:
            self.leave()
        elif self.state == "back" or self.over_fullscreen_app():
            self.show_quick()
        else:
            self.show_home()

    def over_fullscreen_app(self):
        if not Hyprland.available:
            return False
        active = Hyprland.active_window()
        window_class = (active.get("class") or "").lower()
        return bool(active.get("fullscreen")) or window_class.startswith("steam_app_") or window_class == "gamescope"

    # ---- Game session -----------------------------------------------------------

    def on_game_started(self, _session, address):
        if self.state == "front":
            self.go_background()
            Hyprland.focus("0x" + address)

    def on_game_ended(self, _session):
        if self.config["return_on_exit"]:
            self.show_home()
            if self.session.pending:
                self.toast(_("Opening {name}… it shows up when ready").format(name=self.session.pending["entry"].name))

    def on_fullscreen_window(self, _session, address):
        """A game went fullscreen while Big Screen is in front: get out of its way."""
        if self.state == "front":
            self.session.follow(address)
            self.go_background()
            Hyprland.focus("0x" + address)

    # ---- Quick menu ---------------------------------------------------------------

    def open_quick(self):
        self.quick.rebuild()
        self.quick_open = True
        self.quick_scrim.set_visible(True)
        self.quick_revealer.set_reveal_child(True)
        self.update_hints()

    def close_quick(self, animate=True):
        if not self.quick_open:
            return
        self.quick_open = False
        # If the focus stays inside the panel while it hides, GTK moves it to the first
        # header tab, which would switch to Home over whatever was chosen in the menu
        current = self.win.get_focus()
        if current is not None and current.is_ancestor(self.quick):
            self.win.set_focus(None)
        self.quick_scrim.set_visible(False)
        self.quick_revealer.set_transition_duration(220 if animate else 0)
        self.quick_revealer.set_reveal_child(False)
        self.update_hints()
        if self.mode == "home" and self.visible:
            GLib.idle_add(self.restore_focus)

    def on_quick_revealed(self, revealer, _pspec):
        revealer.set_transition_duration(220)
        # Only focusable once the panel is actually on screen
        if revealer.get_child_revealed() and self.quick_open and not self.dialogs:
            current = self.win.get_focus()
            if current is None or not current.is_ancestor(self.quick):
                nav.focus(nav.first_candidate(self.quick))

    # ---- Tabs and focus -------------------------------------------------------------

    def go_tab(self, key, focus=True):
        if key != self.current_tab:
            self.current_tab = key
            self.stack.set_visible_child_name(key)
        self.header.set_active(key)
        if key != "home":
            self.show_default_backdrop()
        if focus:
            GLib.idle_add(self.restore_focus)

    def cycle_tab(self, delta):
        keys = [k for k, _label in TABS]
        self.go_tab(keys[(keys.index(self.current_tab) + delta) % len(keys)])

    def open_settings(self, section):
        if self.mode == "quick" or not self.visible:
            self.show_home()
        self.close_quick(animate=False)
        self.dialogs.close_all()
        self.go_tab("settings", focus=False)
        self.settings.show(section, focus_content=True)

    def on_focus_changed(self, win, _pspec):
        widget = win.get_focus()
        if widget is None:
            return
        # Moving the focus across the tabs or the settings sidebar already switches the page
        if tab := getattr(widget, "tab_key", None):
            self.go_tab(tab, focus=False)
        elif section := getattr(widget, "section_key", None):
            self.settings.show(section)
        page = self.stack.get_visible_child()
        if page and widget.is_ancestor(page):
            self.last_focus[self.current_tab] = widget

    def restore_focus(self):
        if self.dialogs or self.quick_open or not self.visible:
            return False
        page = self.stack.get_visible_child()
        widget = self.last_focus.get(self.current_tab)
        if widget and widget.get_mapped() and page and widget.is_ancestor(page):
            nav.focus(widget)
        elif page:
            nav.focus(nav.first_candidate(page))
        return False

    def preserve_focus(self, container, build):
        """Rebuilds `container` and puts the focus back on the item with the same nav_key."""
        current = self.win.get_focus()
        inside = current is not None and current.is_ancestor(container)
        key = None
        while inside and current is not None and key is None:
            key = getattr(current, "nav_key", None)
            current = current.get_parent()
        build()
        if inside:
            candidates = nav.collect(container)
            target = next((w for w in candidates if key is not None and getattr(w, "nav_key", None) == key), None)
            nav.focus(target or next(iter(candidates), None))
        return False

    def nav_root(self):
        if self.dialogs:
            return self.dialogs.top["widget"]
        return self.quick if self.quick_open else self.main

    def navigate(self, direction):
        if not self.visible or self.splash.get_visible():
            return
        root = self.nav_root()
        current = self.win.get_focus()
        # From the settings sidebar, right enters the section content
        if (root is self.main and self.current_tab == "settings" and direction == "right"
                and current is not None and current.is_ancestor(self.settings.sidebar)):
            self.settings.focus_content()
            return
        nav.navigate(self.win, root, direction, tolerance=self.theme.px(24))

    def activate_focus(self):
        widget = nav.focused_candidate(self.win)
        if widget is None:
            self.navigate("down")
        elif isinstance(widget, Gtk.Button):
            widget.activate()

    def context_action(self):
        widget = self.win.get_focus()
        while widget is not None and not hasattr(widget, "context_action"):
            widget = widget.get_parent()
        if widget is not None:
            widget.context_action()

    def back(self):
        if self.dialogs:
            self.dialogs.close(cancelled=True)
        elif self.quick_open:
            self.leave() if self.mode == "quick" else self.close_quick()
        elif self.current_tab == "settings" and self.settings.in_content(self.win.get_focus()):
            self.settings.focus_sidebar()
        elif self.current_tab != "home":
            self.go_tab("home")
        elif (current := self.win.get_focus()) is not None and current.is_ancestor(self.stack):
            self.header.tabs["home"].grab_focus()
        else:
            nav.focus(nav.first_candidate(self.home))

    # ---- Input --------------------------------------------------------------------

    def on_pad_button(self, _manager, name):
        if not self.visible or self.splash.get_visible():
            return
        keyboard = self.dialogs.keyboard
        if keyboard and keyboard.handle_button(name):
            return
        if name == "a":
            self.activate_focus()
        elif name == "b":
            self.back()
        elif name in ("x", "select"):
            self.context_action()
        elif name in ("lt", "rt"):
            self.nudge_volume(-5 if name == "lt" else 5)
        elif self.dialogs:
            return
        elif name == "y":
            self.dialogs.search()
        elif name in ("lb", "rb") and not self.quick_open:
            self.cycle_tab(-1 if name == "lb" else 1)
        elif name == "start":
            self.back() if self.quick_open else self.open_quick()

    def on_key(self, _ctl, keyval, _keycode, state):
        if self.splash.get_visible():
            return True
        keyboard = self.dialogs.keyboard
        if keyboard and keyboard.handle_key(keyval, state):
            return True
        if keyval in ARROWS:
            self.navigate(ARROWS[keyval])
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.activate_focus()
        elif keyval in (Gdk.KEY_Escape, Gdk.KEY_BackSpace):
            self.back()
        elif keyval == Gdk.KEY_Menu:
            self.context_action()
        elif self.dialogs:
            return False
        elif keyval in (Gdk.KEY_Page_Up, Gdk.KEY_Page_Down) and not self.quick_open:
            self.cycle_tab(-1 if keyval == Gdk.KEY_Page_Up else 1)
        elif keyval == Gdk.KEY_F1:
            self.back() if self.quick_open else self.open_quick()
        elif (char := Gdk.keyval_to_unicode(keyval)) > 32 and not state & (
                Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            # Typing anywhere starts a search
            self.dialogs.search(chr(char))
        else:
            return False
        return True

    def on_pads_changed(self, _manager):
        self.update_hints()
        if self.visible:
            self.header.update()
            if self.current_tab == "settings" and self.settings.current == "controllers":
                self.settings.refresh_current()

    def update_hints(self):
        clear(self.hints)
        names = " ".join(self.gamepads.names()).lower()
        style = "ps" if any(k in names for k in ("sony", "dualsense", "dualshock", "playstation")) else "xbox"
        glyphs = HINT_GLYPHS[style]
        if self.dialogs.keyboard:
            items = [("a", _("Type")), ("x", _("Delete")), ("y", _("Space")), ("LB", _("Shift")),
                     ("☰", _("OK")), ("b", _("Cancel"))]
        elif self.dialogs:
            items = [("a", _("Select")), ("b", _("Cancel"))]
        else:
            items = [("a", _("Select")), ("b", _("Back")), ("x", _("Options")), ("y", _("Search"))]
            if not self.quick_open:
                items.append(("LB RB", _("Tabs")))
        for key, text in items:
            box = Gtk.Box(spacing=8)
            box.append(Gtk.Label(label=glyphs.get(key, key), css_classes=["hint-key"]))
            box.append(Gtk.Label(label=text))
            self.hints.append(box)

    # ---- Status, volume and background --------------------------------------------

    def on_status_tick(self):
        if not self.visible:
            self.status_source = 0
            return False
        self.header.update()
        return True

    def nudge_volume(self, delta):
        default = Audio.default() if Audio.available else None
        if not default:
            return
        value = max(0, min(150, default["volume"] + delta))
        Audio.set_volume(value)
        self.header.set_volume(value)
        self.toast(_("Volume {value}%").format(value=value), value / 150)
        # Volume sliders on screen (Sound settings, quick menu) follow the change
        for widget in nav.collect(self.win.get_child()):
            if getattr(widget, "nav_key", None) == "volume":
                widget.row.set_value(value)

    def show_default_backdrop(self):
        self.backdrop.set_path(shell_wallpaper() if self.config["show_wallpaper"] else None, force=True)

    def on_entry_focus(self, entry):
        if self.config["game_backdrop"] and entry.hero:
            self.backdrop.set_path(entry.hero)
        else:
            self.backdrop.set_path(shell_wallpaper() if self.config["show_wallpaper"] else None)

    def apply_theme(self):
        self.theme.apply()
        self.show_default_backdrop()

    def toast(self, message, fraction=None):
        self.toast_widget.post(message, fraction)

    # ---- Library and launching ------------------------------------------------------

    def reload_library(self):
        self.library.reload()
        self.library_changed()

    def on_shell_config_changed(self, _monitor, _file, _other, event):
        if event in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            # Rebuilding in front of the user would move the focus; do it when hidden
            if self.visible:
                self.library_dirty = True
            else:
                self.library_changed()

    def library_changed(self):
        for page in (self.home, self.games, self.apps):
            page.rebuild()

    def launch(self, entry):
        error = launch(entry, self.win.get_display())
        if error:
            self.toast(_("Could not open: {error}").format(error=error))
            return
        self.config.push_recent(entry.id)
        self.home_dirty = True
        self.session.launched(entry)
        self.dialogs.close_all()
        self.close_quick(animate=False)
        self.splash.start(self.theme, entry, 2600 if entry.source == "steam" else 1600, self.after_splash)

    def after_splash(self):
        if not self.session.available:
            # Without compositor events there is no way to know when the window opens
            self.go_background()
        elif self.session.pending and self.state == "front":
            # The game window is not there yet (Steam may take a while): wait on Home
            self.home.rebuild()
            self.home_dirty = False
            self.restore_focus()
            self.toast(_("Opening {name}… it shows up when ready").format(name=self.session.pending["entry"].name))

    def power_action(self, action):
        self.dialogs.close_all()
        if action == "suspend":
            if not self.session_mode:
                self.hide_ui()
            Power.suspend()
        elif action == "logout":
            self.dialogs.confirm(_("Log out?"), _("Open games and apps will be closed."), _("Log out"),
                                 Hyprland.exit, True)
        elif action == "reboot":
            self.dialogs.confirm(_("Restart the computer?"), None, _("Restart"), Power.reboot, True)
        elif action == "poweroff":
            self.dialogs.confirm(_("Shut down the computer?"), None, _("Shut down"), Power.poweroff, True)
