"""Look and feel: one stylesheet, light/dark palettes, no external assets."""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#f6f7f9",
    "panel": "#ffffff",
    "border": "#e3e6ea",
    "text": "#1f2328",
    "muted": "#667085",
    "accent": "#2563eb",
    "accent_soft": "#eaf0ff",
    "sidebar": "#111827",
    "sidebar_text": "#c7cbd4",
}

DARK = {
    "bg": "#15171c",
    "panel": "#1d2026",
    "border": "#2c313a",
    "text": "#e6e8eb",
    "muted": "#9aa3af",
    "accent": "#4f8cff",
    "accent_soft": "#22304d",
    "sidebar": "#0d0f13",
    "sidebar_text": "#aab1bd",
}


def palette(theme: str) -> dict:
    return DARK if theme == "dark" else LIGHT


def stylesheet(theme: str = "light") -> str:
    c = palette(theme)
    return f"""
    QWidget {{ background: {c['bg']}; color: {c['text']};
               font-size: 13px; }}
    QLabel {{ background: transparent; }}
    QFrame#Sidebar {{ background: {c['sidebar']}; border: none; }}
    QLabel#Brand {{ color: white; font-size: 18px; font-weight: 700; }}
    QLabel#BrandSub {{ color: {c['sidebar_text']}; font-size: 11px; }}
    QPushButton#Nav {{
        color: {c['sidebar_text']}; background: transparent; border: none;
        border-radius: 8px; padding: 10px 14px; text-align: left; font-size: 13px;
    }}
    QPushButton#Nav:hover {{ background: rgba(255,255,255,0.08); color: white; }}
    QPushButton#Nav:checked {{ background: {c['accent']}; color: white; font-weight: 600; }}
    QFrame#Panel, QFrame#QualityCard {{
        background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 12px;
    }}
    QLabel#PageTitle {{ font-size: 22px; font-weight: 700; }}
    QLabel#PageHint, QLabel#Muted {{ color: {c['muted']}; }}
    QLabel#ScoreValue {{ font-size: 46px; font-weight: 800; }}
    QLabel#ScoreVerdict {{ font-size: 16px; font-weight: 600; }}
    QLabel#ScoreFile {{ color: {c['muted']}; }}
    QFrame#DropZone {{
        background: {c['panel']}; border: 2px dashed {c['border']}; border-radius: 12px;
    }}
    QFrame#DropZone:hover {{ border-color: {c['accent']}; background: {c['accent_soft']}; }}
    QLabel#DropTitle {{ font-size: 16px; font-weight: 600; }}
    QLabel#DropHint {{ color: {c['muted']}; }}
    QPushButton {{
        background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{ border-color: {c['accent']}; }}
    QPushButton#Primary {{
        background: {c['accent']}; color: white; border: none; font-weight: 600;
        padding: 9px 20px;
    }}
    QPushButton#Primary:disabled {{ background: {c['border']}; color: {c['muted']}; }}
    QPushButton#Ghost {{ background: transparent; color: {c['sidebar_text']};
                         border: 1px solid #2a3342; }}
    QLineEdit, QComboBox, QSpinBox {{
        background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px;
        padding: 6px 10px;
    }}
    QPlainTextEdit, QListWidget, QTableWidget, QTreeWidget {{
        background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px;
    }}
    QHeaderView::section {{
        background: {c['panel']}; color: {c['muted']}; border: none;
        border-bottom: 1px solid {c['border']}; padding: 6px;
    }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 8px; }}
    QTabBar::tab {{ background: transparent; padding: 7px 14px; color: {c['muted']}; }}
    QTabBar::tab:selected {{ color: {c['accent']}; border-bottom: 2px solid {c['accent']}; }}
    QProgressBar {{
        background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px;
        text-align: center; height: 16px;
    }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
    QCheckBox {{ spacing: 6px; }}
    """


def apply_theme(app: QApplication, theme: str = "system") -> None:
    if theme == "system":
        scheme = app.styleHints().colorScheme().name.lower()
        theme = "dark" if scheme == "dark" else "light"
    app.setStyle("Fusion")
    font = QFont()
    for family in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC"):
        if family in QFontDatabase.families():
            font.setFamily(family)
            break
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(stylesheet(theme))
