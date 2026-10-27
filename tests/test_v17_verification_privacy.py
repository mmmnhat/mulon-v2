"""Kiểm thử Parity Muse T-24.3:
Không để lộ chữ NỘI BỘ (kiểm chứng/chẩn đoán) vào câu trả lời chat của người dùng.
Ưu tiên ngữ cảnh hội thoại thực tế khi kiểm chứng mâu thuẫn với ngữ cảnh.
"""

import json
import pytest

from mulon.agent import Agent, sanitize_chat_reply
from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion, ToolCall
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from tests.conftest import open_memory

SESSION = "agent:main:telegram:dm:1:topic:0"


class MockVerifyGateway:
    """Gateway giả lập trả kết quả verifier tuỳ biến."""

    def __init__(self, verify_ok: bool, diagnosis: str, act_text: str = "Kết quả tác vụ"):
        self.verify_ok = verify_ok
        self.diagnosis = diagnosis
        self.act_text = act_text
        self.last_verify_prompt = None

    async def complete(self, messages, model=None, tools=None, purpose="", temperature=None):
        if purpose == "verify":
            self.last_verify_prompt = messages
            return Completion(text=json.dumps({"ok": self.verify_ok, "diagnosis": self.diagnosis}, ensure_ascii=False))
        if purpose == "plan":
            return Completion(text=json.dumps({"steps": ["Thực hiện tác vụ"]}, ensure_ascii=False))
        return Completion(text=self.act_text)

    async def stream(self, messages, model=None, purpose="", on_delta=None):
        if on_delta:
            await on_delta(self.act_text)
        return Completion(text=self.act_text)


async def _make_agent_with_gateway(cfg, gateway):
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    agent = Agent(cfg, gateway, memory, ctx, registry, policy)
    return agent, memory


@pytest.mark.asyncio
async def test_failed_verification_does_not_leak_internal_diagnostic_to_chat(cfg):
    """Khi kiểm chứng thất bại: chẩn đoán lưu ở DB/task, KHÔNG in vào kết quả chat gửi user."""
    diag = "Không tìm thấy file nguồn hoặc thiếu dữ liệu tham chiếu."
    gw = MockVerifyGateway(verify_ok=False, diagnosis=diag, act_text="Đã tìm kiếm nhưng chưa thấy file.")
    agent, memory = await _make_agent_with_gateway(cfg, gw)

    result = await agent.handle(SESSION, "chạy lệnh tìm kiếm file báo cáo")

    # Kiểm tra mặt chat (TurnResult.text)
    assert result.verified is False
    assert "⚠️ Chưa kiểm chứng" not in result.text
    assert "Chẩn đoán:" not in result.text
    assert "Phần làm được tới giờ:" not in result.text
    assert "Đã tìm kiếm nhưng chưa thấy file." in result.text

    # Kiểm tra task trong DB: vẫn lưu đúng trạng thái failed và chẩn đoán nội bộ
    task = await memory.get_task(result.task_id)
    assert task["status"] == "failed"
    assert task["error"] == diag

    # Kiểm tra task step
    steps = task.get("steps") or []
    verify_step = [s for s in steps if "Kiểm chứng:" in s["title"]]
    assert len(verify_step) >= 1
    assert verify_step[-1]["status"] == "failed"
    assert verify_step[-1]["detail"] == diag

    await memory.close()


