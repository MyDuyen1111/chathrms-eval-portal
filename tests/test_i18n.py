"""Vietnamese mode: every wrapped string has a translation, and the switch is safe."""
import re
import unittest
from pathlib import Path

from evalportal.i18n import VI, placeholders
from tests.test_web import Portal

PACKAGE = Path(__file__).resolve().parent.parent / "evalportal"
# t("...") or t('...') with a literal first argument, in templates and Python.
CALL = re.compile(r"""\bt\(\s*(?P<q>["'])(?P<text>(?:\\.|(?!(?P=q)).)*)(?P=q)""", re.S)


def wrapped_strings():
    for path in [*PACKAGE.glob("templates/*.html"), *PACKAGE.rglob("*.py")]:
        for match in CALL.finditer(path.read_text(encoding="utf-8")):
            yield path.name, match["text"].replace("\\'", "'").replace('\\"', '"')


class Translations(unittest.TestCase):
    def test_every_wrapped_string_has_vietnamese(self):
        missing = sorted({f"{name}: {text}" for name, text in wrapped_strings() if text not in VI})
        self.assertEqual(missing, [])

    def test_placeholders_survive_translation(self):
        for english, vietnamese in VI.items():
            self.assertTrue(vietnamese.strip(), english)
            self.assertEqual(placeholders(english), placeholders(vietnamese), english)


class Switch(Portal):
    def test_english_by_default_and_vietnamese_after_switching(self):
        client = self.client()
        self.assertIn('<html lang="en">', client.get("/login").get_data(as_text=True))
        response = client.get("/language/vi?next=/login")
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIn('<html lang="vi">', client.get("/login").get_data(as_text=True))

    def test_next_never_leaves_the_site(self):
        client = self.client()
        for target in ("//evil.example/x", "https://evil.example/", "/\\evil.example", ""):
            self.assertEqual(client.get("/language/vi", query_string={"next": target}).headers["Location"], "/login", target)

    def test_unknown_language_sets_nothing(self):
        response = self.client().get("/language/xx?next=/login")
        self.assertNotIn("lang=", response.headers.get("Set-Cookie", ""))
