"""The public website (site/): structure, safety and agreement with the evaluation-requests table."""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404 - runs this repository's own build script
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
PAGES = ["index.html", "privacy.html", "404.html"]
# Columns the anonymous role may insert into public.adaptive_ids_evaluation_requests (Supabase).
DB_COLUMNS = {"name", "email", "organisation", "role", "organisation_type", "interest", "message", "consent", "source"}
ORG_TYPES = {"mssp", "sme", "enterprise", "public_sector", "education", "other"}
INTERESTS = {"evaluation", "feedback_call", "partnership", "other"}


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.ids: set[str] = set()
        self.inline_styles = 0
        self.inline_scripts = 0
        self.fields: dict[str, str] = {}
        self.options: dict[str, set[str]] = {}
        self._select: str | None = None
        self._in_script = False
        self.csp = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if "style" in a:
            self.inline_styles += 1
        for key in ("href", "src", "poster"):
            if a.get(key):
                self.refs.append(a[key])
        if tag == "meta" and a.get("http-equiv", "").lower() == "content-security-policy":
            self.csp = a.get("content", "")
        if tag == "script":
            self._in_script = not a.get("src")
        if tag in ("input", "select", "textarea") and a.get("name"):
            self.fields[a["name"]] = tag
        if tag == "select":
            self._select = a.get("name")
            self.options[self._select] = set()
        if tag == "option" and self._select and a.get("value"):
            self.options[self._select].add(a["value"])

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script and data.strip():
            self.inline_scripts += 1


def _parse(name: str) -> _Collector:
    c = _Collector()
    c.feed((SITE / name).read_text(encoding="utf-8"))
    return c


@pytest.mark.parametrize("page", PAGES)
def test_pages_have_a_strict_csp_and_no_inline_code(page):
    c = _parse(page)
    assert "default-src 'none'" in c.csp and "'unsafe-inline'" not in c.csp
    assert c.inline_styles == 0 and c.inline_scripts == 0


@pytest.mark.parametrize("page", ["index.html", "privacy.html"])
def test_local_links_and_assets_exist(page):
    c = _parse(page)
    for ref in c.refs:
        if ref.startswith(("http://", "https://", "mailto:", "%%")) or ref in ("#", "./"):
            continue
        if ref.startswith("#"):
            assert ref[1:] in c.ids, f"{page}: missing anchor {ref}"
            continue
        path = ref.split("#")[0].lstrip("./")
        if path == "assets/video/adaptive-ids-demo.mp4":  # copied in at build time
            assert (REPO / "docs/demo/adaptive-ids-demo.mp4").is_file()
            continue
        if path:
            assert (SITE / path).is_file(), f"{page}: missing {ref}"


def test_form_matches_the_database_table():
    c = _parse("index.html")
    sent = {k for k in c.fields if k != "website"} | {"source"}  # website = bot trap, never sent
    assert sent == DB_COLUMNS
    assert c.options["organisation_type"] - {""} == ORG_TYPES
    assert c.options["interest"] == INTERESTS
    js = (SITE / "assets/js/site.js").read_text(encoding="utf-8")
    for col in DB_COLUMNS:
        assert re.search(rf"\b{col}\s*:", js), f"site.js does not send {col}"


def test_config_holds_only_public_values():
    cfg = (SITE / "assets/js/config.js").read_text(encoding="utf-8")
    cfg = "\n".join(line for line in cfg.splitlines() if not line.lstrip().startswith("//"))
    assert "sb_publishable_" in cfg
    assert not re.search(r"sb_secret_|service_role|eyJ[A-Za-z0-9_-]{20,}", cfg), "secret-looking key in config.js"
    host = re.search(r'supabaseUrl:\s*"https://([^"]+)"', cfg).group(1)
    assert host in _parse("index.html").csp, "the CSP must allow the form's database host"


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
def test_build_fills_every_placeholder(tmp_path):
    out = tmp_path / "_site"
    subprocess.run(["bash", str(REPO / "tools/site/build.sh"), str(out), "https://example.org", "/sub"],  # nosec B603 B607
                   check=True, capture_output=True)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="https://example.org/"' in html and "%%" not in html
    assert 'href="/sub/assets/css/site.css"' in (out / "404.html").read_text(encoding="utf-8")
    assert (out / "assets/video/adaptive-ids-demo.mp4").stat().st_size > 1_000_000
    assert "https://example.org/sitemap.xml" in (out / "robots.txt").read_text(encoding="utf-8")
