"""Widgets designed for gamepads and TVs."""

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from .i18n import _

# ---- Images ---------------------------------------------------------------

_texture_cache = {}


def load_texture_async(path, width, height, callback):
    """Decodes and downscales an image off the main thread; callback(texture or None)."""
    key = (path, width, height)
    if key in _texture_cache:
        callback(_texture_cache[key])
        return
    file = Gio.File.new_for_path(path)

    def on_pixbuf(_src, result):
        try:
            texture = Gdk.Texture.new_for_pixbuf(GdkPixbuf.Pixbuf.new_from_stream_finish(result))
        except GLib.Error:
            callback(None)
            return
        if len(_texture_cache) > 400:
            _texture_cache.clear()
        _texture_cache[key] = texture
        callback(texture)

    def on_read(_file, result):
        try:
            stream = file.read_finish(result)
        except GLib.Error:
            callback(None)
            return
        GdkPixbuf.Pixbuf.new_from_stream_at_scale_async(stream, width, height, True, None, on_pixbuf)

    file.read_async(GLib.PRIORITY_DEFAULT, None, on_read)


class SizedPicture(Gtk.Picture):
    """Picture with a fixed size (its natural size would be the image size)."""

    def __init__(self, width, height, fit=Gtk.ContentFit.COVER):
        super().__init__(content_fit=fit, can_shrink=True)
        self.size = (width, height)

    def do_measure(self, orientation, _for_size):
        value = self.size[0] if orientation == Gtk.Orientation.HORIZONTAL else self.size[1]
        return value, value, -1, -1


class FillPicture(Gtk.Picture):
    """Picture that fills the available space without requesting any."""

    def __init__(self):
        super().__init__(content_fit=Gtk.ContentFit.COVER, can_shrink=True, hexpand=True, vexpand=True)

    def do_measure(self, _orientation, _for_size):
        return 0, 0, -1, -1


def load_picture(picture, path, width, height):
    load_texture_async(path, width, height, lambda texture: texture and picture.set_paintable(texture))


# ---- Layout helpers -----------------------------------------------------------

def scroller(child, horizontal):
    """ScrolledWindow without visible scrollbars; nav.ensure_visible follows the focus."""
    viewport = Gtk.Viewport(scroll_to_focus=False, child=child)
    sw = Gtk.ScrolledWindow(child=viewport)
    if horizontal:
        sw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
    else:
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL)
        sw.set_vexpand(True)
    return sw


def clear(box):
    while child := box.get_first_child():
        box.remove(child)


def on_focus(widget, enter, leave=None):
    controller = Gtk.EventControllerFocus()
    controller.connect("enter", lambda *_: enter())
    if leave:
        controller.connect("leave", lambda *_: leave())
    widget.add_controller(controller)


def set_context(widget, callback):
    """Secondary action: X/Select on the gamepad, Menu key or right click."""
    widget.context_action = callback
    click = Gtk.GestureClick(button=3)
    click.connect("pressed", lambda *_: callback())
    widget.add_controller(click)


def group_title(text):
    return Gtk.Label(label=text, css_classes=["group-title"], xalign=0)


def pill(label, callback, *classes, icon=None):
    button = Gtk.Button(css_classes=["pill", *classes])
    if icon:
        box = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        box.append(Gtk.Image(icon_name=icon))
        box.append(Gtk.Label(label=label))
        button.set_child(box)
    else:
        button.set_label(label)
    button.connect("clicked", lambda *_: callback())
    return button


# ---- Cards ------------------------------------------------------------------

class Card(Gtk.Box):
    """Game/app card: the artwork is the focusable button, the name sits below."""

    def __init__(self, app, entry, style="tile", on_activate=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.START, valign=Gtk.Align.START)
        px = app.theme.px
        poster = style == "poster"
        width, height = (px(210), px(315)) if poster else (px(190), px(190))

        button = Gtk.Button(css_classes=["card", style], overflow=Gtk.Overflow.HIDDEN)
        overlay = Gtk.Overlay()
        button.set_child(overlay)
        if poster and entry.poster:
            picture = SizedPicture(width, height)
            load_picture(picture, entry.poster, round(width * 1.1), round(height * 1.1))
            overlay.set_child(picture)
        elif poster:
            fallback = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card-fallback"], spacing=px(10))
            fallback.set_size_request(width, height)
            fallback.append(Gtk.Image(gicon=entry.icon, pixel_size=px(96), vexpand=True, valign=Gtk.Align.END))
            fallback.append(Gtk.Label(label=entry.name, wrap=True, justify=Gtk.Justification.CENTER,
                                      vexpand=True, valign=Gtk.Align.START, max_width_chars=12))
            overlay.set_child(fallback)
        else:
            image = Gtk.Image(gicon=entry.icon)  # Gtk.Image centers the icon in its area
            image.set_size_request(width, height)
            overlay.set_child(image)
        if entry.id in app.config["favorites"]:
            overlay.add_overlay(Gtk.Image(icon_name="starred-symbolic", css_classes=["badge"],
                                          halign=Gtk.Align.END, valign=Gtk.Align.START))

        label = Gtk.Label(label=entry.name, css_classes=["card-label"], ellipsize=Pango.EllipsizeMode.END,
                          max_width_chars=1, xalign=0.5)
        label.set_size_request(width, -1)
        self.append(button)
        self.append(label)

        button.connect("clicked", lambda *_: (on_activate or app.launch)(entry))
        set_context(button, lambda: app.dialogs.entry_menu(entry))
        on_focus(button,
                 lambda: (label.add_css_class("focused"), app.on_entry_focus(entry)),
                 lambda: label.remove_css_class("focused"))


