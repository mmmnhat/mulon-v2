"""Tests cho T-24.6: Yêu cầu dùng bí mật có sẵn phải đi thẳng đường kho -> API.

Bảo đảm:
1. VaultStore.resolve() hỗ trợ đầy đủ các định dạng nhãn, vault:<label>, ${VAULT:<label>}, ref UUID.
2. run_command tự động thay thế ${VAULT:<nhãn>} và vault:<nhãn> bằng bí mật thật, redact kết quả.
3. run_command báo lỗi rõ ràng ngay lập tức khi thiếu bí mật, không cho chạy lệnh với placeholder rác.
4. run_command chặn lùng sục mã nguồn (find/grep) trong repo khi đã có connector hoặc kho bí mật.
5. _act_loop chặn lặp đọc cùng một trang web tài liệu và chặn loop tool lặp lại >= 3 lần.
6. build_self_knowledge hướng dẫn đường thẳng Kho -> API và đường thẳng Connector.
"""

import asyncio
import json
import pytest
from pathlib import Path

from mulon.agent import Agent, build_self_knowledge
from mulon.config import Config
from mulon.connectors import ConnectorRegistry, register_connector_tools, Connector
from mulon.policy import PolicyEngine
from mulon.tools import ToolRegistry, build_default_registry
from mulon.vault import VaultStore, register_vault_tools


@pytest.fixture
def test_vault(tmp_path):
    vpath = tmp_path / "test_vault.json"
    return VaultStore(vpath)


def test_vault_store_resolve_various_formats(test_vault):
    ref = test_vault.put("accesstrade:api_key", "at_secret_token_12345")
    assert ref.startswith("vault:")

    # 1. Tra cứu theo ref UUID
    assert test_vault.resolve(ref) == "at_secret_token_12345"
    assert test_vault.exists(ref)

    # 2. Tra cứu theo nhãn chính xác
    assert test_vault.resolve("accesstrade:api_key") == "at_secret_token_12345"
    assert test_vault.exists("accesstrade:api_key")

    # 3. Tra cứu với prefix vault:
    assert test_vault.resolve("vault:accesstrade:api_key") == "at_secret_token_12345"
    assert test_vault.exists("vault:accesstrade:api_key")

    # 4. Tra cứu với placeholder ${VAULT:...} và ${vault:...}
    assert test_vault.resolve("${VAULT:accesstrade:api_key}") == "at_secret_token_12345"
    assert test_vault.resolve("${vault:accesstrade:api_key}") == "at_secret_token_12345"
    assert test_vault.exists("${VAULT:accesstrade:api_key}")

    # 5. Tra cứu mềm / normalized (: vs _)
    assert test_vault.resolve("accesstrade_api_key") == "at_secret_token_12345"
    assert test_vault.resolve("ACCESSTRADE:API_KEY") == "at_secret_token_12345"

    # 6. Khóa không tồn tại trả về None / False
    assert test_vault.resolve("non_existent_key") is None
    assert not test_vault.exists("non_existent_key")


@pytest.mark.asyncio
async def test_run_command_vault_expansion_and_redaction(tmp_path):
    vpath = tmp_path / "test_vault.json"
    store = VaultStore(vpath)
    store.put("accesstrade:api_key", "super_secret_value_xyz")

    cfg = Config(
        workspace_dir=str(tmp_path / "workspace"),
        dossier_dir=str(tmp_path / "dossier"),
        vault_path=str(vpath),
    )
    reg = build_default_registry(cfg, memory=None, vault_store=store)

    # Lệnh dùng ${VAULT:accesstrade:api_key}
    res = await reg.execute("run_command", {
        "command": "echo 'Key is ${VAULT:accesstrade:api_key}'"
    })
    assert res.get("ok") is True
    # Giá trị thật phải được giấu / redact lại thành placeholder trong output
    assert "super_secret_value_xyz" not in res.get("stdout", "")
    assert "${VAULT:accesstrade:api_key}" in res.get("stdout", "")

    # Lệnh dùng vault:accesstrade:api_key
    res2 = await reg.execute("run_command", {
        "command": "echo 'Key is vault:accesstrade:api_key'"
    })
    assert res2.get("ok") is True
    assert "super_secret_value_xyz" not in res2.get("stdout", "")
    assert "vault:accesstrade:api_key" in res2.get("stdout", "")


