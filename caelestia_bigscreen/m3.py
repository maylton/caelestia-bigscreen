"""Material 3 controls following Caelestia Shell (StyledSlider, StyledProgressBar, SliderRow).

Geometry from components/controls/StyledSlider.qml and StyledProgressBar.qml:
filled part (primary) | gap | thin tall handle | gap | remaining track
(secondaryContainer) with a dot at the end. Caelestia tokens: extraSmall 4,
small 8, medium 12, all multiplied by the interface scale.
"""

from gi.repository import Adw, Gdk, GLib, GObject, Graphene, Gsk, Gtk

TRACK = 24  # padding.medium * 2, as in the settings SliderRow
RADIUS = 8  # rounding.small
GAP = 4  # spacing.extraSmall
HANDLE_WIDTH = 4
ROUND = 999  # fully rounded


def rgba(hex_colour, alpha=1.0):
    colour = Gdk.RGBA()
    colour.parse("#" + hex_colour)
    colour.alpha = alpha
    return colour


def draw_rect(snapshot, colour, x, y, w, h, tl, tr, br, bl):
    """Rectangle with a radius per corner (each radius is capped to the size)."""
    if w <= 0 or h <= 0:
        return
    limit = min(w, h) / 2
    rect = Graphene.Rect().init(x, y, w, h)

    def size(r):
        r = min(r, limit)
        return Graphene.Size().init(r, r)

    rounded = Gsk.RoundedRect()
    rounded.init(rect, size(tl), size(tr), size(br), size(bl))
    snapshot.push_rounded_clip(rounded)
    snapshot.append_color(colour, rect)
    snapshot.pop()


def lerp(a, b, t):
    return a + (b - a) * t


class M3Slider(Gtk.Widget):
    """Caelestia slider. Emits 'interaction'(value) only for user actions."""

    __gsignals__ = {"interaction": (GObject.SignalFlags.RUN_FIRST, None, (float,))}

    def __init__(self, theme, value=0.0, lower=0.0, upper=100.0, step=5.0):
        super().__init__(focusable=True, hexpand=True, valign=Gtk.Align.CENTER)
        self.theme = theme
        self.lower, self.upper, self.step = lower, upper, step
        self.value = self.clamp(value)
        self.pos = self.fraction(self.value)  # drawn position (animated)
        self.handle_t = 0.0  # 0 = resting, 1 = pressed or focused
        self.pressed = False
        self.drag_start = 0.0
        self.pos_animation = None
        self.handle_animation = None
        self.is_slider = True
        self.set_cursor_from_name("pointer")

        click = Gtk.GestureClick()
        click.connect("pressed", self.on_pressed)
        click.connect("released", self.on_released)
        click.connect("stopped", lambda *_: self.set_pressed(False))
        self.add_controller(click)
        drag = Gtk.GestureDrag()
        drag.connect("drag-update", self.on_drag_update)
        self.add_controller(drag)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self.on_scroll)
        self.add_controller(scroll)
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda *_: self.animate_handle())
        focus.connect("leave", lambda *_: self.animate_handle())
        self.add_controller(focus)

    # ---- Value --------------------------------------------------------------

    def clamp(self, value):
        return max(self.lower, min(self.upper, value))

    def fraction(self, value):
        span = self.upper - self.lower
        return (value - self.lower) / span if span else 0.0

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = self.clamp(value)
        self.animate_pos(self.fraction(self.value))

    def nudge(self, direction):
        self.set_value(self.value + direction * self.step)
        self.emit("interaction", self.value)

    def interact(self, fraction):
        self.value = self.clamp(self.lower + fraction * (self.upper - self.lower))
        self.emit("interaction", self.value)

    # ---- Animations -----------------------------------------------------------

    def animate(self, current, start, end, duration, setter, easing):
        if current:
            current.skip()
        animation = Adw.TimedAnimation.new(self, start, end, duration, Adw.CallbackAnimationTarget.new(setter))
        animation.set_easing(easing)
        animation.play()
        return animation

    def animate_pos(self, target):
        self.pos_animation = self.animate(self.pos_animation, self.pos, target, 300, self.set_pos,
                                          Adw.Easing.EASE_OUT_CUBIC)

    def set_pos(self, value):
        self.pos = value
        self.queue_draw()

    def animate_handle(self):
        target = 1.0 if (self.pressed or self.has_focus()) else 0.0
        self.handle_animation = self.animate(self.handle_animation, self.handle_t, target, 180, self.set_handle,
                                             Adw.Easing.EASE_OUT_BACK)

    def set_handle(self, value):
        self.handle_t = value
        self.queue_draw()

    # ---- Input ----------------------------------------------------------------

    def set_pressed(self, pressed):
        if self.pressed != pressed:
            self.pressed = pressed
            self.animate_handle()

    def on_pressed(self, _gesture, _n, _x, _y):
        self.grab_focus()
        self.set_pressed(True)
        self.drag_start = self.pos

    def on_released(self, _gesture, _n, x, _y):
        self.set_pressed(False)
        # A click without dragging jumps to the clicked position
        if abs(self.pos - self.drag_start) < 1e-6:
            fraction = max(0.0, min(1.0, x / self.get_width()))
            self.interact(fraction)
            self.animate_pos(fraction)

    def on_drag_update(self, _gesture, dx, _dy):
        if dx:
            if self.pos_animation:
                self.pos_animation.skip()
            self.set_pos(max(0.0, min(1.0, self.drag_start + dx / self.get_width())))
            self.interact(self.pos)

    def on_scroll(self, _ctl, _dx, dy):
        if dy:
            self.nudge(-1 if dy > 0 else 1)
        return True

    # ---- Drawing --------------------------------------------------------------

    def handle_heights(self):
        """Resting and pressed handle heights, as in StyledSlider."""
        h = self.theme.px(TRACK)
        t = max(0.0, min(1.0, (h - self.theme.px(12)) / self.theme.px(16)))
        return h * lerp(3, 1.2, t), h * lerp(3.5, 1.5, t)

    def do_measure(self, orientation, _for_size):
        px = self.theme.px
        if orientation == Gtk.Orientation.HORIZONTAL:
            return px(120), px(240), -1, -1
        tallest = round(self.handle_heights()[1])
        return tallest, tallest, -1, -1

    def do_snapshot(self, snapshot):
        px = self.theme.px
        colours = self.theme.colours
        enabled = self.is_sensitive()
        fg = rgba(colours["primary"]) if enabled else rgba(colours["onSurface"], 0.38)
        bg = rgba(colours["secondaryContainer"]) if enabled else rgba(colours["onSurface"], 0.1)
        width, cy = self.get_width(), self.get_height() / 2
        h, gap, handle_w, radius = px(TRACK), px(GAP), px(HANDLE_WIDTH), px(RADIUS)
        inner = gap / 2

        filled = (width - handle_w - gap) * max(0.0, min(1.0, self.pos))
        draw_rect(snapshot, fg, 0, cy - h / 2, filled, h, radius, inner, inner, radius)

        handle_x = filled + gap if filled > 0 else 0
        hh = lerp(*self.handle_heights(), self.handle_t)
        draw_rect(snapshot, fg, handle_x, cy - hh / 2, handle_w, hh, ROUND, ROUND, ROUND, ROUND)

        rem_x = handle_x + handle_w + gap
        rem_w = width - rem_x
        # The remaining track and its end dot fade out as the handle reaches the end
        opacity = max(0.0, min(rem_w, px(12)) / px(12))
        rem_h = h * (opacity if h <= px(12) else min(opacity * 2, 1))
        draw_rect(snapshot, bg, rem_x, cy - rem_h / 2, rem_w, rem_h, inner, radius, radius, inner)

        dot = px(4) * opacity
        if dot > 0:
            fg.alpha *= opacity
            draw_rect(snapshot, fg, width - dot * 2, cy - dot / 2, dot, dot, ROUND, ROUND, ROUND, ROUND)


