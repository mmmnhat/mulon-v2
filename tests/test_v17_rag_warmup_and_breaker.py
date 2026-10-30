"""Bộ test hồi quy cho T-39.3 (Agency Council Chặng 3):
- ISSUE-03: FastEmbed ONNX Startup Warm-up (chạy nền, không chặn, degrade sạch).
- ISSUE-10: Bulkhead Circuit Breaker cách ly lỗi per-tier / per-model.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mulon.config import Config
from mulon.embeddings import FastEmbedEmbedder, HashStubEmbedder
from mulon.gateway import CircuitOpenError, ModelGateway


# ===========================================================================
# 1. Test Bulkhead Circuit Breaker cách ly theo Tier (ISSUE-10)
# ===========================================================================

@pytest.mark.asyncio
async def test_circuit_breaker_bulkhead_isolation():
    """Khi model cheap bị fail 5 lần liên tiếp mở breaker, model brain vẫn hoạt động bình thường."""
    cfg = Config(proxy_base_url="http://127.0.0.1:8317", proxy_api_key="sk-test")
    gw = ModelGateway(cfg)

    # 1. Giả lập model 'cheap' (gemini-3.5-flash-lite) fail liên tiếp 5 lần
    model_cheap = "gemini-3.5-flash-lite"
    model_brain = "gemini-3.8-flash-high"

    with patch("litellm.acompletion", side_effect=RuntimeError("provider 429 quota exhausted")):
        for _ in range(5):
            try:
                await gw.complete(
                    messages=[{"role": "user", "content": "ping cheap"}],
                    model=model_cheap,
                )
            except Exception:
                pass

    # 2. Kiểm tra breaker riêng của cheap đã mở -> ném CircuitOpenError
    with pytest.raises(CircuitOpenError) as exc_info:
        await gw.complete(
            messages=[{"role": "user", "content": "ping cheap again"}],
            model=model_cheap,
        )
    assert "circuit breaker đang mở cho model" in str(exc_info.value)
    assert "gemini-3.5-flash-lite" in str(exc_info.value)

    # 3. Model 'brain' KHÔNG bị ảnh hưởng (Bulkhead Isolation) -> gọi thành công
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Phản hồi từ Brain Model"))]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=10, total_tokens=20)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_resp)):
        comp = await gw.complete(
            messages=[{"role": "user", "content": "ping brain"}],
            model=model_brain,
        )
        assert comp.text == "Phản hồi từ Brain Model"
        assert "gemini-3.8-flash-high" in comp.model


@pytest.mark.asyncio
async def test_circuit_breaker_success_resets_failure_count():
    """Gọi thành công trước khi đạt ngưỡng sẽ reset bộ đếm lỗi của model đó."""
    cfg = Config(proxy_base_url="http://127.0.0.1:8317", proxy_api_key="sk-test")
    gw = ModelGateway(cfg)
    model = "claude-sonnet-4-6"

    # Gọi _record_failure 2 lần (dưới ngưỡng 5)
    gw._record_failure(model)
    gw._record_failure(model)

    key = gw._model_tier_key(model)
    assert gw._breakers[key]["consec_failures"] == 2

    # Gọi thành công 1 lần qua complete()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="Success!"))]
    mock_resp.usage = MagicMock(prompt_tokens=5, completion_tokens=5)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_resp)):
        await gw.complete(messages=[{"role": "user", "content": "hi"}], model=model)

    # Đã được reset về 0
    assert gw._breakers[key]["consec_failures"] == 0


# ===========================================================================
# 2. Test FastEmbed Startup Warm-up (ISSUE-03)
# ===========================================================================

def test_fastembed_warmup_success():
    """Hàm warmup nạp trước model ONNX và chạy dummy embedding."""
    embedder = FastEmbedEmbedder(model="BAAI/bge-m3")

    mock_impl = MagicMock()
    mock_impl.embed.return_value = [[0.1] * 1024]

    with patch.object(embedder, "_ensure_impl", return_value=mock_impl):
        ok = embedder.warmup()
        assert ok is True
        mock_impl.embed.assert_called_once_with(["warmup"])


def test_fastembed_warmup_graceful_degradation():
    """Nếu nạp model gặp lỗi, warmup bắt ngoại lệ và trả False, không sập tiến trình."""
    embedder = FastEmbedEmbedder(model="BAAI/bge-m3")

    with patch.object(embedder, "_ensure_impl", side_effect=RuntimeError("ONNX library missing")):
        ok = embedder.warmup()
        assert ok is False


def test_hash_stub_embedder_warmup():
    """HashStubEmbedder có hàm warmup() tương thích và luôn trả True."""
    stub = HashStubEmbedder(dim=128)
    assert hasattr(stub, "warmup")
    assert stub.warmup() is True
