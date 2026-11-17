"""Voluntary support dialog, with the author's payment QR embedded.

Shown in two situations:

* the user clicks "支持作者" / "Donation";
* an unregistered copy has just finished its 5th, 10th, ... conversion.

Nothing here limits functionality -- the dialog only asks.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

SPONSORS_URL = "https://github.com/sponsors/epoches"
REPO_URL = "https://github.com/epoches/pdfmend"
ASSET = Path(__file__).resolve().parent.parent / "assets" / "donation.png"


def donation_pixmap(width: int = 240) -> QPixmap:
    pixmap = QPixmap(str(ASSET))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaledToWidth(width, Qt.SmoothTransformation)


class DonationDialog(QDialog):
    def __init__(self, parent=None, reminder: bool = False, count: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle("支持作者" if not reminder else "谢谢使用 PDFMend")
        self.setMinimumWidth(620)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)

        picture = QLabel()
        pixmap = donation_pixmap(260)
        if not pixmap.isNull():
            picture.setPixmap(pixmap)
            picture.setAlignment(Qt.AlignTop)
            layout.addWidget(picture)

        side = QVBoxLayout()
        side.setSpacing(10)

        title = QLabel("支持 PDFMend" if not reminder else f"已转换 {count} 个文件")
        title.setObjectName("PageTitle")
        side.addWidget(title)

        body = (
            "PDFMend 永久免费、功能不设限，也不上传你的文件。"
            "如果它替你省下了时间，欢迎用微信扫左边的赞赏码，金额随意；"
            "不赞赏也完全不影响使用。"
        )
        if reminder:
            body = (
                f"你已经完成 {count} 次转换。这个工具没有试用期，也不会因为不付费减少功能；"
                "它只是一直在提醒你：如果它真的有用，可以扫左边的码请作者喝杯咖啡。"
            )
        intro = QLabel(body)
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        side.addWidget(intro)

        tips = QLabel("微信扫码即可；海外可用 GitHub Sponsors。注册用户不会看到这个提示。")
        tips.setObjectName("Muted")
        tips.setWordWrap(True)
        side.addWidget(tips)
        side.addStretch(1)

        buttons = QHBoxLayout()
        sponsors = QPushButton("GitHub Sponsors")
        sponsors.setObjectName("Primary")
        sponsors.setMinimumWidth(160)
        sponsors.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SPONSORS_URL)))
        repo = QPushButton("项目主页")
        repo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(sponsors)
        buttons.addWidget(repo)
        buttons.addStretch(1)
        buttons.addWidget(close)
        side.addLayout(buttons)

        layout.addLayout(side, 1)


def open_donation(parent: QWidget | None = None, reminder: bool = False, count: int = 0) -> None:
    DonationDialog(parent, reminder=reminder, count=count).exec()
