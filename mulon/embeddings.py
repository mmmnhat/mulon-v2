"""Lớp embedding cho hybrid recall (thiết kế mục 4.2).

Interface `Embedder` là protocol tối thiểu: `embed(texts) -> vectors`
(đồng bộ, CPU-bound — tầng gọi bọc bằng asyncio.to_thread). Hai backend:

- `FastEmbedEmbedder`: bge-m3 qua fastembed, **lazy-load** — chỉ nạp
  model ở lần embed đầu tiên (tải ~570MB lần đầu). fastembed là tuỳ
  chọn: vắng thì `build_embedder` trả None và recall degrade sạch
  xuống BM25-only, đúng fallback chain của thiết kế.
- `HashStubEmbedder`: embedding tất định bằng băm túi từ — CHỈ cho
  test và dev offline, không có giá trị ngữ nghĩa thật.

Mọi vector đều được chuẩn hoá đơn vị ở tầng Memory trước khi lưu/
truy vấn, nên khoảng cách L2 của sqlite-vec đổi thẳng ra cosine.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from typing import Optional, Protocol, Sequence, runtime_checkable

logger = logging.getLogger("mulon.embeddings")

# Số chiều đã biết của các model được hỗ trợ sẵn.
KNOWN_DIMS = {
    "BAAI/bge-m3": 1024,
    "intfloat/multilingual-e5-large": 1024,
}


@runtime_checkable
class Embedder(Protocol):
    """Hợp đồng embedder: thuộc tính name/dim + hàm embed đồng bộ."""

    name: str
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...


def normalize(vec: Sequence[float]) -> list[float]:
    """Chuẩn hoá vector về độ dài 1 (vector 0 giữ nguyên)."""
    norm = math.sqrt(sum(float(x) * float(x) for x in vec))
    if norm <= 0:
        return [float(x) for x in vec]
    return [float(x) / norm for x in vec]


class HashStubEmbedder:
    """Embedding tất định cho test: băm từng từ vào 1 chiều, cộng dồn.

    Hai đoạn chia sẻ nhiều từ sẽ có cosine cao — đủ để test cơ chế
    hợp nhất hybrid và đánh chỉ mục lúc ghi, không cần model thật.
    """

    name = "hash-stub"

    def __init__(self, dim: int = 128):
        self.dim = int(dim)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for tok in re.findall(r"[\w]+", (text or "").lower()):
                digest = hashlib.md5(tok.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "little") % self.dim
                vec[idx] += 1.0
            out.append(normalize(vec))
        return out

    def warmup(self) -> bool:
        """HashStubEmbedder luôn sẵn sàng tức thì mà không cần nạp trọng số."""
        return True


class FastEmbedEmbedder:
    """bge-m3 qua fastembed, nạp lười ở lần embed đầu tiên."""

    def __init__(self, model: str = "BAAI/bge-m3"):
        self.model = model
        self.name = f"fastembed:{model}"
        self.dim = KNOWN_DIMS.get(model, 1024)
        self._impl = None
        self._lock = threading.Lock()

    def _ensure_impl(self):
        if self._impl is None:
            with self._lock:
                if self._impl is None:
                    from fastembed import TextEmbedding

                    self._impl = TextEmbedding(model_name=self.model)
        return self._impl

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        impl = self._ensure_impl()
        return [[float(x) for x in vec] for vec in impl.embed(list(texts))]

    def warmup(self) -> bool:
        """Nạp trước model ONNX và thực thi phép embed mẫu để khởi tạo session.

        Chạy trong thread nền (asyncio.to_thread) lúc khởi động bot để triệt tiêu
        độ trễ 3-8s ở lượt chat đầu tiên của người dùng (ISSUE-03).
        """
        try:
            impl = self._ensure_impl()
            list(impl.embed(["warmup"]))
            logger.info("FastEmbed (%s) đã nạp trước (warm-up) thành công", self.model)
            return True
        except Exception as exc:
            logger.warning("Không thể khởi động trước FastEmbed (%s): %s", self.model, exc)
            return False


def build_embedder(cfg) -> Optional[Embedder]:
    """Dựng embedder theo cấu hình; không dựng được thì None (degrade)."""
    backend = str(getattr(cfg, "embedder_backend", "off") or "off").lower()
    if backend in ("off", "none", ""):
        return None
    if backend == "stub":
        return HashStubEmbedder(dim=int(getattr(cfg, "embedder_stub_dim", 128)))
    if backend == "fastembed":
        try:
            import fastembed  # noqa: F401 - chỉ kiểm tra sự có mặt
        except Exception as exc:
            logger.warning(
                "fastembed chưa cài (%s) — recall chạy BM25-only", exc
            )
            return None
        return FastEmbedEmbedder(model=str(cfg.embedder_model))
    logger.warning("EMBEDDER_BACKEND lạ: %r — tắt vector", backend)
    return None