class ActionCard(Gtk.Box):
    """Card for actions such as "All apps" or a settings shortcut."""

    def __init__(self, app, icon, title, callback, style="system"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.START, valign=Gtk.Align.START)
        px = app.theme.px
        button = Gtk.Button(css_classes=["card", style])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=px(8),
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        if style == "tile":
            box.set_size_request(px(190), px(190))
            box.set_valign(Gtk.Align.FILL)
            box.append(Gtk.Image(icon_name=icon, vexpand=True))
        else:
            box.set_size_request(px(230), px(120))
            box.append(Gtk.Image(icon_name=icon))
            box.append(Gtk.Label(label=title))
        button.set_child(box)
        button.connect("clicked", lambda *_: callback())
        on_focus(button, app.show_default_backdrop)
        self.append(button)
        if style == "tile":
            self.append(Gtk.Label(label=title, css_classes=["card-label"]))


def strip(app, title, widgets):
    """Titled horizontal row, console style."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.append(Gtk.Label(label=title, css_classes=["row-title"], xalign=0))
    row = Gtk.Box(spacing=app.theme.px(30), css_classes=["row-strip"])
    for widget in widgets:
        row.append(widget)
    box.append(scroller(row, horizontal=True))
    return box


# ---- Settings rows ---------------------------------------------------------

class SettingRow(Gtk.Button):
    def __init__(self, title, subtitle=None, icon=None, end=None, callback=None, key=None, gicon=None):
        super().__init__(css_classes=["setting"])
        self.nav_key = key or title
        box = Gtk.Box(spacing=18)
        if gicon:
            box.append(Gtk.Image(gicon=gicon, css_classes=["lead"]))
        elif icon:
            box.append(Gtk.Image(icon_name=icon, css_classes=["lead"]))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        text.append(Gtk.Label(label=title, xalign=0, css_classes=["setting-title"], ellipsize=Pango.EllipsizeMode.END,
                              max_width_chars=36))
        if subtitle:
            text.append(Gtk.Label(label=subtitle, xalign=0, css_classes=["setting-sub"], wrap=True))
        box.append(text)
        if end:
            end.set_valign(Gtk.Align.CENTER)
            box.append(end)
        self.set_child(box)
        if callback:
            self.connect("clicked", lambda *_: callback())


class SwitchRow(SettingRow):
    def __init__(self, title, subtitle, active, on_toggle, icon=None):
        switch = Gtk.Switch(active=active, can_focus=False, can_target=False)
        super().__init__(title, subtitle, icon, switch)
        self.connect("clicked", lambda *_: (switch.set_active(not switch.get_active()), on_toggle(switch.get_active())))


def check_icon(visible):
    return Gtk.Image(icon_name="object-select-symbolic", css_classes=["check"], opacity=1 if visible else 0)


# ---- On-screen keyboard -------------------------------------------------------

OSK_ROWS = [
    ("1234567890", "!@#$%&*()_"),
    ("qwertyuiop", "QWERTYUIOP"),
    ("asdfghjklç", "ASDFGHJKLÇ"),
    ("zxcvbnm,.-", "ZXCVBNM;:?"),
]


class OnScreenKeyboard(Gtk.Box):
    """Gamepad-friendly keyboard: X deletes, Y types a space, LB toggles shift, Start submits."""

    def __init__(self, app, entry, on_submit, submit_label):
        spacing = app.theme.px(10)
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=spacing, halign=Gtk.Align.CENTER)
        self.entry, self.on_submit = entry, on_submit
        self.shift = False
        self.keys = []
        for lower, upper in OSK_ROWS:
            row = Gtk.Box(spacing=spacing, halign=Gtk.Align.CENTER)
            for chars in zip(lower, upper):
                key = Gtk.Button(label=chars[0], css_classes=["key"])
                key.chars = chars
                key.connect("clicked", self.on_key)
                self.keys.append(key)
                row.append(key)
            self.append(row)
        bottom = Gtk.Box(spacing=spacing, halign=Gtk.Align.CENTER)
        self.shift_key = self.special("⇧", self.toggle_shift, "wide")
        for key in (self.shift_key,
                    self.special("@", lambda: self.type("@")),
                    self.special(_("Space"), lambda: self.type(" "), "space"),
                    self.special("⌫", self.backspace, "wide"),
                    self.special(submit_label, self.submit, "wide", "accent")):
            bottom.append(key)
        self.append(bottom)

    @staticmethod
    def special(label, callback, *classes):
        key = Gtk.Button(label=label, css_classes=["key", *classes])
        key.connect("clicked", lambda *_: callback())
        return key

    def on_key(self, key):
        self.type(key.chars[self.shift])
        if self.shift:
            self.toggle_shift()

    def type(self, text):
        self.entry.insert_text(text, len(self.entry.get_text()))
        self.entry.set_position(-1)

    def backspace(self):
        length = len(self.entry.get_text())
        if length:
            self.entry.delete_text(length - 1, length)

    def toggle_shift(self):
        self.shift = not self.shift
        for key in self.keys:
            key.set_label(key.chars[self.shift])
        (self.shift_key.add_css_class if self.shift else self.shift_key.remove_css_class)("on")

    def submit(self):
        self.on_submit(self.entry.get_text())

    def handle_button(self, name):
        actions = {"x": self.backspace, "y": lambda: self.type(" "), "lb": self.toggle_shift, "start": self.submit}
        if name in actions:
            actions[name]()
            return True
        return False

    def handle_key(self, keyval, state):
        """A physical keyboard types straight into the field."""
        if keyval == Gdk.KEY_BackSpace:
            self.backspace()
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.submit()
        elif (char := Gdk.keyval_to_unicode(keyval)) >= 32 and not state & (
                Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            self.type(chr(char))
        else:
            return False
        return True