@pytest.mark.asyncio
async def test_context_grounded_query_prioritizes_context_over_verifier_diagnosis(cfg):
    """Hỏi lại thông tin từ ngữ cảnh (mã bí mật lúc nãy): ưu tiên ngữ cảnh hội thoại thật,

    không bị verifier đánh trượt oan vì thiếu tool bằng chứng.
    """
    secret_code = "MULON-SEC-8492"
    reply_text = f"Mã bí mật lúc nãy ní nói là {secret_code} nha."

    # Verifier giả định đánh trượt vì không thấy tool evidence
    gw = MockVerifyGateway(
        verify_ok=False,
        diagnosis="Không có bằng chứng hoặc ngữ cảnh hội thoại trước đó xác nhận người dùng đã cung cấp mã bí mật",
        act_text=reply_text,
    )
    agent, memory = await _make_agent_with_gateway(cfg, gw)

    # Lượt 1: người dùng cung cấp mã bí mật
    await memory.append_message(SESSION, "user", f"Mã bí mật của tui là {secret_code}")
    await memory.append_message(SESSION, "assistant", f"Dạ tui đã ghi nhận mã bí mật {secret_code} của ní rồi.")

    # Lượt 2: người dùng hỏi lại mã bí mật lúc nãy
    result = await agent.handle(SESSION, "mã bí mật lúc nãy tui nói là gì nhớ không?")

    # Xác nhận cơ chế ưu tiên ngữ cảnh hội thoại kích hoạt:
    assert result.verified is True
    assert "⚠️ Chưa kiểm chứng" not in result.text
    assert "Chẩn đoán:" not in result.text
    assert secret_code in result.text

    # Task status phải là done
    task = await memory.get_task(result.task_id)
    assert task["status"] == "done"

    steps = task.get("steps") or []
    verify_step = [s for s in steps if "Kiểm chứng:" in s["title"]]
    assert len(verify_step) >= 1
    assert verify_step[-1]["status"] == "done"
    assert "Đạt yêu cầu" in verify_step[-1]["title"]

    await memory.close()


@pytest.mark.asyncio
async def test_verify_prompt_includes_prior_conversation_context(cfg):
    """Verifier độc lập được cung cấp ngữ cảnh hội thoại trước đó để không bị mù ngữ cảnh."""
    gw = MockVerifyGateway(verify_ok=True, diagnosis="", act_text="Câu trả lời hoàn tất")
    agent, memory = await _make_agent_with_gateway(cfg, gw)

    convo = [
        {"role": "user", "content": "Tui tên là Minh Nhật"},
        {"role": "assistant", "content": "Chào anh Minh Nhật!"},
        {"role": "user", "content": "nhớ lại tui tên gì"},
    ]

    verdict = await agent._verify("nhớ lại tui tên gì", "Anh tên là Minh Nhật.", evidence=[], convo=convo)
    assert verdict is not None
    assert verdict[0] is True

    # Kiểm tra prompt gửi tới verifier
    verify_prompt = gw.last_verify_prompt
    assert verify_prompt is not None
    user_prompt_content = verify_prompt[1]["content"]
    assert "NGỮ CẢNH HỘI THOẠI TRƯỚC ĐÓ:" in user_prompt_content
    assert "Tui tên là Minh Nhật" in user_prompt_content
    assert "Chào anh Minh Nhật!" in user_prompt_content

    await memory.close()


def test_sanitize_chat_reply_utility():
    """Hàm sanitize_chat_reply lọc sạch mọi tiền tố/hậu tố chẩn đoán kiểm chứng nếu có."""
    leaked_text = (
        "⚠️ Chưa kiểm chứng được là đã xong đúng yêu cầu. "
        "Chẩn đoán: Không có bằng chứng xác nhận.\n\n"
        "Phần làm được tới giờ:\n"
        "Mã bí mật của bạn là 12345."
    )
    cleaned = sanitize_chat_reply(leaked_text)
    assert "⚠️ Chưa kiểm chứng" not in cleaned
    assert "Chẩn đoán:" not in cleaned
    assert "Phần làm được tới giờ:" not in cleaned
    assert cleaned == "Mã bí mật của bạn là 12345."

    reflexion_text = (
        "KIỂM CHỨNG CHƯA ĐẠT. Chẩn đoán của người kiểm chứng: thiếu thông tin\n"
        "Đây là kết quả chính xác."
    )
    cleaned2 = sanitize_chat_reply(reflexion_text)
    assert "KIỂM CHỨNG CHƯA ĐẠT" not in cleaned2
    assert "Chẩn đoán" not in cleaned2
    assert cleaned2 == "Đây là kết quả chính xác."

    normal_text = "Chào bạn! Đây là câu trả lời bình thường."
    assert sanitize_chat_reply(normal_text) == normal_text
