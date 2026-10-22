"""Translations via gettext. English is the source language and the fallback."""

import gettext
import locale
from pathlib import Path

DOMAIN = "caelestia-bigscreen"
LOCALE_DIRS = [
    Path(__file__).resolve().parent.parent / "locale",
    Path("/usr/local/share/locale"),
    Path("/usr/share/locale"),
]


def N_(message):
    """Marks a string for extraction without translating it yet."""
    return message


LANGUAGES = {"auto": N_("System language"), "en": "English", "pt_BR": "Português (Brasil)"}

_translation = gettext.NullTranslations()


def setup(language="auto"):
    """Loads the catalog for `language` ("auto" follows the system locale)."""
    global _translation
    # Day and month names in dates follow the chosen language too
    try:
        locale.setlocale(locale.LC_TIME, {"auto": "", "en": "C.UTF-8"}.get(language, f"{language}.UTF-8"))
    except locale.Error:
        pass
    languages = None if language == "auto" else [language]
    for directory in LOCALE_DIRS:
        try:
            _translation = gettext.translation(DOMAIN, directory, languages=languages)
            return
        except OSError:
            continue
    _translation = gettext.NullTranslations()


def _(message):
    return _translation.gettext(message)
