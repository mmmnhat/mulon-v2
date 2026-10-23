"""Agent core: vòng lặp plan-act-verify (thiết kế mục 3.1).

Khác Mulon cũ ở những điểm cốt tử:
- Có kế hoạch thật lưu DB (task + task_steps), không phải chữ hiển thị.
- Tool độc lập trong cùng một lượt model chạy song song (asyncio.gather).
- Có verify độc lập bằng prompt vai "người kiểm tra"; fail thì quay lại
  act kèm chẩn đoán, tối đa số vòng cấu hình được. Hết vòng mà verify
  chưa qua thì báo cáo NÓI THẬT là chưa kiểm chứng được — cấm câu mẫu
  "đã hoàn thành".
- Trace chỉ vào trajectory; history chỉ lưu câu trả lời sạch.
- Ngân sách tác vụ (số lời gọi LLM) chạm trần thì dừng ở trạng thái
  đã lưu + báo cáo, không loop vô hạn.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from .context import frame_external, trim_tool_result
from .gateway import GatewayError
from .tools import result_to_text

logger = logging.getLogger("mulon.agent")

EventFn = Callable[[str, dict], Awaitable[None] | None]
DeltaFn = Callable[[str], Awaitable[None] | None]


class Intent(str, Enum):
    CHAT = "chat"
    TOOL = "tool"
    LONG = "long"


_TOOL_HINTS = (
    "đọc file", "ghi file", "sửa file", "tạo file", "chạy lệnh", "chạy thử",
    "tìm trên web", "tra cứu", "mở link", "xem link", "kiểm tra trong",
    "liệt kê", "list file", "read file", "run ", "search ", "fetch ",
    "nhớ giúp", "lưu lại là", "ghi nhớ",
)
_LONG_HINTS = (
    "báo cáo", "tổng hợp", "phân tích", "nghiên cứu", "so sánh", "lập kế hoạch",
    "từng bước", "toàn bộ", "tất cả các",
)


def classify_intent(text: str) -> Intent:
    """Phân loại ý định Phase 1: heuristic minh bạch.

    Sau này thay bằng semantic-router / model rẻ (Phụ lục 15.3) sau
    cùng interface này. Nguyên tắc fail upward: mơ hồ + dài -> LONG.
    """
    lowered = text.lower()
    if any(h in lowered for h in _LONG_HINTS) and len(text) > 60:
        return Intent.LONG
    if any(h in lowered for h in _TOOL_HINTS):
        return Intent.TOOL
    if len(text) > 400:
        return Intent.LONG
    return Intent.CHAT


@dataclass
class TurnResult:
    text: str
    intent: Intent
    task_id: Optional[str] = None
    verified: Optional[bool] = None


VERIFY_SYSTEM = (
    "Bạn là NGƯỜI KIỂM CHỨNG độc lập. Đối chiếu KẾT QUẢ với YÊU CẦU GỐC "
    "dựa trên BẰNG CHỨNG (output tool, nội dung cuối). Chỉ trả JSON: "
    "{\"ok\": true|false, \"diagnosis\": \"...\"}. ok=true chỉ khi yêu cầu "
    "đã được đáp ứng thật bằng bằng chứng; thiếu bằng chứng thì ok=false."
)


class Agent:
    def __init__(self, cfg, gateway, memory, context_engine, registry, policy):
        self.cfg = cfg
        self.gateway = gateway
        self.memory = memory
        self.ctx = context_engine
        self.registry = registry
        self.policy = policy
        self._llm_calls = 0

    # ---------- tiện ích ----------
    async def _emit(self, on_event: Optional[EventFn], kind: str, **payload):
        if on_event is None:
            return
        try:
            maybe = on_event(kind, payload)
            if asyncio.iscoroutine(maybe):
                await maybe
        except Exception:
            pass

    async def _call(self, *args, **kwargs):
        self._llm_calls += 1
        return await self.gateway.complete(*args, **kwargs)

    # ---------- điểm vào ----------
    async def handle(
        self,
        session_key: str,
        user_text: str,
        on_delta: Optional[DeltaFn] = None,
        on_event: Optional[EventFn] = None,
    ) -> TurnResult:
        self._llm_calls = 0
        await self.memory.get_or_create_session(session_key)
        user_msg_id = await self.memory.append_message(
            session_key, "user", user_text
        )
        built = await self.ctx.build(session_key, user_text)
        intent = classify_intent(user_text)

        if intent is Intent.CHAT:
            result = await self._fast_path(session_key, built.messages, on_delta)
        else:
            result = await self._task_path(
                session_key, user_text, built.messages, intent, on_event
            )

        # History chỉ lưu câu trả lời SẠCH cho user (mục 3.2).
        await self.memory.append_message(
            session_key, "assistant", result.text, meta={"intent": intent.value}
        )
        await self.memory.log_trajectory(
            session_key, "turn_done",
            {"intent": intent.value, "verified": result.verified,
             "llm_calls": self._llm_calls, "user_msg_id": user_msg_id},
        )
        # Gom nén nền nếu history đã dài — không chặn lượt trả lời.
        asyncio.create_task(self._maybe_compact(session_key))
        return result

    async def _maybe_compact(self, session_key: str) -> None:
        try:
            session = await self.memory.get_or_create_session(session_key)
            upto = int(session.get("summary_upto_id") or 0)
            recent = await self.memory.recent_messages(
                session_key, limit=self.cfg.history_max_messages + 1,
                after_id=upto,
            )
            if len(recent) > self.cfg.history_max_messages:
                await self.ctx.compact(session_key)
        except Exception as exc:
            logger.warning("compact nền lỗi: %s", exc)

    # ---------- fast path: chat thường ----------
    async def _fast_path(self, session_key: str, messages: list[dict],
                         on_delta: Optional[DeltaFn]) -> TurnResult:
        try:
            comp = await self.gateway.stream(
                messages, model=self.cfg.model_brain, purpose="chat",
                on_delta=on_delta,
            )
            text = comp.text.strip()
        except GatewayError as exc:
            text = f"(Đang lỗi đường gọi model: {exc})"
        if not text:
            text = "(Model không trả nội dung — thử lại giúp mình.)"
        return TurnResult(text=text, intent=Intent.CHAT, verified=None)

    # ---------- task path: plan-act-verify ----------
    async def _plan(self, user_text: str, intent: Intent) -> list[str]:
        if intent is not Intent.LONG:
            return ["Hoàn thành yêu cầu của user"]
        prompt = [
            {
                "role": "system",
                "content": (
                    "Bẻ yêu cầu thành 3-6 bước ngắn, mỗi bước một mục tiêu "
                    "kiểm chứng được. Chỉ trả JSON {\"steps\": [\"...\", ...]}."
                ),
            },
            {"role": "user", "content": user_text},
        ]
        try:
            comp = await self._call(prompt, model=self.cfg.model_brain,
                                    purpose="plan", temperature=0.3)
            match = re.search(r"\{.*\}", comp.text or "", flags=re.DOTALL)
            if match:
                steps = json.loads(match.group(0)).get("steps") or []
                steps = [str(s).strip() for s in steps if str(s).strip()]
                if steps:
                    return steps[:6]
        except Exception as exc:
            logger.warning("plan lỗi, dùng kế hoạch 1 bước: %s", exc)
        return ["Hoàn thành yêu cầu của user"]

    async def _task_path(
        self, session_key: str, user_text: str, messages: list[dict],
        intent: Intent, on_event: Optional[EventFn],
    ) -> TurnResult:
        task_id = uuid.uuid4().hex[:12]
        steps = await self._plan(user_text, intent)
        await self.memory.create_task(task_id, session_key, user_text[:120], steps)
        await self._emit(on_event, "task_start",
                         task_id=task_id, steps=steps)

        schemas = self.registry.schemas()
        convo: list[dict] = list(messages)
        evidence: list[str] = []
        final_text = ""
        verified: Optional[bool] = None
        diagnosis = ""
        started = time.monotonic()
        attempt = 0

        while attempt <= self.cfg.verify_max_retries:
            # ----- ACT -----
            for step_idx in range(len(steps)):
                await self.memory.update_step(task_id, step_idx, "doing")
            final_text = await self._act_loop(
                session_key, task_id, convo, schemas, evidence, on_event
            )
            for step_idx in range(len(steps)):
                await self.memory.update_step(task_id, step_idx, "done")

            if self._llm_calls >= self.cfg.max_llm_calls_per_task:
                diagnosis = "chạm trần ngân sách lời gọi model của tác vụ"
                verified = False
                break

            # ----- VERIFY -----
            await self._emit(on_event, "verify", task_id=task_id)
            verdict = await self._verify(user_text, final_text, evidence)
            if verdict is None:
                # Không gọi được verifier: không khẳng định đã kiểm chứng.
                verified = None
                break
            verified, diagnosis = verdict
            if verified:
                break
            attempt += 1
            if attempt > self.cfg.verify_max_retries:
                break
            if time.monotonic() - started > self.cfg.max_task_seconds:
                diagnosis += " (hết thời gian tác vụ)"
                break
            # Quay lại ACT kèm chẩn đoán cụ thể (Reflexion — Phụ lục 15.1).
            convo.append(
                {
                    "role": "user",
                    "content": (
                        "KIỂM CHỨNG CHƯA ĐẠT. Chẩn đoán của người kiểm chứng: "
                        f"{diagnosis}\nHãy sửa đúng chỗ đó rồi trình lại kết quả."
                    ),
                }
            )
            await self._emit(on_event, "retry", task_id=task_id,
                             diagnosis=diagnosis)

        status = "done" if verified else ("unverified" if verified is None else "failed")
        await self.memory.finish_task(task_id, status, result=final_text,
                                      error=diagnosis if verified is False else "")
        await self._emit(on_event, "task_done", task_id=task_id, status=status)
        if verified is False:
            text = (
                "⚠️ Chưa kiểm chứng được là đã xong đúng yêu cầu. "
                f"Chẩn đoán: {diagnosis or 'không rõ'}.\n\n"
                f"Phần làm được tới giờ:\n{final_text}"
            )
        else:
            text = final_text
        return TurnResult(text=text, intent=intent, task_id=task_id,
                          verified=verified)

    async def _act_loop(
        self, session_key: str, task_id: str, convo: list[dict],
        schemas: list[dict], evidence: list[str],
        on_event: Optional[EventFn],
    ) -> str:
        """Chạy tool cho tới khi model dừng gọi tool hoặc chạm trần."""
        final_text = ""
        while self._llm_calls < self.cfg.max_llm_calls_per_task:
            comp = await self._call(
                convo, model=self.cfg.model_brain, tools=schemas,
                purpose="act",
            )
            if comp.text:
                final_text = comp.text
            if not comp.tool_calls:
                break
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": comp.text or None,
                "tool_calls": [
                    {
                        "id": tc.id or f"call_{i}",
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for i, tc in enumerate(comp.tool_calls)
                ],
            }
            convo.append(assistant_msg)

            async def run_one(tc) -> tuple[Any, dict]:
                try:
                    args = json.loads(tc.arguments or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except json.JSONDecodeError:
                    args = {}
                spec = self.registry.get(tc.name)
                group = spec.group if spec else ""
                decision = await self.policy.check(tc.name, group,
                                                   session_key=session_key)
                if not decision.allowed:
                    return tc, {"ok": False,
                                "error": f"policy chặn ở lớp {decision.layer}"}
                await self._emit(on_event, "tool_start", task_id=task_id,
                                 tool=tc.name)
                result = await self.registry.execute(tc.name, args)
                await self.memory.log_trajectory(
                    session_key, "tool_call",
                    {"task_id": task_id, "tool": tc.name, "args": args,
                     "ok": result.get("ok")},
                )
                return tc, result

            # Các tool call trong cùng một lượt model là độc lập theo
            # cấu trúc -> chạy song song (nghiệm thu Phase 1, mục 13).
            pairs = await asyncio.gather(
                *[run_one(tc) for tc in comp.tool_calls]
            )
            for tc, result in pairs:
                raw = result_to_text(result)
                if tc.name in {"web_fetch", "read_file"}:
                    raw = frame_external(raw)
                trimmed = trim_tool_result(
                    raw, self.cfg.tool_result_max_chars,
                    self.cfg.artifact_dir, tool_name=tc.name,
                )
                evidence.append(f"{tc.name}: {trimmed.text[:1500]}")
                convo.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id or "",
                        "content": trimmed.text,
                    }
                )
        return final_text

    async def _verify(self, user_text: str, final_text: str,
                      evidence: list[str]) -> Optional[tuple[bool, str]]:
        """Một lượt kiểm chứng độc lập. None = không gọi được verifier."""
        prompt = [
            {"role": "system", "content": VERIFY_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"YÊU CẦU GỐC:\n{user_text}\n\nKẾT QUẢ CUỐI:\n{final_text}\n\n"
                    "BẰNG CHỨNG (output tool đã cắt gọn):\n"
                    + "\n".join(evidence[-8:])[:8000]
                ),
            },
        ]
        try:
            comp = await self._call(prompt, model=self.cfg.model_brain,
                                    purpose="verify", temperature=0.2)
        except GatewayError:
            return None
        match = re.search(r"\{.*\}", comp.text or "", flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return bool(data.get("ok")), str(data.get("diagnosis") or "")
