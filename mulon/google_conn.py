"""Connector thật đầu tiên (1.5.0): Gmail + Google Calendar.

Một lần ủy quyền Google (OAuth2) dùng chung cho 2 connector
`gmail` và `gcalendar` qua khung ở connectors.py. Spec:
``spec-google-connectors-1.5.md`` (bản sao ở thư mục làm việc
mulon-clone, không nằm trong repo).

Luật credential (cứng như khung): client id/secret từ env
GOOGLE_CLIENT_ID/SECRET hoặc Vault label google:client_id /
google:client_secret; refresh token CHỈ ở Vault label
google:refresh_token. Không giá trị bí mật nào vào kết quả
call/health/log. Health chỉ nói: configured/connected/email.
"""

from __future__ import annotations

import base64
import html
import logging
import re
import time
from email.message import EmailMessage
from typing import Awaitable, Callable, Optional
from urllib.parse import urlencode

logger = logging.getLogger("mulon.google")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL_API = "https://www.googleapis.com/calendar/v3/calendars"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
]

LBL_CLIENT_ID = "google:client_id"
LBL_CLIENT_SECRET = "google:client_secret"
LBL_REFRESH = "google:refresh_token"
LBL_EMAIL = "google:account_email"

# Transport tiêm được cho test: (method, url, params, json_body,
# headers) -> (status, dict). Mặc định là bản aiohttp dưới đây.
Transport = Callable[..., Awaitable[tuple[int, dict]]]


async def _aiohttp_transport(method, url, params=None, json_body=None,
                             headers=None):
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.request(
                method, url, params=params, json=json_body,
                headers=headers or {}) as resp:
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {}
            return resp.status, data if isinstance(data, dict) else {}


def _vault_get(store, label: str) -> Optional[str]:
    """Đọc 1 giá trị Vault theo LABEL quy ước (labels() không
    kèm giá trị; resolve() là cửa đọc duy nhất)."""
    if store is None:
        return None
    for item in store.labels():
        if item.get("label") == label:
            return store.resolve(item["ref"])
    return None


def _vault_put(store, label: str, value: str) -> None:
    """Ghi đè theo label: xoá entry cũ cùng label rồi put mới
    (Vault không có update — put luôn sinh ref mới)."""
    if store is None:
        return
    for item in store.labels():
        if item.get("label") == label:
            store.delete(item["ref"])
    if value:
        store.put(label, value)


def _vault_delete(store, label: str) -> None:
    if store is None:
        return
    for item in store.labels():
        if item.get("label") == label:
            store.delete(item["ref"])


