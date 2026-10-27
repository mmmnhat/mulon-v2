"""Khung connector trung tính (thiết kế mục 6 + 16.2) — Phase 3.

Chuẩn chung cho mọi dịch vụ ngoài:
- interface: `health_check()` + `call(action, args)`;
- đăng ký LAZY: factory chỉ chạy ở lần dùng đầu tiên, connector
  chưa cấu hình / factory lỗi -> vắng mặt sạch, không kéo sập hệ
  thống;
- health check trước khi hứa (mục 16.2): trạng thái từng connector
  luôn truy vấn được qua tool `connector_health`.

Luật bảo mật của khung: adapter tự đọc credential của nó từ
env/vault ở phía adapter và KHÔNG BAO GIỜ đưa credential vào kết
quả trả về / log / trajectory. Khung này không giữ secret nào.

Bản này kèm 1 adapter ví dụ trung tính: `system` (giờ + trạng thái
máy) để chứng minh khung chạy thật. Adapter dịch vụ thật cắm vào
cùng interface ở các phase sau.
"""

from __future__ import annotations

import logging
import os
import platform
import socket
import sys
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Union

from .tools import ToolSpec

logger = logging.getLogger("mulon.connectors")


class Connector:
    """Interface connector. Lớp con ghi đè health_check và call."""

    name: str = "base"

    async def health_check(self) -> dict:
        return {"ok": True, "name": self.name}

    async def call(self, action: str, args: dict) -> dict:
        return {"ok": False,
                "error": f"connector {self.name} không hỗ trợ: {action}"}


Factory = Callable[[], Union[Connector, Awaitable[Connector]]]


class ConnectorRegistry:
    def __init__(self):
        self._factories: dict[str, Factory] = {}
        self._instances: dict[str, Connector] = {}
        self._errors: dict[str, str] = {}

    def register(self, connector: Connector) -> Connector:
        self._instances[connector.name] = connector
        self._factories.pop(connector.name, None)
        return connector

    def register_lazy(self, name: str, factory: Factory) -> None:
        if name not in self._instances:
            self._factories[name] = factory

    def names(self) -> list[str]:
        return sorted(set(self._factories) | set(self._instances))

    async def get(self, name: str) -> Optional[Connector]:
        if name in self._instances:
            return self._instances[name]
        factory = self._factories.get(name)
        if factory is None:
            return None
        try:
            instance = factory()
            if isinstance(instance, Awaitable):
                instance = await instance
            self._instances[name] = instance
            return instance
        except Exception as exc:
            self._errors[name] = f"{type(exc).__name__}: {exc}"
            logger.warning("connector '%s' dựng lỗi (vắng mặt): %s",
                           name, exc)
            return None

    async def health_all(self) -> dict[str, dict]:
        report: dict[str, dict] = {}
        for name in self.names():
            conn = await self.get(name)
            if conn is None:
                report[name] = {
                    "ok": False,
                    "configured": False,
                    "error": self._errors.get(name, "không dựng được"),
                }
                continue
            try:
                health = await conn.health_check()
                if isinstance(health, dict) and "ok" in health:
                    report[name] = health
                else:
                    report[name] = {"ok": True, "name": name,
                                    "detail": health}
            except Exception as exc:
                report[name] = {"ok": False, "name": name,
                                "error": f"{type(exc).__name__}: {exc}"}
        return report

    async def call(self, name: str, action: str,
                   args: Optional[dict] = None) -> dict:
        conn = await self.get(name)
        if conn is None:
            return {"ok": False,
                    "error": f"connector không khả dụng: {name}"}
        try:
            result = await conn.call(action, args or {})
        except Exception as exc:
            return {"ok": False,
                    "error": f"{type(exc).__name__}: {exc}"}
        if isinstance(result, dict) and "ok" in result:
            return result
        return {"ok": True, "result": result}


# ---------------------------------------------------------------------------
# Adapter ví dụ trung tính: system
# ---------------------------------------------------------------------------

class SystemConnector(Connector):
    """Báo giờ + trạng thái máy — chứng minh khung, không phụ thuộc
    bất kỳ dịch vụ ngoài nào."""

    name = "system"

    def _status(self) -> dict[str, Any]:
        try:
            load = list(os.getloadavg())  # chỉ có trên Unix
        except (AttributeError, OSError):
            load = []
        return {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "load_avg": load,
            "pid": os.getpid(),
        }

    async def health_check(self) -> dict:
        local = datetime.now().astimezone()
        return {
            "ok": True,
            "name": self.name,
            "time_local": local.isoformat(timespec="seconds"),
            "time_utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            **self._status(),
        }

    async def call(self, action: str, args: dict) -> dict:
        if action == "time":
            local = datetime.now().astimezone()
            return {
                "ok": True,
                "time_local": local.isoformat(timespec="seconds"),
                "time_utc": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"),
            }
        if action == "status":
            return {"ok": True, **self._status()}
        if action == "feed_snapshot":
            st = self._status()
            return {
                "ok": True,
                "items": [{
                    "title": f"Môi trường máy {st.get('hostname', 'localhost')}",
                    "snippet": f"Hệ điều hành {st.get('platform', '')}, Python {st.get('python', '')}",
                    "url": None,
                }]
            }
        return {"ok": False,
                "error": f"system không hỗ trợ action: {action}"}


