"""Full-screen background: the shell wallpaper or the focused game's artwork."""

from gi.repository import GLib, Gtk

from .widgets import FillPicture, load_texture_async


class Backdrop(Gtk.Overlay):
    def __init__(self):
        super().__init__()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=450)
        self.stack.add_named(Gtk.Box(), "none")
        self.set_child(self.stack)
        self.scrim = Gtk.Box(css_classes=["backdrop-scrim"], can_target=False)
        self.add_overlay(self.scrim)
        self.path = None
        self.width = 1920
        self.pending = 0

    def set_path(self, path, force=False):
        """Crossfades to the image at `path` (None = plain background)."""
        if path == self.path and not force:
            return
        self.path = path
        if self.pending:
            GLib.source_remove(self.pending)
        # Short delay: moving quickly across cards only loads the last one
        self.pending = GLib.timeout_add(160, self.load, path)

    def load(self, path):
        self.pending = 0
        (self.scrim.remove_css_class if path else self.scrim.add_css_class)("plain")
        if not path:
            self.stack.set_visible_child_name("none")
        else:
            load_texture_async(path, self.width, -1, lambda texture: self.reveal(path, texture))
        return False

    def reveal(self, path, texture):
        if path != self.path or texture is None:
            return
        old = self.stack.get_visible_child()
        picture = FillPicture()
        picture.set_paintable(texture)
        self.stack.add_child(picture)
        self.stack.set_visible_child(picture)
        if old is not self.stack.get_child_by_name("none"):
            GLib.timeout_add(600, self.drop, old)

    def drop(self, widget):
        if widget.get_parent() is self.stack:
            self.stack.remove(widget)
        return False
