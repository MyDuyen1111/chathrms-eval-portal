"""Vietnamese mode. Pages are written in English and t() swaps in Vietnamese when the viewer picked it.

Terms the Vietnamese handbook keeps in English stay English here too (metric names, behaviors, owners,
failure types, sets, milestones, chips, tab names, Pass and Fail), so QC reads the same words in both.
Exports, error details and anything sent to the client or the AI team stay English.
"""
import importlib
import pkgutil
import string

from flask import request

from . import vi

LANGUAGES = ("en", "vi")


def _load():
    merged = {}
    for module in pkgutil.iter_modules(vi.__path__):
        for english, vietnamese in importlib.import_module(f"{vi.__name__}.{module.name}").VI.items():
            # Two parts may share a string; they must agree, or one page would contradict another.
            assert merged.setdefault(english, vietnamese) == vietnamese, f"two translations for {english!r}"
    return merged


VI = _load()


def placeholders(text):
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)


def lang():
    return "vi" if request.cookies.get("lang") == "vi" else "en"


def t(text, **values):
    """The viewer's language. Values fill {name} placeholders after the lookup, so one entry covers every number."""
    if lang() == "vi":
        text = VI.get(text, text)
    return text.format(**values) if values else text
