"""Test T-16: muse2api theo Đường A (upstream của CLIProxyAPI).

Quy tắc kiểm tra:
- MuLon không gọi thẳng muse2api: module muse2api.py không chứa
  địa chỉ gọi trực tiếp, chỉ sinh cấu hình cho CLIProxyAPI đọc.
- Key thật không lọt vào cấu hình: chỉ placeholder ${...} hoặc
  vault:... được chấp nhận.
- Model muse/muse-spark đi qua proxy 8317 như model thường.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from mulon import muse2api
from mulon.gateway import ModelGateway


def _gateway():
    # Dựng gateway mà không chạy __init__ (tránh validate proxy +
    # dependency ngoài), chỉ để kiểm tra bảng alias chuẩn hóa tên.
    gateway = ModelGateway.__new__(ModelGateway)
    gateway.cfg = SimpleNamespace(model_brain="gemini-3.8-flash")
    return gateway


def test_is_and_resolve_muse_model():
    assert muse2api.is_muse_model("muse/muse-spark")
    assert muse2api.is_muse_model("muse-spark")
    assert muse2api.resolve_muse_model("muse-spark") == "muse/muse-spark"
    assert muse2api.resolve_muse_model("muse/muse-spark") == "muse/muse-spark"
    assert not muse2api.is_muse_model("gemini-3.8-flash")
    assert muse2api.resolve_muse_model("gemini-3.8-flash") is None
    assert not muse2api.is_muse_model(None)
    assert muse2api.resolve_muse_model("") is None


def test_gateway_alias_muse_spark():
    gateway = _gateway()
    assert gateway._litellm_model("muse/muse-spark") == "openai/muse/muse-spark"
    assert gateway._litellm_model("muse-spark") == "openai/muse/muse-spark"
    assert gateway._litellm_model("openai/muse/muse-spark") == "openai/muse/muse-spark"
    # Model thường không bị ảnh hưởng bởi alias mới.
    assert gateway._litellm_model(None) == "openai/gemini-3.8-flash-high"


def test_build_cliproxy_upstream_placeholder_only():
    entry = muse2api.build_cliproxy_upstream(
        "http://127.0.0.1:18610/v1", "${MUSE2API_KEY}"
    )
    upstream = entry["openai-compatibility"][0]
    assert upstream["name"] == "muse2api"
    assert upstream["prefix"] == "muse"
    assert upstream["base-url"] == "http://127.0.0.1:18610/v1"
    assert upstream["keys"] == [{"api-key": "${MUSE2API_KEY}"}]
    assert upstream["models"] == [{"name": "muse-spark", "alias": "muse-spark"}]
    vault_entry = muse2api.build_cliproxy_upstream(
        "http://localhost:18610/v1", "vault:muse2api:key"
    )
    assert vault_entry["openai-compatibility"][0]["keys"] == [
        {"api-key": "vault:muse2api:key"}
    ]


def test_build_cliproxy_upstream_rejects_remote_host():
    with pytest.raises(ValueError):
        muse2api.build_cliproxy_upstream(
            "https://example.com:18610/v1", "${MUSE2API_KEY}"
        )


def test_build_cliproxy_upstream_rejects_missing_port():
    with pytest.raises(ValueError):
        muse2api.build_cliproxy_upstream(
            "http://127.0.0.1/v1", "${MUSE2API_KEY}"
        )


def test_build_cliproxy_upstream_rejects_real_key():
    with pytest.raises(ValueError):
        muse2api.build_cliproxy_upstream(
            "http://127.0.0.1:18610/v1", "my-real-looking-key-123"
        )
    with pytest.raises(ValueError):
        muse2api.build_cliproxy_upstream("http://127.0.0.1:18610/v1", "")


def test_muse_model_in_proxy_models():
    assert muse2api.muse_model_in_proxy_models(["gemini-3.8-flash", "muse-spark"])
    assert muse2api.muse_model_in_proxy_models([{"id": "muse/muse-spark"}])
    assert muse2api.muse_model_in_proxy_models([{"name": "muse-spark"}])
    assert not muse2api.muse_model_in_proxy_models(["gemini-3.8-flash"])
    assert not muse2api.muse_model_in_proxy_models([])


def test_mulon_proxy_must_stay_8317():
    muse2api.assert_mulon_proxy_unchanged("http://127.0.0.1:8317/v1")
    muse2api.assert_mulon_proxy_unchanged("http://localhost:8317/v1")
    with pytest.raises(ValueError):
        muse2api.assert_mulon_proxy_unchanged("http://127.0.0.1:18610/v1")
    with pytest.raises(ValueError):
        muse2api.assert_mulon_proxy_unchanged("https://example.com:8317/v1")


def test_muse2api_module_has_no_direct_call_target():
    source = Path(muse2api.__file__).read_text(encoding="utf-8")
    # Module chỉ sinh cấu hình, không gõ chết cổng gọi trực tiếp.
    assert "18610" not in source
    assert "sk-" not in source


@pytest.mark.asyncio
async def test_gateway_complete_via_stub_proxy(monkeypatch):
    """Test tích hợp complete() model muse-spark qua stub OpenAI-compatible proxy (sửa NEEDS-FIX T-16)."""
    from aiohttp import web
    from mulon.config import Config

    monkeypatch.setenv("MULON_ALLOW_REMOTE_PROXY", "1")

    received_requests = []

    async def handle_completion(request):
        data = await request.json()
        received_requests.append(data)
        return web.json_response({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1234567890,
            "model": data.get("model"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Phản hồi thử từ muse2api stub."},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
        })

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handle_completion)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    try:
        cfg = Config(proxy_base_url=f"http://127.0.0.1:{port}/v1")
        gw = ModelGateway(cfg)

        # 1. Gọi với model alias ngắn: muse-spark
        res1 = await gw.complete([{"role": "user", "content": "xin chào"}], model="muse-spark")
        assert res1.text == "Phản hồi thử từ muse2api stub."
        assert len(received_requests) == 1
        # LiteLLM chuyển wire model 'muse/muse-spark' tới proxy OpenAI-compatible
        assert received_requests[0]["model"] == "muse/muse-spark"

        # 2. Gọi với model đầy đủ: muse/muse-spark
        res2 = await gw.complete([{"role": "user", "content": "xin chào 2"}], model="muse/muse-spark")
        assert res2.text == "Phản hồi thử từ muse2api stub."
        assert len(received_requests) == 2
        assert received_requests[1]["model"] == "muse/muse-spark"
    finally:
        await runner.cleanup()
