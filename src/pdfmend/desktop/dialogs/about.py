"""About box (author, donation QR, registration) and the registration dialog."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdfmend import __version__, licensing
from pdfmend.desktop.dialogs.donation import ASSET, open_donation

REPO_URL = "https://github.com/epoches/pdfmend"
AUTHOR = "epoch"


def _qr_label(width: int = 190) -> QLabel:
    label = QLabel()
    pixmap = QPixmap(str(ASSET))
    if not pixmap.isNull():
        from PySide6.QtCore import Qt

        label.setPixmap(pixmap.scaledToWidth(width, Qt.SmoothTransformation))
        label.setAlignment(Qt.AlignTop)
    return label


class _RegisterSignals(QObject):
    done = Signal(bool, str)


class _RegisterWorker(QRunnable):
    """Runs licensing.register off the UI thread (it may touch the network)."""

    def __init__(self, user: str, code: str, allow_server: bool) -> None:
        super().__init__()
        self.user = user
        self.code = code
        self.allow_server = allow_server
        self.signals = _RegisterSignals()

    def run(self) -> None:  # noqa: D401 - QRunnable entry point
        ok, message = licensing.register(self.user, self.code, allow_server=self.allow_server)
        self.signals.done.emit(ok, message)


class RegisterDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("注册 PDFMend")
        self.setMinimumWidth(520)
        self.pool = QThreadPool.globalInstance()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        title = QLabel("注册")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "注册码由「用户名 + 注册日期 + 本机 MAC」算出，所以内网、离线也能验证。"
            "把下面这行机器码发给作者，可以拿到与你用户名匹配的注册码。"
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        machine = QLabel(f"本机机器码：{licensing.machine_id()}")
        machine.setObjectName("Muted")
        machine.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(machine)

        self.user = QLineEdit()
        self.user.setPlaceholderText("用户名，例如 admin")
        self.user.setText(licensing.load_license().username)
        layout.addWidget(self.user)

        self.code = QLineEdit()
        self.code.setPlaceholderText("注册码，例如 20261117-ABCDEFGH23456789")
        layout.addWidget(self.code)

        self.status = QLabel(licensing.license_summary())
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.check = QPushButton("验证并注册")
        self.check.setObjectName("Primary")
        self.check.clicked.connect(lambda: self._submit(True))
        self.offline = QPushButton("仅本机验证")
        self.offline.clicked.connect(lambda: self._submit(False))
        self.clear = QPushButton("清除注册")
        self.clear.clicked.connect(self._clear)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(self.check)
        buttons.addWidget(self.offline)
        buttons.addWidget(self.clear)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _submit(self, allow_server: bool) -> None:
        self.status.setText("验证中…")
        for button in (self.check, self.offline):
            button.setEnabled(False)
        worker = _RegisterWorker(self.user.text(), self.code.text(), allow_server)
        worker.signals.done.connect(self._done)
        self.pool.start(worker)

    def _done(self, ok: bool, message: str) -> None:
        for button in (self.check, self.offline):
            button.setEnabled(True)
        self.status.setText(("✅ " if ok else "❌ ") + message)
        if ok:
            self.code.setText(licensing.load_license().code)

    def _clear(self) -> None:
        licensing.clear_license()
        self.status.setText("已清除本机注册信息")
        self.code.clear()


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("关于 PDFMend")
        self.setMinimumWidth(660)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)
        layout.addWidget(_qr_label(210))

        side = QVBoxLayout()
        side.setSpacing(8)

        title = QLabel(f"PDFMend {__version__}")
        title.setObjectName("PageTitle")
        side.addWidget(title)

        author = QLabel(f"作者：{AUTHOR}（github.com/epoches）")
        side.addWidget(author)

        blurb = QLabel(
            "本地文档解析与质量检测：PDF / Word / Excel / PPT → Markdown、Excel、JSON、HTML。"
            "文件不出本机；只有主动使用 AI 字段抽取时才会把文本发给你配置的模型。"
        )
        blurb.setObjectName("Muted")
        blurb.setWordWrap(True)
        side.addWidget(blurb)

        donate = QLabel("如果它帮到了你，可以用微信扫左边的码请作者喝杯咖啡。")
        donate.setObjectName("Muted")
        donate.setWordWrap(True)
        side.addWidget(donate)

        self.license_label = QLabel(licensing.license_summary())
        self.license_label.setObjectName("Muted")
        self.license_label.setWordWrap(True)
        side.addWidget(self.license_label)

        machine = QLabel(f"本机机器码：{licensing.machine_id()}")
        machine.setObjectName("Muted")
        side.addWidget(machine)
        side.addStretch(1)

        buttons = QHBoxLayout()
        donate_button = QPushButton("支持作者")
        donate_button.clicked.connect(lambda: open_donation(self))
        register = QPushButton("注册…")
        register.setObjectName("Primary")
        register.clicked.connect(self._open_register)
        repo = QPushButton("项目主页")
        repo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(donate_button)
        buttons.addWidget(register)
        buttons.addWidget(repo)
        buttons.addStretch(1)
        buttons.addWidget(close)
        side.addLayout(buttons)

        layout.addLayout(side, 1)

    def _open_register(self) -> None:
        RegisterDialog(self).exec()
        self.license_label.setText(licensing.license_summary())


def open_about(parent: QWidget | None = None) -> None:
    AboutDialog(parent).exec()
