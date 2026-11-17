"""About / donation dialogs and the reminder hook in the main window."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from pdfmend import licensing, usage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


def test_about_shows_author_version_and_machine(app):
    from PySide6.QtWidgets import QLabel

    from pdfmend import __version__
    from pdfmend.desktop.dialogs.about import AboutDialog

    dialog = AboutDialog()
    joined = "\n".join(lbl.text() for lbl in dialog.findChildren(QLabel))
    assert "epoch" in joined
    assert __version__ in joined
    assert licensing.machine_id() in joined
    assert "注册" in joined
    dialog.deleteLater()


def test_donation_dialog_loads_the_qr_and_mentions_the_count(app):
    from PySide6.QtWidgets import QLabel

    from pdfmend.desktop.dialogs.donation import DonationDialog, donation_pixmap

    assert not donation_pixmap(120).isNull(), "打赏码图片必须随包发布"
    dialog = DonationDialog(reminder=True, count=5)
    labels = "\n".join(lbl.text() for lbl in dialog.findChildren(QLabel))
    assert "5" in labels
    assert "微信" in labels
    dialog.deleteLater()


def test_fifth_conversion_triggers_one_reminder(app, tmp_path, monkeypatch):
    from pdfmend.config.settings import Settings, memory_store
    from pdfmend.desktop import main_window as mw

    monkeypatch.setenv("PDFMEND_TMP", str(tmp_path / "state"))
    calls: list[dict] = []
    monkeypatch.setattr(
        mw, "open_donation", lambda parent=None, **kw: calls.append(kw), raising=True
    )

    window = mw.MainWindow(settings=Settings(store=memory_store()))
    for _ in range(4):
        usage.record_success()
    window._after_convert()
    assert calls == [], "前四次不应打扰"

    usage.record_success()  # 第 5 次
    window._after_convert()
    assert len(calls) == 1 and calls[0]["count"] == 5
    assert calls[0]["reminder"] is True

    window._after_convert()  # 同一里程碑不重复弹
    assert len(calls) == 1
    window.deleteLater()


def test_registered_copy_never_prompts(app, tmp_path, monkeypatch):
    from pdfmend.desktop import main_window as mw

    monkeypatch.setenv("PDFMEND_TMP", str(tmp_path / "state"))
    code = licensing.make_code("alice", "2026-11-17", licensing.machine_id())
    assert licensing.register("alice", code, allow_server=False)[0]

    calls: list[dict] = []
    monkeypatch.setattr(mw, "open_donation", lambda parent=None, **kw: calls.append(kw))
    window = mw.MainWindow()
    for _ in range(10):
        usage.record_success()
    window._after_convert()
    assert calls == []
    window.deleteLater()
