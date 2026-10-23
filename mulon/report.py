"""Báo cáo sức khỏe hệ thống (thiết kế mục 10 + 4.5) — Phase 5.

Đọc trajectory + DB và in các số đo "hệ thống có đang khôn lên
không": độ trễ recall/lời gọi model (p50/p95), đường cong học theo
tuần ISO (số lời gọi LLM + tỉ lệ lỗi sau retry), correction rate
4 tuần gần nhất, tình trạng ký ức (fact đang sống / đã thay thế /
bài học đang áp dụng), dung lượng DB.

Chỉ đọc, không ghi gì. DB trống hoặc chưa tồn tại -> in 0 /
"không có dữ kiện", không crash.

CLI:
    python -m mulon.report [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def _percentile(values: list[float], q: float) -> Optional[float]:
    """Percentile nearest-rank. Rỗng -> None."""
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, math.ceil(q / 100.0 * len(ordered)) - 1)
    return ordered[idx]


def _week_key(ts: datetime) -> str:
    iso = ts.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _parse_ts(raw: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _empty_report(db_path: str) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "db_path": db_path,
        "db_size_bytes": 0,
        "turns": 0,
        "llm_calls_total": 0,
        "recall_ms": {"count": 0, "p50": None, "p95": None},
        "llm_latency_s": {"count": 0, "p50": None, "p95": None},
        "task_seconds": {"count": 0, "p50": None, "p95": None},
        "weekly_llm": [],
        "correction_rate_4w": [],
        "facts": {"active": 0, "superseded": 0, "lessons_active": 0},
        "corrections_total": 0,
    }


def build_report(db_path: str | Path) -> dict:
    """Dựng báo cáo từ DB. Thiếu dữ kiện ở đâu thì để trống ở đó."""
    db_path = Path(db_path)
    report = _empty_report(str(db_path))
    if not db_path.exists():
        return report
    size = db_path.stat().st_size
    for side in ("-wal", "-shm"):
        extra = Path(str(db_path) + side)
        if extra.exists():
            size += extra.stat().st_size
    report["db_size_bytes"] = size

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        _fill_from_db(conn, report)
    finally:
        conn.close()
    return report


def _rows(conn, sql: str, params: tuple = ()) -> list:
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []


def _fill_from_db(conn, report: dict) -> None:
    # ----- trajectory: lượt, recall, lời gọi model -----
    turn_weeks: dict[str, int] = {}
    recall_ms: list[float] = []
    llm_latency: list[float] = []
    weekly_llm: dict[str, dict] = {}
    for row in _rows(conn, "SELECT kind, payload, created_at FROM trajectory"):
        ts = _parse_ts(row["created_at"])
        week = _week_key(ts) if ts else "?"
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        if row["kind"] == "turn_done":
            report["turns"] += 1
            turn_weeks[week] = turn_weeks.get(week, 0) + 1
        elif row["kind"] == "recall":
            if isinstance(payload.get("ms"), (int, float)):
                recall_ms.append(float(payload["ms"]))
        elif row["kind"] == "llm_call":
            report["llm_calls_total"] += 1
            if isinstance(payload.get("latency_s"), (int, float)):
                llm_latency.append(float(payload["latency_s"]))
            bucket = weekly_llm.setdefault(
                week, {"week": week, "calls": 0, "errors": 0,
                       "error_rate": None})
            bucket["calls"] += 1
            if payload.get("ok") is False:
                bucket["errors"] += 1
    for bucket in weekly_llm.values():
        if bucket["calls"]:
            bucket["error_rate"] = round(
                bucket["errors"] / bucket["calls"], 4)
    report["weekly_llm"] = [weekly_llm[k] for k in sorted(weekly_llm)]
    report["recall_ms"] = {
        "count": len(recall_ms),
        "p50": _percentile(recall_ms, 50),
        "p95": _percentile(recall_ms, 95),
    }
    report["llm_latency_s"] = {
        "count": len(llm_latency),
        "p50": _percentile(llm_latency, 50),
        "p95": _percentile(llm_latency, 95),
    }

    # ----- độ trễ tác vụ từ bảng tasks -----
    durations: list[float] = []
    for row in _rows(
            conn, "SELECT created_at, updated_at FROM tasks"
                  " WHERE status != 'running'"):
        start, end = _parse_ts(row["created_at"]), _parse_ts(row["updated_at"])
        if start and end and end >= start:
            durations.append((end - start).total_seconds())
    report["task_seconds"] = {
        "count": len(durations),
        "p50": _percentile(durations, 50),
        "p95": _percentile(durations, 95),
    }

    # ----- correction rate 4 tuần ISO gần nhất (kể cả tuần này) -----
    corr_weeks: dict[str, int] = {}
    for row in _rows(conn, "SELECT created_at FROM corrections"):
        ts = _parse_ts(row["created_at"])
        if ts:
            key = _week_key(ts)
            corr_weeks[key] = corr_weeks.get(key, 0) + 1
            report["corrections_total"] += 1
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    last4: list[dict] = []
    for back in (3, 2, 1, 0):
        day = monday - timedelta(weeks=back)
        key = _week_key(datetime(day.year, day.month, day.day,
                                 tzinfo=timezone.utc))
        turns = turn_weeks.get(key, 0)
        corrs = corr_weeks.get(key, 0)
        last4.append({
            "week": key,
            "turns": turns,
            "corrections": corrs,
            "rate": round(corrs / turns, 4) if turns else None,
        })
    report["correction_rate_4w"] = last4

    # ----- ký ức -----
    def _count(sql: str) -> int:
        rows = _rows(conn, sql)
        return int(rows[0][0]) if rows else 0

    report["facts"] = {
        "active": _count(
            "SELECT COUNT(*) FROM memory_facts WHERE valid_to IS NULL"),
        "superseded": _count(
            "SELECT COUNT(*) FROM memory_facts WHERE valid_to IS NOT NULL"),
        "lessons_active": _count(
            "SELECT COUNT(*) FROM memory_facts"
            " WHERE valid_to IS NULL AND subject LIKE 'lesson:%'"),
    }


def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return "không có dữ kiện"
    if isinstance(value, float):
        return f"{value:g}{suffix}"
    return f"{value}{suffix}"


def format_text(report: dict) -> str:
    lines = [
        "=== Báo cáo sức khỏe Mulon ===",
        f"DB: {report['db_path']} ({report['db_size_bytes']} bytes)",
        f"Tổng lượt chat: {report['turns']}",
        f"Tổng lời gọi LLM: {report['llm_calls_total']}",
        f"Độ trễ recall: p50 {_fmt(report['recall_ms']['p50'], 'ms')}, "
        f"p95 {_fmt(report['recall_ms']['p95'], 'ms')}"
        f" (n={report['recall_ms']['count']})",
        f"Độ trễ lời gọi model: p50 "
        f"{_fmt(report['llm_latency_s']['p50'], 's')}, p95 "
        f"{_fmt(report['llm_latency_s']['p95'], 's')}"
        f" (n={report['llm_latency_s']['count']})",
        f"Độ trễ tác vụ: p50 {_fmt(report['task_seconds']['p50'], 's')}, "
        f"p95 {_fmt(report['task_seconds']['p95'], 's')}"
        f" (n={report['task_seconds']['count']})",
        "",
        "Đường cong học theo tuần (lời gọi LLM / tỉ lệ lỗi sau retry):",
    ]
    if report["weekly_llm"]:
        for b in report["weekly_llm"]:
            rate = "—" if b["error_rate"] is None else f"{b['error_rate']:.0%}"
            lines.append(
                f"  {b['week']}: {b['calls']} lời gọi, lỗi {rate}")
    else:
        lines.append("  không có dữ kiện")
    lines.append("Correction rate 4 tuần gần nhất:")
    for w in report["correction_rate_4w"]:
        rate = "—" if w["rate"] is None else f"{w['rate']:.0%}"
        lines.append(
            f"  {w['week']}: {w['corrections']} correction / "
            f"{w['turns']} lượt = {rate}")
    facts = report["facts"]
    lines += [
        "",
        f"Ký ức: {facts['active']} fact đang sống, "
        f"{facts['superseded']} fact đã bị thay thế, "
        f"{facts['lessons_active']} bài học đang áp dụng",
        f"Tổng sự kiện correction đã ghi: {report['corrections_total']}",
    ]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="mulon.report")
    parser.add_argument("--json", action="store_true",
                        help="in JSON thay vì text")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    from .config import Config

    cfg = Config.load(env_file=args.env_file)
    report = build_report(cfg.db_path)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