def build_default_connectors(cfg, google_auth=None, vault_store=None) -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(SystemConnector())

    if google_auth is None and vault_store is not None:
        try:
            from .google_conn import build_google_auth

            google_auth = build_google_auth(cfg, vault_store)
        except Exception:
            google_auth = None

    if google_auth is not None:
        # 1.5.0 + 1.7.28 (T-17): Google Workspace built-in connectors
        from .google_conn import (
            GCalendarConnector,
            GDocsConnector,
            GDriveConnector,
            GmailConnector,
            GSheetsConnector,
        )

        registry.register(GmailConnector(google_auth))
        registry.register(GCalendarConnector(
            google_auth,
            default_tz=getattr(cfg, "default_timezone", "UTC")))
        registry.register(GDriveConnector(google_auth))
        registry.register(GDocsConnector(google_auth))
        registry.register(GSheetsConnector(google_auth))

    # 1.7.8 (T-22.1 / T-22.2 / T-22.3 / T-30): Connector tài khoản cá nhân (Zalo, Telegram MTProto, Facebook, Instagram DM, Threads DM, Threads Content)
    from .personal_connectors import (
        FacebookPersonalConnector,
        InstagramMessagesConnector,
        TelegramPersonalConnector,
        ThreadsMessagesConnector,
        ThreadsPersonalConnector,
        ZaloPersonalConnector,
    )
    registry.register(ZaloPersonalConnector(cfg=cfg, vault_store=vault_store))
    registry.register(TelegramPersonalConnector(cfg=cfg, vault_store=vault_store))
    registry.register(FacebookPersonalConnector(cfg=cfg, vault_store=vault_store))
    registry.register(InstagramMessagesConnector(cfg=cfg, vault_store=vault_store))
    registry.register(ThreadsPersonalConnector(cfg=cfg, vault_store=vault_store))
    # Spike T-22.3: bridge gửi DM Threads thật qua web. Dựng lỗi
    # thì degrade về None (connector sẽ báo chưa có đường gửi thật
    # thay vì sập hệ thống) — Playwright/profile chỉ kiểm tra lúc
    # gửi, không kiểm tra lúc đăng ký.
    threads_bridge = None
    try:
        from .threads_browser_bridge import ThreadsBrowserBridge

        threads_bridge = ThreadsBrowserBridge(cfg=cfg)
    except Exception as exc:
        logger.warning("dựng Threads browser bridge lỗi (%s) — "
                       "threads_messages chạy không bridge", exc)
    registry.register(ThreadsMessagesConnector(
        cfg=cfg, vault_store=vault_store, browser_bridge=threads_bridge))

    # 1.7.28 (T-17): Connector tích hợp sẵn chính thức (Facebook Page, Instagram Business, Threads Official, TikTok)
    from .social_connectors import (
        FacebookPageConnector,
        InstagramBusinessConnector,
        ThreadsOfficialConnector,
        TikTokConnector,
    )
    registry.register(FacebookPageConnector(cfg=cfg, vault_store=vault_store))
    registry.register(InstagramBusinessConnector(cfg=cfg, vault_store=vault_store))
    registry.register(ThreadsOfficialConnector(cfg=cfg, vault_store=vault_store))
    registry.register(TikTokConnector(cfg=cfg, vault_store=vault_store))
    return registry


def register_connector_tools(registry, connectors: ConnectorRegistry) -> None:
    async def connector_health():
        return {"ok": True, "connectors": await connectors.health_all()}

    async def connector_call(name: str, action: str, args: dict = None):
        return await connectors.call(name, action, args or {})

    registry.register(ToolSpec(
        name="connector_health",
        description=(
            "Kiểm tra trạng thái mọi connector đã đăng ký (health "
            "check trước khi hứa làm việc qua connector)."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        group="connector",
        timeout_s=30,
        handler=connector_health,
    ))
    registry.register(ToolSpec(
        name="connector_call",
        description=(
            "Gọi 1 action của connector theo tên. Kết quả không bao "
            "giờ chứa credential."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "action": {"type": "string"},
                "args": {"type": "object", "default": {}},
            },
            "required": ["name", "action"],
        },
        group="connector",
        timeout_s=60,
        handler=connector_call,
    ))