class GoogleAuth:
    """Giữ credential + access token cho cả 2 connector."""

    def __init__(self, cfg, vault_store, transport: Transport = None):
        self.cfg = cfg
        self.vault = vault_store
        self.transport = transport or _aiohttp_transport
        self._access = ""
        self._access_exp = 0.0
        self._access_for = ""  # refresh token mà access thuộc về

    # ---------- credential ----------
    def client_id(self) -> str:
        return (self.cfg.google_client_id
                or _vault_get(self.vault, LBL_CLIENT_ID) or "")

    def client_secret(self) -> str:
        return (self.cfg.google_client_secret
                or _vault_get(self.vault, LBL_CLIENT_SECRET) or "")

    def refresh_token(self) -> str:
        return _vault_get(self.vault, LBL_REFRESH) or ""

    def account_email(self) -> str:
        return _vault_get(self.vault, LBL_EMAIL) or ""

    def configured(self) -> bool:
        return bool(self.client_id() and self.client_secret())

    def connected(self) -> bool:
        return bool(self.refresh_token())

    def status(self) -> dict:
        return {"configured": self.configured(),
                "connected": self.connected(),
                "email": self.account_email()}

    # ---------- OAuth ----------
    def redirect_uri(self) -> str:
        base = (self.cfg.webapp_url or "").rstrip("/")
        if base:
            return base + "/google/callback"
        return f"http://127.0.0.1:{self.cfg.webapp_port}/google/callback"

    def build_auth_url(self, state: str) -> str:
        q = {
            "client_id": self.client_id(),
            "redirect_uri": self.redirect_uri(),
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return AUTH_URL + "?" + urlencode(q)

    async def exchange_code(self, code: str) -> dict:
        status, data = await self.transport(
            "POST", TOKEN_URL, json_body={
                "code": code,
                "client_id": self.client_id(),
                "client_secret": self.client_secret(),
                "redirect_uri": self.redirect_uri(),
                "grant_type": "authorization_code",
            })
        if status != 200 or not data.get("refresh_token"):
            return {"ok": False,
                    "error": f"Google từ chối đổi code "
                             f"({status}): "
                             f"{_google_error(data)}"}
        _vault_put(self.vault, LBL_REFRESH, data["refresh_token"])
        self._access = ""
        # Lấy email hiển thị (best-effort, lỗi thì thôi).
        try:
            prof = await self.api("GET", GMAIL_API + "/profile")
            if prof.get("ok") and prof.get("emailAddress"):
                _vault_put(self.vault, LBL_EMAIL,
                           str(prof["emailAddress"]))
        except Exception:
            pass
        return {"ok": True, "email": self.account_email()}

    def disconnect(self) -> None:
        _vault_delete(self.vault, LBL_REFRESH)
        _vault_delete(self.vault, LBL_EMAIL)
        self._access = ""

    # ---------- access token + gọi API ----------
    async def _access_token(self, force: bool = False) -> Optional[str]:
        rt = self.refresh_token()
        if not rt:
            return None
        now = time.time()
        if (not force and self._access and self._access_for == rt
                and now < self._access_exp - 60):
            return self._access
        status, data = await self.transport(
            "POST", TOKEN_URL, json_body={
                "refresh_token": rt,
                "client_id": self.client_id(),
                "client_secret": self.client_secret(),
                "grant_type": "refresh_token",
            })
        if status != 200 or not data.get("access_token"):
            logger.warning("google refresh token lỗi (%s)", status)
            return None
        self._access = str(data["access_token"])
        self._access_for = rt
        self._access_exp = now + float(data.get("expires_in") or 3600)
        return self._access

    async def api(self, method: str, url: str, params: dict = None,
                  json_body: dict = None) -> dict:
        """Gọi Google API kèm Bearer; 401 -> ép refresh, thử lại
        đúng 1 lần. Trả dict của Google (kèm khóa ok=False +
        error khi hỏng) — không bao giờ kèm token."""
        token = await self._access_token()
        if not token:
            return {"ok": False,
                    "error": "Chưa kết nối Google hoặc refresh "
                             "token đã hỏng — kết nối lại ở Mini "
                             "App (Công cụ kết nối)."}
        headers = {"Authorization": f"Bearer {token}"}
        status, data = await self.transport(
            method, url, params=params, json_body=json_body,
            headers=headers)
        if status == 401:
            token = await self._access_token(force=True)
            if token:
                headers = {"Authorization": f"Bearer {token}"}
                status, data = await self.transport(
                    method, url, params=params,
                    json_body=json_body, headers=headers)
        if status >= 400:
            return {"ok": False,
                    "error": f"Google {status}: {_google_error(data)}"}
        out = dict(data)
        out["ok"] = True
        return out


def _google_error(data: dict) -> str:
    err = data.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("status") or err)
    if isinstance(err, str):
        desc = data.get("error_description")
        return f"{err}: {desc}" if desc else err
    return "không rõ lỗi"


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _body_text(payload: dict) -> str:
    """Bóc thân thư từ cây parts của Gmail format=full: ưu tiên
    text/plain ở bất kỳ độ sâu nào, fallback text/html đã lột
    thẻ. Cắt 8000 ký tự."""
    plain: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict):
        mime = part.get("mimeType") or ""
        body = part.get("body") or {}
        raw = body.get("data")
        if raw and mime in ("text/plain", "text/html"):
            try:
                decoded = base64.urlsafe_b64decode(
                    raw + "=" * (-len(raw) % 4)).decode(
                        "utf-8", "replace")
            except Exception:
                decoded = ""
            (plain if mime == "text/plain" else html_parts).append(
                decoded)
        for sub in part.get("parts") or []:
            walk(sub)

    walk(payload or {})
    text = "\n".join(plain).strip()
    if not text and html_parts:
        text = _strip_html("\n".join(html_parts))
    return text[:8000]


