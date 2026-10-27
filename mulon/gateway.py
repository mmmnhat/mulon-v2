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
import base64
import logging
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

# Shim cho LiteLLM 1.106+ khi dùng với thư viện mcp:
# LiteLLM kiểm tra experimental proxy MCP và import CacheableResult từ mcp.types,
# nhưng mcp 1.30 không xuất class này gây APIConnectionError.
try:
    import mcp.types as _mcp_types

    if not hasattr(_mcp_types, "CacheableResult"):
        class _CacheableResult:
            pass

        _mcp_types.CacheableResult = _CacheableResult  # type: ignore[attr-defined]
except Exception:
    pass

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
        # Sửa 1.6.3: khóa proxy về localhost ngay khi dựng gateway
        # (fail-fast), kể cả khi Config được dựng thủ công không qua
        # Config.load(). Import lười để khỏi vòng import config <->
        # gateway. Env cho phép tường minh duy nhất:
        # MULON_ALLOW_REMOTE_PROXY=1 (xem config.validate_...).
        from .config import validate_proxy_base_url

        validate_proxy_base_url(getattr(cfg, "proxy_base_url", ""))
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
    _MODEL_ALIASES = {
        "gemini-3.8-flash": "gemini-3.8-flash-high",
        "gemini-3.8": "gemini-3.8-flash-high",
        "gemini-3.5-flash": "gemini-3.5-flash-lite",
        "gemini-3-flash": "gemini-3.1-flash-lite",
        "claude-3-7-sonnet": "claude-sonnet-4-6",
        "claude-sonnet": "claude-sonnet-4-6",
        "muse-wonder-1.0": "muse-wonder-full-1.0",
        "muse-wonder": "muse-wonder-full-1.0",
        # T-16 Đường A: model muse-spark của muse2api qua CLIProxyAPI.
        # MuLon gọi qua proxy 8317 với tên muse/muse-spark, không gọi
        # thẳng muse2api; alias này chỉ chuẩn hóa tên người dùng gõ.
        "muse-spark": "muse/muse-spark",
    }

    def _litellm_model(self, model: Optional[str]) -> str:
        name = model or self.cfg.model_brain
        name = self._MODEL_ALIASES.get(name, name)
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

    _IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}

    def _multimodal_path_allowed(self, p: Path) -> bool:
        """Chặn Local File Disclosure qua tag ảnh (vá audit 2026-10-26).

        Tag ``[Người dùng gửi kèm ảnh: ...]`` có thể bị tiêm từ nội
        dung ngoài (web/email/tài liệu tóm tắt) nên đường dẫn trong
        tag KHÔNG đáng tin: chỉ đóng gói file ẢNH thật (đuôi ảnh,
        không thuộc denylist nhạy cảm) nằm trong workspace, dossier
        hoặc thư mục tạm hệ thống (nơi test/upload tạm ghi vào).
        """
        import tempfile

        try:
            name = p.name.lower()
            if p.suffix.lower().lstrip(".") not in self._IMAGE_EXTS:
                return False
            if (".env" in name or "secret" in name
                    or name == "vault.json" or name.endswith((".pem", ".key", ".db"))):
                return False
            resolved = p.resolve()
            roots = []
            for attr in ("workspace_dir", "dossier_dir"):
                root = getattr(self.cfg, attr, None)
                if isinstance(root, (str, Path)) and str(root):
                    roots.append(Path(root).resolve())
            roots.append(Path(tempfile.gettempdir()).resolve())
            return any(resolved == r or r in resolved.parents for r in roots)
        except Exception:
            return False

    def _prepare_multimodal_messages(self, messages: list[dict]) -> list[dict]:
        """Tự động đóng gói tất cả hình ảnh đính kèm (hỗ trợ nhiều ảnh cùng lúc) thành định dạng Multimodal (OpenAI/LiteLLM vision)."""
        out: list[dict] = []
        for m in messages:
            content = m.get("content")
            if m.get("role") == "user" and isinstance(content, str):
                matches = re.findall(r"\[Người dùng gửi (?:kèm )?(?:ảnh|một tấm ảnh): ([^\]]+)\]", content)
                if matches:
                    parts: list[dict[str, Any]] = [{"type": "text", "text": content}]
                    for raw_path in matches:
                        p = Path(raw_path.strip())
                        if not self._multimodal_path_allowed(p):
                            logger.warning(
                                "chặn đóng gói multimodal: %s (ngoài vùng "
                                "cho phép / không phải ảnh / file nhạy cảm)", p)
                            continue
                        if p.is_file() and p.stat().st_size <= 15 * 1024 * 1024:
                            try:
                                ext = p.suffix.lower().lstrip(".") or "jpeg"
                                if ext == "jpg":
                                    ext = "jpeg"
                                data_b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
                                parts.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/{ext};base64,{data_b64}"
                                    },
                                })
                            except Exception as exc:
                                logger.warning("không thể đóng gói ảnh multimodal (%s): %s", p, exc)
                    if len(parts) > 1:
                        out.append({**m, "content": parts})
                        continue
            out.append(m)
        return out

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
        prepared_messages = self._prepare_multimodal_messages(messages)
        last_err: Optional[Exception] = None
        started = time.monotonic()
        for attempt in range(self._max_attempts):
            self._check_breaker()
            try:
                kwargs: dict[str, Any] = {
                    "model": model_name,
                    "messages": prepared_messages,
                    "api_base": self.cfg.proxy_base_url,
                    "api_key": self.cfg.proxy_api_key,
                    "temperature": temperature,
                    "timeout": timeout,
                    "_skip_mcp_handler": True,
                }
                if tools:
                    kwargs["tools"] = tools
                resp = await acompletion(**kwargs)
                choice = resp.choices[0]
                msg = choice.message
                usage = getattr(resp, "usage", None)
                comp = Completion(
                    text=(
                        getattr(msg, "content", None)
                        or getattr(msg, "reasoning_content", None)
                        or getattr(msg, "thought", None)
                        or ""
                    ),
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
        prepared_messages = self._prepare_multimodal_messages(messages)
        started = time.monotonic()
        self._check_breaker()
        try:
            resp = await acompletion(
                model=model_name,
                messages=prepared_messages,
                api_base=self.cfg.proxy_base_url,
                api_key=self.cfg.proxy_api_key,
                temperature=temperature,
                timeout=timeout,
                stream=True,
                _skip_mcp_handler=True,
            )
            text_parts: list[str] = []
            async for chunk in resp:  # type: AsyncIterator[Any]
                try:
                    delta = chunk.choices[0].delta
                    piece = (
                        getattr(delta, "content", None)
                        or getattr(delta, "text", None)
                        or getattr(delta, "reasoning_content", None)
                        or getattr(delta, "thought", None)
                        or ""
                    )
                except Exception:
                    piece = ""
                if piece:
                    text_parts.append(piece)
                    if on_delta is not None:
                        maybe = on_delta(piece)
                        if asyncio.iscoroutine(maybe):
                            await maybe
            final_text = "".join(text_parts)
            if not final_text.strip():
                logger.warning(
                    "stream() trả về rỗng cho purpose='%s' (model=%s), fallback gọi complete() non-streaming",
                    purpose, model_name,
                )
                try:
                    fb_comp = await self.complete(
                        messages=messages,
                        model=model,
                        temperature=temperature,
                        timeout=timeout,
                        purpose=f"{purpose}_stream_fallback" if purpose else "stream_fallback",
                    )
                    if (fb_comp.text or "").strip():
                        if on_delta is not None:
                            maybe = on_delta(fb_comp.text)
                            if asyncio.iscoroutine(maybe):
                                await maybe
                        return fb_comp
                except Exception as fb_exc:
                    logger.warning("fallback sang complete() sau stream rỗng thất bại: %s", fb_exc)

            comp = Completion(
                text=final_text,
                prompt_tokens=count_messages_tokens(messages),
                completion_tokens=estimate_tokens(final_text),
                latency_s=time.monotonic() - started,
                model=model_name,
            )
            self._record_success()
            await self._log_call(purpose, model_name, comp, ok=True)
            return comp
        except CircuitOpenError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("stream() gặp lỗi: %s, fallback sang complete()", exc)
            try:
                fb_comp = await self.complete(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    timeout=timeout,
                    purpose=f"{purpose}_stream_fallback" if purpose else "stream_fallback",
                )
                if (fb_comp.text or "").strip():
                    if on_delta is not None:
                        maybe = on_delta(fb_comp.text)
                        if asyncio.iscoroutine(maybe):
                            await maybe
                    return fb_comp
            except Exception:
                pass
            self._record_failure()
            comp = Completion(latency_s=time.monotonic() - started, model=model_name)
            await self._log_call(purpose, model_name, comp, ok=False, error=str(exc))
            raise GatewayError(f"stream model thất bại: {exc}") from exc
