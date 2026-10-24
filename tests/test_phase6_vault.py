"""Phase 6 — Secure Vault (mục 16.12): form một lần bind
127.0.0.1, token dùng 1 lần/hết hạn ~10 phút, giá trị ghi thẳng
vào file vault 0600 dưới ref vault:<uuid>; giá trị TUYỆT ĐỐI
không xuất hiện trong chat/log/trajectory — chỉ resolve() đọc."""

import asyncio
import json
import logging
import re
import socket
import stat
import urllib.parse
import urllib.request
from dataclasses import replace

from mulon.vault import VaultFormServer, VaultStore
from tests.conftest import open_memory

SECRET = "S3CRET-VALUE-khong-duoc-lo-123"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _http(method, url, data=None):
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


async def _http_async(method, url, data=None):
    return await asyncio.to_thread(_http, method, url, data)


def test_store_put_resolve_labels_delete(cfg):
    store = VaultStore(cfg.vault_path)
    ref = store.put("api-key-x", SECRET)
    assert ref.startswith("vault:")
    assert store.exists(ref) is True
    assert store.resolve(ref) == SECRET  # cửa đọc duy nhất
    labels = store.labels()
    assert labels and labels[0]["label"] == "api-key-x"
    assert SECRET not in json.dumps(labels)  # label list không lộ giá trị
    mode = stat.S_IMODE(cfg.vault_path.stat().st_mode)
    assert mode == 0o600
    assert store.delete(ref) is True
    assert store.resolve(ref) is None


async def test_form_flow_single_use_and_redaction(cfg, caplog):
    port = _free_port()
    cfg2 = replace(cfg, vault_port=port, vault_token_ttl_s=600)
    store = VaultStore(cfg2.vault_path)
    server = VaultFormServer(cfg2, store)
    assert server.start() is True
    try:
        link = server.link_for("token-dich-vu")
        assert f"127.0.0.1:{port}" in link
        # GET lần 1: ra form, KHÔNG chứa giá trị nào.
        status, body = await _http_async("GET", link)
        assert status == 200 and "token-dich-vu" in body
        assert SECRET not in body
        # POST giá trị -> nhận ref, giá trị không bị echo lại.
        data = urllib.parse.urlencode({"value": SECRET}).encode()
        with caplog.at_level(logging.DEBUG):
            status, body = await _http_async("POST", link, data)
        assert status == 200
        m = re.search(r"vault:[0-9a-f-]{36}", body)
        assert m, body
        ref = m.group(0)
        assert SECRET not in body
        assert store.resolve(ref) == SECRET
        # Token đã dùng -> cả GET lẫn POST đều 410.
        status, _ = await _http_async("GET", link)
        assert status == 410
        status, _ = await _http_async("POST", link, data)
        assert status == 410
        # Token bịa -> 410.
        status, _ = await _http_async(
            "GET", f"http://127.0.0.1:{port}/v/khong-co-that")
        assert status == 410
        # Giá trị không lọt vào log của bất kỳ logger nào.
        assert SECRET not in caplog.text
    finally:
        server.stop()


async def test_token_expiry(cfg):
    cfg2 = replace(cfg, vault_port=_free_port(), vault_token_ttl_s=0)
    server = VaultFormServer(cfg2, VaultStore(cfg2.vault_path))
    token = server.create_token("het-han")
    assert server.check_token(token) is None  # ttl=0 -> hết hạn ngay
    assert server.check_token("bie") is None
    assert server.check_token(None) is None


async def test_secret_never_touches_memory(cfg):
    """Luồng vault chạy độc lập với Memory: quét toàn bộ trajectory
    + ledger khẳng định không chứa giá trị bí mật."""
    memory = await open_memory(cfg)
    store = VaultStore(cfg.vault_path)
    ref = store.put("khoa-bao-mat", SECRET)
    assert store.resolve(ref) == SECRET
    cur = await memory.db.execute(
        "SELECT payload FROM trajectory UNION ALL SELECT detail"
        " FROM ledger")
    blob = " ".join(str(r[0]) for r in await cur.fetchall())
    assert SECRET not in blob
    await memory.close()


def test_vault_store_update_and_delete_by_label(cfg):
    store = VaultStore(cfg.vault_path)
    ref = store.put("old_label", "old_val")
    assert store.resolve(ref) == "old_val"

    # Update label only
    assert store.update(ref, label="new_label") is True
    assert store.resolve(ref) == "old_val"
    labels = store.labels()
    found = [x for x in labels if x["ref"] == ref]
    assert found and found[0]["label"] == "new_label"

    # Update value only
    assert store.update(ref, value="new_val") is True
    assert store.resolve(ref) == "new_val"

    # Update both
    assert store.update(ref, label="final_label", value="final_val") is True
    assert store.resolve(ref) == "final_val"

    # Delete by label
    deleted_cnt = store.delete_by_label("final_label")
    assert deleted_cnt == 1
    assert store.resolve(ref) is None


async def test_vault_tools_list_and_delete(cfg):
    from mulon.tools import ToolRegistry
    from mulon.vault import register_vault_tools

    reg = ToolRegistry()
    register_vault_tools(reg, cfg)
    assert reg.get("list_vault_secrets") is not None
    assert reg.get("delete_vault_secret") is not None

    store = VaultStore(cfg.vault_path)
    ref = store.put("secret:test_item", "my_secret_token_999")

    list_tool = reg.get("list_vault_secrets").handler
    list_res = await list_tool()
    assert list_res["ok"] is True
    assert any(x["ref"] == ref for x in list_res["secrets"])
    assert "my_secret_token_999" not in json.dumps(list_res)

    del_tool = reg.get("delete_vault_secret").handler
    del_res = await del_tool(label="secret:test_item")
    assert del_res["ok"] is True
    assert store.resolve(ref) is None
