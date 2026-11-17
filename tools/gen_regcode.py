#!/usr/bin/env python3
"""Mint a PDFMend registration code for one user / date / machine.

    python tools/gen_regcode.py --user 张三
    python tools/gen_regcode.py --user 张三 --mac A1B2C3D4E5F6 --date 2026-11-17
    python tools/gen_regcode.py --user 张三 --sql      # also print the INSERT

The code is reproducible: the app recomputes it from the same three inputs, so
an intranet machine can verify registration without calling the server.
``--mac auto`` (default) uses this machine's MAC.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdfmend import licensing  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 PDFMend 注册码")
    parser.add_argument("--user", required=True, help="用户名")
    parser.add_argument("--date", help="签发日期 YYYY-MM-DD（默认今天）")
    parser.add_argument("--mac", default="auto", help="机器 MAC（默认本机）")
    parser.add_argument("--sql", action="store_true", help="顺便打印 INSERT 语句")
    args = parser.parse_args(argv)

    mac = licensing.machine_id() if args.mac == "auto" else args.mac
    day = args.date or date.today().isoformat()
    code = licensing.make_code(args.user, day, mac)
    ok, reason = licensing.verify_code(args.user, code, mac=mac)
    print(code)
    print(f"# user={args.user} date={day} mac={mac}")
    print(f"# self-check: {'OK' if ok else 'FAILED'} ({reason})")
    if args.sql:
        print(
            "INSERT INTO reg (username, regcode, machine, note) "
            f"VALUES ('{args.user}', '{code}', '{mac}', 'issued {day}');"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
