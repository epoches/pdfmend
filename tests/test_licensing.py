"""Registration codes: derived locally, verifiable offline, server as a second opinion."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from pdfmend import licensing


def test_code_round_trip_on_the_same_machine(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFMEND_TMP", str(tmp_path / "state"))
    code = licensing.make_code("alice", date(2026, 11, 17), "A1B2C3D4E5F6")
    assert code.startswith("20261117-")
    ok, why = licensing.verify_code("alice", code, mac="A1B2C3D4E5F6")
    assert ok, why
    assert "2026-11-17" in why


def test_code_is_bound_to_user_and_machine():
    code = licensing.make_code("alice", "2026-11-17", "A1B2C3D4E5F6")
    assert not licensing.verify_code("bob", code, mac="A1B2C3D4E5F6")[0]
    assert not licensing.verify_code("alice", code, mac="FFFFFFFFFFFF")[0]


def test_code_rejects_future_dates():
    tomorrow = date.today() + timedelta(days=1)
    code = licensing.make_code("alice", tomorrow, "A1B2C3D4E5F6")
    ok, why = licensing.verify_code("alice", code, mac="A1B2C3D4E5F6")
    assert not ok and "将来" in why


def test_bad_format_and_empty_input():
    assert not licensing.verify_code("alice", "hello")[0]
    assert not licensing.verify_code("", "20261117-JVGDUGGI35PUMN7D")[0]
    assert not licensing.verify_code("alice", "")[0]


def test_admin_is_a_server_only_pair():
    ok, why = licensing.verify_code("admin", "admin", mac="A1B2C3D4E5F6")
    assert not ok and "服务器" in why


def test_register_persists_and_counts_as_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFMEND_TMP", str(tmp_path / "state"))
    monkeypatch.setenv("PDFMEND_MACHINE_ID", "A1B2C3D4E5F6")
    assert not licensing.is_registered()

    code = licensing.make_code("alice", "2026-11-17", "A1B2C3D4E5F6")
    ok, message = licensing.register("alice", code, allow_server=False)
    assert ok, message
    assert licensing.is_registered()
    assert "alice" in licensing.license_summary()

    licensing.clear_license()
    assert not licensing.is_registered()


def test_failed_registration_is_not_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFMEND_TMP", str(tmp_path / "state"))
    ok, _ = licensing.register("alice", "20261117-AAAAAAAAAAAAAAAA", allow_server=False)
    assert not ok
    assert not licensing.load_license().active


def test_server_result_parsing():
    parse = licensing._parse_flag
    assert parse({"ok": True})
    assert parse({"ok": 1})
    assert parse({"valid": "yes"})
    assert parse(True)
    assert not parse({"ok": False})
    assert not parse("nope")
    assert not parse({})


def test_machine_id_is_twelve_hex(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFMEND_MACHINE_ID", "aa:bb:cc:dd:ee:ff")
    assert licensing.machine_id() == "AABBCCDDEEFF"


@pytest.mark.parametrize("day", ["2026-01-31", "2026-11-17"])
def test_generator_and_verifier_agree(day):
    code = licensing.make_code("张三", day, "001122334455")
    # The verifier is case-insensitive about the code, not the name.
    assert licensing.verify_code("张三", code.lower(), mac="001122334455")[0]
