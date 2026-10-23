"""Lớp ký ức: SQLite WAL + FTS5 + fact bi-temporal.

Ba lớp tách bạch theo thiết kế mục 4.1:
- Working memory  -> bảng tasks / task_steps (runtime state).
- Episodic        -> bảng messages + FTS5 (kèm cột gấp dấu tiếng Việt).
- Semantic        -> bảng memory_facts có vòng đời bi-temporal
  (valid_from / valid_to / superseded_by / source_msg_id, mượn schema
  Graphiti — Phụ lục 15.2): fact cũ bị thay thế chứ không bị xóa.

Recall: giao diện hybrid sạch. Bản Phase 1 chạy FTS/BM25 làm chính;
vector qua sqlite-vec là optional import — nếu extension không có,
recall tự degrade xuống BM25-only (fallback chain kiểu OpenClaw, mục
4.2) thay vì sập.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

# sqlite-vec là optional: có thì bật đường vector, không có thì BM25-only.
try:  # pragma: no cover - phụ thuộc môi trường
    import sqlite_vec  # type: ignore

    HAS_SQLITE_VEC = True
except Exception:  # pragma: no cover
    sqlite_vec = None  # type: ignore
    HAS_SQLITE_VEC = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fold_vi(text: str) -> str:
    """Gấp dấu tiếng Việt để FTS khớp cả bản có dấu lẫn không dấu."""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(
        ch for ch in decomposed if unicodedata.category(ch) != "Mn"
    )
    return stripped.lower()


def _fts_query(query: str) -> str:
    """Dựng truy vấn FTS5 an toàn: OR các từ (có dấu + đã gấp), BM25 xếp hạng."""
    words = re.findall(r"[\w]+", query, flags=re.UNICODE)
    terms: list[str] = []
    for w in words:
        if len(w) < 2:
            continue
        terms.append(f'"{w}"')
        folded = fold_vi(w)
        if folded != w:
            terms.append(f'"{folded}"')
    if not terms:
        return '""'
    return " OR ".join(dict.fromkeys(terms))


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    session_key   TEXT PRIMARY KEY,
    chat_id       INTEGER DEFAULT 0,
    topic_id      INTEGER DEFAULT 0,
    summary       TEXT DEFAULT '',
    summary_upto_id INTEGER DEFAULT 0,
    flush_upto_id   INTEGER DEFAULT 0,
    flush_count     INTEGER DEFAULT 0,
    closed_at     TEXT DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key   TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    content_nodau TEXT NOT NULL DEFAULT '',
    meta          TEXT DEFAULT '{}',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_key, id);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, content_nodau, content='messages', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, content_nodau)
    VALUES (new.id, new.content, new.content_nodau);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, content_nodau)
    VALUES ('delete', old.id, old.content, old.content_nodau);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, content_nodau)
    VALUES ('delete', old.id, old.content, old.content_nodau);
    INSERT INTO messages_fts(rowid, content, content_nodau)
    VALUES (new.id, new.content, new.content_nodau);
END;

CREATE TABLE IF NOT EXISTS memory_facts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject       TEXT NOT NULL DEFAULT '',
    fact          TEXT NOT NULL,
    fact_nodau    TEXT NOT NULL DEFAULT '',
    salience      REAL DEFAULT 0.5,
    valid_from    TEXT NOT NULL,
    valid_to      TEXT,
    superseded_by INTEGER REFERENCES memory_facts(id),
    source_msg_id INTEGER,
    source        TEXT DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_active ON memory_facts(valid_to);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    subject, fact, fact_nodau, content='memory_facts', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON memory_facts BEGIN
    INSERT INTO facts_fts(rowid, subject, fact, fact_nodau)
    VALUES (new.id, new.subject, new.fact, new.fact_nodau);
END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON memory_facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, subject, fact, fact_nodau)
    VALUES ('delete', old.id, old.subject, old.fact, old.fact_nodau);
END;
CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON memory_facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, subject, fact, fact_nodau)
    VALUES ('delete', old.id, old.subject, old.fact, old.fact_nodau);
    INSERT INTO facts_fts(rowid, subject, fact, fact_nodau)
    VALUES (new.id, new.subject, new.fact, new.fact_nodau);
END;

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    session_key TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'running',
    plan_json   TEXT NOT NULL DEFAULT '[]',
    result      TEXT DEFAULT '',
    error       TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_steps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT NOT NULL REFERENCES tasks(id),
    idx        INTEGER NOT NULL,
    title      TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    detail     TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trajectory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT DEFAULT '',
    kind        TEXT NOT NULL,
    payload     TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    target     TEXT NOT NULL,
    action     TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    detail     TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""


class Memory:
    """Cửa ngõ duy nhất tới DB. Mọi ghi/đọc ký ức đi qua đây."""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self.vector_enabled = False

    # ---------- mở / đóng ----------
    @classmethod
    async def open(cls, db_path: str | Path) -> "Memory":
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(str(path))
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA)
        await db.commit()
        mem = cls(db)
        mem.vector_enabled = await mem._try_enable_vector()
        return mem

    async def _try_enable_vector(self) -> bool:
        """Bật sqlite-vec nếu import được; không được thì BM25-only."""
        if not HAS_SQLITE_VEC:
            return False
        try:  # pragma: no cover - phụ thuộc extension của môi trường
            await self.db.enable_load_extension(True)
            await sqlite_vec.load(self.db)  # type: ignore[union-attr]
            await self.db.enable_load_extension(False)
            return True
        except Exception:
            return False

    async def close(self) -> None:
        await self.db.close()

    # ---------- sessions ----------
    async def get_or_create_session(
        self, session_key: str, chat_id: int = 0, topic_id: int = 0
    ) -> dict:
        ts = now_iso()
        await self.db.execute(
            "INSERT OR IGNORE INTO sessions(session_key, chat_id, topic_id,"
            " created_at, updated_at) VALUES (?,?,?,?,?)",
            (session_key, chat_id, topic_id, ts, ts),
        )
        await self.db.commit()
        cur = await self.db.execute(
            "SELECT * FROM sessions WHERE session_key=?", (session_key,)
        )
        row = await cur.fetchone()
        return dict(row)

    async def close_session(self, session_key: str) -> None:
        """Chốt phiên (thiết kế 16.0): cắt history bằng summary pointer,
        giữ nguyên dữ liệu thô để truy vết. Lượt sau bắt đầu sạch."""
        cur = await self.db.execute(
            "SELECT COALESCE(MAX(id),0) AS m FROM messages WHERE session_key=?",
            (session_key,),
        )
        row = await cur.fetchone()
        last_id = int(row["m"]) if row else 0
        ts = now_iso()
        await self.db.execute(
            "UPDATE sessions SET closed_at=?, summary_upto_id=?, flush_upto_id=?,"
            " updated_at=? WHERE session_key=?",
            (ts, last_id, last_id, ts, session_key),
        )
        await self.db.commit()
        await self.log_trajectory(session_key, "session_closed", {"upto_id": last_id})

    async def set_summary(self, session_key: str, summary: str, upto_id: int) -> None:
        await self.db.execute(
            "UPDATE sessions SET summary=?, summary_upto_id=?, updated_at=?"
            " WHERE session_key=?",
            (summary, upto_id, now_iso(), session_key),
        )
        await self.db.commit()

    # ---------- messages (episodic) ----------
    async def append_message(
        self, session_key: str, role: str, content: str, meta: Optional[dict] = None
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO messages(session_key, role, content, content_nodau,"
            " meta, created_at) VALUES (?,?,?,?,?,?)",
            (
                session_key,
                role,
                content,
                fold_vi(content),
                json.dumps(meta or {}, ensure_ascii=False),
                now_iso(),
            ),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def recent_messages(
        self, session_key: str, limit: int = 60, after_id: int = 0
    ) -> list[dict]:
        cur = await self.db.execute(
            "SELECT id, role, content, created_at FROM messages"
            " WHERE session_key=? AND id>? AND role IN ('user','assistant')"
            " ORDER BY id DESC LIMIT ?",
            (session_key, after_id, limit),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        rows.reverse()
        return rows

    async def get_message(self, message_id: int) -> Optional[dict]:
        cur = await self.db.execute(
            "SELECT * FROM messages WHERE id=?", (message_id,)
        )
        row = await cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["meta"] = json.loads(d.get("meta") or "{}")
        return d

    # ---------- facts (semantic, bi-temporal) ----------
    async def add_fact(
        self,
        fact: str,
        subject: str = "",
        salience: float = 0.5,
        source_msg_id: Optional[int] = None,
        source: str = "",
        supersedes: Optional[list[int]] = None,
    ) -> int:
        """Thêm fact mới; các fact trong ``supersedes`` bị đóng vòng đời
        (valid_to = now, superseded_by = fact mới) — không bị xóa."""
        ts = now_iso()
        cur = await self.db.execute(
            "INSERT INTO memory_facts(subject, fact, fact_nodau, salience,"
            " valid_from, source_msg_id, source, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (subject, fact, fold_vi(fact), salience, ts, source_msg_id, source, ts),
        )
        new_id = int(cur.lastrowid)
        for old_id in supersedes or []:
            await self.db.execute(
                "UPDATE memory_facts SET valid_to=?, superseded_by=?"
                " WHERE id=? AND valid_to IS NULL",
                (ts, new_id, old_id),
            )
        await self.db.commit()
        return new_id

    async def active_facts(self, limit: int = 200) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM memory_facts WHERE valid_to IS NULL"
            " ORDER BY salience DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_fact(self, fact_id: int) -> Optional[dict]:
        cur = await self.db.execute(
            "SELECT * FROM memory_facts WHERE id=?", (fact_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    # ---------- recall (hybrid: FTS/BM25 chính, vector optional) ----------
    async def recall(
        self,
        query: str,
        limit: int = 8,
        exclude_session: Optional[str] = None,
    ) -> list[dict]:
        """Tìm ký ức liên quan: facts đang hiệu lực + đoạn hội thoại cũ.

        Trả về bản ghi nguyên văn (session search kiểu Hermes — không
        tóm tắt bằng LLM). Vector là đường nâng cấp sau cùng interface
        này khi có embedder; bản Phase 1 là BM25/FTS.
        """
        if not query.strip():
            return []
        fts = _fts_query(query)
        hits: dict[str, dict] = {}

        cur = await self.db.execute(
            "SELECT f.id AS fid, f.subject, f.fact, f.salience,"
            " bm25(facts_fts) AS rank"
            " FROM facts_fts JOIN memory_facts f ON f.id = facts_fts.rowid"
            " WHERE facts_fts MATCH ? AND f.valid_to IS NULL"
            " ORDER BY rank LIMIT ?",
            (fts, limit),
        )
        for r in await cur.fetchall():
            d = dict(r)
            key = f"fact:{d['fid']}"
            hits[key] = {
                "source": "fact",
                "id": d["fid"],
                "text": (f"[{d['subject']}] " if d["subject"] else "") + d["fact"],
                "score": float(d["salience"]) + 1.0 / (1.0 + abs(float(d["rank"]))),
            }

        sql = (
            "SELECT m.id AS mid, m.session_key, m.role, m.content,"
            " bm25(messages_fts) AS rank"
            " FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid"
            " WHERE messages_fts MATCH ?"
        )
        params: list[Any] = [fts]
        if exclude_session:
            sql += " AND m.session_key <> ?"
            params.append(exclude_session)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        cur = await self.db.execute(sql, params)
        for r in await cur.fetchall():
            d = dict(r)
            key = f"message:{d['mid']}"
            hits[key] = {
                "source": "message",
                "id": d["mid"],
                "text": d["content"],
                "score": 1.0 / (1.0 + abs(float(d["rank"]))),
            }

        merged = sorted(hits.values(), key=lambda h: h["score"], reverse=True)
        return merged[:limit]

    # ---------- tasks (working memory) ----------
    async def create_task(
        self, task_id: str, session_key: str, title: str, steps: list[str]
    ) -> None:
        ts = now_iso()
        await self.db.execute(
            "INSERT INTO tasks(id, session_key, title, status, plan_json,"
            " created_at, updated_at) VALUES (?,?,?,'running',?,?,?)",
            (task_id, session_key, title, json.dumps(steps, ensure_ascii=False), ts, ts),
        )
        for i, step in enumerate(steps):
            await self.db.execute(
                "INSERT INTO task_steps(task_id, idx, title, updated_at)"
                " VALUES (?,?,?,?)",
                (task_id, i, step, ts),
            )
        await self.db.commit()

    async def update_step(
        self, task_id: str, idx: int, status: str, detail: str = ""
    ) -> None:
        await self.db.execute(
            "UPDATE task_steps SET status=?, detail=?, updated_at=?"
            " WHERE task_id=? AND idx=?",
            (status, detail, now_iso(), task_id, idx),
        )
        await self.db.commit()

    async def finish_task(
        self, task_id: str, status: str, result: str = "", error: str = ""
    ) -> None:
        await self.db.execute(
            "UPDATE tasks SET status=?, result=?, error=?, updated_at=? WHERE id=?",
            (status, result, error, now_iso(), task_id),
        )
        await self.db.commit()

    async def get_task(self, task_id: str) -> Optional[dict]:
        cur = await self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        row = await cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        cur = await self.db.execute(
            "SELECT idx, title, status, detail FROM task_steps"
            " WHERE task_id=? ORDER BY idx",
            (task_id,),
        )
        d["steps"] = [dict(r) for r in await cur.fetchall()]
        return d

    # ---------- trajectory & ledger ----------
    async def log_trajectory(
        self, session_key: str, kind: str, payload: Optional[dict] = None
    ) -> None:
        """Trace chỉ vào trajectory — KHÔNG BAO GIỜ vào history/prompt."""
        try:
            await self.db.execute(
                "INSERT INTO trajectory(session_key, kind, payload, created_at)"
                " VALUES (?,?,?,?)",
                (
                    session_key,
                    kind,
                    json.dumps(payload or {}, ensure_ascii=False, default=str),
                    now_iso(),
                ),
            )
            await self.db.commit()
        except Exception:
            pass  # log lỗi không được phép làm hỏng lượt chính

    async def append_ledger(
        self, target: str, action: str, content: str, detail: str = ""
    ) -> int:
        """Sổ cái append-only kèm SHA-256 (kiểu curator của Hermes, mục 4.4)."""
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        cur = await self.db.execute(
            "INSERT INTO ledger(target, action, sha256, detail, created_at)"
            " VALUES (?,?,?,?,?)",
            (target, action, digest, detail, now_iso()),
        )
        await self.db.commit()
        return int(cur.lastrowid)