@pytest.mark.asyncio
async def test_run_command_vault_missing_secret_fails_fast(tmp_path):
    vpath = tmp_path / "test_vault.json"
    store = VaultStore(vpath)
    store.put("openai:key", "sk-123456")

    cfg = Config(
        workspace_dir=str(tmp_path / "workspace"),
        dossier_dir=str(tmp_path / "dossier"),
        vault_path=str(vpath),
    )
    reg = build_default_registry(cfg, memory=None, vault_store=store)

    res = await reg.execute("run_command", {
        "command": "curl -H 'Authorization: Bearer ${VAULT:accesstrade:api_key}' https://api.accesstrade.vn"
    })
    # Phải fail fast ngay lập tức, không chạy curl
    assert res.get("ok") is False
    assert "Không tìm thấy bí mật trong Kho an toàn" in res.get("error", "")
    assert "list_vault_secrets" in res.get("error", "")
    assert "request_vault_secret" in res.get("error", "")


@pytest.mark.asyncio
async def test_run_command_blocks_repo_search_for_connectors_and_vault(tmp_path):
    cfg = Config(
        workspace_dir=str(tmp_path / "workspace"),
        dossier_dir=str(tmp_path / "dossier"),
    )
    reg = build_default_registry(cfg, memory=None)

    # 1. Tìm kiếm Threads trong repo
    res = await reg.execute("run_command", {
        "command": "find . -maxdepth 3 -name '*threads*'"
    })
    assert res.get("ok") is False
    assert "Chặn tìm kiếm mã nguồn" in res.get("error", "")
    assert "threads_personal" in res.get("error", "")

    # 2. Tìm kiếm Accesstrade trong repo
    res2 = await reg.execute("run_command", {
        "command": "grep -r 'accesstrade' ."
    })
    assert res2.get("ok") is False
    assert "Chặn tìm kiếm mã nguồn" in res2.get("error", "")
    assert "Kho an toàn Vault" in res2.get("error", "")


def test_build_self_knowledge_contains_direct_path():
    cfg = Config()
    reg = ToolRegistry()
    knowledge = build_self_knowledge(cfg, reg)
    assert "ĐƯỜNG THẲNG KHO BÍ MẬT -> API" in knowledge
    assert "ĐƯỜNG THẲNG CONNECTOR" in knowledge
    assert "CẤM LẶP ĐỌC CÙNG MỘT TRANG TÀI LIỆU" in knowledge
    assert "${VAULT:<nhãn>}" in knowledge
    assert "threads_personal" in knowledge


@pytest.mark.asyncio
async def test_connector_call_unknown_name_hints_available():
    creg = ConnectorRegistry()
    class DummyConn(Connector):
        name = "threads_personal"
    creg.register(DummyConn())

    reg = ToolRegistry()
    register_connector_tools(reg, creg)

    res = await reg.execute("connector_call", {"name": "invalid_conn", "action": "test"})
    assert res.get("ok") is False
    assert "threads_personal" in res.get("error", "")


class _FakeToolCall:
    def __init__(self, name: str, args: dict, call_id: str = "c1"):
        self.id = call_id
        self.name = name
        self.arguments = json.dumps(args)


class _FakeCompletion:
    def __init__(self, text: str = "", tool_calls=None):
        self.text = text
        self.tool_calls = tool_calls or []


class _ScriptedGateway:
    def __init__(self, scripted_responses):
        self.responses = list(scripted_responses)
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.responses:
            return self.responses.pop(0)
        return _FakeCompletion(text="Xong tác vụ.")


