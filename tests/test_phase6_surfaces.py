"""Phase 6 — bề mặt ký ức + quyền (mục 16.8, 16.11, 16.13):
trình duyệt proactive notes bằng reply, policy tóm tắt bằng lời
thường, lịch sử duyệt từ trajectory, quên có kế hoạch -> xác
nhận 'quên thật' -> thực thi; export/import ký ức."""

import json
from types import SimpleNamespace

from aiogram.enums import ChatType

from mulon import surfaces as surf
from mulon.context import Dossier
from mulon.policy import PolicyEngine
from mulon.telegram_bot import TelegramSurface
from tests.conftest import open_memory


# --------------------- notes: parse + trình duyệt ---------------------

def test_parse_note_action():
    assert surf.parse_note_action("duyệt #3") == ("sent", 3)
    assert surf.parse_note_action("Duyệt", "- #5: nội dung") == ("sent", 5)
    assert surf.parse_note_action("bỏ qua", "note #9 ...") == ("dismissed", 9)
    assert surf.parse_note_action("duyệt") is None       # thiếu id -> không đoán
    assert surf.parse_note_action("ừ hay đấy", "#3") is None
    assert surf.parse_note_action("xin chào") is None


async def test_notes_presenter_via_reply(cfg):
    memory = await open_memory(cfg)
    note_id = await memory.add_proactive_note(
        "Nhắc gia hạn tên miền", reason="sắp tới hạn")
    dossier = Dossier.load(cfg.dossier_dir)
    surface = TelegramSurface(cfg, agent=None, memory=memory,
                              dossier=dossier)

    msg = _fake_message("duyệt", reply_text=f"- #{note_id}: Nhắc...")
    handled = await surface._try_reply_actions(msg)
    assert handled is True
    notes = await memory.list_proactive_notes(status="sent")
    assert [n["id"] for n in notes] == [note_id]
    rows = await memory.recent_trajectory(
        kind="proactive_note_decided", limit=5)
    assert rows and rows[0]["payload"]["note_id"] == note_id
    assert any("Đã duyệt" in a for a in msg.answers)
    await memory.close()


def _fake_message(text, reply_text=None, chat_id=42):
    chat = SimpleNamespace(id=chat_id, type=ChatType.PRIVATE,
                           is_forum=False)
    msg = SimpleNamespace(
        chat=chat, text=text, is_topic_message=False,
        message_thread_id=None,
        from_user=SimpleNamespace(id=42),
        reply_to_message=(SimpleNamespace(text=reply_text)
                          if reply_text is not None else None),
        answers=[],
    )

    async def answer(t, **kw):
        msg.answers.append(t)

    msg.answer = answer
    return msg


# --------------------- quyền bằng lời thường ---------------------

async def test_policy_summary_and_approvals(cfg):
    policy_path = cfg.policy_path
    policy_path.write_text(json.dumps({
        "default": "allow",
        "tools": {"run_command": "deny"},
        "groups": {"web": "allow"},
    }), encoding="utf-8")
    memory = await open_memory(cfg)
    policy = PolicyEngine(policy_path, memory=memory)
    text = surf.summarize_policy(policy)
    assert "full-auto" in text
    assert "run_command" in text and "phải hỏi" in text
    assert "policy.json" in text

    # Quyết định qua check() được ghi trajectory -> /approvals đọc ra.
    decision = await policy.check("run_command", "shell",
                                  session_key="sk")
    assert decision.allowed is False
    await policy.check("read_file", "file", session_key="sk")
    rows = await memory.recent_trajectory(kind="policy_decision",
                                          limit=10)
    assert len(rows) == 2
    out = surf.format_approvals(rows)
    assert "CHẶN" in out and "run_command" in out and "CHO" in out
    await memory.close()


# --------------------- quên có kế hoạch ---------------------

async def _seed_forget(memory, cfg):
    await memory.add_fact("User đang dùng gói dữ liệu VinaPhone.",
                          subject="user", source="chat")
    await memory.add_fact("User thích ăn phở bò.",
                          subject="user", source="chat")
    await memory.add_fact(
        "Bài học: nhắc VinaPhone phải kèm hạn dùng.",
        subject="lesson:giong_format", source="correction")
    mem_file = cfg.dossier_dir / "MEMORY.md"
    mem_file.write_text(
        "# MEMORY\n- User dùng VinaPhone từ 2024.\n- Dòng khác giữ "
        "nguyên.\n", encoding="utf-8")