class M3Progress(Gtk.Widget):
    """Determinate progress bar (StyledProgressBar, 4 px tall)."""

    def __init__(self, theme, fraction=0.0, width=160):
        super().__init__(valign=Gtk.Align.CENTER)
        self.theme = theme
        self.fraction = max(0.0, min(1.0, fraction))
        self.natural = width

    def set_fraction(self, fraction):
        self.fraction = max(0.0, min(1.0, fraction))
        self.queue_draw()

    def do_measure(self, orientation, _for_size):
        px = self.theme.px
        if orientation == Gtk.Orientation.HORIZONTAL:
            return px(40), px(self.natural), -1, -1
        return px(4), px(4), -1, -1

    def do_snapshot(self, snapshot):
        colours = self.theme.colours
        fg, bg = rgba(colours["primary"]), rgba(colours["secondaryContainer"])
        width, height = self.get_width(), self.get_height()
        filled = width * self.fraction
        draw_rect(snapshot, fg, 0, 0, filled, height, ROUND, ROUND, ROUND, ROUND)
        rem_x = filled + self.theme.px(GAP) if filled > 0 else 0
        draw_rect(snapshot, bg, rem_x, 0, width - rem_x, height, ROUND, ROUND, ROUND, ROUND)
        if self.fraction < 1:
            dot = self.theme.px(4)
            draw_rect(snapshot, fg, width - (height + dot) / 2, (height - dot) / 2, dot, dot,
                      ROUND, ROUND, ROUND, ROUND)


class SliderRow(Gtk.Box):
    """Slider row from Caelestia's settings (nexus/common/SliderRow.qml)."""

    def __init__(self, theme, icon, label, value, on_change, upper=100, key=None):
        super().__init__(spacing=theme.px(12), css_classes=["slider-row"])
        self.on_change = on_change
        self.pending = 0
        self.append(Gtk.Image(icon_name=icon, css_classes=["slider-icon"], valign=Gtk.Align.START))
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=theme.px(6), hexpand=True)
        top = Gtk.Box(spacing=theme.px(8))
        top.append(Gtk.Label(label=label, css_classes=["slider-label"], xalign=0, hexpand=True))
        self.value_label = Gtk.Label(label=f"{value:.0f}%", css_classes=["slider-value"])
        top.append(self.value_label)
        column.append(top)
        self.slider = M3Slider(theme, value, upper=upper)
        self.slider.row = self
        self.slider.nav_key = key
        self.slider.connect("interaction", self.changed)
        column.append(self.slider)
        self.append(column)
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda *_: self.add_css_class("focused"))
        focus.connect("leave", lambda *_: self.remove_css_class("focused"))
        self.slider.add_controller(focus)

    def set_value(self, value):
        """Updates from an external change, without calling on_change."""
        self.slider.set_value(value)
        self.value_label.set_label(f"{self.slider.get_value():.0f}%")

    def changed(self, _slider, value):
        self.value_label.set_label(f"{value:.0f}%")
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(60, self.commit)

    def commit(self):
        self.pending = 0
        self.on_change(self.slider.get_value())
        return False
