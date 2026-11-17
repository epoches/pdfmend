"""Settings page: output, OCR, theme and the AI provider / API key."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdfmend import __version__
from pdfmend.config import settings as config

UPDATE_URL = "https://api.github.com/repos/epoches/pdfmend/releases/latest"


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    saved = Signal()

    def __init__(self, settings: config.Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        title = QLabel("设置")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)

        self.outdir = QLineEdit(str(settings.output_dir or ""))
        self.outdir.setPlaceholderText("留空 = 与源文件同目录")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.outdir, 1)
        row.addWidget(browse)
        form.addRow("输出目录", row)

        self.formats: dict[str, QCheckBox] = {}
        fmt_row = QHBoxLayout()
        for key, label in (("md", "Markdown"), ("xlsx", "Excel"), ("json", "JSON"), ("html", "HTML")):
            box = QCheckBox(label)
            box.setChecked(key in settings.formats)
            self.formats[key] = box
            fmt_row.addWidget(box)
        fmt_row.addStretch(1)
        form.addRow("默认格式", fmt_row)

        self.ocr = QComboBox()
        for key, label in (("auto", "自动（仅扫描页）"), ("always", "总是 OCR"), ("never", "关闭")):
            self.ocr.addItem(label, key)
        self.ocr.setCurrentIndex(max(0, self.ocr.findData(settings.ocr)))
        form.addRow("OCR", self.ocr)

        self.theme = QComboBox()
        for key, label in (("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")):
            self.theme.addItem(label, key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        form.addRow("主题", self.theme)

        layout.addLayout(form)

        ai_title = QLabel("AI 抽取（可选）")
        ai_title.setObjectName("PageHint")
        layout.addWidget(ai_title)
        ai_form = QFormLayout()
        ai_form.setSpacing(10)
        self.provider = QComboBox()
        for key, label in (("deepseek", "DeepSeek"), ("qwen", "Qwen（百炼兼容）"), ("openai", "OpenAI 兼容")):
            self.provider.addItem(label, key)
        self.provider.setCurrentIndex(max(0, self.provider.findData(settings.provider)))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        ai_form.addRow("服务商", self.provider)

        self.model = QLineEdit(settings.model)
        self.model.setPlaceholderText("留空使用服务商默认模型")
        ai_form.addRow("模型", self.model)

        self.base_url = QLineEdit(settings.base_url)
        self.base_url.setPlaceholderText("留空使用官方地址；自建/代理请填 https://…/v1")
        ai_form.addRow("Base URL", self.base_url)

        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("粘贴 API Key 后点「保存 Key」")
        save_key = QPushButton("保存 Key")
        save_key.clicked.connect(self._save_key)
        clear_key = QPushButton("清除")
        clear_key.clicked.connect(self._clear_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        key_row.addWidget(save_key)
        key_row.addWidget(clear_key)
        ai_form.addRow("API Key", key_row)

        self.key_state = QLabel("")
        self.key_state.setObjectName("Muted")
        ai_form.addRow("", self.key_state)
        layout.addLayout(ai_form)

        note = QLabel(
            "Key 只存进系统凭据管理器（Windows 凭据管理器），不会写进配置文件；"
            "没有 Key 时所有本地功能照常可用。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        actions = QHBoxLayout()
        save = QPushButton("保存设置")
        save.setObjectName("Primary")
        save.clicked.connect(self.save)
        self.update_button = QPushButton("检查更新")
        self.update_button.clicked.connect(self.check_update)
        self.update_status = QLabel("")
        self.update_status.setObjectName("Muted")
        actions.addWidget(save)
        actions.addWidget(self.update_button)
        actions.addWidget(self.update_status, 1)
        layout.addLayout(actions)

        about = QLabel(f"PDFMend {__version__} · MIT · github.com/epoches/pdfmend")
        about.setObjectName("Muted")
        layout.addWidget(about)
        layout.addStretch(1)

        self._refresh_key_state()

    # -- helpers ---------------------------------------------------------
    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录", str(Path.home()))
        if folder:
            self.outdir.setText(folder)

    def _provider_changed(self) -> None:
        self._refresh_key_state()

    def _save_key(self) -> None:
        key = self.key.text().strip()
        if not key:
            self.key_state.setText("先粘贴 Key")
            return
        provider = self.provider.currentData()
        if config.set_api_key(provider, key):
            self.key.clear()
            self.key_state.setText(f"已保存 {provider} 的 Key（系统凭据管理器）")
        else:
            self.key_state.setText("系统凭据库不可用：可改用环境变量 " + config.ENV_KEYS[provider])

    def _clear_key(self) -> None:
        provider = self.provider.currentData()
        if config.set_api_key(provider, None):
            self.key_state.setText(f"已清除 {provider} 的 Key")
        else:
            self.key_state.setText("凭据库不可用")

    def _refresh_key_state(self) -> None:
        provider = self.provider.currentData()
        current = config.api_key(provider)
        if current:
            self.key_state.setText(f"当前：{config.masked(current)}（来自系统凭据或环境变量）")
        else:
            self.key_state.setText("当前未配置（可用环境变量 " + config.ENV_KEYS.get(provider, "") + "）")

    def save(self) -> None:
        text = self.outdir.text().strip()
        self.settings.output_dir = Path(text) if text else ""
        self.settings.formats = [key for key, box in self.formats.items() if box.isChecked()]
        self.settings.ocr = self.ocr.currentData()
        self.settings.provider = self.provider.currentData()
        self.settings.model = self.model.text().strip()
        self.settings.base_url = self.base_url.text().strip()
        theme = self.theme.currentData()
        self.settings.theme = theme
        self.update_status.setText("已保存")
        self.theme_changed.emit(theme)
        self.saved.emit()

    def check_update(self) -> None:
        self.update_button.setEnabled(False)
        self.update_status.setText("检查中…")
        try:
            request = urllib.request.Request(UPDATE_URL, headers={"User-Agent": f"pdfmend/{__version__}"})
            with urllib.request.urlopen(request, timeout=6) as response:
                data = json.loads(response.read().decode("utf-8"))
            latest = str(data.get("tag_name", "")).lstrip("v")
            if latest and latest != __version__:
                self.update_status.setText(f"有新版本 {latest}（当前 {__version__}）")
            else:
                self.update_status.setText(f"已是最新（{__version__}）")
        except Exception:  # noqa: BLE001 - offline is a normal state
            self.update_status.setText("检查失败：离线或接口不可用")
        finally:
            self.update_button.setEnabled(True)
