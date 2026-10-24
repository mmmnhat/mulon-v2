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
from .gateway import GatewayError, estimate_tokens
from .learning import detect_and_record
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
    def __init__(self, cfg, gateway, memory, context_engine, registry,
                 policy, broker=None):
        self.cfg = cfg
        self.gateway = gateway
        self.memory = memory
        self.ctx = context_engine
        self.registry = registry
        self.policy = policy
        # ApprovalBroker (1.2.0): chỉ agent chính được nối; thiếu
        # broker thì nấc "ask" của policy degrade thành chặn an
        # toàn thay vì treo chờ một thẻ duyệt không ai thấy.
        self.broker = broker
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
        # Học từ sửa sai (mục 4.4 tầng 2): nếu tin này là user đang sửa
        # câu trả lời trước, ghi sự kiện correction NGAY trong lượt.
        # Lỗi ở bước này không bao giờ được làm hỏng lượt chính.
        correction_id: Optional[int] = None
        try:
            correction_id = await detect_and_record(
                self.memory, self.gateway, self.cfg, session_key,
                user_msg_id, user_text,
            )
        except Exception as exc:
            logger.warning("phát hiện correction lỗi (bỏ qua): %s", exc)
        built = await self.ctx.build(session_key, user_text)
        intent = classify_intent(user_text)

        if intent is Intent.CHAT:
            result = await self._fast_path(session_key, built.messages, on_delta)
        else:
            result = await self._task_path(
                session_key, user_text, built.messages, intent, on_event
            )

        # History chỉ lưu câu trả lời SẠCH cho user (mục 3.2).
        assistant_msg_id = await self.memory.append_message(
            session_key, "assistant", result.text, meta={"intent": intent.value}
        )
        await self.memory.log_trajectory(
            session_key, "turn_done",
            {"intent": intent.value, "verified": result.verified,
             "llm_calls": self._llm_calls, "user_msg_id": user_msg_id},
        )
        # Gom nén nền nếu history đã dài — không chặn lượt trả lời.
        asyncio.create_task(self._maybe_compact(session_key))
        # Review fork nền (mục 4.3, pattern Hermes): rà soát lượt vừa
        # rồi, ghi digest + fact. Chạy sau khi đã trả lời, lỗi của fork
        # không ảnh hưởng lượt chính.
        if getattr(self.cfg, "review_fork_enabled", True):
            asyncio.create_task(
                self._review_fork(
                    session_key, user_msg_id, assistant_msg_id,
                    user_text, result.text, correction_id,
                )
            )
        return result

    async def _review_fork(self, session_key: str, user_msg_id: int,
                           assistant_msg_id: int, user_text: str,
                           assistant_text: str,
                           correction_id: Optional[int]) -> None:
        """Fork nhẹ sau lượt: trích digest + fact bằng model rẻ.

        Ngữ cảnh rút gọn (chỉ cặp tin vừa rồi), trần token đầu vào cấu
        hình được (review_fork_token_budget). Mọi lỗi đều bị nuốt —
        fork hỏng thì lượt chính vẫn nguyên vẹn, digest vẫn được ghi
        (rỗng) để truy vết là fork đã chạy.
        """
        digest_text = ""
        facts_saved = 0
        try:
            budget_chars = max(
                500, int(self.cfg.review_fork_token_budget) * 3
            )
            u = user_text[: budget_chars // 2]
            a = assistant_text[: budget_chars // 2]
            prompt = [
                {
                    "role": "system",
                    "content": (
                        "Tóm tắt lượt hội thoại vừa diễn ra thành digest "
                        "1-2 câu và trích các sự kiện bền đáng nhớ lâu "
                        "dài (nếu có). Chỉ trả JSON: {\"digest\": \"...\", "
                        "\"facts\": [\"...\", ...]}. Không có fact thì "
                        "\"facts\": []."
                    ),
                },
                {
                    "role": "user",
                    "content": f"USER:\n{u}\n\nASSISTANT:\n{a}",
                },
            ]
            if estimate_tokens(u) + estimate_tokens(a) > \
                    int(self.cfg.review_fork_token_budget):
                prompt[1]["content"] = prompt[1]["content"][:budget_chars]
            comp = await self.gateway.complete(
                prompt, model=self.cfg.model_cheap, purpose="review_fork",
                temperature=0.2,
            )
            match = re.search(r"\{.*\}", comp.text or "", flags=re.DOTALL)
            data = json.loads(match.group(0)) if match else {}
            digest_text = str(data.get("digest") or "")[:1000]
            for fact in data.get("facts") or []:
                if isinstance(fact, str) and fact.strip():
                    await self.memory.add_fact(
                        fact.strip(), source="review_fork",
                        source_msg_id=assistant_msg_id,
                    )
                    facts_saved += 1
        except Exception as exc:
            logger.warning("review fork lỗi (nuốt, lượt chính an toàn): %s",
                           exc)
        try:
            await self.memory.add_digest(
                session_key, user_msg_id, assistant_msg_id, digest_text,
                facts_saved=facts_saved, correction_id=correction_id,
            )
        except Exception:
            pass  # DB đóng (test/shutdown) — fork không được làm ồn

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
            # LOI-1: mặt user chỉ thấy lời thường; chi tiết kỹ
            # thuật (URL proxy, JSON lỗi nhà cung cấp) đi vào
            # log + trajectory, KHÔNG lộ ra chat.
            logger.warning("fast path lỗi gateway: %s", exc)
            try:
                await self.memory.log_trajectory(
                    session_key, "turn_error",
                    {"where": "fast_path", "error": str(exc)[:500]})
            except Exception:
                pass
            text = ("Mô hình đang không trả lời được — anh thử "
                    "lại sau ít phút.")
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
                if decision.needs_ask:
                    # Lý do trên thẻ = lời dẫn của chính model ở
                    # lượt gọi tool này (comp.text) — có thì trình,
                    # không có thì thẻ không hiện dòng lý do.
                    ok_run, err = await self._ask_approval(
                        session_key, task_id, tc.name, group, args,
                        on_event, reason=comp.text or "")
                    if not ok_run:
                        return tc, {"ok": False, "error": err}
                elif not decision.allowed:
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

    async def _ask_approval(
        self, session_key: str, task_id: str, tool_name: str,
        group: str, args: dict, on_event: Optional[EventFn],
        reason: str = "",
    ) -> tuple[bool, str]:
        """Nấc "ask" của policy: mở thẻ duyệt qua broker và chờ.

        Trả (được chạy?, lỗi cho model nếu không). Payload duyệt
        chỉ chứa tóm tắt args an toàn — không secret. Cả hai nhánh
        kết quả đều ghi trajectory (mục 16.8: lịch sử duyệt).
        ``reason``: lời agent tự giải thích vì sao cần việc này
        (lời dẫn của model ở lượt gọi tool) — tùy chọn, rỗng thì
        thẻ không có dòng lý do; KHÔNG bịa lý do mẫu.
        """
        if self.broker is None:
            await self.memory.log_trajectory(
                session_key, "approval_decision",
                {"task_id": task_id, "tool": tool_name, "group": group,
                 "outcome": "no_broker",
                 "approved": False})
            return False, (
                f"policy yêu cầu duyệt trước tool {tool_name} nhưng "
                "kênh duyệt chưa được nối ở bản chạy này — việc bị "
                "chặn an toàn.")
        from .approvals import normalize_reason, summarize_args, \
            summarize_target

        approval_id = uuid.uuid4().hex[:12]
        payload = {
            "approval_id": approval_id,
            "tool": tool_name,
            "group": group,
            "summary": summarize_args(args),
            "target": summarize_target(args),
            "reason": normalize_reason(reason),
            "session_key": session_key,
            "task_id": task_id,
        }
        self.broker.open(approval_id, payload)
        await self.memory.log_trajectory(
            session_key, "approval_requested",
            {"task_id": task_id, "tool": tool_name, "group": group,
             "approval_id": approval_id})
        await self._emit(on_event, "approval_requested", **payload)
        record = await self.broker.wait(approval_id)
        outcome = record.get("outcome", "denied")
        await self.memory.log_trajectory(
            session_key, "approval_decision",
            {"task_id": task_id, "tool": tool_name, "group": group,
             "approval_id": approval_id, "outcome": outcome,
             "approved": bool(record.get("approved")),
             "remember": bool(record.get("remember"))})
        if record.get("approved"):
            return True, ""
        if outcome == "expired":
            return False, (
                f"thẻ duyệt cho tool {tool_name} đã hết hạn "
                f"({int(self.broker.timeout_s)}s) mà chưa được duyệt "
                "— việc bị hủy, KHÔNG tự chạy.")
        return False, (
            f"người dùng TỪ CHỐI duyệt tool {tool_name} — không "
            "được chạy việc này, hãy báo lại và hỏi hướng khác.")

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
