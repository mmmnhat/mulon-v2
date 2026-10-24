"""Mini App server (1.2.0) — backend cho bảng điều khiển Mulon.

Một aiohttp app nhỏ chạy CÙNG process bot, bind 127.0.0.1 cổng
WEBAPP_PORT. Telegram mở Mini App qua Direct Link
(https://t.me/<bot>/<app>?startapp=...) trỏ tới WEBAPP_URL (URL
HTTPS công khai, thường là tunnel về cổng này).

BẢO MẬT (bắt buộc, không có ngoại lệ):
- Mọi /api/* phải có header ``X-Telegram-Init-Data`` hợp lệ:
  chữ ký HMAC-SHA256 theo chuẩn Telegram WebApp (secret key =
  HMAC_SHA256(key="WebAppData", msg=bot_token)), ``auth_date``
  không quá 1 giờ, và ``user.id`` == ALLOWED_USER_ID. Sai bất
  kỳ điều nào -> 401/403.
- Không payload nào chứa giá trị bí mật Vault — chỉ nhãn + ref.
- Server chỉ bind localhost; lớp HTTPS/tunnel là việc của host.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import logging
import platform
import socket
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl

from . import __version__ as MULON_VERSION
from .approvals import GROUP_SCOPE_LABELS
from .cron import parse_cron
from .feed_auto import valid_quiet_hours
from .planning import internal_kind
from .proactivity import PROACTIVITY_KV_KEY, effective_enabled

logger = logging.getLogger("mulon.webapp")

try:
    from aiohttp import web

    HAS_AIOHTTP = True
except Exception:  # pragma: no cover - môi trường thiếu gói
    web = None  # type: ignore
    HAS_AIOHTTP = False

INIT_DATA_MAX_AGE_S = 3600
INDEX_HTML = Path(__file__).resolve().parent / "webapp" / "index.html"
WEBAPP_DIR = Path(__file__).resolve().parent / "webapp"
# Asset tĩnh của Mini App (1.3.0): atlas sprite states của avatar
# + manifest hình học đi kèm. Chỉ phục vụ đúng 2 file trong danh
# sách trắng này — không mở đường duyệt thư mục.
STATIC_ASSETS = {
    "sprite-sheet-alpha.png": "image/png",
    "mulon-states-manifest.json": "application/json",
}

# Màu chủ đề Mini App: chỉ đổi HỌ màu nhận diện (lớp 30% — tím
# Mulon và các hue thay thế). Accent hành động chính (10%) là
# bậc đậm nhất của chính hue đang chọn, suy ra ở frontend —
# không có hue riêng. Danh sách này phải khớp THEMES ở
# frontend (index.html).
THEME_KEYS = ("lavender", "blue", "pink", "peach", "green",
              "graphite")
DEFAULT_THEME = "lavender"
THEME_KV_KEY = "webapp_theme"

PROXY_HOST, PROXY_PORT = "127.0.0.1", 8317
PROXY_CACHE_TTL_S = 5.0


# ---------------------------------------------------------------------------
# Validate initData (thuần — test được không cần server)
# ---------------------------------------------------------------------------

def validate_init_data(init_data: str, bot_token: str,
                       allowed_user_id: int,
                       max_age_s: int = INIT_DATA_MAX_AGE_S,
                       now: Optional[float] = None) -> Optional[dict]:
    """Kiểm initData của Telegram WebApp. Hợp lệ -> dict user;
    sai chữ ký / hết hạn / sai user / thiếu trường -> None."""
    if not init_data or not bot_token or not allowed_user_id:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
    except Exception:
        return None
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None
    check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"),
                      hashlib.sha256).digest()
    calc = hmac.new(secret, check_string.encode("utf-8"),
                    hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        return None
    now = time.time() if now is None else now
    try:
        auth_date = int(data.get("auth_date") or 0)
    except ValueError:
        return None
    if not auth_date or now - auth_date > max_age_s \
            or auth_date - now > 300:
        return None
    try:
        user = json.loads(data.get("user") or "{}")
    except Exception:
        return None
    if not isinstance(user, dict) or int(user.get("id") or 0) \
            != int(allowed_user_id):
        return None
    return user


# ---------------------------------------------------------------------------
# Nhãn trạng thái LỜI THƯỜNG — một bảng ánh xạ duy nhất dùng cho
# cả dòng trạng thái trong chat lẫn header Mini App. Mặt chat/app
# không bao giờ lộ tên tool thô (run_command...) — tên thô chỉ
# xuất hiện ở màn chi tiết lượt việc.
# ---------------------------------------------------------------------------

TOOL_STEP_LABELS = {
    "run_command": "Đang chạy lệnh",
    "read_file": "Đang đọc file",
    "write_file": "Đang ghi file",
    "edit_file": "Đang sửa file",
    "list_files": "Đang liệt kê file",
    "web_fetch": "Đang đọc web",
    "web_read": "Đang đọc web",
    "web_search": "Đang tìm trên web",
    "web_screenshot": "Đang chụp trang web",
    "now": "Đang xem giờ",
    "connector_health": "Đang kiểm tra kết nối",
    "connector_call": "Đang gọi dịch vụ ngoài",
    "session_search": "Đang tra ký ức",
    "spawn_subagent": "Đang giao việc cho agent con",
    "skill_list": "Đang tra kỹ năng",
    "skill_read": "Đang đọc kỹ năng",
}

GROUP_STEP_LABELS = {
    "shell": "Đang chạy lệnh",
    "file": "Đang xử lý file",
    "web": "Đang đọc web",
    "outbound": "Đang gửi tin nhắn",
    "connector": "Đang gọi dịch vụ ngoài",
    "media": "Đang xử lý media",
    "agent": "Đang giao việc con",
    "skills": "Đang tra kỹ năng",
    "memory": "Đang tra ký ức",
    "schedule": "Đang xử lý lịch hẹn",
    "goals": "Đang xử lý mục tiêu",
}

EVENT_STEP_LABELS = {
    "task_start": "Đang làm việc",
    "verify": "Đang kiểm chứng",
    "retry": "Đang làm lại",
    "approval_requested": "Đang chờ duyệt",
    "task_done": "Sẵn sàng",
}

TOOL_ACTION_LABELS = {
    "run_command": "Chạy lệnh hệ thống",
    "read_file": "Đọc file",
    "write_file": "Ghi file",
    "edit_file": "Sửa file",
    "web_fetch": "Đọc trang web",
    "web_read": "Đọc trang web",
    "web_search": "Tìm trên web",
    "connector_call": "Gọi dịch vụ ngoài",
    "spawn_subagent": "Giao việc cho agent con",
    "send_message": "Gửi tin nhắn",
    "github_push": "Đẩy lên GitHub",
    "the_duyet": "Gửi thẻ phê duyệt thử",
}


def plain_step_label(kind: str, payload: Optional[dict] = None) -> str:
    """Ánh xạ 1 event của agent -> cụm động từ tiếng Việt ngắn."""
    payload = payload or {}
    if kind == "tool_start":
        tool = str(payload.get("tool") or "")
        if tool in TOOL_STEP_LABELS:
            return TOOL_STEP_LABELS[tool]
        if tool.startswith("media_"):
            return "Đang xử lý media"
        if tool.startswith("schedule"):
            return "Đang xử lý lịch hẹn"
        group = str(payload.get("group") or "")
        return GROUP_STEP_LABELS.get(group, "Đang xử lý")
    return EVENT_STEP_LABELS.get(kind, "")


_GROUP_ACTION_LABELS = {
    "shell": "Chạy lệnh hệ thống",
    "web": "Đọc trang web",
    "file": "Thao tác file",
    "outbound": "Gửi tin nhắn",
}


def known_action_label(tool: str, group: str = "") -> str:
    """Nhãn hành động lời thường ĐÃ BIẾT cho 1 tool: tra bảng
    theo tool trước, theo nhóm sau. Không có nhãn nào khớp ->
    "" để bề mặt tự fallback về tên tool thô (vẫn truy vết
    được ở dòng chi tiết) thay vì bịa nhãn."""
    if tool in TOOL_ACTION_LABELS:
        return TOOL_ACTION_LABELS[tool]
    return _GROUP_ACTION_LABELS.get(group, "")


def tool_action_label(tool: str, group: str = "") -> str:
    """Tên hành động lời thường cho dòng 1 của thẻ duyệt."""
    label = known_action_label(tool, group)
    if label:
        return label
    return f"Dùng công cụ {tool}"


def policy_group_label(group: str) -> str:
    """Nhãn tiếng Việt của 1 nhóm policy cho màn Quyền: dùng
    lại GROUP_SCOPE_LABELS (nguồn nhãn nhóm của thẻ duyệt trên
    chat, ở dạng danh từ) viết hoa chữ đầu. Nhóm lạ (vd
    "mcp:<server>") -> "" để frontend fallback về key thô."""
    raw = GROUP_SCOPE_LABELS.get(group or "", "")
    if not raw:
        return ""
    return raw[:1].upper() + raw[1:]


# ---------------------------------------------------------------------------
# Theo dõi hoạt động (header trạng thái + tab Việc)
# ---------------------------------------------------------------------------

class ActivityTracker:
    """Trạng thái sống tối thiểu cho Mini App: lượt đang chạy +
    bước hiện tại. Bề mặt Telegram cập nhật; server chỉ đọc."""

    def __init__(self):
        self.current: Optional[dict] = None

    def start_turn(self, session_key: str, text: str) -> None:
        self.current = {
            "session_key": session_key,
            "title": (text or "")[:120],
            "step": "Đang xử lý…",
            "started_at": time.time(),
        }

    def set_step(self, label: str) -> None:
        if self.current is not None:
            self.current["step"] = label

    def end_turn(self) -> None:
        self.current = None

    def snapshot(self) -> dict:
        if self.current is None:
            return {"busy": False, "label": "Sẵn sàng", "current": None}
        return {"busy": True,
                "label": self.current.get("step") or "Đang xử lý",
                "current": dict(self.current)}


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class WebAppServer:
    def __init__(self, cfg, *, memory, policy, broker, connectors,
                 mcp_manager, vault_store, registry, dossier=None,
                 skills=None, activity: Optional[ActivityTracker] = None,
                 marketplace=None, feed_auto=None, google_auth=None,
                 library=None):
        self.cfg = cfg
        self.memory = memory
        self.policy = policy
        self.broker = broker
        self.connectors = connectors
        self.mcp = mcp_manager
        self.vault_store = vault_store
        self.registry = registry
        self.dossier = dossier
        self.skills = skills
        self.library = library
        # Marketplace 1.3.0 (mulon.marketplace) — None thì toàn bộ
        # /api/marketplace/* trả 503 sạch, màn Kết nối giữ hành vi cũ.
        self.marketplace = marketplace
        # Feed chủ động 1.4.0 (mulon.feed_auto.FeedAutoRunner) —
        # None thì block state "feed" là None và /api/feed trả 503.
        # KHÔNG có action tắt Feed ở API này (quyết định 0.2b).
        self.feed_auto = feed_auto
        # Google connectors 1.5.0 (mulon.google_conn.GoogleAuth)
        # — None thì /api/google/* trả 503 và /google/callback
        # trả trang báo chưa nối.
        self.google_auth = google_auth
        self.activity = activity or ActivityTracker()
        self._runner = None
        self._site = None
        # Mốc start của tiến trình webapp (uptime cho thẻ hệ thống)
        # + cache kiểm tra proxy 8317 (tránh probe mỗi lần poll).
        self._started_at = time.time()
        self._proxy_cache: Optional[tuple] = None

    # ---------- vòng đời ----------
    @property
    def port(self) -> int:
        if self._site is not None:
            return int(self._site._server.sockets[0].getsockname()[1])
        return int(self.cfg.webapp_port)

    @property
    def running(self) -> bool:
        return self._runner is not None

    def build_app(self):
        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp chưa được cài")

        @web.middleware
        async def _auth(request, handler):
            return await self._auth_middleware(request, handler)

        app = web.Application(middlewares=[_auth])
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/a", self._handle_index)
        app.router.add_get("/a/", self._handle_index)
        app.router.add_get("/app", self._handle_index)
        app.router.add_get("/app/", self._handle_index)
        app.router.add_get("/panel", self._handle_index)
        app.router.add_get("/app/avatar", self._handle_avatar)
        app.router.add_get("/app/assets/{name}",
                           self._handle_static_asset)
        app.router.add_get("/api/state", self._handle_state)
        app.router.add_get("/api/task", self._handle_task)
        app.router.add_get("/api/profile/content",
                           self._handle_profile_content)
        app.router.add_post("/api/policy", self._handle_policy)
        app.router.add_post("/api/connector", self._handle_connector)
        app.router.add_post("/api/approve", self._handle_approve)
        app.router.add_post("/api/schedule", self._handle_schedule)
        # 1.4.0: điều khiển Feed chủ động (không có action tắt).
        app.router.add_post("/api/feed", self._handle_feed)
        app.router.add_post("/api/profile/theme", self._handle_theme)
        # 1.3.0 (gói vá Mini App): kỹ năng đọc được + Vault nhập
        # ngay trong app — cùng middleware auth initData.
        app.router.add_get("/api/skills", self._handle_skills)
        app.router.add_get("/api/skills/{name}",
                           self._handle_skill_detail)
        app.router.add_post("/api/vault/capture",
                            self._handle_vault_capture)
        # 1.5.0: Google OAuth — auth-url + disconnect qua auth
        # initData như mọi /api/*; callback là route CÔNG KHAI
        # duy nhất (trình duyệt ngoài quay về từ Google, bảo vệ
        # bằng state nonce dùng 1 lần, xem _handle_google_callback).
        app.router.add_get("/api/google/auth-url",
                           self._handle_google_auth_url)
        app.router.add_post("/api/google/disconnect",
                            self._handle_google_disconnect)
        app.router.add_get("/google/callback",
                           self._handle_google_callback)
        # 1.3.0: Chợ MCP — mọi route qua cùng middleware auth
        # initData owner-only như các /api/* khác.
        app.router.add_get("/api/marketplace/summary",
                           self._mkt_summary)
        app.router.add_get("/api/marketplace/categories",
                           self._mkt_categories)
        app.router.add_get("/api/marketplace/catalog",
                           self._mkt_catalog)
        app.router.add_get(
            "/api/marketplace/listings/{provider}/{slug}",
            self._mkt_listing)
        app.router.add_get("/api/marketplace/installed",
                           self._mkt_installed)
        app.router.add_get("/api/marketplace/installed/{name}",
                           self._mkt_installed_detail)
        app.router.add_get("/api/marketplace/operations/{id}",
                           self._mkt_operation)
        app.router.add_post("/api/marketplace/refresh",
                            self._mkt_refresh)
        app.router.add_post("/api/marketplace/import/parse",
                            self._mkt_import_parse)
        app.router.add_post("/api/marketplace/install/prepare",
                            self._mkt_prepare)
        app.router.add_post(
            "/api/marketplace/operations/{id}/bind-secrets",
            self._mkt_bind_secrets)
        app.router.add_post(
            "/api/marketplace/operations/{id}/request-probe-approval",
            self._mkt_request_probe)
        app.router.add_post(
            "/api/marketplace/operations/{id}/request-commit-approval",
            self._mkt_request_commit)
        app.router.add_post("/api/marketplace/operations/{id}/cancel",
                            self._mkt_cancel)
        app.router.add_post(
            "/api/marketplace/installed/{name}/health-check",
            self._mkt_health_check)
        app.router.add_post("/api/marketplace/installed/{name}/enable",
                            self._mkt_enable)
        app.router.add_post("/api/marketplace/installed/{name}/disable",
                            self._mkt_disable)
        app.router.add_post(
            "/api/marketplace/installed/{name}/update/check",
            self._mkt_update_check)
        app.router.add_post(
            "/api/marketplace/installed/{name}/update/prepare",
            self._mkt_update_prepare)
        app.router.add_post(
            "/api/marketplace/installed/{name}/uninstall/prepare",
            self._mkt_uninstall_prepare)
        # 1.6.0: Chia sẻ tài liệu / Artifacts công khai không qua auth
        app.router.add_get("/share/{token}", self._handle_public_share)
        # 1.6.0: Library management API cho Mini App
        app.router.add_get("/api/library/items", self._handle_library_items)
        app.router.add_post("/api/library/items/{id}/pin", self._handle_library_pin)
        app.router.add_post("/api/library/items/{id}/rename", self._handle_library_rename)
        app.router.add_post("/api/library/items/{id}/share", self._handle_library_share)
        # 1.6.0: One-click MCP Install
        app.router.add_post(
            "/api/marketplace/operations/{id}/install-now",
            self._mkt_install_now)
        return app

    async def start(self) -> bool:
        if not HAS_AIOHTTP:
            logger.warning("thiếu aiohttp — Mini App server TẮT")
            return False
        if self._runner is not None:
            return True
        self._runner = web.AppRunner(self.build_app())
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1",
                                 int(self.cfg.webapp_port))
        await self._site.start()
        logger.info("Mini App server: http://127.0.0.1:%d/app",
                    self.port)
        return True

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    # ---------- auth ----------
    async def _auth_middleware(self, request, handler):
        if request.path.startswith("/api/"):
            init_data = request.headers.get("X-Telegram-Init-Data", "")
            user = validate_init_data(
                init_data, self.cfg.telegram_bot_token,
                self.cfg.allowed_user_id)
            if user is None:
                return web.json_response(
                    {"ok": False, "error": "initData không hợp lệ "
                                           "hoặc không phải chủ nhân"},
                    status=403)
            request["tg_user"] = user
        return await handler(request)

    # ---------- trang tĩnh ----------
    async def _handle_index(self, request):
        if not INDEX_HTML.exists():
            return web.Response(status=404, text="thiếu index.html")
        return web.FileResponse(INDEX_HTML)

    async def _handle_static_asset(self, request):
        """Phục vụ asset tĩnh trong danh sách trắng STATIC_ASSETS
        (atlas sprite + manifest). Tên ngoài danh sách -> 404."""
        name = str(request.match_info.get("name") or "")
        ctype = STATIC_ASSETS.get(name)
        if ctype is None:
            return web.Response(status=404, text="asset lạ")
        path = WEBAPP_DIR / "assets" / name
        if not path.is_file():
            return web.Response(status=404, text="thiếu asset")
        resp = web.FileResponse(path)
        resp.content_type = ctype
        # Atlas/manifest bất biến theo bản phát hành — cho trình
        # duyệt cache để avatar không tải lại 1.2MB mỗi lần mở app.
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    async def _handle_avatar(self, request):
        path = Path(self.cfg.dossier_dir).parent / "assets" \
            / "mulon-avatar.webp"
        if path.exists():
            return web.FileResponse(path)
        return web.Response(status=404, text="no avatar")

    # ---------- state ----------
    async def _connectors_state(self) -> list[dict]:
        out: list[dict] = []
        try:
            health = await self.connectors.health_all()
        except Exception:
            health = {}
        for name in self.connectors.names():
            h = health.get(name) or {}
            item = {
                "id": name, "name": name, "kind": "builtin",
                "ok": bool(h.get("ok")), "enabled": True,
                "toggleable": False,
                "detail": str(h.get("error") or h.get("detail") or ""),
            }
            if name in ("gmail", "gcalendar") \
                    and self.google_auth is not None:
                # 1.5.0: frontend vẽ nút Kết nối/Ngắt kết nối
                # theo trạng thái này (cả 2 connector dùng
                # chung 1 ủy quyền Google).
                item["google"] = self.google_auth.status()
            out.append(item)
        # MCP servers: trạng thái nối từ manager + enabled từ file
        # cấu hình (đọc tươi để toggle phản ánh đúng).
        if self.mcp is not None:
            from .mcp_client import load_server_configs

            entries = load_server_configs(self.mcp.config_path)
            status = self.mcp.status()
            managed = {}
            if self.marketplace is not None:
                managed = {r["local_name"]: r for r in
                           self.marketplace.installed_list()}
            for entry in entries:
                name = str(entry.get("name"))
                st = status.get(name) or {}
                item = {
                    "id": f"mcp:{name}", "name": name, "kind": "mcp",
                    "ok": bool(st.get("connected")),
                    "enabled": bool(entry.get("enabled", False)),
                    "toggleable": True,
                    "detail": str(st.get("error") or ""),
                }
                record = managed.get(name)
                if record is not None:
                    # Server do marketplace quản lý: UI hiện vòng
                    # đời + sức khoẻ thay cho trạng thái nối thô.
                    item["managed"] = True
                    item["lifecycle_state"] = record[
                        "lifecycle_state"]
                    item["health_state"] = record["health_state"]
                    item["pending_restart"] = record[
                        "pending_restart"]
                out.append(item)
        return out

    def _policy_state(self) -> dict:
        desc = self.policy.describe()
        groups = sorted({
            *(desc["groups"].keys()), *(desc["session_groups"].keys()),
            *(spec.group for spec in self.registry.specs() if spec.group),
        })
        # Nhóm có tiền tố (mcp:<server>, connector:<tên>) không
        # liệt kê ở mục Nhóm việc nữa — chúng có mục riêng
        # "Connector & server MCP" ngay dưới, tên đọc được.
        groups = [g for g in groups
                  if not g.startswith(("mcp:", "connector:"))]
        tools = sorted({
            *(desc["tools"].keys()),
            *(desc["session_tools"].keys()),
            *self.registry.names(),
        })
        # Quyền RIÊNG từng connector/server (đợt vá sau 1.4 —
        # trước đây màn Quyền không có mục nào cho connector).
        # Danh sách lấy từ trạng thái sống nên cài thêm cái nào
        # là tự xuất hiện.
        connectors: dict[str, str] = {}
        for name in self.connectors.names():
            key = f"connector:{name}"
            connectors[key] = self.policy.decide("", key).verdict
        if self.mcp is not None:
            try:
                from .mcp_client import load_server_configs
                for entry in load_server_configs(self.mcp.config_path):
                    key = f"mcp:{entry.get('name')}"
                    connectors[key] = self.policy.decide(
                        "", key).verdict
            except Exception:
                pass
        return {
            "default": desc["default"],
            "groups": {
                g: self.policy.decide("", g).verdict for g in groups},
            "group_labels": {
                g: label for g in groups
                if (label := policy_group_label(g))},
            "connectors": connectors,
            "connector_labels": {
                k: k.split(":", 1)[1] for k in connectors},
            "tools": {
                t: self.policy.decide(
                    t, (self.registry.get(t).group
                        if self.registry.get(t) else "")).verdict
                for t in tools},
            "host": desc,
            "connector_specs": desc.get("connector_specs", {}),
        }

    async def _schedule_state(self) -> dict:
        items: list[dict] = []
        try:
            rows = await self.memory.list_schedules()
        except Exception:
            rows = []
            available = False
        else:
            available = True
        for r in rows:
            # Schema thật của schedules: payload (không có
            # title/prompt) — NC-3: tên lịch lấy từ payload.
            payload = str(r.get("payload") or "")
            internal = internal_kind(payload)
            if internal is not None:
                # Job hệ thống nội bộ (1.4): hiển thị minh bạch
                # nhưng KHÔNG toggle được ở tab Lịch — điều
                # khiển ở Cài đặt → Feed chủ động.
                items.append({
                    "id": str(r.get("id")),
                    "name": "Feed chủ động (tự động)",
                    "cron": r.get("cron", ""),
                    "prompt": "Job hệ thống: tự viết bài Feed "
                              "theo lịch. Điều khiển ở Cài đặt → "
                              "Feed chủ động.",
                    "enabled": bool(r.get("enabled")),
                    "next_run_at": r.get("next_run_at") or "",
                    "last_run_at": r.get("last_run_at") or "",
                    "toggleable": False, "kind": "feed_auto",
                })
                continue
            items.append({
                "id": str(r.get("id")),
                "name": payload[:60] or str(r.get("id")),
                "cron": r.get("cron", ""),
                "prompt": payload[:120],
                "enabled": bool(r.get("enabled")),
                "next_run_at": r.get("next_run_at") or "",
                "last_run_at": r.get("last_run_at") or "",
                "toggleable": True, "kind": "schedule",
            })
        items.append({
            "id": "heartbeat", "name": "Heartbeat chủ động",
            "cron": f"mỗi {self.cfg.proactivity_interval_s}s",
            "prompt": "Quét checklist HEARTBEAT.md — gạt công tắc "
                      "là áp dụng ngay, không cần sửa .env, "
                      "không cần khởi động lại.",
            "enabled": await effective_enabled(self.memory,
                                               self.cfg),
            "next_run_at": "", "last_run_at": "",
            "toggleable": True, "kind": "heartbeat",
        })
        scheduler_on = bool(self.cfg.scheduler_enabled)
        return {"available": available, "scheduler_enabled": scheduler_on,
                # 1.4: tab Lịch cần biết vòng tick vẫn chạy cho job
                # nội bộ dù scheduler thường tắt (tránh banner
                # "scheduler đang tắt" gây hiểu nhầm cho Feed).
                "feed_auto": self.feed_auto is not None,
                "items": items}

    async def _profile_state(self) -> dict:
        import os

        files = []
        if self.dossier is not None:
            base = Path(self.cfg.dossier_dir)
            for name in sorted(self.dossier.files):
                updated = ""
                fpath = base / name
                if fpath.exists():
                    import datetime

                    updated = datetime.datetime.fromtimestamp(
                        os.path.getmtime(fpath)).isoformat(
                        timespec="seconds")
                files.append({"name": name, "updated_at": updated,
                              "chars": len(self.dossier.files[name])})
        facts = 0
        try:
            facts = len(await self.memory.active_facts(limit=10000))
        except Exception:
            pass
        skills_info = {"available": False, "count": 0, "names": []}
        if self.skills is not None:
            try:
                names = self.skills.visible_names()
                skills_info = {"available": True, "count": len(names),
                               "names": names}
            except Exception:
                pass
        theme = DEFAULT_THEME
        if self.memory is not None:
            try:
                stored = await self.memory.kv_get(THEME_KV_KEY)
                if stored in THEME_KEYS:
                    theme = stored
            except Exception:
                pass
        return {"dossier_files": files, "facts_active": facts,
                "skills": skills_info, "theme": theme}

    async def _probe_proxy(self) -> dict:
        """Kiểm tra proxy model 127.0.0.1:8317 bằng TCP connect
        (timeout ngắn, cache vài giây). Kết quả trung thực:
        nối được -> ok; bị từ chối (cổng đóng) -> down; còn lại
        (timeout/lỗi lạ) -> unknown "không kiểm được", không đoán."""
        now = time.time()
        if self._proxy_cache is not None:
            ts, cached = self._proxy_cache
            if now - ts < PROXY_CACHE_TTL_S:
                return cached
        result = {"status": "unknown",
                  "detail": "không kiểm được"}
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(PROXY_HOST, PROXY_PORT),
                timeout=0.6)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            result = {"status": "ok",
                      "detail": f"đang nghe ở {PROXY_HOST}:{PROXY_PORT}"}
        except ConnectionRefusedError:
            result = {"status": "down",
                      "detail": f"cổng {PROXY_PORT} đang đóng"}
        except Exception:
            pass  # giữ unknown — không đoán
        self._proxy_cache = (now, result)
        return result

    async def _system_state(self, user: Optional[dict]) -> dict:
        """Thẻ "Thiết bị & hệ thống": chỉ dữ kiện THẬT của máy
        đang chạy Mulon + phiên Telegram đang xem. Mulon không
        có hệ thống ghép thiết bị — không bịa danh sách máy."""
        viewer = None
        if user:
            name = " ".join(
                x for x in [str(user.get("first_name") or ""),
                            str(user.get("last_name") or "")] if x)
            viewer = {
                "id": user.get("id"),
                "name": name,
                "username": str(user.get("username") or ""),
            }
        os_name = " ".join(
            x for x in [platform.system(), platform.release()] if x)
        return {
            "hostname": socket.gethostname(),
            "os": os_name,
            "arch": platform.machine() or "",
            "version": MULON_VERSION,
            "uptime_s": max(0, int(time.time() - self._started_at)),
            "proxy": await self._probe_proxy(),
            "scheduler_enabled": bool(self.cfg.scheduler_enabled),
            "heartbeat_enabled": await effective_enabled(
                self.memory, self.cfg),
            "viewer": viewer,
        }

    async def _handle_state(self, request):
        # Tab Việc = TASK THẬT (vá sau 1.4, owner bắt): chỉ
        # bản ghi từ bảng tasks (đường plan-act-verify, job,
        # agent con, build ý tưởng). Bản 1.3 từng gộp lượt
        # chat (trajectory turn_done/turn_error) cho khỏi
        # trống — owner chê đúng: đó là lịch sử chat, không
        # phải việc. Lượt chat ở yên trong chat.
        tasks = []
        try:
            for t in await self.memory.list_tasks(limit=20):
                tasks.append({
                    "id": t["id"], "kind": "task",
                    "title": t.get("title") or "",
                    "status": t.get("status") or "",
                    "error": t.get("error") or "",
                    "steps_total": t.get("steps_total") or 0,
                    "steps_done": t.get("steps_done") or 0,
                    "created_at": t.get("created_at") or "",
                    "updated_at": t.get("updated_at") or "",
                })
        except Exception:
            pass
        history = []
        try:
            rows = await self.memory.recent_trajectory(
                kind="approval_decision", limit=20)
            for r in rows:
                p = r.get("payload") or {}
                h_tool = str(p.get("tool", "?"))
                h_group = str(p.get("group", ""))
                history.append({
                    "tool": h_tool,
                    "group": h_group,
                    # Nhãn lời thường để app hiện thay tên thô;
                    # không có nhãn -> "" và frontend fallback
                    # về tên tool (chi tiết vẫn còn tên thô).
                    "action_label": known_action_label(h_tool, h_group),
                    "group_label": policy_group_label(h_group),
                    "layer": p.get("layer", "ask"),
                    "outcome": p.get("outcome", ""),
                    "approved": bool(p.get("approved")),
                    "remember": bool(p.get("remember")),
                    "at": r.get("created_at", ""),
                })
        except Exception:
            pass
        # Thẻ chờ duyệt: server gắn nhãn hành động lời thường
        # (cùng tool_action_label mà thẻ duyệt trên chat dùng)
        # để frontend chỉ trình bày — tên tool thô chỉ còn ở
        # dòng chi tiết của thẻ.
        pending = []
        if self.broker:
            for item in self.broker.pending():
                item = dict(item)
                i_tool = str(item.get("tool") or "")
                i_group = str(item.get("group") or "")
                item["action_label"] = tool_action_label(
                    i_tool, i_group)
                item["group_label"] = policy_group_label(i_group)
                pending.append(item)
        state = {
            "ok": True,
            "status": self.activity.snapshot(),
            "tasks": tasks,
            "approvals": {
                "pending": pending,
                "history": history,
            },
            "schedule": await self._schedule_state(),
            "profile": await self._profile_state(),
            "system": await self._system_state(
                request.get("tg_user")),
            "connectors": await self._connectors_state(),
            "vault": self.vault_store.labels()
                     if self.vault_store is not None else [],
            "policy": self._policy_state(),
            # 1.3.0: tóm tắt marketplace nhỏ cho badge điều hướng.
            "marketplace_summary": (self.marketplace.summary()
                                    if self.marketplace is not None
                                    else None),
            # 1.4.0: trạng thái Feed chủ động cho màn Cài đặt →
            # Feed chủ động. None khi bản chạy chưa nối runner.
            "feed": (await self.feed_auto.get_state()
                     if self.feed_auto is not None else None),
        }
        return web.json_response(state)

    async def _handle_task(self, request):
        task_id = request.query.get("id", "")
        task = await self.memory.get_task(task_id) if task_id else None
        if task is None:
            return web.json_response(
                {"ok": False, "error": "không thấy task"}, status=404)
        events = []
        try:
            rows = await self.memory.recent_trajectory(limit=300)
            for r in rows:
                p = r.get("payload") or {}
                if p.get("task_id") == task_id:
                    events.append({"kind": r.get("kind"),
                                   "payload": p,
                                   "at": r.get("created_at", "")})
        except Exception:
            pass
        events.reverse()
        return web.json_response({
            "ok": True,
            "task": {
                "id": task["id"], "title": task.get("title") or "",
                "status": task.get("status") or "",
                "result": (task.get("result") or "")[:4000],
                "error": task.get("error") or "",
                "created_at": task.get("created_at") or "",
                "updated_at": task.get("updated_at") or "",
                "steps": task.get("steps") or [],
            },
            "events": events,
        })

    async def _handle_profile_content(self, request):
        kind = request.query.get("kind", "")
        name = request.query.get("name", "")
        if kind == "dossier" and self.dossier is not None \
                and name in self.dossier.files:
            return web.json_response({
                "ok": True, "title": name,
                "content": self.dossier.files[name][:6000]})
        if kind == "memory":
            facts = await self.memory.active_facts(limit=50)
            lines = [f"- {f['fact']}" for f in facts]
            mem_md = ""
            if self.dossier is not None:
                mem_md = self.dossier.files.get("MEMORY.md", "")
            content = (mem_md[:3000] + "\n\n" + "\n".join(lines))[:6000]
            return web.json_response({
                "ok": True, "title": "Bộ nhớ (MEMORY.md + facts)",
                "content": content})
        return web.json_response(
            {"ok": False, "error": "không có nội dung này"}, status=404)

    # ---------- actions ----------
    async def _json_body(self, request) -> dict:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def _handle_policy(self, request):
        body = await self._json_body(request)
        scope = str(body.get("scope") or "group")
        name = str(body.get("name") or "")
        verdict = str(body.get("verdict") or "")
        if not name or verdict not in ("allow", "ask", "deny"):
            return web.json_response(
                {"ok": False, "error": "thiếu name/verdict hợp lệ"},
                status=400)
        if body.get("persist"):
            applied = self.policy.set_host_rule(scope, name, verdict)
            layer = "host"
        else:
            applied = self.policy.set_session_rule(scope, name, verdict)
            layer = "session"
        if self.memory is not None:
            await self.memory.log_trajectory(
                "webapp", "policy_changed",
                {"scope": scope, "name": name, "verdict": applied,
                 "layer": layer})
        return web.json_response(
            {"ok": True, "verdict": applied, "layer": layer,
             "policy": self._policy_state()})

    async def _handle_connector(self, request):
        body = await self._json_body(request)
        name = str(body.get("name") or "")
        enabled = bool(body.get("enabled"))
        if name.startswith("mcp:") and self.mcp is not None:
            server = name[4:]
            # 1.3.0: server do marketplace quản lý -> route sang
            # MarketplaceService (kèm policy deny/restore + journal
            # + restart) — KHÔNG ghi file trực tiếp, không ghi 2 lần.
            if self.marketplace is not None and \
                    self.marketplace.store.get_installed(server) \
                    is not None:
                from .marketplace import MarketplaceError

                try:
                    result = (self.marketplace.enable(server)
                              if enabled else
                              self.marketplace.disable(server))
                except MarketplaceError as exc:
                    return web.json_response(
                        {"ok": False, "error": exc.message,
                         "code": exc.code}, status=400)
                return web.json_response({
                    "ok": True, "enabled": enabled,
                    "operation_id": result.get("operation_id"),
                    "restart_required": True,
                    "note": "Đã ghi — bot đang tự khởi động lại "
                            "để áp dụng."})
            path = Path(self.mcp.config_path)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                servers = data.get("servers") or []
                hit = False
                for entry in servers:
                    if isinstance(entry, dict) \
                            and entry.get("name") == server:
                        entry["enabled"] = enabled
                        hit = True
                if not hit:
                    return web.json_response(
                        {"ok": False,
                         "error": f"không thấy MCP server {server}"},
                        status=404)
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False,
                                          indent=2),
                               encoding="utf-8")
                tmp.replace(path)
            except Exception as exc:
                return web.json_response(
                    {"ok": False, "error": f"ghi config lỗi: {exc}"},
                    status=500)
            return web.json_response({
                "ok": True, "enabled": enabled,
                "restart_required": True,
                "note": "Đã ghi vào mcp_servers.json — khởi động "
                        "lại bot để áp dụng."})
        return web.json_response({
            "ok": False, "restart_required": True,
            "error": "Connector này không tắt/bật nóng được — "
                     "chỉ MCP server mới đổi được qua đây."})

    async def _handle_approve(self, request):
        body = await self._json_body(request)
        approval_id = str(body.get("id") or "")
        decision = str(body.get("decision") or "")
        if self.broker is None or not approval_id:
            return web.json_response(
                {"ok": False, "error": "thiếu id"}, status=400)
        mapping = {"approve": (True, False), "deny": (False, False),
                   "approve_remember": (True, True)}
        if decision not in mapping:
            return web.json_response(
                {"ok": False, "error": "decision không hợp lệ"},
                status=400)
        approved, remember = mapping[decision]
        resolved = self.broker.resolve(approval_id, approved,
                                       remember=remember)
        return web.json_response({"ok": resolved,
                                  "resolved": resolved})

    async def _handle_theme(self, request):
        body = await self._json_body(request)
        theme = str(body.get("theme") or "")
        if theme not in THEME_KEYS:
            return web.json_response(
                {"ok": False,
                 "error": "theme không thuộc danh sách cho phép"},
                status=400)
        if self.memory is not None:
            await self.memory.kv_set(THEME_KV_KEY, theme)
            await self.memory.log_trajectory(
                "webapp", "theme_changed", {"theme": theme})
        return web.json_response({"ok": True, "theme": theme})

    async def _handle_schedule(self, request):
        body = await self._json_body(request)
        schedule_id = str(body.get("id") or "")
        enabled = bool(body.get("enabled"))
        if not schedule_id:
            return web.json_response(
                {"ok": False, "error": "Thiếu id lịch."},
                status=400)
        if schedule_id == "heartbeat":
            # Công tắc heartbeat thật: lưu kv, engine đọc lại mỗi
            # lượt quét nên ăn ngay, không restart.
            await self.memory.kv_set(
                PROACTIVITY_KV_KEY, "1" if enabled else "0")
            await self.memory.log_trajectory(
                "webapp", "heartbeat_toggled",
                {"enabled": enabled})
            return web.json_response(
                {"ok": True, "enabled": enabled})
        row = await self.memory.get_schedule(schedule_id)
        if row is not None and internal_kind(
                row.get("payload") or "") is not None:
            return web.json_response(
                {"ok": False,
                 "error": "Job hệ thống nội bộ — điều khiển ở "
                          "Cài đặt → Feed chủ động, không bật/tắt "
                          "ở tab Lịch."},
                status=400)
        ok = await self.memory.set_schedule_enabled(schedule_id,
                                                    enabled)
        return web.json_response({"ok": ok})

    # ---------- 1.4.0: Feed chủ động ----------
    async def _handle_feed(self, request):
        """Điều khiển Feed chủ động từ Mini App (owner-only qua
        middleware auth như mọi /api/*).

        Cố ý KHÔNG có action tắt/bật tổng (quyết định 0.2b: Feed
        luôn tự động). Actions: set_cron, set_quiet, set_limits,
        add_source, remove_source, set_source_enabled,
        set_denylist, run_now, resume.
        """
        if self.feed_auto is None:
            return web.json_response(
                {"ok": False, "error": "Feed chủ động chưa được "
                                       "nối ở bản chạy này."},
                status=503)
        body = await self._json_body(request)
        action = str(body.get("action") or "")
        runner = self.feed_auto
        engine = runner.engine

        def _bad(msg: str):
            return web.json_response(
                {"ok": False, "error": msg}, status=400)

        if action == "set_cron":
            cron = str(body.get("cron") or "").strip()
            try:
                parse_cron(cron)
            except Exception:
                return _bad("cron không hợp lệ (cần 5 trường: "
                            "phút giờ ngày tháng thứ)")
            await runner.apply_settings({"cron": cron})
        elif action == "set_quiet":
            quiet = str(body.get("quiet_hours") or "").strip()
            if not valid_quiet_hours(quiet):
                return _bad("giờ yên lặng phải dạng HH:MM-HH:MM")
            await runner.apply_settings({"quiet_hours": quiet})
        elif action == "set_limits":
            changes = {}
            for key in ("max_posts_per_day", "daily_token_budget"):
                if body.get(key) is not None:
                    try:
                        value = int(body[key])
                    except (TypeError, ValueError):
                        return _bad(f"{key} phải là số nguyên")
                    if value < 0:
                        return _bad(f"{key} không được âm")
                    changes[key] = value
            if not changes:
                return _bad("không có giới hạn nào để đặt")
            await runner.apply_settings(changes)
        elif action == "add_source":
            url = str(body.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                return _bad("URL nguồn phải bắt đầu http:// "
                            "hoặc https://")
            trust = str(body.get("trust") or "normal").lower()
            if trust not in ("high", "normal", "low"):
                trust = "normal"
            sources = engine.read_sources()
            if any(s["url"] == url for s in sources):
                return _bad("nguồn này đã có trong danh sách")
            sources.append({"url": url,
                            "label": str(body.get("label") or "")[:60],
                            "trust": trust, "enabled": True})
            engine.set_sources(sources)
        elif action == "remove_source":
            url = str(body.get("url") or "").strip()
            sources = [s for s in engine.read_sources()
                       if s["url"] != url]
            engine.set_sources(sources)
        elif action == "set_source_enabled":
            url = str(body.get("url") or "").strip()
            sources = engine.read_sources()
            for s in sources:
                if s["url"] == url:
                    s["enabled"] = bool(body.get("enabled"))
            engine.set_sources(sources)
        elif action == "set_denylist":
            raw = body.get("denylist")
            if not isinstance(raw, list):
                return _bad("denylist phải là danh sách domain")
            await runner.apply_settings(
                {"denylist": [str(d) for d in raw]})
        elif action == "run_now":
            if runner._sender is None:
                return web.json_response(
                    {"ok": False,
                     "error": "bot chưa sẵn sàng gửi (sender "
                              "chưa được gắn)"},
                    status=503)
            result = await runner.run_once(force=True)
            return web.json_response(
                {"ok": bool(result.get("ok")), "result": result,
                 "feed": await runner.get_state()})
        elif action == "resume":
            await runner.resume()
        else:
            return _bad(f"action không hỗ trợ: {action or '(trống)'}")
        return web.json_response(
            {"ok": True, "feed": await runner.get_state()})

    # ---------- 1.3.0 (gói vá Mini App): kỹ năng + Vault ----------
    async def _handle_skills(self, request):
        """Danh sách kỹ năng owner ĐỌC được: tên + mô tả + nguồn
        (đường file SKILL.md) — từ đúng catalog agent đang nạp
        (đã qua vet + đủ điều kiện), không danh sách bịa."""
        if self.skills is None:
            return web.json_response(
                {"ok": True, "available": False, "skills": []})
        paths = {}
        try:
            paths = {e["name"]: e.get("path", "")
                     for e in self.skills.entries}
        except Exception:
            pass
        items = [{
            "name": e["name"],
            "description": e.get("description", ""),
            "source": paths.get(e["name"], ""),
        } for e in self.skills.catalog()]
        return web.json_response(
            {"ok": True, "available": True, "skills": items})

    async def _handle_skill_detail(self, request):
        """Nội dung đầy đủ của 1 SKILL.md để owner mở đọc ngay
        trong app (trước đây app chỉ có tên + số lượng). Nội dung
        qua SkillCatalog.read — cùng cửa agent dùng, tôn trọng
        vet/eligibility."""
        name = str(request.match_info.get("name") or "")
        if self.skills is None:
            return web.json_response(
                {"ok": False, "error": "chưa nạp catalog kỹ năng"},
                status=404)
        result = self.skills.read(name)
        if not result.get("ok"):
            return web.json_response(
                {"ok": False,
                 "error": result.get("error") or "không đọc được"},
                status=404)
        return web.json_response({
            "ok": True, "name": name,
            "content": result.get("content", ""),
            "source": result.get("path", "")})

    async def _handle_vault_capture(self, request):
        """Nhập bí mật NGAY trong Mini App (1.3.0): owner gõ nhãn
        + giá trị ở màn Vault -> ghi thẳng VaultStore.put -> chỉ
        trả ref. Giá trị KHÔNG echo về response, KHÔNG vào
        trajectory/log (chỉ nhãn + ref được ghi vết) — cùng kỷ
        luật với form một lần qua link, nhưng không cần link
        127.0.0.1 (link đó chết trên điện thoại vì trỏ về máy
        tính của owner)."""
        body = await self._json_body(request)
        label = str(body.get("label") or "").strip()
        value = body.get("value")
        value = value if isinstance(value, str) else ""
        if self.vault_store is None:
            return web.json_response(
                {"ok": False, "error": "Vault chưa được nối ở "
                                       "bản chạy này."},
                status=503)
        if not label or not value:
            return web.json_response(
                {"ok": False, "error": "thiếu nhãn hoặc giá trị"},
                status=400)
        if len(label) > 120 or len(value) > 8192:
            return web.json_response(
                {"ok": False, "error": "nhãn hoặc giá trị quá dài"},
                status=400)
        ref = self.vault_store.put(label, value)
        if self.memory is not None:
            try:
                await self.memory.log_trajectory(
                    "webapp", "vault_captured",
                    {"label": label, "ref": ref})
            except Exception:
                pass
        return web.json_response({"ok": True, "ref": ref})

    # ---------- 1.5.0: Google OAuth ----------

    _GOOGLE_KV_STATE = "google_oauth_state"

    async def _handle_google_auth_url(self, request):
        if self.google_auth is None:
            return web.json_response(
                {"ok": False, "error": "Google connector chưa "
                                       "được nối ở bản chạy này."},
                status=503)
        if not self.google_auth.configured():
            return web.json_response(
                {"ok": False,
                 "error": "Chưa có client id/secret: nhập 2 bí "
                          "mật nhãn google:client_id và "
                          "google:client_secret ở màn Kho lưu "
                          "trữ, hoặc đặt env GOOGLE_CLIENT_ID / "
                          "GOOGLE_CLIENT_SECRET."},
                status=400)
        import secrets as _secrets

        state = _secrets.token_urlsafe(24)
        await self.memory.kv_set(
            self._GOOGLE_KV_STATE,
            json.dumps({"state": state, "ts": time.time()}))
        return web.json_response({
            "ok": True,
            "url": self.google_auth.build_auth_url(state),
            "redirect_uri": self.google_auth.redirect_uri(),
        })

    async def _handle_google_disconnect(self, request):
        if self.google_auth is None:
            return web.json_response(
                {"ok": False, "error": "Google connector chưa "
                                       "được nối ở bản chạy này."},
                status=503)
        self.google_auth.disconnect()
        await self.memory.log_trajectory(
            "webapp", "google_disconnected", {})
        return web.json_response({"ok": True})

    async def _handle_google_callback(self, request):
        """Route CÔNG KHAI duy nhất của webapp: trình duyệt
        ngoài quay về từ Google nên không có initData. Bảo vệ
        bằng state nonce (ngẫu nhiên, lưu kv, hạn 10 phút, dùng
        1 lần) + code chỉ đổi được token khi kèm client_secret
        phía server. Trang trả về không chứa dữ liệu nhạy cảm."""

        def page(msg: str, ok: bool):
            color = "#3E9B6C" if ok else "#D95F57"
            body = (
                "<!doctype html><html lang=\"vi\"><head>"
                "<meta charset=\"utf-8\"><title>Mulon — Google"
                "</title></head><body style=\"font-family:"
                "sans-serif;max-width:32rem;margin:3rem auto;"
                "text-align:center\">"
                f"<h3 style=\"color:{color}\">{msg}</h3>"
                "<p>Đóng trang này và quay lại Telegram được "
                "rồi.</p></body></html>")
            return web.Response(text=body,
                                content_type="text/html")

        if self.google_auth is None:
            return page("Bản chạy này chưa nối Google "
                        "connector.", False)
        code = request.query.get("code") or ""
        state = request.query.get("state") or ""
        saved = None
        try:
            raw = await self.memory.kv_get(self._GOOGLE_KV_STATE)
            saved = json.loads(raw) if raw else None
        except Exception:
            saved = None
        # Dùng 1 lần: xoá ngay khi có bất kỳ callback nào.
        try:
            await self.memory.kv_set(self._GOOGLE_KV_STATE, "")
        except Exception:
            pass
        if (not code or not saved
                or saved.get("state") != state
                or time.time() - float(saved.get("ts") or 0) > 600):
            return page("Liên kết kết nối không hợp lệ hoặc đã "
                        "hết hạn. Hãy bấm Kết nối lại trong Mini "
                        "App.", False)
        result = await self.google_auth.exchange_code(code)
        if not result.get("ok"):
            return page("Google từ chối kết nối: " +
                        str(result.get("error") or "không rõ"),
                        False)
        await self.memory.log_trajectory(
            "webapp", "google_connected",
            {"email": result.get("email") or ""})
        return page("Đã kết nối Google" +
                    (f" ({result['email']})"
                     if result.get("email") else "") + ".", True)

    # ---------- 1.3.0: Chợ MCP ----------
    def _mkt_guard(self):
        """None nếu marketplace sẵn sàng; response 503 nếu chưa
        nối (giữ hành vi sạch như các dịch vụ tuỳ chọn khác)."""
        if self.marketplace is None:
            return web.json_response(
                {"ok": False, "code": "catalog_unavailable",
                 "error": "Marketplace chưa được nối trong bản "
                          "chạy này."}, status=503)
        return None

    def _mkt_error(self, exc):
        from .marketplace import MarketplaceError

        if isinstance(exc, MarketplaceError):
            status = 404 if exc.code in (
                "catalog_unavailable", "invalid_config") else 400
            if exc.code == "operation_conflict":
                status = 409
            return web.json_response(
                {"ok": False, "error": exc.message,
                 "code": exc.code}, status=status)
        logger.exception("marketplace API lỗi")
        return web.json_response(
            {"ok": False, "error": "lỗi nội bộ marketplace",
             "code": "probe_failed"}, status=500)

    def _idem_key(self, request) -> str:
        return str(request.headers.get("Idempotency-Key") or "")

    async def _mkt_summary(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        return web.json_response(
            {"ok": True, **self.marketplace.summary()})

    async def _mkt_categories(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        return web.json_response(
            {"ok": True, **self.marketplace.categories()})

    async def _mkt_catalog(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        q = request.query
        result = self.marketplace.search_catalog(
            query=q.get("query", ""), category=q.get("category", ""),
            pricing=q.get("pricing", ""),
            installed=q.get("installed", ""),
            cursor=q.get("cursor", ""),
            limit=int(q.get("limit", "20") or 20))
        return web.json_response({"ok": True, **result})

    async def _mkt_listing(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            detail = self.marketplace.listing_detail(
                request.match_info["provider"],
                request.match_info["slug"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "listing": detail})

    async def _mkt_installed(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        return web.json_response(
            {"ok": True, "items": self.marketplace.installed_list()})

    async def _mkt_installed_detail(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            view = self.marketplace.installed_detail(
                request.match_info["name"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "installed": view})

    async def _mkt_operation(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        op = self.marketplace.store.get_operation(
            request.match_info["id"])
        if op is None:
            return web.json_response(
                {"ok": False, "error": "không tìm thấy operation",
                 "code": "invalid_config"}, status=404)
        return web.json_response(
            {"ok": True,
             "operation": self.marketplace.operation_view(op)})

    async def _mkt_refresh(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        result = await self.marketplace.refresh_catalog()
        return web.json_response({"ok": True, **result})

    async def _mkt_import_parse(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        body = await self._json_body(request)
        try:
            result = self.marketplace.parse_import(
                text=body.get("text"), url=body.get("url"),
                name=body.get("name"))
        except Exception as exc:
            return self._mkt_error(exc)
        if not result.get("ok"):
            return web.json_response(result, status=400)
        return web.json_response(result)

    async def _mkt_prepare(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        body = await self._json_body(request)
        source = {}
        if body.get("draft_id"):
            source = {"draft_id": str(body["draft_id"])}
        elif body.get("slug"):
            source = {"provider_id": str(
                body.get("provider_id") or "mulon-curated"),
                "slug": str(body["slug"])}
        else:
            return web.json_response(
                {"ok": False, "code": "invalid_config",
                 "error": "thiếu slug hoặc draft_id"}, status=400)
        try:
            view = self.marketplace.prepare_install(
                source, alias=body.get("alias"),
                idempotency_key=self._idem_key(request))
            if body.get("auto_install") and view.get("stage") == "awaiting_probe_approval":
                import asyncio as _asyncio
                _asyncio.create_task(
                    self.marketplace.install_one_click(view["id"]))
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "operation": view})

    async def _mkt_bind_secrets(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        body = await self._json_body(request)
        try:
            view = self.marketplace.bind_secrets(
                request.match_info["id"],
                body.get("bindings") or {})
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "operation": view})

    async def _mkt_request_probe(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = self.marketplace.request_stage_approval(
                request.match_info["id"], "probe")
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_request_commit(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = self.marketplace.request_stage_approval(
                request.match_info["id"], "commit")
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_cancel(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            view = self.marketplace.cancel_operation(
                request.match_info["id"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "operation": view})

    async def _mkt_health_check(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = await self.marketplace.run_health_check(
                request.match_info["name"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_enable(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = self.marketplace.enable(
                request.match_info["name"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_disable(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = self.marketplace.disable(
                request.match_info["name"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_update_check(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = self.marketplace.update_check(
                request.match_info["name"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_update_prepare(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            view = self.marketplace.prepare_update(
                request.match_info["name"],
                idempotency_key=self._idem_key(request))
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "operation": view})

    async def _mkt_uninstall_prepare(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        body = await self._json_body(request)
        try:
            view = self.marketplace.prepare_uninstall(
                request.match_info["name"],
                delete_vault_refs=body.get("delete_vault_refs")
                or [],
                idempotency_key=self._idem_key(request))
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "operation": view})

    async def _mkt_install_now(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        op_id = request.match_info["id"]
        try:
            res = await self.marketplace.install_one_click(op_id)
            return web.json_response({"ok": True, "operation": res})
        except Exception as exc:
            return self._mkt_error(exc)

    # ---------- 1.6.0: Library & Public Artifact Sharing ----------
    async def _handle_public_share(self, request):
        token = request.match_info.get("token", "")
        if self.library is None:
            return web.Response(
                text="Library service chưa được kích hoạt.", status=503)
        res = await self.library.get_item_by_token(token)
        if not res.get("ok"):
            err = html.escape(res.get("error", "Tài liệu không khả dụng."))
            html_body = f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mulon Share · Lỗi</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #1e293b; max-width: 600px; margin: 80px auto; padding: 20px; text-align: center; }}
h2 {{ font-size: 20px; font-weight: 600; color: #e11d48; margin-bottom: 8px; }}
p {{ color: #64748b; font-size: 15px; }}
</style></head>
<body><h2>Liên kết không khả dụng</h2><p>{err}</p></body></html>"""
            return web.Response(text=html_body, content_type="text/html", status=404)

        item = res["item"]
        name = html.escape(str(item.get("name") or "Tài liệu"))
        kind = html.escape(str(item.get("kind") or "tài liệu"))
        content = str(res.get("content") or "")
        is_binary = res.get("is_binary", False)

        if is_binary:
            p = Path(item["path"])
            if p.is_file():
                return web.FileResponse(p)
            return web.Response(text="File không tồn tại", status=404)

        escaped_content = html.escape(content)
        html_page = f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} · Mulon Artifact</title>
<style>
:root {{
  --bg: #ffffff; --fg: #0f172a; --muted: #64748b; --border: #e2e8f0;
  --card-bg: #f8fafc; --accent: #2563eb; --accent-hover: #1d4ed8;
  --code-bg: #1e293b; --code-fg: #f8fafc;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0b0f17; --fg: #f1f5f9; --muted: #94a3b8; --border: #1e293b;
    --card-bg: #131b2a; --accent: #3b82f6; --accent-hover: #60a5fa;
    --code-bg: #050811; --code-fg: #f1f5f9;
  }}
}}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg); color: var(--fg);
  max-width: 820px; margin: 0 auto; padding: 24px 16px 80px;
  line-height: 1.65;
}}
header {{
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px;
}}
.title-group {{ display: flex; flex-direction: column; gap: 4px; }}
h1 {{ font-size: 20px; font-weight: 700; margin: 0; }}
.meta {{ font-size: 13px; color: var(--muted); display: flex; gap: 10px; align-items: center; }}
.badge {{ background: var(--card-bg); border: 1px solid var(--border); padding: 2px 8px; border-radius: 999px; text-transform: uppercase; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}
.actions {{ display: flex; gap: 8px; }}
button {{
  background: var(--card-bg); border: 1px solid var(--border); color: var(--fg);
  padding: 8px 14px; border-radius: 8px; font-size: 13px; font-weight: 500;
  cursor: pointer; transition: all 0.15s ease;
}}
button:hover {{ border-color: var(--accent); color: var(--accent); }}
pre {{
  background: var(--card-bg); border: 1px solid var(--border);
  padding: 20px; border-radius: 12px; overflow-x: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;
}}
footer {{ margin-top: 40px; text-align: center; font-size: 12px; color: var(--muted); }}
</style></head>
<body>
<header>
  <div class="title-group">
    <h1>{name}</h1>
    <div class="meta">
      <span class="badge">{kind}</span>
      <span>Được chia sẻ từ Mulon</span>
    </div>
  </div>
  <div class="actions">
    <button id="copy-btn" onclick="copyContent()">Sao chép</button>
  </div>
</header>
<main>
  <pre id="artifact-content">{escaped_content}</pre>
</main>
<footer>Mulon Personal Agent · Chia sẻ bảo mật</footer>
<script>
function copyContent() {{
  const txt = document.getElementById("artifact-content").innerText;
  navigator.clipboard.writeText(txt).then(() => {{
    const b = document.getElementById("copy-btn");
    b.innerText = "Đã sao chép!";
    setTimeout(() => b.innerText = "Sao chép", 2000);
  }});
}}
</script>
</body></html>"""
        return web.Response(text=html_page, content_type="text/html")

    async def _handle_library_items(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        items = await self.library.list_items(status="active", limit=100)
        return web.json_response({"ok": True, "items": items})

    async def _handle_library_pin(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        body = await self._json_body(request)
        item_id = int(request.match_info["id"])
        pinned = bool(body.get("pinned", True))
        res = await self.library.pin_item(item_id, pinned=pinned)
        return web.json_response(res)

    async def _handle_library_rename(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        body = await self._json_body(request)
        item_id = int(request.match_info["id"])
        name = str(body.get("name") or "").strip()
        res = await self.library.rename_item(item_id, name)
        return web.json_response(res)

    async def _handle_library_share(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        body = await self._json_body(request)
        item_id = int(request.match_info["id"])
        hours = float(body.get("hours") or 48.0)
        base = self.cfg.webapp_url or f"{request.scheme}://{request.host}"
        res = await self.library.share_item(item_id, hours=hours, base_url=base)
        return web.json_response(res)