@pytest.mark.asyncio
async def test_act_loop_repetition_guard_blocks_repeat_web_and_tool_loops(tmp_path):
    from mulon.context import ContextEngine, Dossier
    from tests.conftest import open_memory
    from mulon.tools import ToolSpec

    cfg = Config(
        workspace_dir=str(tmp_path / "workspace"),
        dossier_dir=str(tmp_path / "dossier"),
        policy_path=str(tmp_path / "policy.json"),
        db_path=str(tmp_path / "test.db"),
    )
    Path(cfg.policy_path).write_text("{}", encoding="utf-8")
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    reg = ToolRegistry()

    # Giả lập tool web_fetch
    fetch_calls = []
    async def fake_web_fetch(url: str):
        fetch_calls.append(url)
        return {"ok": True, "text": f"Nội dung từ {url}"}

    reg.register(ToolSpec(
        name="web_fetch",
        description="Đọc web",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
        group="web",
        timeout_s=5,
        handler=fake_web_fetch,
    ))

    # Kịch bản: model gọi web_fetch 2 lần liên tiếp cùng một URL
    scripted = [
        # Lượt 1: Gọi web_fetch lần 1
        _FakeCompletion(tool_calls=[_FakeToolCall("web_fetch", {"url": "https://developer.accesstrade.vn/docs"}, "c1")]),
        # Lượt 2: Model lại gọi web_fetch đúng URL đó lần 2
        _FakeCompletion(tool_calls=[_FakeToolCall("web_fetch", {"url": "https://developer.accesstrade.vn/docs"}, "c2")]),
        # Lượt 3: Model kết thúc
        _FakeCompletion(text="Báo cáo kết quả."),
    ]
    gw = _ScriptedGateway(scripted)
    ctx = ContextEngine(cfg, dossier, memory, gw)
    agent = Agent(cfg, gw, memory, ctx, reg, policy)

    await memory.create_task("task_1", "sess_1", "Tra cứu", ["bước 1"])
    convo = [{"role": "user", "content": "Tra cứu tài liệu"}]
    evidence = []
    final_text = await agent._act_loop("sess_1", "task_1", convo, reg.schemas(), evidence, None)

    # Tool web_fetch chỉ được chạy THẬT ĐÚNG 1 LẦN
    assert len(fetch_calls) == 1
    # Ở lượt 2, tool message trả về lỗi chặn lặp
    tool_msgs = [m for m in convo if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    assert "đã được đọc thành công ở bước trước" in tool_msgs[1]["content"]
    assert "TUYỆT ĐỐI không đọc lại" in tool_msgs[1]["content"]


@pytest.mark.asyncio
async def test_act_loop_repetition_guard_blocks_3x_identical_tool_calls(tmp_path):
    from mulon.context import ContextEngine, Dossier
    from tests.conftest import open_memory
    from mulon.tools import ToolSpec

    cfg = Config(
        workspace_dir=str(tmp_path / "workspace"),
        dossier_dir=str(tmp_path / "dossier"),
        policy_path=str(tmp_path / "policy.json"),
        db_path=str(tmp_path / "test2.db"),
    )
    Path(cfg.policy_path).write_text("{}", encoding="utf-8")
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    reg = ToolRegistry()

    call_count = 0
    async def fake_custom_tool(item: str):
        nonlocal call_count
        call_count += 1
        return {"ok": False, "error": f"chưa tìm thấy {item}"}

    reg.register(ToolSpec(
        name="custom_search",
        description="Search something",
        parameters={"type": "object", "properties": {"item": {"type": "string"}}},
        group="custom",
        timeout_s=5,
        handler=fake_custom_tool,
    ))

    # Kịch bản: model gọi custom_search 3 lần liên tiếp với cùng tham số
    scripted = [
        _FakeCompletion(tool_calls=[_FakeToolCall("custom_search", {"item": "balance"}, "c1")]),
        _FakeCompletion(tool_calls=[_FakeToolCall("custom_search", {"item": "balance"}, "c2")]),
        _FakeCompletion(tool_calls=[_FakeToolCall("custom_search", {"item": "balance"}, "c3")]),
        _FakeCompletion(text="Dừng lại vì không tìm thấy."),
    ]
    gw = _ScriptedGateway(scripted)
    ctx = ContextEngine(cfg, dossier, memory, gw)
    agent = Agent(cfg, gw, memory, ctx, reg, policy)

    await memory.create_task("task_2", "sess_2", "Tìm kiếm", ["bước 1"])
    convo = [{"role": "user", "content": "Tìm balance"}]
    evidence = []
    final_text = await agent._act_loop("sess_2", "task_2", convo, reg.schemas(), evidence, None)

    # Tool chỉ được execute 2 lần, lần thứ 3 bị chặn bởi repetition guard
    assert call_count == 2
    tool_msgs = [m for m in convo if m.get("role") == "tool"]
    assert len(tool_msgs) == 3
    assert "gọi 3 lần trong tác vụ nhưng không đem lại kết quả mới" in tool_msgs[2]["content"]
    assert "TUYỆT ĐỐI dừng lặp lại" in tool_msgs[2]["content"]


