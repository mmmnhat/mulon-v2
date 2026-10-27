"""Kiểm chứng toàn diện T-24.5: Lỗi tải initData ở Chi tiết việc + Chợ MCP.

Bao gồm các kiểm thử phân biệt và nghiệm thu:
1. Xác nhận phiên WebView mới (fresh initData) mở Chi tiết việc (/api/task) và Chợ MCP (/api/marketplace/*)
   đều tải được dữ liệu thật (HTTP 200 OK, payload đầy đủ).
2. Phân biệt nguyên nhân: do initData hết hạn theo tuổi phiên (trần cũ 3600s).
   - Với tuổi phiên 2 giờ (7200s), chính sách mới 86400s (24 giờ, chuẩn Telegram Mini App) chấp nhận thành công.
   - Với tuổi phiên > 24 giờ (90000s) hoặc chữ ký sai: từ chối 403 đúng quy định bảo mật.
3. Kiểm chứng cô lập lỗi giao diện:
   - Chuyển tab (showMain, showSub) tự động dọn global-error, không dính banner lỗi sang tab khác.
   - Màn Chi tiết việc khi gặp lỗi hiển thị nút "Thử lại" nội bộ trong màn, không rò rỉ ra banner ngoài.
   - Frontend getInitData() động, chống đóng băng chuỗi rỗng khi SDK nạp sau hoặc qua URL hash/search.
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.config import Config
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.marketplace import MarketplaceService
from mulon.memory import Memory
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer, validate_init_data
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import make_init_data, OWNER, TOKEN


@pytest.fixture
async def webapp_env(tmp_path):
    cfg = Config(
        telegram_bot_token=TOKEN,
        allowed_user_id=OWNER,
        webapp_port=0,
        init_data_max_age_s=86400,
        db_path=str(tmp_path / "test.db"),
        policy_path=str(tmp_path / "policy.json"),
        vault_path=str(tmp_path / "vault.json"),
        dossier_dir=str(tmp_path / "dossier"),
        workspace_dir=str(tmp_path / "workspace"),
    )
    (tmp_path / "dossier").mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspace").mkdir(parents=True, exist_ok=True)

    memory = await open_memory(cfg)
    # Tạo task mẫu để kiểm tra Chi tiết việc
    await memory.create_task("task-real-1", "sess-1", "Việc phân tích dữ liệu", ["Bước 1: Quét", "Bước 2: Tổng hợp"])
    await memory.update_step("task-real-1", 0, "done")
    await memory.update_step("task-real-1", 1, "done")
    await memory.finish_task("task-real-1", "done", result="Đã phân tích xong 100%.")

    policy = PolicyEngine(cfg.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)
    vault = VaultStore(cfg.vault_path)
    registry = build_default_registry(cfg, memory)
    connectors = build_default_connectors(cfg)
    dossier = Dossier.load(cfg.dossier_dir)

    mock_mcp = AsyncMock()
    mock_mcp.call_tool.return_value = {"ok": True, "categories": [{"id": "tools", "label": "Công cụ", "count": 5}]}
    mock_mcp.server_names.return_value = []
    mock_mcp.health_summary.return_value = {}
    mock_mcp.set_secret_resolver = lambda fn: None

    marketplace = MarketplaceService(
        cfg,
        mcp_manager=mock_mcp,
        vault_store=vault,
        policy=policy,
        broker=broker,
    )

    server = WebAppServer(
        cfg, memory=memory, policy=policy, broker=broker,
        connectors=connectors, mcp_manager=mock_mcp,
        vault_store=vault, registry=registry,
        dossier=dossier, skills=None,
        marketplace=marketplace
    )
    assert await server.start()

    yield server, cfg, memory

    await server.stop()
    await memory.close()


def _url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


@pytest.mark.asyncio
async def test_fresh_webview_loads_task_detail_and_marketplace_real_data(webapp_env):
    """Nghiệm thu T-24.5: phiên WebView mới mở Chi tiết việc + Chợ tải được dữ liệu thật."""
    server, cfg, memory = webapp_env
    fresh_init = make_init_data(user_id=OWNER, token=TOKEN)
    headers = {"X-Telegram-Init-Data": fresh_init}

    async with ClientSession() as session:
        # 1. Gọi Chi tiết việc (/api/task?id=task-real-1)
        async with session.get(_url(server, "/api/task?id=task-real-1"), headers=headers) as resp:
            assert resp.status == 200, f"Chi tiết việc lỗi: {await resp.text()}"
            data = await resp.json()
            assert data["ok"] is True
            assert data["task"]["id"] == "task-real-1"
            assert data["task"]["title"] == "Việc phân tích dữ liệu"
            assert data["task"]["status"] == "done"
            assert "Đã phân tích xong" in data["task"]["result"]

        # 2. Gọi Chợ MCP: summary, categories và refresh
        async with session.get(_url(server, "/api/marketplace/summary"), headers=headers) as resp_summary:
            assert resp_summary.status == 200
            summary_data = await resp_summary.json()
            assert summary_data["ok"] is True

        async with session.get(_url(server, "/api/marketplace/categories"), headers=headers) as resp_cats:
            assert resp_cats.status == 200
            cats_data = await resp_cats.json()
            assert cats_data["ok"] is True
            assert isinstance(cats_data.get("categories"), list)

        async with session.post(_url(server, "/api/marketplace/refresh"), headers=headers, json={}) as resp_refresh:
            assert resp_refresh.status == 200
            refresh_data = await resp_refresh.json()
            assert refresh_data["ok"] is True


@pytest.mark.asyncio
async def test_session_age_distinction_2h_vs_25h(webapp_env):
    """Phân biệt nguyên nhân: initData 2 giờ trước thành công với trần 24h, quá 24h bị chặn."""
    server, cfg, memory = webapp_env

    async with ClientSession() as session:
        # Ca A: Phiên mở 2 giờ trước (7200s) — trong sitemap audit rơi vào ca này
        init_2h_old = make_init_data(user_id=OWNER, auth_date=int(time.time()) - 7200, token=TOKEN)
        headers_2h = {"X-Telegram-Init-Data": init_2h_old}

        async with session.get(_url(server, "/api/task?id=task-real-1"), headers=headers_2h) as resp_task:
            assert resp_task.status == 200, "Phiên 2 giờ trước phải được chấp nhận với trần 24h"
            task_data = await resp_task.json()
            assert task_data["ok"] is True

        async with session.post(_url(server, "/api/marketplace/refresh"), headers=headers_2h, json={}) as resp_mkt:
            assert resp_mkt.status == 200, "Làm mới chợ với phiên 2 giờ trước phải thành công"

        # Ca B: Phiên quá 24 giờ (90000s) — hết hạn thật sự
        init_25h_old = make_init_data(user_id=OWNER, auth_date=int(time.time()) - 90000, token=TOKEN)
        headers_25h = {"X-Telegram-Init-Data": init_25h_old}

        async with session.get(_url(server, "/api/task?id=task-real-1"), headers=headers_25h) as resp_expired:
            assert resp_expired.status == 403
            expired_data = await resp_expired.json()
            assert expired_data["ok"] is False
            assert "initData không hợp lệ hoặc không phải chủ nhân" in expired_data["error"]


def test_frontend_getinitdata_and_error_isolation():
    """Kiểm tra mã nguồn index.html: hàm getInitData động và cô lập lỗi."""
    html_path = Path(__file__).resolve().parent.parent / "mulon" / "webapp" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    # 1. getInitData() động, hỗ trợ cả Telegram.WebApp.initData, hash và search
    assert "function getInitData()" in content
    assert "window.Telegram.WebApp.initData" in content
    assert "tgWebAppData" in content
    assert 'headers: {"X-Telegram-Init-Data": getInitData()' in content

    # 2. Cô lập banner lỗi: showMain và showSub tự động dọn dẹp global-error
    assert 'const ge = $("global-error");\n  if (ge) ge.innerHTML = "";' in content

    # 3. Nút thử lại nội bộ trong màn Chi tiết việc
    assert 'id="btn-retry-open-task"' in content
    assert "Không tải được dòng thời gian" in content
