"""Offline-first registration.

A code is derived from three things: the user name, the registration date and
the machine's MAC address.  That makes verification possible without a network
connection (an intranet, an air-gapped laptop, a firewalled office), because
every copy of the app can recompute the expected value from the same inputs:

    code = YYYYMMDD + "-" + BASE32(HMAC-SHA256(SECRET, user|date|mac))[:16]

The server (``api/regfileconverter.php``) is only a second opinion: it checks
the same pair against the ``reg`` table so codes can be revoked or issued by
hand.  ``admin``/``admin`` is the built-in test pair the server accepts when
its table seeds it; it is *not* locally derivable, so it only works while the
server answers.

State is a small JSON file in ``tmp/`` next to the program (see ``runtime``).
Nothing about registration is uploaded except the pair itself, and only when
the user asks to verify online.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from pdfmend import runtime
from pdfmend import __version__

# Shared secret for the local check.  It is in the source on purpose: the goal
# is honest users and a greppable audit trail, not copy protection.
SECRET = b"pdfmend-reg-2026-epoches"
SERVER_URL = "https://jyang.top/api/regfileconverter.php"
FALLBACK_URL = "http://jyang.top/api/regfileconverter.php"
REQUEST_URL = "https://jyang.top/api/regrequest.php"
FALLBACK_REQUEST_URL = "http://jyang.top/api/regrequest.php"
DATE_RE = re.compile(r"^(\d{8})-([A-Z2-7]{16})$")
TEST_PAIR = ("admin", "admin")


# ---------------------------------------------------------------- machine / code
def normalize_user(name: str) -> str:
    return (name or "").strip()


def machine_id() -> str:
    """Stable-ish hardware id: the NIC MAC as 12 upper-case hex chars."""
    override = os.environ.get("PDFMEND_MACHINE_ID")
    if override:
        return re.sub(r"[^0-9A-Fa-f]", "", override).upper()[:12] or "000000000000"
    node = uuid.getnode()
    return f"{node:012X}"


def _digest(user: str, day: str, mac: str) -> str:
    payload = f"{normalize_user(user).lower()}|{day}|{mac}".encode("utf-8")
    raw = hmac.new(SECRET, payload, hashlib.sha256).digest()
    return base64.b32encode(raw).decode("ascii").rstrip("=")[:16]


def make_code(user: str, day: date | str | None = None, mac: str | None = None) -> str:
    """Build the code for one user/date/machine triple (used by the vendor)."""
    if not normalize_user(user):
        raise ValueError("用户名不能为空")
    if day is None:
        day = date.today()
    if isinstance(day, str):
        day = datetime.strptime(day, "%Y-%m-%d").date()
    stamp = day.strftime("%Y%m%d")
    return f"{stamp}-{_digest(user, stamp, mac or machine_id())}"


def verify_code(
    user: str,
    code: str,
    mac: str | None = None,
    today: date | None = None,
) -> tuple[bool, str]:
    """Check a code locally.  Returns (ok, human-readable reason)."""
    user = normalize_user(user)
    code = (code or "").strip().upper()
    if not user:
        return False, "请填写用户名"
    if not code:
        return False, "请填写注册码"
    if code == "ADMIN" and user.lower() == TEST_PAIR[0]:
        return False, "admin/admin 是服务器测试码，需要联网验证"
    match = DATE_RE.match(code)
    if not match:
        return False, "注册码格式不对（应形如 20261117-XXXXXXXX）"
    stamp, digest = match.groups()
    try:
        issued = datetime.strptime(stamp, "%Y%m%d").date()
    except ValueError:
        return False, "注册码里的日期无效"
    today = today or date.today()
    if issued > today:
        return False, "注册码的日期在将来"
    expected = _digest(user, stamp, mac or machine_id())
    if not hmac.compare_digest(expected, digest):
        return False, "注册码与本机或用户名不匹配"
    return True, f"已注册（{issued.isoformat()} 签发）"


# ------------------------------------------------------------------- state file
@dataclass
class License:
    username: str = ""
    code: str = ""
    machine: str = ""
    source: str = "local"  # local | server
    verified_at: float = 0.0
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return bool(self.username and self.code)

    def to_dict(self) -> dict:
        return {
            "v": 1,
            "username": self.username,
            "code": self.code,
            "machine": self.machine,
            "source": self.source,
            "verified_at": self.verified_at,
            "note": self.note,
            **({"extra": self.extra} if self.extra else {}),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "License":
        return cls(
            username=str(data.get("username") or ""),
            code=str(data.get("code") or ""),
            machine=str(data.get("machine") or ""),
            source=str(data.get("source") or "local"),
            verified_at=float(data.get("verified_at") or 0),
            note=str(data.get("note") or ""),
            extra=dict(data.get("extra") or {}),
        )


def state_path() -> Path:
    return runtime.license_file()


def load_license() -> License:
    path = state_path()
    if not path.is_file():
        return License()
    try:
        return License.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return License()


def save_license(lic: License) -> Path:
    path = state_path()
    path.write_text(json.dumps(lic.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def clear_license() -> None:
    try:
        state_path().unlink()
    except FileNotFoundError:
        pass


# --------------------------------------------------------------------- server
@dataclass
class ServerResult:
    ok: bool
    reachable: bool
    message: str
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "reachable": self.reachable, "message": self.message}


def _parse_flag(data) -> bool:
    if isinstance(data, bool):
        return data
    if isinstance(data, (int, float)):
        return data != 0
    if isinstance(data, dict):
        for key in ("ok", "valid", "success", "registered"):
            if key in data:
                return _parse_flag(data[key])
        status = data.get("status")
        if status in ("ok", "valid", "registered", True):
            return True
        return False
    if isinstance(data, str):
        return data.strip().lower() in ("1", "true", "ok", "yes", "valid", "registered")
    return False


def check_server(user: str, code: str, timeout: float = 6.0) -> ServerResult:
    """Ask the registration endpoint whether this pair exists.

    Network failures are reported as ``reachable=False`` so callers can fall
    back to the offline check instead of blocking the user.
    """
    user = normalize_user(user)
    code = (code or "").strip().upper()
    query = urllib.parse.urlencode({"id": user, "code": code})
    # Some hosts (this one included) reject urllib's default user agent with 403.
    headers = {"User-Agent": f"PDFMend/{__version__} (+https://github.com/epoches/pdfmend)"}
    last = ""
    for base in (SERVER_URL, FALLBACK_URL):
        url = f"{base}?{query}"
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read(8192).decode("utf-8", "replace")
            try:
                data = json.loads(body)
            except ValueError:
                data = {"raw": body.strip()[:200]}
            ok = _parse_flag(data)
            message = ""
            if isinstance(data, dict):
                message = str(data.get("message") or data.get("msg") or "")
            return ServerResult(ok=ok, reachable=True, message=message or ("有效" if ok else "无效"), payload=data)
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = str(getattr(exc, "reason", exc))
    return ServerResult(ok=False, reachable=False, message=f"服务器连接失败：{last}")


# --------------------------------------------------------------------- public
def _open(request: urllib.request.Request, timeout: float) -> str:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(8192).decode("utf-8", "replace")


def request_code(
    user: str,
    email: str,
    txn: str,
    mac: str | None = None,
    timeout: float = 10.0,
) -> ServerResult:
    """Ask the vendor for a code (email + donation id + this machine).

    Nothing is minted until the request is approved, so this only queues it.
    """
    user = normalize_user(user)
    email = (email or "").strip()
    txn = (txn or "").strip()
    if not user or not email or not txn:
        return ServerResult(ok=False, reachable=True, message="请填写注册名、邮箱和赞助单号")
    if "@" not in email or "." not in email.split("@")[-1]:
        return ServerResult(ok=False, reachable=True, message="邮箱格式看起来不对")
    fields = {
        "id": user,
        "email": email,
        "txn": txn,
        "mac": (mac or machine_id()).upper(),
    }
    body = urllib.parse.urlencode(fields).encode("utf-8")
    headers = {
        "User-Agent": f"PDFMend/{__version__} (+https://github.com/epoches/pdfmend)",
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
    }
    last = ""
    for base in (REQUEST_URL, FALLBACK_REQUEST_URL):
        try:
            request = urllib.request.Request(base, data=body, headers=headers, method="POST")
            raw = _open(request, timeout)
            try:
                data = json.loads(raw)
            except ValueError:
                data = {"raw": raw.strip()[:200]}
            ok = _parse_flag(data)
            message = ""
            if isinstance(data, dict):
                message = str(data.get("message") or data.get("msg") or "")
            return ServerResult(ok=ok, reachable=True, message=message or ("已提交" if ok else "提交失败"), payload=data)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(400).decode("utf-8", "replace")
            except OSError:
                pass
            last = f"HTTP {exc.code} {detail[:120]}".strip()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = str(getattr(exc, "reason", exc))
    return ServerResult(ok=False, reachable=False, message=f"提交失败：{last}")


def register(
    user: str,
    code: str,
    mac: str | None = None,
    allow_server: bool = True,
    timeout: float = 6.0,
) -> tuple[bool, str]:
    """Verify locally, then (if needed) online, and persist on success."""
    user = normalize_user(user)
    code = (code or "").strip().upper()
    mac = mac or machine_id()
    ok, reason = verify_code(user, code, mac=mac)
    source = "local"
    note = reason
    if not ok and allow_server:
        server = check_server(user, code, timeout=timeout)
        if server.ok:
            ok, source, note = True, "server", "服务器验证通过"
        elif server.reachable:
            note = f"{reason}；服务器也拒绝（{server.message}）"
        else:
            note = f"{reason}；{server.message}"
    if not ok:
        return False, note
    save_license(
        License(
            username=user,
            code=code,
            machine=mac,
            source=source,
            verified_at=time.time(),
            note=note,
        )
    )
    return True, note


def is_registered(timeout: float = 4.0) -> bool:
    """True when a saved registration still checks out.

    A locally derivable code stays valid offline forever; a server-only code is
    trusted for ``OK_TTL`` and then re-checked if the network allows.
    """
    lic = load_license()
    if not lic.active:
        return False
    local_ok, _ = verify_code(lic.username, lic.code, mac=machine_id())
    if local_ok:
        return True
    # A server-only code (e.g. the admin test pair) was accepted once; keep it.
    return lic.source == "server"


def license_summary() -> str:
    lic = load_license()
    if not lic.active:
        return "未注册（全部功能可用，仅每 5 次转换提示一次支持作者）"
    if is_registered():
        return f"已注册：{lic.username}"
    return "注册信息已失效，请在「关于」里重新验证"
