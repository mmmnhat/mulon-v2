"""Phase 3 — khung connector trung tính: interface health_check +
call, đăng ký lazy, connector lỗi/vắng thì degrade sạch. Adapter
'system' chạy thật; transport giả cho các case còn lại."""

from mulon.connectors import (
    Connector,
    ConnectorRegistry,
    SystemConnector,
    build_default_connectors,
    register_connector_tools,
)
from mulon.tools import ToolRegistry


class FakeTransportConnector(Connector):
    """Connector test với transport giả lập (không mạng, không key)."""

    name = "fake"

    def __init__(self, transport):
        self._transport = transport

    async def health_check(self):
        data = await self._transport("health", {})
        return {"ok": True, "name": self.name, "balance": data["balance"]}

    async def call(self, action, args):
        data = await self._transport(action, args)
        return {"ok": True, "data": data}


async def fake_transport(action, args):
    if action == "health":
        return {"balance": 12345}
    if action == "items":
        return {"items": ["a", "b"]}
    raise RuntimeError("transport không rõ action")


async def test_system_connector_real(cfg):
    conn = SystemConnector()
    health = await conn.health_check()
    assert health["ok"] is True
    assert health["name"] == "system"
    assert health["hostname"]
    assert health["time_utc"]
    t = await conn.call("time", {})
    assert t["ok"] is True and t["time_local"]
    bad = await conn.call("không_có", {})
    assert bad["ok"] is False


async def test_registry_lazy_and_health(cfg):
    registry = ConnectorRegistry()
    built = []

    def factory():
        built.append(1)
        return FakeTransportConnector(fake_transport)

    registry.register_lazy("fake", factory)
    assert built == []  # lazy: chưa dùng thì chưa dựng
    report = await registry.health_all()
    assert built == [1]
    assert report["fake"]["ok"] is True
    assert report["fake"]["balance"] == 12345

    out = await registry.call("fake", "items", {})
    assert out["ok"] is True
    assert out["data"]["items"] == ["a", "b"]

    missing = await registry.call("không_tồn_tại", "x", {})
    assert missing["ok"] is False


async def test_broken_factory_degrades(cfg):
    registry = ConnectorRegistry()

    def bad_factory():
        raise RuntimeError("chưa cấu hình")

    registry.register_lazy("hỏng", bad_factory)
    report = await registry.health_all()
    assert report["hỏng"]["ok"] is False
    assert report["hỏng"]["configured"] is False
    out = await registry.call("hỏng", "x", {})
    assert out["ok"] is False


async def test_connector_tools(cfg):
    connectors = build_default_connectors(cfg)
    connectors.register(FakeTransportConnector(fake_transport))
    reg = ToolRegistry()
    register_connector_tools(reg, connectors)

    health = await reg.execute("connector_health", {})
    assert health["ok"] is True
    assert health["connectors"]["system"]["ok"] is True
    assert health["connectors"]["fake"]["balance"] == 12345

    call = await reg.execute("connector_call", {
        "name": "system", "action": "time",
    })
    assert call["ok"] is True and call["time_utc"]

    bad = await reg.execute("connector_call", {
        "name": "system", "action": "hack",
    })
    assert bad["ok"] is False
