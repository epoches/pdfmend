"""Where the app keeps its small local state files.

Everything lives in a ``tmp`` folder next to the program (or next to the
repository when running from source), so a portable copy keeps its own
history and nobody has to guess where the data went:

    tmp/conversions.jsonl   one line per finished conversion
    tmp/usage.json          counters used for the donation reminder
    tmp/license.json        the registration that was accepted

``PDFMEND_TMP`` overrides the folder; tests use it to stay isolated.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "tmp"


def app_dir() -> Path:
    """Folder of the running program (exe when frozen, project root otherwise)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # src/pdfmend/runtime.py -> src/pdfmend -> src -> project root
    return Path(__file__).resolve().parents[2]


def tmp_dir(create: bool = True) -> Path:
    override = os.environ.get("PDFMEND_TMP")
    path = Path(override).expanduser() if override else app_dir() / APP_DIR_NAME
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Read-only install location (Program Files, a mounted image…):
            # keep state per user instead of failing the conversion.
            path = fallback_dir()
            path.mkdir(parents=True, exist_ok=True)
    return path


def fallback_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "PDFMend" / APP_DIR_NAME


def conversions_file() -> Path:
    return tmp_dir() / "conversions.jsonl"


def usage_file() -> Path:
    return tmp_dir() / "usage.json"


def license_file() -> Path:
    return tmp_dir() / "license.json"
