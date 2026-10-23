"""Artwork for games outside Steam (cover, hero and logo), from SteamGridDB.

SteamGridDB needs a free personal API key. Downloaded images are cached, so
each game is looked up only once; games without a match are remembered too.
"""

import json
import re
import shutil
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from gi.repository import GLib

from . import APP_NAME, __version__

API = "https://www.steamgriddb.com/api/v2"
CACHE = Path(GLib.get_user_cache_dir()) / "caelestia-bigscreen" / "artwork"
USER_AGENT = f"{APP_NAME.replace(' ', '')}/{__version__}"
# Entry field -> (SteamGridDB endpoint, query, cached file name)
KINDS = {
    "poster": ("grids", {"dimensions": "600x900", "types": "static", "nsfw": "false", "humor": "false"}, "poster"),
    "hero": ("heroes", {"types": "static", "nsfw": "false", "humor": "false"}, "hero"),
    "logo": ("logos", {"types": "static", "nsfw": "false", "humor": "false"}, "logo"),
}
NOT_FOUND = "not-found"


class InvalidKey(Exception):
    pass


def folder(entry):
    return CACHE / re.sub(r"[^\w.-]", "_", entry.id)


def search_name(name):
    """"Genshin Impact (direct)" -> "Genshin Impact"."""
    return re.sub(r"\s*[(\[].*?[)\]]", "", name).strip() or name


def wants_artwork(entry):
    return entry.is_game and entry.source != "steam"


def apply_cached(entries):
    """Fills poster/hero/logo of non-Steam games from the cache."""
    for entry in filter(wants_artwork, entries):
        directory = folder(entry)
        for field in KINDS:
            path = next(directory.glob(f"{KINDS[field][2]}.*"), None) if directory.is_dir() else None
            if path:
                setattr(entry, field, str(path))


def clear_cache():
    shutil.rmtree(CACHE, ignore_errors=True)


def request(key, path, params=None):
    url = f"{API}/{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as err:
        if err.code == 401:
            raise InvalidKey from err
        return {}


def download(url, target):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as response:
        target.write_bytes(response.read())


def fetch_entry(key, entry):
    """Looks the game up and downloads its images. Returns True if anything was found."""
    directory = folder(entry)
    directory.mkdir(parents=True, exist_ok=True)
    results = request(key, f"search/autocomplete/{urllib.parse.quote(search_name(entry.name))}").get("data")
    if not results:
        (directory / NOT_FOUND).touch()
        return False
    game_id = results[0]["id"]
    found = False
    for endpoint, params, name in KINDS.values():
        images = request(key, f"{endpoint}/game/{game_id}", params).get("data") or []
        if images:
            url = images[0]["url"]
            download(url, directory / f"{name}{Path(urllib.parse.urlparse(url).path).suffix or '.png'}")
            found = True
    if not found:
        (directory / NOT_FOUND).touch()
    return found


def fetch_missing(key, entries, on_done):
    """Downloads artwork for games without it, off the main thread.

    on_done(found, error) runs on the main loop; error is "invalid-key", "network" or None.
    """
    missing = [e for e in entries if wants_artwork(e) and not folder(e).is_dir()]

    def work():
        found, error = 0, None
        for entry in missing:
            try:
                found += fetch_entry(key, entry)
            except InvalidKey:
                shutil.rmtree(folder(entry), ignore_errors=True)
                error = "invalid-key"
                break
            except (OSError, ValueError, KeyError):
                shutil.rmtree(folder(entry), ignore_errors=True)
                error = "network"
        GLib.idle_add(on_done, found, error)

    threading.Thread(target=work, daemon=True).start()
    return len(missing)
