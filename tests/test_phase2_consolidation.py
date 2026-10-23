"""Phase 2 — consolidation worker (mục 4.3): trích fact bằng model
rẻ (giả lập), trùng -> bỏ, mâu thuẫn cùng subject -> supersede +
ledger, watermark chống xử lý trùng, chạy theo phiên (/new)."""

import json

from mulon.consolidation import ConsolidationWorker
from mulon.gateway import Completion
from tests.conftest import open_memory

S1 = "agent:main:telegram:dm:1:topic:0"
S2 = "agent:main:telegram:dm:2:topic:0"


class ExtractGateway:
    """Trả lô fact ứng viên cố định cho mọi lần trích xuất."""

    def __init__(self, facts):
        self._facts = facts

    async def complete(self, messages, model=None, tools=None, purpose="",
                       temperature=None):
        if purpose == "consolidation_extract":
            return Completion(text=json.dumps({"facts": self._facts}))
        return Completion(text="{}")


async def test_run_once_dedup_supersede_add(cfg):
    memory = await open_memory(cfg)
    old_id = await memory.add_fact("User thích uống trà đá", subject="uống")
    await memory.get_or_create_session(S1)
    await memory.append_message(
        S1, "user", "tui bỏ trà đá rồi, giờ uống cà phê đen; nhà ở Hà Nội"
    )
    await memory.append_message(S1, "assistant", "Đã ghi nhận.")
    gateway = ExtractGateway([
        # trùng nguyên văn fact đang có -> bỏ qua
        {"fact": "User thích uống trà đá", "subject": "uống",
         "salience": 0.6, "source_msg_id": 1},
        # cùng subject, nội dung mới -> supersede
        {"fact": "User thích uống cà phê đen", "subject": "uống",
         "salience": 0.7, "source_msg_id": 1},
        # hoàn toàn mới -> thêm
        {"fact": "User sống ở Hà Nội", "subject": "nơi ở",
         "salience": 0.8, "source_msg_id": 1},
    ])
    worker = ConsolidationWorker(cfg, memory, gateway)
    stats = await worker.run_once()
    assert stats["messages"] == 2
    assert stats["candidates"] == 3
    assert stats["duplicates"] == 1
    assert stats["superseded"] == 1
    assert stats["added"] == 1

    old = await memory.get_fact(old_id)
    assert old["valid_to"] is not None
    assert old["superseded_by"] is not None
    winner = await memory.get_fact(old["superseded_by"])
    assert "cà phê đen" in winner["fact"]
    assert winner["source"] == "consolidation"

    active_texts = [f["fact"] for f in await memory.active_facts()]
    assert any("Hà Nội" in t for t in active_texts)
    assert not any("trà đá" in t for t in active_texts)

    # Mọi ghi của worker đều có vết trong ledger.
    cur = await memory.db.execute(
        "SELECT action FROM ledger WHERE action LIKE 'consolidation_%'"
    )
    actions = [r["action"] for r in await cur.fetchall()]
    assert "consolidation_add" in actions
    assert "consolidation_supersede" in actions

    # Watermark: chạy lại không xử lý trùng tin nào.
    stats2 = await worker.run_once()
    assert stats2["messages"] == 0
    assert stats2["candidates"] == 0
    await memory.close()


async def test_run_once_scoped_to_session(cfg):
    memory = await open_memory(cfg)
    for key in (S1, S2):
        await memory.get_or_create_session(key)
        await memory.append_message(key, "user", "một sự kiện đáng nhớ")
    gateway = ExtractGateway([
        {"fact": "Fact mới tinh chưa từng có", "subject": "khác",
         "salience": 0.5, "source_msg_id": 1},
    ])
    worker = ConsolidationWorker(cfg, memory, gateway)
    # Chỉ phiên S1 (đường lệnh /new gọi).
    stats = await worker.run_once(session_key=S1)
    assert stats["sessions"] == 1
    assert stats["messages"] == 1
    # Phiên S2 vẫn còn tin chưa xử lý cho vòng toàn cục.
    stats2 = await worker.run_once()
    assert stats2["sessions"] == 1
    assert stats2["messages"] == 1
    await memory.close()
