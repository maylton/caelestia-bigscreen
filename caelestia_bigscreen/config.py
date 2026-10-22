"""Persistent settings (~/.config/caelestia-bigscreen/config.json)."""

import json
import os
from copy import deepcopy
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "caelestia-bigscreen"
# Automated tests (BIGSCREEN_TEST=1) never touch the real favorites and recents
CONFIG_FILE = CONFIG_DIR / ("config.test.json" if os.environ.get("BIGSCREEN_TEST") else "config.json")

DEFAULTS = {
    "language": "auto",
    "monitor": "auto",  # connector name, or "auto" for the focused monitor
    "ui_scale": 0,  # 0 = automatic, from the monitor height
    "guide_button": True,
    "select_start_combo": True,
    "use_shell_colors": True,
    "show_wallpaper": True,
    "game_backdrop": True,
    "return_on_exit": True,
    "sources": {"steam": True, "desktop": True},
    "favorites": [],
    "recents": [],
    "hidden": [],
}

MAX_RECENTS = 12


class Config:
    def __init__(self):
        self.data = deepcopy(DEFAULTS)
        try:
            stored = json.loads(CONFIG_FILE.read_text())
        except (OSError, ValueError):
            stored = {}
        for key, value in stored.items():
            if isinstance(value, dict) and isinstance(self.data.get(key), dict):
                self.data[key].update(value)
            else:
                self.data[key] = value

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))
        tmp.replace(CONFIG_FILE)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value
        self.save()

    def toggle_in(self, key, item):
        """Adds or removes `item` from a list setting; returns True if it is now present."""
        items = self.data[key]
        if item in items:
            items.remove(item)
        else:
            items.insert(0, item)
        self.save()
        return item in items

    def push_recent(self, item):
        recents = [r for r in self.data["recents"] if r != item]
        self.data["recents"] = [item, *recents][:MAX_RECENTS]
        self.save()
