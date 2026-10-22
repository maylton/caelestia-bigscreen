"""Theme: Caelestia Material You colours (or a default palette), scaled for TVs."""

import json
from pathlib import Path

from gi.repository import Gdk, Gio, Gtk

STATE = Path.home() / ".local/state/caelestia"
SCHEME_FILE = STATE / "scheme.json"
WALLPAPER_FILE = STATE / "wallpaper/path.txt"

FALLBACK = {
    "background": "0f1114",
    "surfaceContainerLow": "16191d",
    "surfaceContainer": "1b1f24",
    "surfaceContainerHigh": "23282e",
    "surfaceContainerHighest": "2c3239",
    "onSurface": "e2e6ec",
    "onSurfaceVariant": "a9b1bb",
    "outline": "7a838e",
    "primary": "8ab4f8",
    "onPrimary": "0b2a55",
    "primaryContainer": "1f4277",
    "onPrimaryContainer": "d6e3ff",
    "secondaryContainer": "353f4f",
    "onSecondaryContainer": "d8e2f6",
    "error": "ffb4ab",
}


def shell_colours(enabled):
    colours = dict(FALLBACK)
    if enabled:
        try:
            scheme = json.loads(SCHEME_FILE.read_text()).get("colours", {})
        except (OSError, ValueError):
            scheme = {}
        colours.update({k: scheme[k].lstrip("#") for k in colours if scheme.get(k)})
    return colours


def shell_wallpaper():
    try:
        path = WALLPAPER_FILE.read_text().strip()
    except OSError:
        return None
    return path if path and Path(path).is_file() else None