def _headers_map(payload: dict) -> dict:
    out = {}
    for h in (payload or {}).get("headers") or []:
        out[str(h.get("name", "")).lower()] = h.get("value", "")
    return out


class GmailConnector:
    name = "gmail"

    def __init__(self, auth: GoogleAuth):
        self.auth = auth

    async def health_check(self) -> dict:
        st = self.auth.status()
        if not st["configured"]:
            return {"ok": False, "name": self.name, **st,
                    "detail": "Chưa có client id/secret — nhập "
                              "vào Vault (google:client_id, "
                              "google:client_secret) hoặc đặt env "
                              "GOOGLE_CLIENT_ID/SECRET."}
        if not st["connected"]:
            return {"ok": False, "name": self.name, **st,
                    "detail": "Chưa kết nối — bấm Kết nối Google "
                              "ở màn Công cụ kết nối."}
        return {"ok": True, "name": self.name, **st,
                "detail": st["email"] or "Đã kết nối"}

    async def call(self, action: str, args: dict) -> dict:
        if action == "search":
            return await self._search(args)
        if action == "read":
            return await self._read(args)
        if action == "send":
            return await self._send(args)
        return {"ok": False,
                "error": f"gmail không hỗ trợ action: {action}"}

    async def _search(self, args: dict) -> dict:
        q = str(args.get("query") or "")
        limit = max(1, min(int(args.get("max_results") or 10), 20))
        lst = await self.auth.api(
            "GET", GMAIL_API + "/messages",
            params={"q": q, "maxResults": limit})
        if not lst.get("ok"):
            return lst
        items = []
        for m in lst.get("messages") or []:
            meta = await self.auth.api(
                "GET", f"{GMAIL_API}/messages/{m['id']}",
                params={"format": "metadata",
                        "metadataHeaders": ["Subject", "From",
                                            "Date"]})
            if not meta.get("ok"):
                continue
            hdrs = _headers_map(meta.get("payload") or {})
            items.append({
                "id": m["id"],
                "subject": hdrs.get("subject", ""),
                "from": hdrs.get("from", ""),
                "date": hdrs.get("date", ""),
                "snippet": meta.get("snippet", ""),
            })
        return {"ok": True, "count": len(items), "messages": items}

    async def _read(self, args: dict) -> dict:
        mid = str(args.get("id") or "")
        if not mid:
            return {"ok": False, "error": "thiếu id thư"}
        msg = await self.auth.api(
            "GET", f"{GMAIL_API}/messages/{mid}",
            params={"format": "full"})
        if not msg.get("ok"):
            return msg
        payload = msg.get("payload") or {}
        hdrs = _headers_map(payload)
        return {"ok": True, "id": mid,
                "subject": hdrs.get("subject", ""),
                "from": hdrs.get("from", ""),
                "to": hdrs.get("to", ""),
                "date": hdrs.get("date", ""),
                "body": _body_text(payload)}

    async def _send(self, args: dict) -> dict:
        to = str(args.get("to") or "").strip()
        subject = str(args.get("subject") or "")
        body = str(args.get("body") or "")
        if not to:
            return {"ok": False, "error": "thiếu địa chỉ người nhận"}
        em = EmailMessage()
        em["To"] = to
        em["Subject"] = subject
        em.set_content(body)
        raw = base64.urlsafe_b64encode(
            em.as_bytes()).decode("ascii")
        res = await self.auth.api(
            "POST", GMAIL_API + "/messages/send",
            json_body={"raw": raw})
        if not res.get("ok"):
            return res
        return {"ok": True, "id": res.get("id", ""),
                "thread_id": res.get("threadId", "")}


# ---------------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------------

