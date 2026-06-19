"""Lightweight i18n module — loads translations from JSON, instant language switch."""

import json
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

_i18n_dir = Path(__file__).parent

_translations: dict[str, dict[str, str]] = {}
_current_lang = "zh_CN"


class _LangNotifier(QObject):
    languageChanged = pyqtSignal(str)


_lang_notifier = _LangNotifier()
languageChanged = _lang_notifier.languageChanged


def load_translations():
    """Load translations from JSON files."""
    global _translations
    _translations = {}
    for lang_file in sorted(_i18n_dir.glob("*.json")):
        lang_code = lang_file.stem
        _translations[lang_code] = json.loads(lang_file.read_text(encoding="utf-8"))


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Return the translation for *key* in the given or current language."""
    lang = lang or _current_lang
    text = _translations.get(lang, {}).get(key)
    if text is None:
        text = _translations.get("zh_CN", {}).get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text


_ = t  # shorthand


def current_lang() -> str:
    return _current_lang


def set_language(code: str):
    global _current_lang
    if code in _translations:
        _current_lang = code
        languageChanged.emit(code)


# Init on import
load_translations()