async def test_forget_plan_and_execute(cfg):
    memory = await open_memory(cfg)
    await _seed_forget(memory, cfg)
    plan = await surf.build_forget_plan(memory, cfg.dossier_dir,
                                        "VinaPhone")
    assert len(plan["facts"]) == 1
    assert len(plan["lessons"]) == 1
    assert len(plan["dossier_lines"]) == 1
    text = surf.format_forget_plan(plan)
    assert "quên thật" in text

    summary = await surf.execute_forget_plan(
        memory, cfg.dossier_dir, plan, session_key="sk")
    assert summary["facts_forgotten"] == 2  # fact + lesson
    assert summary["dossier_lines_removed"] == 1
    active = await memory.active_facts()
    facts_text = " ".join(f["fact"] for f in active)
    assert "VinaPhone" not in facts_text
    assert "phở" in facts_text  # fact không liên quan còn nguyên
    mem_text = (cfg.dossier_dir / "MEMORY.md").read_text(
        encoding="utf-8")
    assert "VinaPhone" not in mem_text
    assert "Dòng khác giữ nguyên" in mem_text
    # Dấu vết kiểm toán: ledger có mục forget, fact cũ truy được.
    cur = await memory.db.execute(
        "SELECT action FROM ledger WHERE action='forget'")
    assert await cur.fetchone() is not None
    gone = await memory.search_facts("VinaPhone")
    assert gone == []
    await memory.close()


async def test_forget_confirm_via_surface(cfg):
    memory = await open_memory(cfg)
    await _seed_forget(memory, cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    surface = TelegramSurface(cfg, agent=None, memory=memory,
                              dossier=dossier)
    # Chưa có kế hoạch chờ -> 'quên thật' không làm gì.
    msg0 = _fake_message("quên thật")
    assert await surface._try_forget_confirm(msg0) is False
    # Có kế hoạch chờ (như /forget vừa tạo) -> thực thi.
    plan = await surf.build_forget_plan(memory, cfg.dossier_dir,
                                        "VinaPhone")
    from mulon.telegram_bot import session_key_for

    key = session_key_for(_fake_message("x"))
    await memory.kv_set(f"forget_pending:{key}",
                        json.dumps(plan, ensure_ascii=False))
    msg = _fake_message("quên thật")
    assert await surface._try_forget_confirm(msg) is True
    assert any("Đã quên" in a for a in msg.answers)
    assert await memory.search_facts("VinaPhone") == []
    assert await memory.kv_get(f"forget_pending:{key}") in (None, "")
    await memory.close()


# --------------------- export / import ---------------------

async def test_export_memory_text_has_provenance(cfg):
    memory = await open_memory(cfg)
    await memory.add_fact("Fact có nguồn rõ ràng.", subject="user",
                          source="telegram-dm")
    text = await surf.export_memory_text(
        memory, {"MEMORY.md": "# MEMORY\nnội dung dossier"})
    assert "nội dung dossier" in text
    assert "Fact có nguồn rõ ràng." in text
    assert "nguồn: telegram-dm" in text
    await memory.close()


def test_parse_import_json_and_markdown():
    items = surf.parse_import_content(json.dumps({
        "facts": [{"subject": "user", "fact": "Thích trà đá."},
                  "Câu trần trụi."]}), "x.json")
    assert items == [{"subject": "user", "fact": "Thích trà đá."},
                     {"subject": "", "fact": "Câu trần trụi."}]
    md = ("# Sở thích\n- Thích cà phê đen.\n"
          "- Fact xuất (nguồn: chat, từ 2026-01-01)\n")
    items = surf.parse_import_content(md, "memory.md")
    assert items[0] == {"subject": "Sở thích",
                        "fact": "Thích cà phê đen."}
    assert items[1]["fact"] == "Fact xuất"
    assert surf.parse_import_content("{hỏng", "x.json") == []
    assert surf.parse_import_content("", "x.md") == []


async def test_import_adds_facts_with_source(cfg):
    memory = await open_memory(cfg)
    items = surf.parse_import_content(
        "# user\n- Ở Sài Gòn.\n- Làm việc tự do.\n", "ghi.md")
    for item in items:
        await memory.add_fact(item["fact"], subject=item["subject"],
                              source="import")
    facts = await memory.active_facts()
    assert len(facts) == 2
    assert all(f["source"] == "import" for f in facts)
    await memory.close()


# --------------------- reaction -> taste qua surface ---------------------

async def test_surface_reaction_routes_to_feed(cfg):
    from mulon.feed import FeedEngine
    from mulon.gateway import Completion

    class GW:
        async def complete(self, messages, model=None, tools=None,
                           **kw):
            return Completion(text="bài feed")

    memory = await open_memory(cfg)
    feed = FeedEngine(cfg, memory, GW())
    dossier = Dossier.load(cfg.dossier_dir)
    surface = TelegramSurface(
        cfg, agent=None, memory=memory, dossier=dossier,
        surfaces={"feed": feed})

    class Bot:
        async def send_message(self, chat_id, text,
                               message_thread_id=None):
            return SimpleNamespace(message_id=31337)

    await feed.publish(Bot(), chat_id=-5)
    assert await surface._handle_reaction(-5, 31337, ["👍"]) is True
    counts = await memory.feed_signal_counts()
    assert counts and counts[0]["reaction"] == "👍"
    # Reaction trên tin lạ: im lặng, không lỗi.
    assert await surface._handle_reaction(-5, 999, ["👍"]) is False
    await memory.close()
