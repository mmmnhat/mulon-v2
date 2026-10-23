"""Model gateway: mọi lời gọi model đi qua đây (thiết kế mục 2.3).

- Qua LiteLLM trỏ vào proxy OpenAI-compatible duy nhất của user.
- Streaming toàn tuyến, retry backoff + jitter, circuit breaker theo
  provider, timeout từng lời gọi.
- Đếm token bằng estimator của LiteLLM (tiktoken-compatible) với
  fallback ước lượng theo ký tự nếu estimator lỗi.
- Mọi lời gọi được đo (model, token, latency) và ghi trajectory —
  KHÔNG ghi cost tiền vì qua proxy không có giá chính thức; "tiết
  kiệm" ở hệ này là quota + độ trễ (thiết kế mục 2.2).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Optional

logger = logging.getLogger("mulon.gateway")


class GatewayError(Exception):
    """Lỗi gọi model (sau khi đã retry hết lượt)."""


class CircuitOpenError(GatewayError):
    """Circuit breaker đang mở — provider bị coi là sập tạm thời."""


def estimate_tokens(text: str) -> int:
    """Ước lượng token: ưu tiên estimator của LiteLLM, fallback ký tự."""
    if not text:
        return 0
    try:
        from litellm import token_counter

        return int(token_counter(model="gpt-4", text=text))
    except Exception:
        # Heuristic dự phòng: ~3.5 ký tự/token cho text Anh/Việt trộn.
        return max(1, int(len(text) / 3.5))


def count_messages_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content) + 4  # overhead mỗi message
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens(str(part.get("text", ""))) + 4
        for tc in m.get("tool_calls") or []:
            fn = (tc or {}).get("function") or {}
            total += estimate_tokens(str(fn.get("arguments", ""))) + 8
    return total


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON string thô từ model


@dataclass
class Completion:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    model: str = ""


class ModelGateway:
    def __init__(self, cfg, memory=None):
        self.cfg = cfg
        self.memory = memory
        self._consec_failures = 0
        self._breaker_open_until = 0.0
        self._breaker_threshold = 5
        self._breaker_cooldown_s = 30.0
        self._max_attempts = 3

    # ---------- circuit breaker ----------
    def _check_breaker(self) -> None:
        if time.monotonic() < self._breaker_open_until:
            raise CircuitOpenError("circuit breaker đang mở (proxy bị coi là sập)")

    def _record_success(self) -> None:
        self._consec_failures = 0

    def _record_failure(self) -> None:
        self._consec_failures += 1
        if self._consec_failures >= self._breaker_threshold:
            self._breaker_open_until = time.monotonic() + self._breaker_cooldown_s
            self._consec_failures = 0
            logger.warning("circuit breaker mở %ss", self._breaker_cooldown_s)

    # ---------- chuẩn hoá ----------
    def _litellm_model(self, model: Optional[str]) -> str:
        name = model or self.cfg.model_brain
        return name if "/" in name else f"openai/{name}"

    @staticmethod
    def _normalize_tool_calls(raw) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for tc in raw or []:
            if isinstance(tc, dict):
                fn = tc.get("function") or {}
                calls.append(
                    ToolCall(
                        id=str(tc.get("id") or ""),
                        name=str(fn.get("name") or ""),
                        arguments=str(fn.get("arguments") or "{}"),
                    )
                )
            else:  # object kiểu pydantic của LiteLLM
                fn = getattr(tc, "function", None)
                calls.append(
                    ToolCall(
                        id=str(getattr(tc, "id", "") or ""),
                        name=str(getattr(fn, "name", "") or ""),
                        arguments=str(getattr(fn, "arguments", "") or "{}"),
                    )
                )
        return [c for c in calls if c.name]

    async def _log_call(self, purpose: str, model: str, comp: Completion, ok: bool,
                        error: str = "") -> None:
        if self.memory is not None:
            await self.memory.log_trajectory(
                "",
                "llm_call",
                {
                    "purpose": purpose,
                    "model": model,
                    "ok": ok,
                    "latency_s": round(comp.latency_s, 3),
                    "prompt_tokens": comp.prompt_tokens,
                    "completion_tokens": comp.completion_tokens,
                    "cost": None,  # qua proxy: không có giá chính thức
                    "error": error,
                },
            )

    # ---------- lời gọi chính ----------
    async def complete(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        timeout: Optional[int] = None,
        purpose: str = "",
    ) -> Completion:
        """Một lời gọi không-stream, có retry + breaker."""
        from litellm import acompletion

        model_name = self._litellm_model(model)
        timeout = timeout or self.cfg.llm_timeout_s
        last_err: Optional[Exception] = None
        started = time.monotonic()
        for attempt in range(self._max_attempts):
            self._check_breaker()
            try:
                kwargs: dict[str, Any] = {
                    "model": model_name,
                    "messages": messages,
                    "api_base": self.cfg.proxy_base_url,
                    "api_key": self.cfg.proxy_api_key,
                    "temperature": temperature,
                    "timeout": timeout,
                }
                if tools:
                    kwargs["tools"] = tools
                resp = await acompletion(**kwargs)
                choice = resp.choices[0]
                msg = choice.message
                usage = getattr(resp, "usage", None)
                comp = Completion(
                    text=getattr(msg, "content", None) or "",
                    tool_calls=self._normalize_tool_calls(
                        getattr(msg, "tool_calls", None)
                    ),
                    prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    completion_tokens=int(
                        getattr(usage, "completion_tokens", 0) or 0
                    ),
                    latency_s=time.monotonic() - started,
                    model=model_name,
                )
                self._record_success()
                await self._log_call(purpose, model_name, comp, ok=True)
                return comp
            except CircuitOpenError:
                raise
            except Exception as exc:  # noqa: BLE001 - retry mọi lỗi provider
                last_err = exc
                self._record_failure()
                if attempt < self._max_attempts - 1:
                    backoff = (2**attempt) + random.uniform(0, 0.5)
                    await asyncio.sleep(backoff)
        comp = Completion(latency_s=time.monotonic() - started, model=model_name)
        await self._log_call(purpose, model_name, comp, ok=False,
                             error=str(last_err))
        raise GatewayError(f"gọi model thất bại sau {self._max_attempts} lần: {last_err}")

    async def stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        timeout: Optional[int] = None,
        purpose: str = "",
        on_delta: Optional[Callable[[str], Any]] = None,
    ) -> Completion:
        """Lời gọi streaming cho đường chat thường (fast path).

        Tool calls không đi đường này — agent loop dùng complete().
        """
        from litellm import acompletion

        model_name = self._litellm_model(model)
        timeout = timeout or self.cfg.llm_timeout_s
        started = time.monotonic()
        self._check_breaker()
        try:
            resp = await acompletion(
                model=model_name,
                messages=messages,
                api_base=self.cfg.proxy_base_url,
                api_key=self.cfg.proxy_api_key,
                temperature=temperature,
                timeout=timeout,
                stream=True,
            )
            text_parts: list[str] = []
            async for chunk in resp:  # type: AsyncIterator[Any]
                try:
                    delta = chunk.choices[0].delta
                    piece = getattr(delta, "content", None) or ""
                except Exception:
                    piece = ""
                if piece:
                    text_parts.append(piece)
                    if on_delta is not None:
                        maybe = on_delta(piece)
                        if asyncio.iscoroutine(maybe):
                            await maybe
            comp = Completion(
                text="".join(text_parts),
                prompt_tokens=count_messages_tokens(messages),
                completion_tokens=estimate_tokens("".join(text_parts)),
                latency_s=time.monotonic() - started,
                model=model_name,
            )
            self._record_success()
            await self._log_call(purpose, model_name, comp, ok=True)
            return comp
        except CircuitOpenError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._record_failure()
            comp = Completion(latency_s=time.monotonic() - started, model=model_name)
            await self._log_call(purpose, model_name, comp, ok=False, error=str(exc))
            raise GatewayError(f"stream model thất bại: {exc}") from exc
