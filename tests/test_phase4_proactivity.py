"""Phase 4 — proactivity engine (mục 7): heartbeat gom việc bằng
model rẻ + ngữ cảnh nhẹ; ngoài giờ -> bỏ qua; checklist rỗng ->
HEARTBEAT_OK im lặng; có việc -> xếp hàng proactive_notes (chưa
gửi); PROACTIVE_PREFERENCES chặn đúng chủ đề."""

import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from mulon.gateway import Completion
from mulon.proactivity import (ProactivityEngine, in_active_hours,
                               parse_active_hours, parse_blocked_topics,
                               parse_checklist)
from tests.conftest import open_memory

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
IN_HOURS = datetime(2026, 10, 23, 10, 0, tzinfo=TZ)
OUT_HOURS = datetime(2026, 10, 23, 3, 0, tzinfo=TZ)

CHECKLIST = """# HEARTBEAT

<!-- comment ẩn, có gạch đầu dòng giả:
- [ ] mục giả trong comment không được tính
-->

- [ ] Có task nền nào kẹt không?
- [ ] Cam kết nào sắp tới hạn?
"""

PREFS_BLOCK = """# PROACTIVE_PREFERENCES

## Không chủ động về

- khuyến mãi
- tin tức giải trí

## Muốn được nhắc

- cam kết sắp tới hạn
"""


class HeartbeatGateway:
    """Model rẻ giả: trả lô notes cố định cho lượt heartbeat."""

    def __init__(self, notes=None, boom=False):
        self._notes = notes or []
        self._boom = boom
        self.calls = 0

    async def complete(self, messages, model=None, tools=None,
                       purpose="", temperature=None):
        self.calls += 1
        if self._boom:
            raise RuntimeError("proxy sập")
        assert purpose == "heartbeat"
        return Completion(
            text=json.dumps({"notes": self._notes}, ensure_ascii=False))


def _write_dossier(cfg, checklist=CHECKLIST, prefs=PREFS_BLOCK):
    (cfg.dossier_dir / "HEARTBEAT.md").write_text(checklist,
                                                  encoding="utf-8")
    if prefs is not None:
        (cfg.dossier_dir / "PROACTIVE_PREFERENCES.md").write_text(
            prefs, encoding="utf-8")


async def _heartbeat_rows(memory):
    cur = await memory.db.execute(
        "SELECT payload FROM trajectory WHERE kind='heartbeat'"
        " ORDER BY id")
    return [json.loads(r["payload"]) for r in await cur.fetchall()]


# ------------------------- hàm thuần -------------------------

def test_parse_checklist_strips_comments_and_boxes():
    items = parse_checklist(CHECKLIST)
    assert items == ["Có task nền nào kẹt không?",
                     "Cam kết nào sắp tới hạn?"]
    assert parse_checklist("") == []
    assert parse_checklist("# Chỉ có tiêu đề\n") == []


def test_parse_blocked_topics_only_under_block_heading():
    blocked = parse_blocked_topics(PREFS_BLOCK)
    assert blocked == ["khuyến mãi", "tin tức giải trí"]
    # bullet ở mục "Muốn được nhắc" không bị coi là chặn
    assert "cam kết sắp tới hạn" not in blocked


def test_active_hours_window_and_overnight():
    assert parse_active_hours("07:00-23:00").__str__() is not None
    assert in_active_hours(IN_HOURS, "07:00-23:00") is True
    assert in_active_hours(OUT_HOURS, "07:00-23:00") is False
    # khung qua đêm 22:00-06:00
    assert in_active_hours(OUT_HOURS, "22:00-06:00") is True
    assert in_active_hours(IN_HOURS, "22:00-06:00") is False
    # spec hỏng -> mặc định 07:00-23:00, không crash
    assert in_active_hours(IN_HOURS, "tào lao") is True


# ------------------------- engine -------------------------

