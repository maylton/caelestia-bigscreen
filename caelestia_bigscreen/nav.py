"""Spatial (TV-style) navigation and smooth scrolling that follows the focus.

Instead of GTK's focus chain, the next widget is picked by its real position on
screen: first the nearest "row" in the requested direction, then the item best
aligned with the current one.
"""

from gi.repository import Adw, Gtk

VERTICAL = ("up", "down")


def is_candidate(widget):
    return (
        (isinstance(widget, Gtk.Button) or getattr(widget, "is_slider", False))
        and widget.get_focusable()
        and widget.get_can_focus()
        and widget.is_sensitive()
    )


def collect(root, out=None):
    out = [] if out is None else out
    child = root.get_first_child()
    while child:
        if child.get_mapped() and child.get_child_visible():
            if is_candidate(child):
                out.append(child)
            else:
                collect(child, out)
        child = child.get_next_sibling()
    return out


def first_candidate(root):
    return next(iter(collect(root)), None)


def focused_candidate(window):
    widget = window.get_focus()
    while widget is not None and not is_candidate(widget):
        widget = widget.get_parent()
    return widget


def focus(widget):
    if widget:
        widget.grab_focus()
        ensure_visible(widget)
    return widget


def rect(widget, relative):
    ok, bounds = widget.compute_bounds(relative)
    if not ok:
        return None
    x, y = bounds.get_x(), bounds.get_y()
    return x, y, x + bounds.get_width(), y + bounds.get_height()


def pick(window, current, candidates, direction, tolerance):
    cur = rect(current, window)
    if not cur:
        return None
    fx1, fy1, fx2, fy2 = cur
    fcx, fcy = (fx1 + fx2) / 2, (fy1 + fy2) / 2
    scored = []
    for widget in candidates:
        r = rect(widget, window) if widget is not current else None
        if not r:
            continue
        x1, y1, x2, y2 = r
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if direction == "right":
            valid, distance = cx > fcx + 1 and x1 > fx1, x1 - fx2
        elif direction == "left":
            valid, distance = cx < fcx - 1 and x2 < fx2, fx1 - x2
        elif direction == "down":
            valid, distance = cy > fcy + 1 and y1 > fy1, y1 - fy2
        else:
            valid, distance = cy < fcy - 1 and y2 < fy2, fy1 - y2
        if not valid:
            continue
        if direction in VERTICAL:
            gap, offset = max(0.0, max(x1, fx1) - min(x2, fx2)), abs(cx - fcx)
        else:
            gap, offset = max(0.0, max(y1, fy1) - min(y2, fy2)), abs(cy - fcy)
        scored.append((max(0.0, distance), gap, offset, widget))
    if direction not in VERTICAL:
        aligned = [s for s in scored if s[1] == 0]
        # In card rows, reaching the end does not jump to another row
        if aligned or current.has_css_class("card"):
            scored = aligned
    if not scored:
        return None
    nearest = min(s[0] for s in scored)
    band = sorted((s for s in scored if s[0] <= nearest + tolerance), key=lambda s: (s[1], s[2]))
    return band[0][3]


def vertical_scroller(widget):
    parent = widget.get_parent()
    while parent and not (isinstance(parent, Gtk.ScrolledWindow) and parent.get_policy()[1] != Gtk.PolicyType.NEVER):
        parent = parent.get_parent()
    return parent


def navigate(window, root, direction, tolerance=24):
    current = focused_candidate(window)
    if not current or not (current is root or current.is_ancestor(root)) or not current.get_mapped():
        return focus(first_candidate(root))
    if getattr(current, "is_slider", False) and direction in ("left", "right"):
        current.nudge(1 if direction == "right" else -1)
        return current
    candidates = collect(root)
    target = None
    # Vertical moves stay inside the same list (settings content, sidebar, home page) when possible
    region = vertical_scroller(current) if direction in VERTICAL else None
    if region:
        target = pick(window, current, [c for c in candidates if c.is_ancestor(region)], direction, tolerance)
    return focus(target or pick(window, current, candidates, direction, tolerance))


# ---- Scrolling ------------------------------------------------------------

_animations = {}


def scroll_to(sw, adjustment, value):
    value = max(adjustment.get_lower(), min(value, adjustment.get_upper() - adjustment.get_page_size()))
    if abs(value - adjustment.get_value()) < 1:
        return
    previous = _animations.pop(adjustment, None)
    if previous:
        previous.skip()
    target = Adw.CallbackAnimationTarget.new(adjustment.set_value)
    animation = Adw.TimedAnimation.new(sw, adjustment.get_value(), value, 220, target)
    animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)
    animation.connect("done", lambda *_: _animations.pop(adjustment, None))
    _animations[adjustment] = animation
    animation.play()


def ensure_visible(widget):
    """Scrolls every ancestor ScrolledWindow so the widget is visible with some margin."""
    parent = widget.get_parent()
    while parent:
        if isinstance(parent, Gtk.ScrolledWindow):
            content = parent.get_child()
            if isinstance(content, Gtk.Viewport) and content.get_child():
                content = content.get_child()
            r = rect(widget, content)
            if r:
                x1, y1, x2, y2 = r
                for adj, start, end in ((parent.get_hadjustment(), x1, x2), (parent.get_vadjustment(), y1, y2)):
                    page = adj.get_page_size()
                    if page <= 0 or adj.get_upper() <= page:
                        continue
                    margin = min(page * 0.2, max(0, (page - (end - start)) / 2))
                    if start - margin < adj.get_value():
                        scroll_to(parent, adj, start - margin)
                    elif end + margin > adj.get_value() + page:
                        scroll_to(parent, adj, end + margin - page)
        parent = parent.get_parent()
