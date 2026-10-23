"""Phase 5 — báo cáo sức khỏe: số liệu gieo sẵn phải khớp
percentile/tỉ lệ đã biết trước; DB trống không crash."""

import json

from mulon import report as report_mod
from tests.conftest import open_memory


async def _seed(cfg):
    memory = await open_memory(cfg)
    try:
        session = "report:test"
        for _ in range(3):
            await memory.log_trajectory(session, "turn_done",
                                        {"intent": "chat"})
        for ms in (10, 20, 30, 40):
            await memory.log_trajectory(session, "recall",
                                        {"ms": ms, "hits": 1})
        await memory.log_trajectory(session, "llm_call",
                                    {"purpose": "chat", "latency_s": 0.5,
                                     "ok": True})
        await memory.log_trajectory(session, "llm_call",
                                    {"purpose": "chat", "latency_s": 1.5,
                                     "ok": False})
        a = await memory.add_fact("Fact A", subject="x", source="test")
        await memory.add_fact("Fact B", subject="x", source="test",
                              supersedes=[a])
        await memory.add_fact("Bài học mẫu", subject="lesson:du_kien",
                              source="test")
        await memory.add_correction(
            session_key=session, corrected="x", original_request="y",
            wrong_output="z", user_msg_id=1, category="du_kien",
            severity="normal", explicit=True)
    finally:
        await memory.close()


async def test_report_numbers(cfg):
    await _seed(cfg)
    report = report_mod.build_report(cfg.db_path)
    assert report["turns"] == 3
    assert report["llm_calls_total"] == 2
    assert report["recall_ms"] == {"count": 4, "p50": 20, "p95": 40}
    assert report["llm_latency_s"]["p50"] == 0.5
    assert report["llm_latency_s"]["p95"] == 1.5
    assert report["db_size_bytes"] > 0

    weekly = {b["week"]: b for b in report["weekly_llm"]}
    assert len(weekly) == 1
    bucket = next(iter(weekly.values()))
    assert bucket["calls"] == 2 and bucket["errors"] == 1
    assert bucket["error_rate"] == 0.5

    current = report["correction_rate_4w"][-1]
    assert current["turns"] == 3 and current["corrections"] == 1
    assert current["rate"] == round(1 / 3, 4)
    assert len(report["correction_rate_4w"]) == 4

    assert report["facts"] == {"active": 2, "superseded": 1,
                                "lessons_active": 1}
    assert report["corrections_total"] == 1
    text = report_mod.format_text(report)
    assert "Tổng lượt chat: 3" in text
    assert "1 bài học đang áp dụng" in text


def test_report_missing_db(tmp_path, capsys):
    report = report_mod.build_report(tmp_path / "chua-co.db")
    assert report["turns"] == 0
    assert report["recall_ms"]["p50"] is None
    assert report["weekly_llm"] == []
    text = report_mod.format_text(report)
    assert "không có dữ kiện" in text


async def test_report_cli_json(cfg, monkeypatch, capsys):
    await _seed(cfg)
    monkeypatch.setenv("MULON_DB_PATH", str(cfg.db_path))
    rc = report_mod.main(["--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["turns"] == 3
    assert data["facts"]["lessons_active"] == 1