def build_css(colours, scale):
    """Sizes are designed for 1080p and multiplied by `scale`."""
    def px(value):
        return f"{round(value * scale)}px"

    defines = "\n".join(f"@define-color {k} #{v};" for k, v in colours.items())
    return defines + f"""
window.bigscreen {{
  background: transparent;
  color: @onSurface;
  font-family: Rubik, "Noto Sans", sans-serif;
  font-size: {px(17)};
}}
.backdrop-scrim {{
  background-image: linear-gradient(to bottom, alpha(@background, .55) 0%,
                                    alpha(@background, .72) 45%, alpha(@background, .94) 100%);
}}
.backdrop-scrim.plain {{ background: @background; }}
.quick-scrim {{ background: alpha(black, .55); }}

/* Header */
.header {{ padding: {px(26)} {px(56)} {px(10)} {px(56)}; }}
.brand {{ font-size: {px(26)}; font-weight: 800; letter-spacing: {px(1)}; color: @primary; margin-right: {px(26)}; }}
button.tab {{
  background: transparent; color: @onSurfaceVariant; border-radius: 999px;
  padding: {px(8)} {px(22)}; font-size: {px(19)}; font-weight: 600; min-height: 0;
  box-shadow: none; outline: none; transition: all 150ms ease-out;
}}
button.tab.active {{ background: alpha(@onSurface, .12); color: @onSurface; }}
button.tab:focus {{ background: @primary; color: @onPrimary; }}
button.icon-button {{
  background: alpha(@onSurface, .08); border-radius: 999px; padding: {px(10)};
  min-width: 0; min-height: 0; outline: none; box-shadow: none; color: @onSurface;
  margin-left: {px(10)};
}}
button.icon-button:focus {{ background: @primary; color: @onPrimary; }}
button.icon-button image {{ -gtk-icon-size: {px(22)}; }}
.status image {{ -gtk-icon-size: {px(22)}; color: @onSurfaceVariant; }}
.status label {{ color: @onSurfaceVariant; font-size: {px(16)}; }}
.clock-box {{ margin-left: {px(18)}; }}
.clock {{ font-size: {px(30)}; font-weight: 700; }}
.date {{ font-size: {px(15)}; color: @onSurfaceVariant; }}

/* Rows and cards */
.page {{ padding-bottom: {px(40)}; }}
.row-title {{ font-size: {px(23)}; font-weight: 700; margin: {px(18)} 0 0 {px(56)}; }}
.row-strip {{ padding: {px(18)} {px(56)} {px(22)} {px(56)}; }}
.hero {{ padding: {px(30)} {px(56)} {px(6)} {px(56)}; }}
.hero-title {{ font-size: {px(54)}; font-weight: 800; }}
.hero-sub {{ font-size: {px(19)}; color: @onSurfaceVariant; }}

button.card {{
  background: alpha(@surfaceContainerHigh, .85); border-radius: {px(20)}; padding: 0;
  border: none; outline: none; box-shadow: 0 {px(6)} {px(18)} alpha(black, .35);
  transition: transform 160ms ease-out, box-shadow 160ms ease-out, background 160ms;
  transform-origin: center;
}}
button.card:hover {{ background: alpha(@surfaceContainerHighest, .95); }}
button.card:focus {{
  transform: scale(1.07);
  box-shadow: 0 0 0 {px(4)} @primary, 0 {px(14)} {px(38)} alpha(black, .55);
  background: @surfaceContainerHighest;
}}
button.card picture {{ border-radius: {px(20)}; }}
button.card.poster {{ min-width: {px(210)}; min-height: {px(315)}; }}
button.card.tile {{ min-width: {px(190)}; min-height: {px(190)}; }}
button.card.tile image {{ -gtk-icon-size: {px(92)}; }}
button.card.system {{ min-width: {px(230)}; min-height: {px(120)}; background: alpha(@secondaryContainer, .75); }}
button.card.system:focus {{ background: @primaryContainer; }}
button.card.system image {{ -gtk-icon-size: {px(40)}; color: @onSecondaryContainer; }}
button.card.system label {{ font-size: {px(18)}; font-weight: 600; }}
.card-fallback {{ background: linear-gradient(160deg, @primaryContainer, @surfaceContainerHigh); border-radius: {px(20)}; }}
.card-fallback label {{ font-size: {px(22)}; font-weight: 700; color: @onPrimaryContainer; padding: {px(14)}; }}
.card-label {{ font-size: {px(16)}; color: @onSurfaceVariant; margin-top: {px(10)}; }}
.card-label.focused {{ color: @onSurface; font-weight: 600; }}
.badge {{
  background: @primary; color: @onPrimary; border-radius: 999px; font-size: {px(13)};
  font-weight: 700; padding: {px(2)} {px(10)}; margin: {px(10)};
}}
button.pill {{
  background: @primary; color: @onPrimary; border-radius: 999px; font-weight: 700;
  padding: {px(12)} {px(30)}; font-size: {px(19)}; outline: none; box-shadow: none;
  transition: transform 150ms ease-out;
}}
button.pill.secondary {{ background: alpha(@onSurface, .12); color: @onSurface; }}
button.pill.danger {{ background: @error; color: black; }}
button.pill:focus {{ box-shadow: 0 0 0 {px(4)} @onSurface; transform: scale(1.05); }}

.grid {{ padding: {px(18)} {px(56)}; }}
.page-title {{ font-size: {px(34)}; font-weight: 800; margin: {px(8)} {px(56)} 0 {px(56)}; }}
.page-action {{ margin-right: {px(56)}; }}
.empty {{ font-size: {px(19)}; color: @onSurfaceVariant; margin: {px(40)}; }}

/* Settings */
.sidebar {{ padding: {px(18)} {px(12)} {px(18)} {px(56)}; min-width: {px(300)}; }}
button.side-item {{
  background: transparent; border-radius: {px(16)}; padding: {px(14)} {px(18)};
  outline: none; box-shadow: none; color: @onSurfaceVariant; font-size: {px(19)}; font-weight: 600;
}}
button.side-item image {{ -gtk-icon-size: {px(24)}; }}
button.side-item.active {{ background: alpha(@onSurface, .10); color: @onSurface; }}
button.side-item:focus {{ background: @primary; color: @onPrimary; }}
.settings-content {{ padding: {px(18)} {px(56)} {px(40)} {px(28)}; }}
.section-title {{ font-size: {px(30)}; font-weight: 800; margin-bottom: {px(6)}; }}
.section-sub {{ font-size: {px(16)}; color: @onSurfaceVariant; margin-bottom: {px(10)}; }}
.group-title {{ font-size: {px(15)}; font-weight: 700; color: @primary; margin: {px(18)} 0 {px(4)} {px(6)}; }}
button.setting, .setting-static {{
  background: alpha(@surfaceContainer, .82); border-radius: {px(18)};
  padding: {px(16)} {px(22)}; outline: none; box-shadow: none; color: @onSurface;
  transition: background 120ms;
}}
button.setting:hover {{ background: alpha(@surfaceContainerHigh, .9); }}
button.setting:focus {{ background: @primaryContainer; box-shadow: 0 0 0 {px(3)} @primary; }}
button.setting image.lead, .setting-static image.lead {{ -gtk-icon-size: {px(26)}; color: @onSurfaceVariant; }}
button.setting:focus image.lead {{ color: @onPrimaryContainer; }}
.setting-title {{ font-size: {px(19)}; font-weight: 600; }}
.setting-sub {{ font-size: {px(15)}; color: @onSurfaceVariant; }}
button.setting:focus .setting-sub {{ color: @onPrimaryContainer; }}
.check {{ color: @primary; -gtk-icon-size: {px(24)}; }}
switch {{ min-width: {px(52)}; min-height: {px(28)}; border-radius: 999px; }}
switch slider {{ min-width: {px(22)}; min-height: {px(22)}; }}
/* Caelestia SliderRow: surfaceContainer card, largeIncreased/large padding */
.slider-row {{
  background: alpha(@surfaceContainer, .82); border-radius: {px(18)};
  padding: {px(16)} {px(20)} {px(20)} {px(20)};
}}
.slider-row.focused {{ background: @primaryContainer; box-shadow: 0 0 0 {px(3)} @primary; }}
.slider-icon {{ -gtk-icon-size: {px(26)}; color: @onSurfaceVariant; margin-top: {px(2)}; }}
.slider-label {{ font-size: {px(19)}; font-weight: 600; }}
.slider-value {{ font-size: {px(17)}; color: @outline; font-weight: 600; }}
.slider-row.focused .slider-value {{ color: @onPrimaryContainer; }}
.battery {{ font-size: {px(15)}; color: @onSurfaceVariant; min-width: {px(48)}; }}
spinner {{ min-width: {px(24)}; min-height: {px(24)}; }}

/* Quick menu */
.quick-panel {{
  background: alpha(@surfaceContainer, .97); min-width: {px(440)};
  padding: {px(30)} {px(26)}; border-radius: 0 {px(28)} {px(28)} 0;
  box-shadow: {px(10)} 0 {px(40)} alpha(black, .5);
}}
.quick-panel .clock {{ font-size: {px(44)}; }}

/* Dialogs, keyboard, hints and toasts */
.modal-scrim {{ background: alpha(black, .6); }}
.modal {{
  background: @surfaceContainerHigh; border-radius: {px(30)}; padding: {px(32)};
  box-shadow: 0 {px(20)} {px(60)} alpha(black, .6);
}}
.modal-title {{ font-size: {px(28)}; font-weight: 800; }}
.modal-text {{ font-size: {px(18)}; color: @onSurfaceVariant; }}
entry.osk-entry {{
  font-size: {px(26)}; min-height: {px(60)}; border-radius: {px(16)};
  background: @surfaceContainerLow; color: @onSurface; padding: 0 {px(18)};
}}
button.key {{
  min-width: {px(66)}; min-height: {px(62)}; border-radius: {px(14)};
  background: alpha(@onSurface, .08); color: @onSurface; font-size: {px(22)}; font-weight: 600;
  outline: none; box-shadow: none; padding: 0; transition: transform 100ms ease-out;
}}
button.key.wide {{ min-width: {px(150)}; }}
button.key.space {{ min-width: {px(380)}; }}
button.key.accent {{ background: @primaryContainer; color: @onPrimaryContainer; }}
button.key.on {{ background: @secondaryContainer; color: @onSecondaryContainer; }}
button.key:focus {{ background: @primary; color: @onPrimary; transform: scale(1.08); }}
.hints {{ font-size: {px(15)}; color: @onSurfaceVariant; margin: 0 {px(56)} {px(20)} 0; }}
.hint-key {{
  background: alpha(@onSurface, .14); border-radius: 999px; min-width: {px(26)};
  min-height: {px(26)}; padding: 0 {px(6)}; font-weight: 800; font-size: {px(13)}; color: @onSurface;
}}
.toast {{
  background: @surfaceContainerHigh; color: @onSurface; border-radius: {px(28)};
  padding: {px(16)} {px(28)}; font-size: {px(18)}; font-weight: 600; margin-bottom: {px(40)};
  box-shadow: 0 {px(10)} {px(30)} alpha(black, .5);
}}
.splash-title {{ font-size: {px(36)}; font-weight: 800; }}
.splash picture {{ border-radius: {px(24)}; }}
.splash image {{ -gtk-icon-size: {px(160)}; }}
"""


class Theme:
    def __init__(self, config, on_change=None):
        self.config = config
        self.on_change = on_change
        self.scale = 1.0
        self.colours = dict(FALLBACK)
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10)
        # Follow wallpaper and scheme changes made in the shell
        self.monitors = [Gio.File.new_for_path(str(p)).monitor_file(Gio.FileMonitorFlags.NONE, None)
                         for p in (SCHEME_FILE, WALLPAPER_FILE)]
        for monitor in self.monitors:
            monitor.connect("changed", self.on_file_changed)

    def on_file_changed(self, _monitor, _file, _other, event):
        if event in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            self.apply()
            if self.on_change:
                self.on_change()

    @staticmethod
    def auto_scale(monitor):
        return max(0.8, min(2.6, monitor.get_geometry().height / 1080)) if monitor else 1.0

    def apply(self, monitor=None):
        if monitor is not None:
            self.scale = self.config["ui_scale"] or self.auto_scale(monitor)
        self.colours = shell_colours(self.config["use_shell_colors"])
        self.provider.load_from_string(build_css(self.colours, self.scale))

    def px(self, value):
        return round(value * self.scale)