class GCalendarConnector:
    name = "gcalendar"

    def __init__(self, auth: GoogleAuth, default_tz: str = "UTC"):
        self.auth = auth
        self.default_tz = default_tz or "UTC"

    async def health_check(self) -> dict:
        st = self.auth.status()
        if not st["configured"]:
            return {"ok": False, "name": self.name, **st,
                    "detail": "Chưa có client id/secret Google."}
        if not st["connected"]:
            return {"ok": False, "name": self.name, **st,
                    "detail": "Chưa kết nối — bấm Kết nối Google "
                              "ở màn Công cụ kết nối."}
        return {"ok": True, "name": self.name, **st,
                "detail": st["email"] or "Đã kết nối"}

    async def call(self, action: str, args: dict) -> dict:
        if action == "list_events":
            return await self._list(args)
        if action == "create_event":
            return await self._create(args)
        if action == "delete_event":
            return await self._delete(args)
        return {"ok": False,
                "error": f"gcalendar không hỗ trợ action: {action}"}

    def _cal(self, args: dict) -> str:
        return str(args.get("calendar_id") or "primary")

    async def _list(self, args: dict) -> dict:
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        tmin = str(args.get("time_min") or
                   now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        days = int(args.get("days") or 7)
        if args.get("time_max"):
            tmax = str(args["time_max"])
        else:
            start = datetime.fromisoformat(
                tmin.replace("Z", "+00:00"))
            tmax = (start + timedelta(days=days)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
        res = await self.auth.api(
            "GET", f"{CAL_API}/{self._cal(args)}/events",
            params={"timeMin": tmin, "timeMax": tmax,
                    "singleEvents": "true", "orderBy": "startTime",
                    "maxResults": int(args.get("max_results") or 20)})
        if not res.get("ok"):
            return res
        events = []
        for e in res.get("items") or []:
            events.append({
                "id": e.get("id", ""),
                "summary": e.get("summary", ""),
                "start": (e.get("start") or {}),
                "end": (e.get("end") or {}),
                "location": e.get("location", ""),
                "description": (e.get("description") or "")[:500],
            })
        return {"ok": True, "count": len(events), "events": events}

    async def _create(self, args: dict) -> dict:
        summary = str(args.get("summary") or "").strip()
        start = str(args.get("start") or "")
        end = str(args.get("end") or "")
        if not summary or not start or not end:
            return {"ok": False,
                    "error": "cần summary, start, end (RFC3339)"}
        tz = str(args.get("timezone") or self.default_tz)
        body = {"summary": summary,
                "start": {"dateTime": start, "timeZone": tz},
                "end": {"dateTime": end, "timeZone": tz}}
        if args.get("description"):
            body["description"] = str(args["description"])
        if args.get("location"):
            body["location"] = str(args["location"])
        res = await self.auth.api(
            "POST", f"{CAL_API}/{self._cal(args)}/events",
            json_body=body)
        if not res.get("ok"):
            return res
        return {"ok": True, "id": res.get("id", ""),
                "html_link": res.get("htmlLink", "")}

    async def _delete(self, args: dict) -> dict:
        eid = str(args.get("event_id") or args.get("id") or "")
        if not eid:
            return {"ok": False, "error": "thiếu event_id"}
        res = await self.auth.api(
            "DELETE",
            f"{CAL_API}/{self._cal(args)}/events/{eid}")
        if not res.get("ok"):
            return res
        return {"ok": True, "deleted": eid}


def build_google_auth(cfg, vault_store, transport=None) -> GoogleAuth:
    return GoogleAuth(cfg, vault_store, transport=transport)


def register_google_connectors(registry, cfg, vault_store,
                               transport=None):
    """Đăng ký gmail + gcalendar vào ConnectorRegistry. Factory
    dựng nhẹ, cấu hình đọc tại thời điểm dùng — owner nhập
    Vault xong dùng được ngay không cần restart."""
    auth = build_google_auth(cfg, vault_store, transport=transport)
    registry.register(GmailConnector(auth))
    registry.register(GCalendarConnector(
        auth, default_tz=getattr(cfg, "default_timezone", "UTC")))
    return auth