async def test_out_of_hours_skips_without_calling_model(cfg):
    cfg = replace(cfg, proactivity_enabled=True)  # vá 1.4.1: run_once tôn trọng công tắc
    _write_dossier(cfg)
    memory = await open_memory(cfg)
    gateway = HeartbeatGateway(notes=[{"content": "x"}])
    engine = ProactivityEngine(cfg, memory, gateway)
    stats = await engine.run_once(now=OUT_HOURS)
    assert stats["skipped"] == "out_of_hours"
    assert stats["notes"] == 0
    assert gateway.calls == 0  # ngoài giờ: không tốn lời gọi nào
    assert await memory.list_proactive_notes(status=None) == []
    rows = await _heartbeat_rows(memory)
    assert rows and rows[-1]["result"] == "skipped_out_of_hours"
    await memory.close()


async def test_empty_checklist_is_heartbeat_ok_and_silent(cfg):
    cfg = replace(cfg, proactivity_enabled=True)  # vá 1.4.1: run_once tôn trọng công tắc
    _write_dossier(cfg, checklist="# HEARTBEAT\n\n<!-- trống -->\n")
    memory = await open_memory(cfg)
    gateway = HeartbeatGateway(notes=[{"content": "không được dùng"}])
    engine = ProactivityEngine(cfg, memory, gateway)
    stats = await engine.run_once(now=IN_HOURS)
    assert stats["items"] == 0
    assert stats["heartbeat_ok"] is True
    assert gateway.calls == 0
    rows = await _heartbeat_rows(memory)
    assert rows[-1]["result"] == "HEARTBEAT_OK"
    assert await memory.list_proactive_notes(status=None) == []
    await memory.close()


async def test_notes_queued_and_preferences_suppress(cfg):
    cfg = replace(cfg, proactivity_enabled=True)  # vá 1.4.1: run_once tôn trọng công tắc
    _write_dossier(cfg)
    memory = await open_memory(cfg)
    gateway = HeartbeatGateway(notes=[
        {"content": "Cam kết giao hàng hết hạn chiều nay",
         "reason": "tracked item sắp tới hạn", "topic": "cam kết"},
        {"content": "Đợt khuyến mãi lớn vừa bắt đầu",
         "reason": "có ưu đãi", "topic": "khuyến mãi"},
        {"content": "Bản tin tức giải trí buổi sáng",
         "reason": "mới", "topic": "giải trí"},
    ])
    engine = ProactivityEngine(cfg, memory, gateway)
    stats = await engine.run_once(now=IN_HOURS)
    assert stats["items"] == 2
    assert stats["candidates"] == 3
    assert stats["suppressed"] == 2  # khuyến mãi + giải trí bị chặn
    assert stats["notes"] == 1
    assert stats["heartbeat_ok"] is False
    queued = await memory.list_proactive_notes()
    assert len(queued) == 1
    assert queued[0]["status"] == "pending"  # chỉ xếp hàng, chưa gửi
    assert "Cam kết giao hàng" in queued[0]["content"]
    # đổi trạng thái theo vòng đời Phase 6 sẽ dùng
    assert await memory.set_proactive_note_status(
        queued[0]["id"], "dismissed") is True
    assert await memory.list_proactive_notes() == []  # hết pending
    dismissed = await memory.list_proactive_notes(status="dismissed")
    assert dismissed[0]["id"] == queued[0]["id"]
    assert await memory.set_proactive_note_status(
        queued[0]["id"], "trạng thái lạ") is False
    await memory.close()


async def test_model_empty_or_down_is_heartbeat_ok(cfg):
    _write_dossier(cfg)
    memory = await open_memory(cfg)
    engine = ProactivityEngine(cfg, memory, HeartbeatGateway(notes=[]))
    stats = await engine.run_once(now=IN_HOURS)
    assert stats["heartbeat_ok"] is True
    assert stats["notes"] == 0
    # model sập -> vẫn im lặng, không raise, không sinh note giả
    engine2 = ProactivityEngine(cfg, memory, HeartbeatGateway(boom=True))
    stats2 = await engine2.run_once(now=IN_HOURS)
    assert stats2["heartbeat_ok"] is True
    assert await memory.list_proactive_notes(status=None) == []
    await memory.close()
