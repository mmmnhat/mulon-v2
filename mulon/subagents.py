"""Subagents thật (thiết kế mục 3.4) — Phase 3.

Subagent KHÔNG phải 1 lời gọi LLM trần như Mulon cũ: nó là agent
loop đầy đủ (cùng Agent core: plan-act-verify, policy, trajectory)
nhưng với:
- toolset THU HẸP theo hồ sơ (profile) — và không bao giờ chứa
  spawn_subagent (chống đệ quy);
- trần vòng lặp + trần token RIÊNG, chạm trần thì dừng an toàn;
- session riêng, tối đa N chạy đồng thời (semaphore);
- kết quả trả về là DIGEST nén (tóm tắt + trạng thái + số liệu),
  không trả nguyên transcript cho agent chính.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import replace
from typing import Callable

from .agent import Agent, clean_task_title
from .gateway import Completion
from .tools import ToolRegistry, ToolSpec

logger = logging.getLogger("mulon.subagents")

# Hồ sơ toolset. Nguyên tắc: mặc định KHÔNG có tool ghi ra ngoài.
PROFILES: dict[str, dict] = {
    "researcher": {
        "description": "Chỉ đọc + web + ký ức: tra cứu, tổng hợp.",
        "tools": {
            "web_fetch", "web_read", "memory_search", "session_search",
            "memory_get", "now",
        },
    },
    "coder": {
        "description": "File + lệnh trong workspace (jail giữ nguyên).",
        "tools": {
            "read_file", "write_file", "edit_file", "list_dir",
            "run_command", "web_fetch", "now",
        },
    },
    "default": {
        "description": "Tối thiểu, chỉ đọc: web + ký ức.",
        "tools": {"web_fetch", "memory_search", "memory_get", "now"},
    },
}

NEVER_TOOLS = {"spawn_subagent", "spawn_subagents_parallel"}


class _CountingGateway:
    """Bọc gateway để đếm token của riêng subagent.

    Chạm trần token: các lời gọi sau trả Completion rỗng (không tool
    call) để vòng act tự kết thúc an toàn thay vì văng lỗi.
    """

    def __init__(self, inner, token_budget: int):
        self._inner = inner
        self.token_budget = token_budget
        self.prompt_tokens = 0
        self.completion_tokens = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def exhausted(self) -> bool:
        return self.total_tokens >= self.token_budget

    def _account(self, comp: Completion) -> Completion:
        self.prompt_tokens += comp.prompt_tokens or 0
        self.completion_tokens += comp.completion_tokens or 0
        return comp

    async def complete(self, messages, **kwargs):
        if self.exhausted:
            return Completion(text="")
        return self._account(await self._inner.complete(messages, **kwargs))

    async def stream(self, messages, **kwargs):
        if self.exhausted:
            return Completion(text="")
        return self._account(await self._inner.stream(messages, **kwargs))


class SubagentRunner:
    def __init__(self, cfg, gateway, memory, ctx, policy,
                 registry_factory: Callable[[], ToolRegistry]):
        self.cfg = cfg
        self.gateway = gateway
        self.memory = memory
        self.ctx = ctx
        self.policy = policy
        self._registry_factory = registry_factory
        self._semaphore = asyncio.Semaphore(cfg.subagent_max_concurrent)

    def _filtered_registry(self, profile: str) -> ToolRegistry:
        allowed = PROFILES[profile]["tools"] - NEVER_TOOLS
        full = self._registry_factory()
        sub = ToolRegistry()
        for spec in full.specs():
            if spec.name in allowed:
                sub.register(spec)
        return sub

    async def run(self, task: str, profile: str = "default",
                  parent_session: str = "") -> dict:
        if profile not in PROFILES:
            return {"ok": False,
                    "error": f"profile không tồn tại: {profile} "
                             f"(có: {', '.join(sorted(PROFILES))})"}
        async with self._semaphore:
            return await self._run_inner(task, profile, parent_session)

    async def _run_inner(self, task: str, profile: str,
                         parent_session: str) -> dict:
        sub_id = uuid.uuid4().hex[:8]
        session_key = f"subagent:{profile}:{sub_id}"
        sub_task_id = f"sub_{sub_id}"
        sub_task_title = f"Sub-agent [{profile}]: {clean_task_title(task)}"
        sub_steps = [f"Khởi động ({profile})", "Thực thi tác vụ con", "Tổng hợp digest"]
        try:
            await self.memory.create_task(sub_task_id, session_key, sub_task_title, sub_steps)
            await self.memory.update_step(sub_task_id, 0, "done")
            await self.memory.update_step(sub_task_id, 1, "doing")
        except Exception as exc:
            logger.warning("tạo task cho subagent trong memory lỗi: %s", exc)

        counting = _CountingGateway(self.gateway,
                                    self.cfg.subagent_token_budget)
        child_cfg = replace(
            self.cfg,
            max_llm_calls_per_task=(
                self.cfg.subagent_max_llm_calls
                if self.cfg.max_llm_calls_per_task <= 0
                else min(
                    self.cfg.max_llm_calls_per_task,
                    self.cfg.subagent_max_llm_calls,
                )
            ),
            max_task_seconds=self.cfg.subagent_max_seconds,
            review_fork_enabled=False,  # subagent không sinh fork cháu
        )
        child = Agent(child_cfg, counting, self.memory, self.ctx,
                      self._filtered_registry(profile), self.policy)
        status = "failed"
        summary = ""
        verified = None
        try:
            result = await asyncio.wait_for(
                child.handle(session_key, task),
                timeout=self.cfg.subagent_max_seconds + 30,
            )
            summary = (result.text or "")[: self.cfg.subagent_digest_max_chars]
            verified = result.verified
            if result.task_id:
                task_row = await self.memory.get_task(result.task_id)
                status = task_row["status"] if task_row else "done"
            else:
                status = "done"
        except asyncio.TimeoutError:
            summary = "subagent chạm trần thời gian, đã dừng an toàn"
        except Exception as exc:
            summary = f"subagent lỗi: {type(exc).__name__}: {exc}"
        finally:
            try:
                final_step_status = "done" if status == "done" else "failed"
                await self.memory.update_step(sub_task_id, 1, final_step_status)
                await self.memory.update_step(sub_task_id, 2, final_step_status)
                await self.memory.finish_task(sub_task_id, status, result=summary)
            except Exception:
                pass

        digest = {
            "ok": status == "done",
            "subagent_id": sub_id,
            "profile": profile,
            "status": status,
            "verified": verified,
            "llm_calls": child._llm_calls,
            "tokens_used": counting.total_tokens,
            "summary": summary,
        }
        if parent_session:
            await self.memory.log_trajectory(
                parent_session, "subagent_done",
                {"subagent_id": sub_id, "profile": profile,
                 "status": status, "llm_calls": child._llm_calls},
            )
        return digest


def register_subagent_tool(registry, runner: SubagentRunner,
                           parent_session: str = "") -> None:
    async def spawn_subagent(task: str, profile: str = "default"):
        return await runner.run(task, profile=profile,
                                parent_session=parent_session)

    async def spawn_subagents_parallel(tasks: list[dict]):
        if not isinstance(tasks, list):
            return {"ok": False, "error": "tasks phải là danh sách [{'task': '...', 'profile': '...'}]"}

        async def _run_single(item: dict) -> dict:
            if not isinstance(item, dict):
                return {"ok": False, "error": "mỗi item phải là dict"}
            t_text = str(item.get("task") or "")
            t_prof = str(item.get("profile") or "default")
            return await runner.run(t_text, profile=t_prof, parent_session=parent_session)

        results = await asyncio.gather(*[_run_single(item) for item in tasks])
        all_ok = all(r.get("ok", False) for r in results)
        return {
            "ok": all_ok,
            "count": len(results),
            "results": list(results),
        }

    registry.register(ToolSpec(
        name="spawn_subagent",
        description=(
            "Giao 1 việc con cho subagent (agent đầy đủ với toolset thu "
            "hẹp theo profile) chạy độc lập. Trả về digest nén, không "
            "phải transcript. profile: researcher (chỉ đọc + web), "
            "coder (file + lệnh trong workspace), default (tối thiểu)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "profile": {
                    "type": "string",
                    "enum": sorted(PROFILES),
                    "default": "default",
                },
            },
            "required": ["task"],
        },
        group="agent",
        timeout_s=runner.cfg.subagent_max_seconds + 60,
        handler=spawn_subagent,
    ))

    registry.register(ToolSpec(
        name="spawn_subagents_parallel",
        description=(
            "Giao nhiều việc con độc lập cho các subagent chạy song song, "
            "tổng hợp danh sách digest nén trả về. Dùng khi cần tra cứu hoặc "
            "xử lý nhiều nguồn/nhiệm vụ độc lập cùng một lúc."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string"},
                            "profile": {
                                "type": "string",
                                "enum": sorted(PROFILES),
                                "default": "default",
                            },
                        },
                        "required": ["task"],
                    },
                },
            },
            "required": ["tasks"],
        },
        group="agent",
        timeout_s=runner.cfg.subagent_max_seconds + 60,
        handler=spawn_subagents_parallel,
    ))
