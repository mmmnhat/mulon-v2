"""Tests cho danh mục Chợ MCP mở rộng & tích hợp mcp-marketplace."""

import pytest
from unittest.mock import AsyncMock

from mulon.config import Config
from mulon.marketplace import MarketplaceService
from mulon.policy import PolicyEngine
from mulon.vault import VaultStore
from mulon.approvals import ApprovalBroker


@pytest.fixture
def service_env(tmp_path):
    cfg = Config()
    policy_file = tmp_path / "policy.json"
    policy_file.write_text("{}", encoding="utf-8")
    db_file = tmp_path / "mulon.db"
    policy = PolicyEngine(policy_file)
    vault = VaultStore(db_file)
    broker = ApprovalBroker(policy=policy)
    return cfg, policy, vault, broker


@pytest.mark.asyncio
async def test_fallback_categories_when_no_mcp(service_env):
    cfg, policy, vault, broker = service_env
    svc = MarketplaceService(
        cfg, policy=policy, broker=broker, vault_store=vault, mcp_manager=None
    )
    data = await svc.get_categories()
    cats = data.get("categories", [])
    assert len(cats) >= 16
    slugs = {c["id"] for c in cats}
    assert "developer-tools" in slugs
    assert "finance" in slugs
    assert "security" in slugs
    assert "file-storage" in slugs
    dev_cat = next(c for c in cats if c["id"] == "developer-tools")
    assert dev_cat["label"] == "Công cụ dev"
    assert dev_cat["count"] > 0
    assert "Kho code" in dev_cat["description"]


@pytest.mark.asyncio
async def test_dynamic_categories_from_mcp_marketplace(service_env):
    cfg, policy, vault, broker = service_env
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.return_value = {
        "ok": True,
        "result": [
            {
                "slug": "custom-cat",
                "name": "Custom Category",
                "description": "Danh mục thử nghiệm",
                "server_count": 42,
            }
        ],
    }
    svc = MarketplaceService(
        cfg, policy=policy, broker=broker, vault_store=vault, mcp_manager=mock_mcp
    )
    data = await svc.get_categories()
    cats = data.get("categories", [])
    slugs = {c["id"] for c in cats}
    assert "custom-cat" in slugs
    custom = next(c for c in cats if c["id"] == "custom-cat")
    assert custom["count"] == 42
    assert custom["description"] == "Danh mục thử nghiệm"


@pytest.mark.asyncio
async def test_search_catalog_async_with_mcp_servers(service_env):
    cfg, policy, vault, broker = service_env
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.return_value = {
        "ok": True,
        "result": {
            "results": [
                {
                    "name": "Excel MCP",
                    "slug": "excel-mcp",
                    "tagline": "Thao tác Excel dễ dàng",
                    "category": "File & Storage",
                    "pricing": "Free",
                    "security_score": 10,
                    "risk_level": "low",
                }
            ]
        },
    }
    svc = MarketplaceService(
        cfg, policy=policy, broker=broker, vault_store=vault, mcp_manager=mock_mcp
    )
    res = await svc.search_catalog_async(category="file-storage", limit=5)
    items = res.get("items", [])
    excel = next((it for it in items if it["slug"] == "excel-mcp"), None)
    assert excel is not None
    assert excel["provider_id"] == "mcp-marketplace"
    assert excel["security"]["score"] == 10
    assert excel["summary"] == "Thao tác Excel dễ dàng"


@pytest.mark.asyncio
async def test_get_listing_detail_mcp_marketplace(service_env):
    cfg, policy, vault, broker = service_env
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.return_value = {
        "ok": True,
        "result": {
            "name": "Excel MCP",
            "slug": "excel-mcp",
            "tagline": "Thao tác Excel",
            "description": "Mô tả chi tiết Excel",
            "security": {
                "score": 10,
                "risk_level": "low",
                "critical_findings": [],
            },
            "install": {
                "config_local": {
                    "mcpServers": {
                        "excel-mcp": {
                            "command": "uvx",
                            "args": ["excel-mcp-server"],
                        }
                    }
                }
            },
        },
    }
    svc = MarketplaceService(
        cfg, policy=policy, broker=broker, vault_store=vault, mcp_manager=mock_mcp
    )
    detail = await svc.get_listing_detail("mcp-marketplace", "excel-mcp")
    assert detail["name"] == "Excel MCP"
    assert detail["manifest"]["command"] == "uvx"
    assert detail["manifest"]["args"] == ["excel-mcp-server"]
    assert detail["security"]["score"] == 10


@pytest.mark.asyncio
async def test_get_listing_detail_mcp_marketplace_without_command(service_env):
    cfg, policy, vault, broker = service_env
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.return_value = {
        "ok": True,
        "result": {
            "name": "Custom Unknown MCP",
            "slug": "custom-unknown-mcp",
            "tagline": "Custom MCP",
            "description": "No local command provided",
            "security": {
                "score": 8,
                "risk_level": "medium",
                "critical_findings": [],
            },
            "install": {
                "config_local": {
                    "mcpServers": {
                        "custom-unknown-mcp": {}
                    }
                }
            },
        },
    }
    svc = MarketplaceService(
        cfg, policy=policy, broker=broker, vault_store=vault, mcp_manager=mock_mcp
    )
    detail = await svc.get_listing_detail("mcp-marketplace", "custom-unknown-mcp")
    assert detail["name"] == "Custom Unknown MCP"
    assert detail["support_state"] == "supported"
    assert detail["manifest"] is not None
    assert detail["manifest"]["command"] == "npx"
    assert "custom-unknown-mcp" in detail["manifest"]["args"]


@pytest.mark.asyncio
async def test_get_listing_detail_google_workspace_fallback(service_env):
    cfg, policy, vault, broker = service_env
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.return_value = {
        "ok": True,
        "result": {
            "name": "Google Workspace MCP",
            "slug": "google-workspace-mcp",
            "tagline": "Google Workspace",
            "description": "Google Workspace integration",
            "security": {
                "score": 8,
                "risk_level": "medium",
                "critical_findings": [],
            },
            "install": {},
        },
    }
    svc = MarketplaceService(
        cfg, policy=policy, broker=broker, vault_store=vault, mcp_manager=mock_mcp
    )
    detail = await svc.get_listing_detail("mcp-marketplace", "google-workspace-mcp")
    assert detail["name"] == "Google Workspace MCP"
    assert detail["support_state"] == "supported"
    assert detail["manifest"]["command"] == "uvx"
    assert "workspace-mcp" in detail["manifest"]["args"]


@pytest.mark.asyncio
async def test_search_catalog_async_pagination(service_env):
    cfg, policy, vault, broker = service_env
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.return_value = {
        "ok": True,
        "result": {
            "total_matches": 100,
            "has_more": True,
            "page": 2,
            "results": [
                {
                    "name": "Server Page 2",
                    "slug": "server-p2",
                    "tagline": "Server ở trang 2",
                    "category": "developer-tools",
                    "pricing": "Free",
                    "security_score": 9,
                    "risk_level": "low",
                }
            ],
        },
    }
    svc = MarketplaceService(
        cfg, policy=policy, broker=broker, vault_store=vault, mcp_manager=mock_mcp
    )
    res = await svc.search_catalog_async(
        category="developer-tools", page=2, limit=10
    )
    assert res["page"] == 2
    assert res["has_more"] is True
    assert res["next_cursor"] == "3"
    assert len(res["items"]) == 1
    assert res["items"][0]["slug"] == "server-p2"
    mock_mcp.call_tool.assert_called_with(
        "mcp-marketplace",
        "search_servers",
        {"category": "developer-tools", "page": 2, "limit": 10},
    )
