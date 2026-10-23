"""Phase 5 — Langfuse tracing: no-op khi thiếu env, ghi đúng
metadata đã che khi có client, lỗi client không làm hỏng gateway."""

import json

from mulon.gateway import Completion
from mulon.tracing import build_tracer, traced_gateway


class FakeGateway:
    def __init__(self):
        self.calls = 0

    async def complete(self, messages, model=None, tools=None,
                       temperature=0.7, timeout=None, purpose=""):
        self.calls += 1
        return Completion(
            text="câu trả lời", prompt_tokens=11, completion_tokens=7,
            latency_s=0.25, model="openai/model-x",
        )

    async def stream(self, messages, model=None, temperature=0.7,
                     timeout=None, purpose="", on_delta=None):
        self.calls += 1
        if on_delta:
            import asyncio

            maybe = on_delta("câu trả lời")
            if asyncio.iscoroutine(maybe):
                await maybe
        return Completion(
            text="câu trả lời", prompt_tokens=5, completion_tokens=3,
            latency_s=0.1, model="openai/model-x",
        )


class FakeClient:
    """Giả Langfuse SDK v2: ghi lại mọi lần gọi .trace()."""

    def __init__(self, boom: bool = False):
        self.traces: list[dict] = []
        self.boom = boom

    def trace(self, name=None, metadata=None):
        if self.boom:
            raise RuntimeError("langfuse sập")
        self.traces.append({"name": name, "metadata": metadata})


def test_noop_without_env(cfg):
    tracer = build_tracer(cfg)
    assert tracer.enabled is False
    gateway = FakeGateway()
    assert traced_gateway(gateway, cfg) is gateway


def test_partial_env_still_noop(cfg):
    import dataclasses

    cfg2 = dataclasses.replace(cfg, langfuse_public_key="pk-only")
    assert build_tracer(cfg2).enabled is False


async def test_traced_gateway_emits_metadata_only(cfg):
    client = FakeClient()
    tracer = build_tracer(cfg, client=client)
    assert tracer.enabled is True
    gateway = traced_gateway(FakeGateway(), cfg, tracer=tracer)
    secret_text = "TIN-NHAN-BI-MAT-KHONG-DUOC-VAO-TRACE"
    comp = await gateway.complete(
        [{"role": "user", "content": secret_text}], purpose="chat")
    assert comp.text == "câu trả lời"
    assert len(client.traces) == 1
    trace = client.traces[0]
    assert trace["name"] == "chat"
    meta = trace["metadata"]
    assert meta["model"] == "openai/model-x"
    assert meta["prompt_tokens"] == 11
    assert meta["completion_tokens"] == 7
    assert meta["latency_s"] == 0.25
    assert meta["input_chars"] == len(secret_text)
    assert meta["output_chars"] == len("câu trả lời")
    assert meta["ok"] is True
    # Không một trường nào trong trace chứa nội dung tin nhắn.
    assert secret_text not in json.dumps(trace, ensure_ascii=False)


async def test_traced_stream_and_client_failure_swallowed(cfg):
    client = FakeClient()
    gateway = traced_gateway(FakeGateway(), cfg,
                             tracer=build_tracer(cfg, client=client))
    pieces: list[str] = []
    comp = await gateway.stream(
        [{"role": "user", "content": "chào"}], purpose="chat",
        on_delta=lambda p: pieces.append(p))
    assert comp.text == "câu trả lời" and pieces == ["câu trả lời"]
    assert client.traces and client.traces[0]["metadata"]["ok"] is True

    boom_gateway = traced_gateway(
        FakeGateway(), cfg,
        tracer=build_tracer(cfg, client=FakeClient(boom=True)))
    comp = await boom_gateway.complete(
        [{"role": "user", "content": "chào"}], purpose="chat")
    assert comp.text == "câu trả lời"  # client sập, bot vẫn chạy
