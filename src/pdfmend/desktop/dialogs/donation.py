"""Voluntary support dialog: WeChat / Alipay / GitHub Sponsors."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

SPONSORS_URL = "https://github.com/sponsors/epoches"
REPO_URL = "https://github.com/epoches/pdfmend"


class _Card(QFrame):
    def __init__(self, title: str, body: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        text = QLabel(body)
        text.setObjectName("Muted")
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch(1)


class DonationDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("支持作者")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("支持 PDFMend")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        intro = QLabel(
            "PDFMend 完全免费、没有功能限制，也不收集你的文件。"
            "如果它帮你省下了时间，欢迎自愿支持；不支持也完全不影响使用。"
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(
            _Card("微信赞赏", "打开微信 → 扫作者赞赏码（在项目主页或 README 里），金额随意。")
        )
        row.addWidget(
            _Card("支付宝赞赏", "打开支付宝 → 扫作者收款码（同上）。备注可以写你用它处理了什么文件。")
        )
        row.addWidget(
            _Card("GitHub Sponsors", "海外或订阅式支持：github.com/sponsors/epoches。")
        )
        layout.addLayout(row)

        buttons = QHBoxLayout()
        sponsors = QPushButton("打开 GitHub Sponsors")
        sponsors.setObjectName("Primary")
        sponsors.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SPONSORS_URL)))
        repo = QPushButton("项目主页")
        repo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(sponsors)
        buttons.addWidget(repo)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)


def open_donation(parent: QWidget | None = None) -> None:
    DonationDialog(parent).exec()
