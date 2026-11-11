"""Phase 7 / spec check 11: sensitive material stays out of the repository.

Scans the files git tracks (what would be published), not the working tree.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

FORBIDDEN_PREFIXES = ("data/raw/", "data/processed/", "data/sample/", "var/", "experiments/runs/", "docs/inventory/", "models/")
ALLOWED_UNDER_FORBIDDEN = {"models/README.md", "models/trusted_artifacts.example.json"}
FORBIDDEN_SUFFIXES = (".pkl", ".pickle", ".joblib", ".pcap", ".pcapng", ".ipynb", ".sqlite", ".db", ".dump", ".env", ".pem", ".key")
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "Anthropic/OpenAI key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}\b"),
    "credentials in a URL": re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^:\s/]+:(?!change-me|ci_only_password|adaptive_ids_dev|\$|\{)[^@\s]{6,}@"),
}
MAX_BYTES = 2_000_000
# The recorded demonstration is the one deliberate exception: a screen recording of SYNTHETIC data.
MEDIA_LIMITS = {"docs/demo/adaptive-ids-demo.mp4": 12_000_000}


def _tracked() -> list[str]:
    if not shutil.which("git") or not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True).stdout  # noqa: S603,S607
    return [p for p in out.decode().split("\0") if p]


def test_no_datasets_models_or_local_state_are_tracked():
    bad = [p for p in _tracked() if (p.startswith(FORBIDDEN_PREFIXES) and p not in ALLOWED_UNDER_FORBIDDEN
                                     and not p.endswith(".gitkeep")) or p.lower().endswith(FORBIDDEN_SUFFIXES)]
    assert bad == [], f"files that must not be committed: {bad}"


def test_no_large_files_are_tracked():
    big = [(p, (REPO / p).stat().st_size) for p in _tracked()
           if (REPO / p).is_file() and (REPO / p).stat().st_size > MEDIA_LIMITS.get(p, MAX_BYTES)]
    assert big == [], f"files over {MAX_BYTES} bytes (datasets or captures?): {big}"


def test_no_secrets_in_tracked_text_files():
    hits = []
    for p in _tracked():
        f = REPO / p
        if not f.is_file() or f.suffix.lower() in (".png", ".jpg", ".svg", ".ico", ".woff", ".woff2"):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits += [f"{p}: {name}" for name, rx in SECRET_PATTERNS.items() if rx.search(text)]
    assert hits == [], f"possible secrets: {hits}"


def test_gitignore_keeps_sensitive_paths_out():
    rules = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    for required in (".env", "data/raw/*", "*.joblib", "*.pkl", "*.pcap", "var/", "experiments/runs/"):
        assert required in rules, f".gitignore must contain {required!r}"


def test_env_example_has_no_real_secrets():
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if re.match(r"^[A-Z_]*(PASSWORD|SECRET|TOKEN|KEY)[A-Z_]*=", line):
            value = line.split("=", 1)[1].strip()
            assert value in ("", "change-me-local-only") or "change-me" in value, line
