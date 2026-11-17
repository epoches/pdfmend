"""Desktop GUI (PySide6). Importing this package does not import Qt."""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    from pdfmend.desktop.app import main as _main

    return _main(argv)
