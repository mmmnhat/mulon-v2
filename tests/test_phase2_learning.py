"""Phase 2 — học từ correction (mục 4.4): heuristic tiếng Việt,
phân loại bằng model rẻ (giả lập), chống overfit (>=1 rõ ràng hoặc
>=2 lần lặp; lỗi critical 1 lần là đủ), lesson vào context snapshot,
correction nghiêm trọng sinh eval case JSONL."""

import dataclasses
import json

from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion
from mulon.learning import detect_and_record, detect_correction
from tests.conftest import open_memory

S = "agent:main:telegram:dm:1:topic:0"


class ClassifyGateway:
    def __init__(self, payload):
        self.payload = payload

    async def complete(self, messages, model=None, tools=None, purpose="",
                       temperature=None):
        if purpose == "correction_classify":
            return Completion(text=json.dumps(self.payload))
        return Completion(text="{}")

    async def stream(self, messages, model=None, purpose="", on_delta=None):
        return Completion(text="")


def test_detect_correction_heuristic():
    assert detect_correction("sai rồi, không phải vậy") is True
    assert detect_correction("Ý tao là đặt 7 giờ") is True
    assert detect_correction("lần sau nhớ ngắn gọn thôi") is True
    assert detect_correction("cảm ơn bạn nhiều nhé") is False
    assert detect_correction("ok rồi, tiếp tục đi") is False


async def _seed_pair(memory, user_text, assistant_text):
    await memory.get_or_create_session(S)
    await memory.append_message(S, "user", user_text)
    await memory.append_message(S, "assistant", assistant_text)


async def test_explicit_correction_becomes_lesson_in_context(cfg):
    memory = await open_memory(cfg)
    await _seed_pair(memory, "đặt báo thức lúc 6 giờ sáng nhé",
                     "Đã đặt báo thức 6h sáng.")
    corr_msg = await memory.append_message(
        S, "user", "sai rồi, phải là 7 giờ, không phải 6 giờ"
    )
    gateway = ClassifyGateway({
        "is_correction": True, "explicit": True, "category": "du_kien",
        "severity": "normal", "corrected": "Báo thức phải đặt lúc 7 giờ",
    })
    corr_id = await detect_and_record(memory, gateway, cfg, S, corr_msg,
                                      "sai rồi, phải là 7 giờ")
    assert corr_id is not None
    corr = await memory.get_correction(corr_id)
    assert corr["category"] == "du_kien"
    assert corr["explicit"] == 1
    assert corr["status"] == "lesson_created"
    assert corr["lesson_fact_id"] is not None

    lessons = [f for f in await memory.active_facts()
               if str(f["subject"]).startswith("lesson:")]
    assert len(lessons) == 1
    assert "7 giờ" in lessons[0]["fact"]

    # Lesson xuất hiện trong snapshot ngữ cảnh của lượt sau.
    dossier = Dossier.load(cfg.dossier_dir)
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    built = await ctx.build(S, "báo thức mai mấy giờ?")
    system_text = "\n".join(
        m["content"] for m in built.messages if m["role"] == "system"
    )
    assert "BÀI HỌC ĐÃ RÚT" in system_text
    assert "7 giờ" in system_text
    await memory.close()


async def test_two_implicit_corrections_needed(cfg):
    memory = await open_memory(cfg)
    gateway = ClassifyGateway({
        "is_correction": True, "explicit": False,
        "category": "giong_format", "severity": "normal",
        "corrected": "Trả lời ngắn gọn, đi thẳng vào ý",
    })
    await _seed_pair(memory, "kể dài về lịch sử cà phê", "Bài dài lê thê...")
    m1 = await memory.append_message(S, "user", "lần sau ngắn gọn thôi")
    cid1 = await detect_and_record(memory, gateway, cfg, S, m1,
                                   "lần sau ngắn gọn thôi")
    assert cid1 is not None
    lessons = [f for f in await memory.active_facts()
               if str(f["subject"]).startswith("lesson:")]
    assert lessons == []  # 1 lần chưa rõ ràng -> chưa thành bài học

    await memory.append_message(S, "assistant", "Lại một bài dài nữa...")
    m2 = await memory.append_message(S, "user", "lần sau ngắn gọn nữa nhé")
    cid2 = await detect_and_record(memory, gateway, cfg, S, m2,
                                   "lần sau ngắn gọn nữa nhé")
    assert cid2 is not None
    lessons = [f for f in await memory.active_facts()
               if str(f["subject"]).startswith("lesson:")]
    assert len(lessons) == 1
    assert lessons[0]["subject"] == "lesson:giong_format"
    await memory.close()


async def test_critical_correction_lesson_and_eval_case(cfg, tmp_path):
    cfg = dataclasses.replace(cfg, evals_dir=tmp_path / "evals")
    memory = await open_memory(cfg)
    await _seed_pair(memory, "stk của tui là gì", "STK của bạn là 123456.")
    corr_msg = await memory.append_message(
        S, "user", "sai rồi, số tài khoản tui không phải số đó"
    )
    gateway = ClassifyGateway({
        "is_correction": True, "explicit": False, "category": "du_kien",
        "severity": "critical",
        "corrected": "Số tài khoản phải tra lại từ hồ sơ, không đoán",
    })
    corr_id = await detect_and_record(
        memory, gateway, cfg, S, corr_msg,
        "sai rồi, số tài khoản tui không phải số đó",
    )
    corr = await memory.get_correction(corr_id)
    # Critical: 1 lần là đủ thành bài học dù không explicit.
    assert corr["status"] == "lesson_created"
    # Và tự sinh 1 test case vào bộ eval.
    cases_file = tmp_path / "evals" / "cases.jsonl"
    assert cases_file.exists()
    lines = cases_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    case = json.loads(lines[0])
    assert case["source_correction_id"] == corr_id
    assert case["severity"] == "critical"
    await memory.close()


async def test_classifier_rejection_records_nothing(cfg):
    memory = await open_memory(cfg)
    await _seed_pair(memory, "hôm nay thứ mấy", "Hôm nay thứ sáu.")
    corr_msg = await memory.append_message(
        S, "user", "không phải hỏi vậy đâu, kể chuyện cười đi"
    )
    gateway = ClassifyGateway({"is_correction": False})
    result = await detect_and_record(
        memory, gateway, cfg, S, corr_msg, "không phải hỏi vậy đâu"
    )
    assert result is None
    assert await memory.count_corrections() == 0
    await memory.close()
