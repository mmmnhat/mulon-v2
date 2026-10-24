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

logger = logging.getLogger("mulon.webapp")

try:
    from aiohttp import web

    HAS_AIOHTTP = True
except Exception:  # pragma: no cover - môi trường thiếu gói
    web = None  # type: ignore
    HAS_AIOHTTP = False

INIT_DATA_MAX_AGE_S = 3600
INDEX_HTML = Path(__file__).resolve().parent / "webapp" / "index.html"

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
                 skills=None, activity: Optional[ActivityTracker] = None):
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
        app.router.add_get("/app", self._handle_index)
        app.router.add_get("/app/avatar", self._handle_avatar)
        app.router.add_get("/api/state", self._handle_state)
        app.router.add_get("/api/task", self._handle_task)
        app.router.add_get("/api/profile/content",
                           self._handle_profile_content)
        app.router.add_post("/api/policy", self._handle_policy)
        app.router.add_post("/api/connector", self._handle_connector)
        app.router.add_post("/api/approve", self._handle_approve)
        app.router.add_post("/api/schedule", self._handle_schedule)
        app.router.add_post("/api/profile/theme", self._handle_theme)
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
            out.append({
                "id": name, "name": name, "kind": "builtin",
                "ok": bool(h.get("ok")), "enabled": True,
                "toggleable": False,
                "detail": str(h.get("error") or h.get("detail") or ""),
            })
        # MCP servers: trạng thái nối từ manager + enabled từ file
        # cấu hình (đọc tươi để toggle phản ánh đúng).
        if self.mcp is not None:
            from .mcp_client import load_server_configs

            entries = load_server_configs(self.mcp.config_path)
            status = self.mcp.status()
            for entry in entries:
                name = str(entry.get("name"))
                st = status.get(name) or {}
                out.append({
                    "id": f"mcp:{name}", "name": name, "kind": "mcp",
                    "ok": bool(st.get("connected")),
                    "enabled": bool(entry.get("enabled", False)),
                    "toggleable": True,
                    "detail": str(st.get("error") or ""),
                })
        return out

    def _policy_state(self) -> dict:
        desc = self.policy.describe()
        groups = sorted({
            *(desc["groups"].keys()), *(desc["session_groups"].keys()),
            *(spec.group for spec in self.registry.specs() if spec.group),
        })
        tools = sorted({
            *(desc["tools"].keys()),
            *(desc["session_tools"].keys()),
            *self.registry.names(),
        })
        return {
            "default": desc["default"],
            "groups": {
                g: self.policy.decide("", g).verdict for g in groups},
            "group_labels": {
                g: label for g in groups
                if (label := policy_group_label(g))},
            "tools": {
                t: self.policy.decide(
                    t, (self.registry.get(t).group
                        if self.registry.get(t) else "")).verdict
                for t in tools},
            "host": desc,
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
            "prompt": "Quét checklist HEARTBEAT.md (mặc định tắt, "
                      "bật bằng PROACTIVITY_ENABLED trong .env)",
            "enabled": bool(self.cfg.proactivity_enabled),
            "next_run_at": "", "last_run_at": "",
            "toggleable": False, "kind": "heartbeat",
        })
        scheduler_on = bool(self.cfg.scheduler_enabled)
        return {"available": available, "scheduler_enabled": scheduler_on,
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
            "heartbeat_enabled": bool(self.cfg.proactivity_enabled),
            "viewer": viewer,
        }

    async def _handle_state(self, request):
        tasks = []
        try:
            for t in await self.memory.list_tasks(limit=20):
                tasks.append({
                    "id": t["id"], "title": t.get("title") or "",
                    "status": t.get("status") or "",
                    "error": t.get("error") or "",
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
        if not schedule_id or schedule_id == "heartbeat":
            return web.json_response(
                {"ok": False,
                 "error": "Heartbeat bật/tắt bằng biến môi trường "
                          "PROACTIVITY_ENABLED, không đổi ở đây."},
                status=400)
        ok = await self.memory.set_schedule_enabled(schedule_id,
                                                    enabled)
        return web.json_response({"ok": ok})
