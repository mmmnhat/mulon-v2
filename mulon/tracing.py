"""Langfuse tracing TUỲ CHỌN (thiết kế mục 10) — Phase 5.

Bọc quanh ModelGateway: mỗi lời gọi model sinh 1 trace chứa DUY NHẤT
metadata đo lường (model, token, latency, độ dài ký tự vào/ra, trạng
thái ok). TUYỆT ĐỐI không ghi nội dung tin nhắn, không ghi prompt,
không ghi secret — dữ kiện nhạy cảm không rời máy qua kênh này.

Bất hoạt hoàn toàn (no-op) khi:
- thiếu một trong ba env LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY /
  LANGFUSE_HOST, hoặc
- gói `langfuse` chưa được cài (gói tuỳ chọn trong requirements), hoặc
- client khởi tạo lỗi.

Mọi lỗi của chính tracing đều bị nuốt: tracing hỏng thì bot vẫn chạy
y như không có nó.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger("mulon.tracing")


def _input_chars(messages: Any) -> int:
    """Tổng số ký tự nội dung trong messages — CHỈ đếm, không giữ lại."""
    total = 0
    if not isinstance(messages, (list, tuple)):
        return 0
    for m in messages:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += len(str(part.get("text", "")))
    return total


class Tracer:
    """Điểm phát trace. client=None nghĩa là tracing đang tắt."""

    def __init__(self, client: Any = None):
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def emit(
        self,
        *,
        name: str,
        model: str,
        latency_s: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        input_chars: int = 0,
        output_chars: int = 0,
        ok: bool = True,
    ) -> None:
        if self._client is None:
            return
        metadata = {
            "model": model,
            "latency_s": round(float(latency_s), 3),
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "input_chars": int(input_chars),
            "output_chars": int(output_chars),
            "ok": bool(ok),
        }
        try:
            self._send(name or "llm_call", metadata)
        except Exception as exc:  # tracing không bao giờ làm hỏng bot
            logger.debug("langfuse emit lỗi (nuốt): %s", exc)

    def _send(self, name: str, metadata: dict) -> None:
        client = self._client
        trace_fn = getattr(client, "trace", None)
        if callable(trace_fn):  # Langfuse SDK v2
            trace_fn(name=name, metadata=metadata)
            return
        span_fn = getattr(client, "start_span", None)
        if callable(span_fn):  # Langfuse SDK v3
            span = span_fn(name=name, metadata=metadata)
            end = getattr(span, "end", None)
            if callable(end):
                end()
            return
        logger.debug("langfuse client không có trace/start_span — bỏ qua")

    def flush(self) -> None:
        if self._client is None:
            return
        try:
            flush = getattr(self._client, "flush", None)
            if callable(flush):
                flush()
        except Exception:
            pass


def build_tracer(cfg, client: Any = None) -> Tracer:
    """Dựng Tracer từ config. ``client`` cho phép test tiêm client giả.

    Thiếu env hoặc thiếu gói -> Tracer tắt (client None).
    """
    if client is not None:
        return Tracer(client)
    if not (
        getattr(cfg, "langfuse_public_key", "")
        and getattr(cfg, "langfuse_secret_key", "")
        and getattr(cfg, "langfuse_host", "")
    ):
        return Tracer(None)
    try:
        from langfuse import Langfuse
    except Exception as exc:
        logger.info("langfuse chưa cài — tracing TẮT (%s)", exc)
        return Tracer(None)
    try:
        real = Langfuse(
            public_key=cfg.langfuse_public_key,
            secret_key=cfg.langfuse_secret_key,
            host=cfg.langfuse_host,
        )
    except Exception as exc:
        logger.warning("khởi tạo langfuse lỗi — tracing TẮT: %s", exc)
        return Tracer(None)
    logger.info("langfuse tracing BẬT (host %s)", cfg.langfuse_host)
    return Tracer(real)


class TracedGateway:
    """Bọc gateway: đo + phát trace cho complete/stream, uỷ quyền còn lại."""

    def __init__(self, inner: Any, tracer: Tracer):
        self._inner = inner
        self._tracer = tracer

    def __getattr__(self, name: str):  # chỉ chạy khi attr không có sẵn
        return getattr(self.__dict__["_inner"], name)

    async def complete(self, messages, *args, **kwargs):
        started = time.monotonic()
        try:
            comp = await self._inner.complete(messages, *args, **kwargs)
        except Exception:
            self._tracer.emit(
                name=str(kwargs.get("purpose") or "llm_call"),
                model=str(kwargs.get("model") or ""),
                latency_s=time.monotonic() - started,
                input_chars=_input_chars(messages),
                ok=False,
            )
            raise
        self._tracer.emit(
            name=str(kwargs.get("purpose") or "llm_call"),
            model=getattr(comp, "model", "") or str(kwargs.get("model") or ""),
            latency_s=getattr(comp, "latency_s", 0.0)
            or (time.monotonic() - started),
            prompt_tokens=getattr(comp, "prompt_tokens", 0),
            completion_tokens=getattr(comp, "completion_tokens", 0),
            input_chars=_input_chars(messages),
            output_chars=len(getattr(comp, "text", "") or ""),
            ok=True,
        )
        return comp

    async def stream(self, messages, *args, **kwargs):
        started = time.monotonic()
        try:
            comp = await self._inner.stream(messages, *args, **kwargs)
        except Exception:
            self._tracer.emit(
                name=str(kwargs.get("purpose") or "llm_call"),
                model=str(kwargs.get("model") or ""),
                latency_s=time.monotonic() - started,
                input_chars=_input_chars(messages),
                ok=False,
            )
            raise
        self._tracer.emit(
            name=str(kwargs.get("purpose") or "llm_call"),
            model=getattr(comp, "model", "") or str(kwargs.get("model") or ""),
            latency_s=getattr(comp, "latency_s", 0.0)
            or (time.monotonic() - started),
            prompt_tokens=getattr(comp, "prompt_tokens", 0),
            completion_tokens=getattr(comp, "completion_tokens", 0),
            input_chars=_input_chars(messages),
            output_chars=len(getattr(comp, "text", "") or ""),
            ok=True,
        )
        return comp


def traced_gateway(gateway: Any, cfg, tracer: Optional[Tracer] = None):
    """Trả gateway đã bọc nếu tracing bật; ngược lại trả nguyên bản."""
    tracer = tracer if tracer is not None else build_tracer(cfg)
    if not tracer.enabled:
        return gateway
    return TracedGateway(gateway, tracer)
