"""Assemble the public website into OUT_DIR for GitHub Pages (or a local preview).

    python tools/site/build.py OUT_DIR SITE_URL [BASE_PATH]
    e.g. python tools/site/build.py _site https://adaptiveids.com
         python tools/site/build.py _site https://user.github.io/Ml-Detection-Project /Ml-Detection-Project

SITE_URL fills canonical links, the sitemap and social-preview tags; BASE_PATH is the path the
site is served under ("" for a custom domain), used by the 404 page. Standard library only, so it
runs the same on Linux, macOS and Windows.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".html", ".xml", ".txt"}
PLACEHOLDER = re.compile(r"%%[A-Z_]+%%")


def build(out: Path, site_url: str, base_path: str = "") -> None:
    site_url, base_path = site_url.rstrip("/"), base_path.rstrip("/")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    video = out / "assets" / "video"
    video.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "docs" / "demo" / "adaptive-ids-demo.mp4", video / "adaptive-ids-demo.mp4")
    left = []
    for path in sorted(out.rglob("*")):
        if path.suffix not in TEXT_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        text = text.replace("%%SITE_URL%%", site_url).replace("%%BASE_PATH%%", base_path)
        path.write_text(text, encoding="utf-8", newline="\n")
        if PLACEHOLDER.search(text):
            left.append(str(path.relative_to(out)))
    if left:
        raise SystemExit(f"unreplaced placeholders remain in: {', '.join(left)}")


def main(argv: list[str]) -> None:
    if len(argv) not in (2, 3):
        raise SystemExit(__doc__)
    build(Path(argv[0]), argv[1], argv[2] if len(argv) == 3 else "")
    print(f"Built {argv[0]} for {argv[1].rstrip('/')}")


if __name__ == "__main__":
    main(sys.argv[1:])
