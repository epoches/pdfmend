"""Guards for the published repo: no credentials, no .env in git."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Anything that looks like a live secret in a tracked text file.
SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ghp_[A-Za-z0-9]{30,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".yml", ".yaml", ".txt", ".cfg", ".ini", ".example"}
SKIP_DIRS = {".git", ".venv", "__pycache__", "tmp", "out", "build", "dist", ".pytest_cache", "node_modules"}


def _tracked_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if SKIP_DIRS & set(path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name == ".env.example":
            yield path


def test_no_hardcoded_credentials():
    hits = []
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in SECRET.finditer(text):
            hits.append(f"{path.relative_to(ROOT)}: {match.group()[:6]}...")
    assert not hits, "疑似真实 key 出现在仓库里：" + "; ".join(hits)


def test_dotenv_is_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in ignored.split("\n")


def test_example_env_uses_placeholders_only():
    example = ROOT / ".env.example"
    assert example.exists()
    for line in example.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            value = line.split("=", 1)[1].strip()
            assert not SECRET.match(value), line
