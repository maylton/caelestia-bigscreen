"""Game and app library: system .desktop entries plus the local Steam library."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from gi.repository import Gio, GLib

from . import APP_ID

STEAM_ROOTS = [
    Path.home() / ".local/share/Steam",
    Path.home() / ".steam/steam",
    Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
]
STEAM_TOOL_RE = re.compile(r"^(Proton|Steam Linux Runtime|Steamworks Common|SteamVR|Steam ?Audio)", re.I)
STEAM_URI_RE = re.compile(r"steam://rungameid/(\d+)")
VDF_PAIR_RE = re.compile(r'"([^"]+)"\s+"([^"]*)"')
LAUNCHER_RE = re.compile(
    r"(^steam\.desktop|heroic|lutris|epic_games|protonplus|protonup|bottles|itch|minigalaxy|cartridges|playnite)",
    re.I,
)

POSTER_NAMES = ("library_600x900.jpg", "library_capsule.jpg", "library_600x900.png")
HERO_NAMES = ("library_hero.jpg", "library_hero.png")
LOGO_NAMES = ("logo.png",)


@dataclass
class Entry:
    id: str
    name: str
    kind: str  # "game" | "launcher" | "app"
    source: str  # "steam" | "desktop"
    icon: Gio.Icon | None = None
    poster: str | None = None
    hero: str | None = None
    logo: str | None = None
    last_played: int = 0
    app_info: Gio.DesktopAppInfo | None = None
    uri: str | None = None
    keywords: list = field(default_factory=list)

    @property
    def is_game(self):
        return self.kind == "game"

    def matches(self, text):
        text = text.casefold()
        return text in self.name.casefold() or any(text in k.casefold() for k in self.keywords)


def parse_vdf_pairs(path):
    try:
        return VDF_PAIR_RE.findall(Path(path).read_text(errors="replace"))
    except OSError:
        return []


def find_art(cache_dir, names):
    """Finds an artwork file (old flat layout or new hashed subfolders)."""
    if not cache_dir.is_dir():
        return None
    for folder in [cache_dir, *(p for p in cache_dir.iterdir() if p.is_dir())]:
        for name in names:
            if (folder / name).is_file():
                return str(folder / name)
    return None


def load_steam():
    root = next((r.resolve() for r in STEAM_ROOTS if (r / "steamapps").is_dir()), None)
    if not root:
        return []
    libraries = {root} | {Path(v) for k, v in parse_vdf_pairs(root / "steamapps/libraryfolders.vdf") if k == "path"}
    cache = root / "appcache/librarycache"
    entries = {}
    for manifest in (m for lib in libraries for m in (lib / "steamapps").glob("appmanifest_*.acf")):
        fields = {}
        for key, value in parse_vdf_pairs(manifest):
            fields.setdefault(key, value)
        appid, name = fields.get("appid"), fields.get("name")
        # StateFlags bit 4 = fully installed
        if not appid or not name or STEAM_TOOL_RE.match(name) or not int(fields.get("StateFlags") or 0) & 4:
            continue
        art = cache / appid
        entries[appid] = Entry(
            id=f"steam:{appid}",
            name=name,
            kind="game",
            source="steam",
            icon=Gio.ThemedIcon.new_from_names([f"steam_icon_{appid}", "steam", "applications-games"]),
            poster=find_art(art, POSTER_NAMES),
            hero=find_art(art, HERO_NAMES),
            logo=find_art(art, LOGO_NAMES),
            last_played=int(fields.get("LastPlayed") or 0),
            uri=f"steam://rungameid/{appid}",
        )
    return list(entries.values())


def load_desktop(steam_ids):
    entries = []
    for info in Gio.AppInfo.get_all():
        if not isinstance(info, Gio.DesktopAppInfo) or not info.should_show():
            continue
        app_id = info.get_id() or ""
        if app_id.startswith(APP_ID):
            continue
        match = STEAM_URI_RE.search(info.get_commandline() or "")
        if match and match.group(1) in steam_ids:
            continue  # Steam shortcut: the Steam entry already has the artwork
        categories = [c for c in (info.get_categories() or "").split(";") if c]
        if "Game" not in categories:
            kind = "app"
        elif LAUNCHER_RE.search(app_id):
            kind = "launcher"
        else:
            kind = "game"
        entries.append(Entry(
            id=f"desktop:{app_id}",
            name=info.get_display_name() or info.get_name() or app_id,
            kind=kind,
            source="desktop",
            icon=info.get_icon(),
            app_info=info,
            keywords=list(info.get_keywords() or []) + categories,
        ))
    return entries


def by_name(entry):
    return entry.name.casefold()


class Library:
    def __init__(self, config):
        self.config = config
        self.entries = {}
        self.reload()

    def reload(self):
        sources = self.config["sources"]
        steam = load_steam() if sources.get("steam", True) else []
        desktop = load_desktop({e.id.split(":", 1)[1] for e in steam}) if sources.get("desktop", True) else []
        self.entries = {e.id: e for e in steam + desktop}

    def get(self, entry_id):
        return self.entries.get(entry_id)

    def visible(self, kind=None):
        hidden = set(self.config["hidden"])
        return [e for e in self.entries.values() if e.id not in hidden and kind in (None, e.kind)]

    def games(self):
        return sorted(self.visible("game"), key=lambda e: (-e.last_played, by_name(e)))

    def launchers(self):
        return sorted(self.visible("launcher"), key=by_name)

    def apps(self):
        return sorted(self.visible("app"), key=by_name)

    def from_ids(self, ids):
        hidden = set(self.config["hidden"])
        return [self.entries[i] for i in ids if i in self.entries and i not in hidden]

    def favorites(self):
        return self.from_ids(self.config["favorites"])

    def recents(self):
        return self.from_ids(self.config["recents"])

    def hidden(self):
        return [self.entries[i] for i in self.config["hidden"] if i in self.entries]

    def search(self, text, limit=24):
        text = text.strip().casefold()
        if not text:
            return []
        hits = [e for e in self.visible() if e.matches(text)]
        hits.sort(key=lambda e: (not by_name(e).startswith(text), not e.is_game, by_name(e)))
        return hits[:limit]


def launch(entry, display):
    """Starts the entry. Returns an error message, or None on success."""
    context = display.get_app_launch_context()
    context.unsetenv("LD_PRELOAD")
    try:
        if entry.app_info:
            entry.app_info.launch([], context)
        else:
            Gio.AppInfo.launch_default_for_uri(entry.uri, context)
    except GLib.Error as err:
        if not entry.uri:
            return err.message
        # No handler registered for steam:// — call the client directly
        try:
            GLib.spawn_async(["steam", entry.uri], flags=GLib.SpawnFlags.SEARCH_PATH)
        except GLib.Error:
            return err.message
    return None
