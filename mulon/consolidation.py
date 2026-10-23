"""Consolidation worker — tổng hợp ký ức nền (thiết kế mục 4.3).

Hồi sinh đúng nghĩa phần dead code của Mulon cũ: đọc episode chưa
xử lý -> model rẻ trích fact ứng viên (JSON chặt, parse phòng thủ)
-> đối chiếu kho fact đang hiệu lực:

- trùng nguyên văn (sau gấp dấu)  -> bỏ qua
- cùng subject nhưng nội dung khác -> fact mới supersede fact cũ
  theo cơ chế bi-temporal sẵn có (bản cũ đóng vòng đời, không xóa)
- còn lại                          -> thêm fact mới

Mọi ghi của worker đều có nguồn (source='consolidation' +
source_msg_id) và ghi ledger — hoàn tác được theo mục 4.4.
Watermark theo từng session lưu trong kv_state
(`consolidation_upto:<session_key>`): đã xử lý tới đâu đánh dấu
tới đó, chạy lại không xử lý trùng.

Chạy tay:  python -m mulon.consolidation --once [--session KEY]
Trong bot: main.py bật vòng lặp nền khi CONSOLIDATION_ENABLED=1,
và lệnh /new kích hoạt run_once cho phiên vừa đóng.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from typing import Optional

from .memory import fold_vi

logger = logging.getLogger("mulon.consolidation")

EXTRACT_SYSTEM = (
    "Trích xuất các SỰ KIỆN BỀN đáng nhớ lâu dài từ đoạn hội thoại: "
    "quyết định đã chốt, cam kết, sở thích bền, thông tin về user "
    "hoặc người khác, con số/tên riêng quan trọng. Bỏ câu xã giao và "
    "việc nhất thời. Chỉ trả JSON: {\"facts\": [{\"fact\": \"...\", "
    "\"subject\": \"chủ đề ngắn\", \"salience\": 0.0-1.0, "
    "\"source_msg_id\": <id tin nhắn nguồn>}]}. Không có gì đáng nhớ "
    "thì {\"facts\": []}."
)


class ConsolidationWorker:
    def __init__(self, cfg, memory, gateway):
        self.cfg = cfg
        self.memory = memory
        self.gateway = gateway

    # ---------- điểm vào ----------
    async def run_once(self, session_key: Optional[str] = None) -> dict:
        """Xử lý các episode chưa consolidation.

        session_key=None: mọi session có tin chưa xử lý.
        Có session_key: chỉ phiên đó (lệnh /new gọi đường này).
        """
        stats = {"sessions": 0, "messages": 0, "candidates": 0,
                 "added": 0, "duplicates": 0, "superseded": 0,
                 "backfilled": 0}
        # Nhúng bù trước: message/fact nào trượt lúc ghi thì bổ sung.
        try:
            stats["backfilled"] = await self.memory.backfill_embeddings()
        except Exception as exc:
            logger.warning("backfill embeddings lỗi: %s", exc)
        if session_key:
            keys = [session_key]
        else:
            keys = await self._pending_sessions()
        for key in keys:
            try:
                one = await self._process_session(key)
            except Exception as exc:
                logger.warning("consolidation phiên %s lỗi: %s", key, exc)
                continue
            stats["sessions"] += 1
            for field in ("messages", "candidates", "added",
                          "duplicates", "superseded"):
                stats[field] += one[field]
        if stats["messages"] or stats["backfilled"]:
            await self.memory.log_trajectory("", "consolidation", stats)
        return stats

    async def _pending_sessions(self) -> list[str]:
        cur = await self.memory.db.execute(
            "SELECT DISTINCT session_key FROM messages"
        )
        keys = []
        for (key,) in await cur.fetchall():
            upto = await self._watermark(key)
            cur2 = await self.memory.db.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE session_key=?"
                " AND id>?",
                (key, upto),
            )
            row = await cur2.fetchone()
            if row and int(row["n"]) > 0:
                keys.append(key)
        return keys

    async def _watermark(self, session_key: str) -> int:
        raw = await self.memory.kv_get(f"consolidation_upto:{session_key}")
        try:
            return int(raw or 0)
        except ValueError:
            return 0

    # ---------- xử lý 1 phiên ----------
    async def _process_session(self, session_key: str) -> dict:
        stats = {"messages": 0, "candidates": 0, "added": 0,
                 "duplicates": 0, "superseded": 0}
        upto = await self._watermark(session_key)
        cur = await self.memory.db.execute(
            "SELECT id, role, content FROM messages WHERE session_key=?"
            " AND id>? ORDER BY id LIMIT ?",
            (session_key, upto, int(self.cfg.consolidation_batch)),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        if not rows:
            return stats
        stats["messages"] = len(rows)
        candidates = await self._extract(rows)
        stats["candidates"] = len(candidates)
        active = await self.memory.active_facts(limit=1000)
        for cand in candidates:
            outcome = await self._apply_candidate(session_key, cand, active)
            stats[outcome] += 1
        # Đánh dấu đã xử lý: watermark tiến tới tin cuối của lô.
        await self.memory.kv_set(
            f"consolidation_upto:{session_key}", str(rows[-1]["id"])
        )
        return stats

    async def _extract(self, rows: list[dict]) -> list[dict]:
        transcript = "\n".join(
            f"[{r['id']}] {r['role']}: {r['content']}" for r in rows
        )
        prompt = [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": transcript[:30_000]},
        ]
        try:
            comp = await self.gateway.complete(
                prompt, model=self.cfg.model_cheap,
                purpose="consolidation_extract", temperature=0.2,
            )
        except Exception as exc:
            logger.warning("consolidation extract lỗi: %s", exc)
            return []
        match = re.search(r"\{.*\}", comp.text or "", flags=re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
        out: list[dict] = []
        for item in data.get("facts") or []:
            if not isinstance(item, dict):
                continue
            fact = str(item.get("fact") or "").strip()
            if not fact:
                continue
            try:
                salience = float(item.get("salience", 0.5))
            except (TypeError, ValueError):
                salience = 0.5
            src = item.get("source_msg_id")
            out.append({
                "fact": fact,
                "subject": str(item.get("subject") or "").strip(),
                "salience": max(0.0, min(1.0, salience)),
                "source_msg_id": int(src) if isinstance(src, int) else None,
            })
        return out

    async def _apply_candidate(self, session_key: str, cand: dict,
                               active: list[dict]) -> str:
        """Đối chiếu 1 fact ứng viên với kho. Trả: added/duplicates/
        superseded. `active` được cập nhật tại chỗ cho các ứng viên sau."""
        folded = fold_vi(cand["fact"])
        for old in active:
            if old.get("valid_to") is None and \
                    fold_vi(str(old.get("fact") or "")) == folded:
                return "duplicates"
        subject_folded = fold_vi(cand["subject"]) if cand["subject"] else ""
        conflicts = []
        if subject_folded:
            for old in active:
                if old.get("valid_to") is not None:
                    continue
                if fold_vi(str(old.get("subject") or "")) == subject_folded:
                    conflicts.append(int(old["id"]))
        new_id = await self.memory.add_fact(
            cand["fact"], subject=cand["subject"],
            salience=cand["salience"],
            source_msg_id=cand["source_msg_id"],
            source="consolidation",
            supersedes=conflicts,
        )
        await self.memory.append_ledger(
            f"fact:{new_id}",
            "consolidation_supersede" if conflicts else "consolidation_add",
            cand["fact"],
            detail=(f"session:{session_key} "
                    f"supersedes:{conflicts if conflicts else '-'}"),
        )
        fresh = await self.memory.get_fact(new_id)
        if fresh:
            active[:] = [a for a in active if a["id"] not in conflicts]
            active.append(fresh)
        return "superseded" if conflicts else "added"


# ------------------------------- CLI -------------------------------

async def _amain(args) -> int:
    from .config import Config
    from .embeddings import build_embedder
    from .gateway import ModelGateway
    from .memory import Memory

    cfg = Config.load(env_file=args.env_file)
    memory = await Memory.open(cfg.db_path)
    embedder = build_embedder(cfg)
    if embedder is not None:
        memory.embed_timeout_s = cfg.embed_timeout_s
        await memory.set_embedder(embedder)
    gateway = ModelGateway(cfg, memory=memory)
    worker = ConsolidationWorker(cfg, memory, gateway)
    stats = await worker.run_once(session_key=args.session)
    print(json.dumps(stats, ensure_ascii=False))
    await memory.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mulon.consolidation")
    parser.add_argument("--once", action="store_true",
                        help="chạy 1 vòng consolidation rồi thoát")
    parser.add_argument("--session", default=None,
                        help="chỉ xử lý session_key này")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.once:
        parser.error("chỉ hỗ trợ --once ở bản này")
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
