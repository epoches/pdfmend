"""Desktop entry point: ``python -m pdfmend.desktop`` / ``pdfmend-desktop``."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from pdfmend.desktop.main_window import MainWindow

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("PDFMend")
    app.setOrganizationName("pdfmend")
    app.setApplicationDisplayName("PDFMend")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
