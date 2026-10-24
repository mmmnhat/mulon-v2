"""Lớp ký ức: SQLite WAL + FTS5 + fact bi-temporal.

Ba lớp tách bạch theo thiết kế mục 4.1:
- Working memory  -> bảng tasks / task_steps (runtime state).
- Episodic        -> bảng messages + FTS5 (kèm cột gấp dấu tiếng Việt).
- Semantic        -> bảng memory_facts có vòng đời bi-temporal
  (valid_from / valid_to / superseded_by / source_msg_id, mượn schema
  Graphiti — Phụ lục 15.2): fact cũ bị thay thế chứ không bị xóa.

Recall (Phase 2, mục 4.2): hybrid thật — FTS/BM25 + vector sqlite-vec
hợp nhất theo trọng số (mặc định 70% vector / 30% BM25, điểm từng
nhánh chuẩn hoá về [0,1] trước khi trộn). Đánh chỉ mục LÚC GHI:
message/fact vừa ghi được embed ngay (best-effort, có timeout, lỗi
thì bỏ qua và consolidation backfill sau). Embedder vắng hoặc lỗi
-> recall degrade xuống BM25-only + ghi trajectory, không sập.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from .embeddings import normalize

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

-- ===== Phase 2: ký ức sống (mục 4.3, 4.4) =====

CREATE TABLE IF NOT EXISTS kv_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT ''
);

-- Sự kiện user sửa agent (mục 4.4 tầng 2): ghi NGAY trong lượt.
-- category theo taxonomy cố định: du_kien / quy_trinh / giong_format /
-- tool / tri_nho. severity='critical' khi đụng tiền bạc / an toàn.
CREATE TABLE IF NOT EXISTS corrections (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key      TEXT NOT NULL DEFAULT '',
    user_msg_id      INTEGER,
    original_request TEXT NOT NULL DEFAULT '',
    wrong_output     TEXT NOT NULL DEFAULT '',
    corrected        TEXT NOT NULL DEFAULT '',
    category         TEXT NOT NULL DEFAULT '',
    severity         TEXT NOT NULL DEFAULT 'normal',
    explicit         INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'recorded',
    lesson_fact_id   INTEGER,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_corrections_cat ON corrections(category, status);

-- ===== Phase 3: scheduler + goals/tracking (mục 7) =====

-- Việc hẹn giờ: cron 5 trường + múi giờ tường minh. Scheduler MẶC
-- ĐỊNH TẮT ở tầng main (chỉ chạy khi SCHEDULER_ENABLED=1) — bảng này
-- chỉ là dữ liệu, không tự nó sinh việc.
CREATE TABLE IF NOT EXISTS schedules (
    id          TEXT PRIMARY KEY,
    cron        TEXT NOT NULL,
    timezone    TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
    payload     TEXT NOT NULL DEFAULT '',
    session_key TEXT NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1,
    last_run_at TEXT DEFAULT '',
    next_run_at TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Mục tiêu dài hạn: chỉ 2 trạng thái theo thiết kế mục 16.6.
-- Goal KHÔNG bao giờ tự đóng chỉ vì 1 bước xong.
CREATE TABLE IF NOT EXISTS goals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    closed_at   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS goal_activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id    INTEGER NOT NULL REFERENCES goals(id),
    note       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_goal_activity ON goal_activity(goal_id, id);

-- Cam kết cụ thể (đặt chỗ, đơn hàng, hạn chót...), gắn goal hoặc độc lập.
CREATE TABLE IF NOT EXISTS tracked_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id    INTEGER REFERENCES goals(id),
    title      TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'open',
    due_at     TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracked_goal ON tracked_items(goal_id, status);

-- Digest của background review fork sau mỗi lượt (mục 4.3, pattern Hermes).
CREATE TABLE IF NOT EXISTS turn_digests (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key      TEXT NOT NULL DEFAULT '',
    user_msg_id      INTEGER,
    assistant_msg_id INTEGER,
    digest           TEXT NOT NULL DEFAULT '',
    facts_saved      INTEGER NOT NULL DEFAULT 0,
    correction_id    INTEGER,
    created_at       TEXT NOT NULL
);

-- ===== Phase 4: proactivity (mục 7) =====

-- Đề xuất chủ động do heartbeat sinh ra. Phase 4 CHỈ xếp hàng ở
-- trạng thái 'pending' — bề mặt Phase 6 mới trình cho user; không
-- dòng nào ở đây tự biến thành tin nhắn gửi đi.
CREATE TABLE IF NOT EXISTS proactive_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content    TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    topic      TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proactive_status
    ON proactive_notes(status, id);

-- ===== Phase 6: bề mặt group (mục 16) =====

-- Bài Feed đã đăng: map (chat, message) -> nội dung để reaction
-- trên đúng bài mới thành tín hiệu taste.
CREATE TABLE IF NOT EXISTS feed_posts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feed_posts_msg
    ON feed_posts(chat_id, message_id);

-- Tín hiệu taste: reaction của user trên bài Feed (mục 16.4).
CREATE TABLE IF NOT EXISTS feed_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL DEFAULT 0,
    post_message_id INTEGER NOT NULL,
    reaction        TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feed_signals_post
    ON feed_signals(post_message_id);

-- ===== 1.4.0: Feed chủ động (spec Feed 1.4, mục 10.1) =====

-- URL tư liệu NGOÀI đã trích trong từng bài Feed: nền của chống
-- trùng URL (7 ngày) và taste-theo-nguồn. content_hash = hash của
-- tư liệu tại thời điểm trích (để luật "hash đổi thì dùng lại
-- được 1 lần" kiểm được tất định).
CREATE TABLE IF NOT EXISTS feed_post_sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id      INTEGER NOT NULL,
    url          TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    fetched_at   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_feed_post_sources_url
    ON feed_post_sources(url);
CREATE INDEX IF NOT EXISTS idx_feed_post_sources_post
    ON feed_post_sources(post_id);

-- Cache tư liệu ngoài theo URL: hash đổi/mới + bản rút gọn đã cắt.
-- Chỉ là cache collector — tư liệu ngoài KHÔNG BAO GIỜ vào facts.
CREATE TABLE IF NOT EXISTS feed_material_cache (
    url          TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL DEFAULT '',
    fetched_at   TEXT NOT NULL DEFAULT '',
    payload      TEXT NOT NULL DEFAULT ''
);

-- Cấu hình Feed khi chạy: env chỉ là seed lần đầu, từ lần owner
-- đổi đầu tiên thì bảng này THẮNG env (spec Feed 1.4 mục 8.1,
-- điều chỉnh 0.2b: không có khóa 'enabled' — Feed luôn tự động).
CREATE TABLE IF NOT EXISTS feed_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

-- Thẻ ý tưởng (mục 16.5): tự hết hạn (mặc định 14 ngày), làm luôn
-- -> goal + task; trạng thái open/done/dismissed/expired.
CREATE TABLE IF NOT EXISTS idea_cards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open',
    goal_id     INTEGER,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ideas_status
    ON idea_cards(status, expires_at);

-- Catalog Library (mục 16.7): file agent tạo/lưu cho user.
-- path = đường dẫn gốc; trash_path = nơi đang nằm khi ở thùng rác.
CREATE TABLE IF NOT EXISTS library_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    kind             TEXT NOT NULL DEFAULT 'other',
    path             TEXT NOT NULL DEFAULT '',
    trash_path       TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'active',
    share_status     TEXT NOT NULL DEFAULT '',
    share_expires_at TEXT DEFAULT '',
    trashed_at       TEXT DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_path ON library_items(path);
CREATE INDEX IF NOT EXISTS idx_library_status
    ON library_items(status, id);
"""


async def _migrate_feed_14(db) -> None:
    """Migration 1.4.0: feed_posts thêm cột origin/topic.

    CREATE TABLE IF NOT EXISTS không thêm cột cho DB đã tồn tại
    (mọi DB từ 1.3 trở xuống) — kiểm PRAGMA rồi ALTER, idempotent.
    """
    cur = await db.execute("PRAGMA table_info(feed_posts)")
    cols = {row[1] for row in await cur.fetchall()}
    if "origin" not in cols:
        await db.execute(
            "ALTER TABLE feed_posts ADD COLUMN origin"
            " TEXT DEFAULT 'manual'")
    if "topic" not in cols:
        await db.execute(
            "ALTER TABLE feed_posts ADD COLUMN topic"
            " TEXT DEFAULT ''")
    await db.commit()


class Memory:
    """Cửa ngõ duy nhất tới DB. Mọi ghi/đọc ký ức đi qua đây."""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self.vector_enabled = False
        # Phase 2: embedder + đường vector. vector_enabled (Phase 1) chỉ
        # nói extension sqlite-vec nạp được; vec_ready mới là "hybrid
        # chạy thật" (extension + embedder + bảng vec đúng số chiều).
        self.embedder = None
        self.vec_ready = False
        self._vec_ext_loaded = False
        self.embed_timeout_s = 5.0
        self.recall_vector_weight = 0.7
        self.recall_bm25_weight = 0.3

    # ---------- mở / đóng ----------
    @classmethod
    async def open(cls, db_path: str | Path) -> "Memory":
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(str(path))
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA)
        await db.commit()
        await _migrate_feed_14(db)
        mem = cls(db)
        mem.vector_enabled = await mem._try_enable_vector()
        return mem

    async def _try_enable_vector(self) -> bool:
        """Nạp extension sqlite-vec nếu gói có mặt; không thì BM25-only.

        Lưu ý kỹ thuật: phải dùng `db.load_extension(loadable_path())`
        của aiosqlite — helper `sqlite_vec.load(conn)` chỉ hợp với
        sqlite3 đồng bộ, gọi trên aiosqlite sẽ không nạp được gì.
        """
        if not HAS_SQLITE_VEC:
            return False
        if self._vec_ext_loaded:
            return True
        try:
            await self.db.enable_load_extension(True)
            await self.db.load_extension(sqlite_vec.loadable_path())  # type: ignore[union-attr]
            await self.db.enable_load_extension(False)
            self._vec_ext_loaded = True
            return True
        except Exception:
            return False

    # ---------- embedder & bảng vector (Phase 2) ----------
    async def set_embedder(self, embedder) -> bool:
        """Gắn embedder và dựng bảng vec0 đúng số chiều.

        Trả True khi đường hybrid sẵn sàng. Mọi lỗi (thiếu extension,
        lệch số chiều với DB cũ) đều degrade sạch: giữ BM25-only.
        """
        self.embedder = embedder
        self.vec_ready = False
        if embedder is None:
            return False
        if not await self._try_enable_vector():
            return False
        try:
            stored_dim = await self.kv_get("vec_dim")
            if stored_dim and int(stored_dim) != int(embedder.dim):
                await self.log_trajectory(
                    "", "vector_dim_mismatch",
                    {"stored": stored_dim, "embedder": int(embedder.dim)},
                )
                return False
            dim = int(embedder.dim)
            await self.db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS messages_vec "
                f"USING vec0(embedding float[{dim}])"
            )
            await self.db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS facts_vec "
                f"USING vec0(embedding float[{dim}])"
            )
            await self.db.commit()
            await self.kv_set("vec_dim", str(dim))
            self.vector_enabled = True
            self.vec_ready = True
            return True
        except Exception as exc:
            await self.log_trajectory("", "vector_setup_failed",
                                      {"error": str(exc)})
            return False

    async def _embed_texts(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Embed 1 lô text (đã chuẩn hoá đơn vị). Lỗi/timeout -> None."""
        if not self.vec_ready or self.embedder is None or not texts:
            return None
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self.embedder.embed, texts),
                timeout=self.embed_timeout_s,
            )
            vecs = [normalize(v) for v in raw]
            if any(len(v) != int(self.embedder.dim) for v in vecs):
                raise ValueError("embedder trả vector sai số chiều")
            return vecs
        except Exception as exc:
            await self.log_trajectory("", "embed_error", {"error": str(exc)})
            return None

    async def _vec_upsert(self, table: str, rowid: int, vec: list[float]) -> None:
        blob = sqlite_vec.serialize_float32(vec)  # type: ignore[union-attr]
        await self.db.execute(f"DELETE FROM {table} WHERE rowid=?", (rowid,))
        await self.db.execute(
            f"INSERT INTO {table}(rowid, embedding) VALUES (?,?)",
            (rowid, blob),
        )
        await self.db.commit()

    async def _index_message_embedding(self, msg_id: int, content: str) -> None:
        """Đánh chỉ mục vector cho message NGAY lúc ghi (mục 4.2)."""
        vecs = await self._embed_texts([content])
        if vecs:
            try:
                await self._vec_upsert("messages_vec", msg_id, vecs[0])
            except Exception as exc:
                await self.log_trajectory("", "embed_error",
                                          {"error": str(exc)})

    async def _index_fact_embedding(self, fact_id: int, subject: str,
                                    fact: str) -> None:
        text = f"{subject}: {fact}" if subject else fact
        vecs = await self._embed_texts([text])
        if vecs:
            try:
                await self._vec_upsert("facts_vec", fact_id, vecs[0])
            except Exception as exc:
                await self.log_trajectory("", "embed_error",
                                          {"error": str(exc)})

    async def backfill_embeddings(self, limit: int = 200) -> int:
        """Nhúng bù các message/fact còn thiếu vector (consolidation gọi)."""
        if not self.vec_ready:
            return 0
        done = 0
        try:
            cur = await self.db.execute(
                "SELECT m.id, m.content FROM messages m"
                " LEFT JOIN messages_vec v ON v.rowid = m.id"
                " WHERE v.rowid IS NULL ORDER BY m.id LIMIT ?",
                (limit,),
            )
            rows = [dict(r) for r in await cur.fetchall()]
            if rows:
                vecs = await self._embed_texts([r["content"] for r in rows])
                if vecs:
                    for r, v in zip(rows, vecs):
                        await self._vec_upsert("messages_vec", int(r["id"]), v)
                        done += 1
            cur = await self.db.execute(
                "SELECT f.id, f.subject, f.fact FROM memory_facts f"
                " LEFT JOIN facts_vec v ON v.rowid = f.id"
                " WHERE v.rowid IS NULL AND f.valid_to IS NULL"
                " ORDER BY f.id LIMIT ?",
                (limit,),
            )
            rows = [dict(r) for r in await cur.fetchall()]
            if rows:
                texts = [
                    f"{r['subject']}: {r['fact']}" if r["subject"] else r["fact"]
                    for r in rows
                ]
                vecs = await self._embed_texts(texts)
                if vecs:
                    for r, v in zip(rows, vecs):
                        await self._vec_upsert("facts_vec", int(r["id"]), v)
                        done += 1
        except Exception as exc:
            await self.log_trajectory("", "embed_error",
                                      {"error": f"backfill: {exc}"})
        return done

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
        msg_id = int(cur.lastrowid)
        # Đánh chỉ mục lúc ghi (mục 4.2): embed ngay, best-effort —
        # lỗi/timeout thì consolidation backfill sau, không chặn ghi.
        await self._index_message_embedding(msg_id, content)
        return msg_id

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
        await self._index_fact_embedding(new_id, subject, fact)
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

    # ---------- recall hybrid (Phase 2, mục 4.2) ----------
    async def _knn(self, table: str, query_vec: list[float],
                   k: int) -> list[tuple[int, float]]:
        """KNN trên bảng vec0 -> [(rowid, cosine)] với vector đã chuẩn hoá.

        sqlite-vec trả khoảng cách L2; với vector đơn vị:
        cos = 1 - d^2/2. Lỗi ở đây được recall() bắt và degrade.
        """
        blob = sqlite_vec.serialize_float32(query_vec)  # type: ignore[union-attr]
        cur = await self.db.execute(
            f"SELECT rowid, distance FROM {table}"
            f" WHERE embedding MATCH ? AND k = {int(k)} ORDER BY distance",
            (blob,),
        )
        out: list[tuple[int, float]] = []
        for rowid, dist in await cur.fetchall():
            d = float(dist)
            cos = max(0.0, min(1.0, 1.0 - d * d / 2.0))
            out.append((int(rowid), cos))
        return out

    async def recall(
        self,
        query: str,
        limit: int = 8,
        exclude_session: Optional[str] = None,
    ) -> list[dict]:
        """Hybrid recall: facts đang hiệu lực + đoạn hội thoại cũ.

        Hai nhánh FTS/BM25 và vector chạy rồi hợp nhất theo trọng số
        (mặc định 70% vector / 30% BM25); điểm BM25 được chuẩn hoá
        1/(1+|rank|) về (0,1], vector dùng cosine [0,1]. Embedder lỗi
        -> degrade BM25-only + trajectory. Không LLM rerank ở đây.
        Trả bản ghi nguyên văn (không tóm tắt bằng LLM).
        """
        if not query.strip():
            return []
        started = time.perf_counter()
        mode = "bm25"
        fts = _fts_query(query)
        cand: dict[str, dict] = {}

        def slot(key: str, base: dict) -> dict:
            if key not in cand:
                base.update({"score_vec": 0.0, "score_bm25": 0.0,
                             "salience": 0.0})
                cand[key] = base
            return cand[key]

        # --- nhánh BM25/FTS ---
        pool = max(limit * 2, 8)
        cur = await self.db.execute(
            "SELECT f.id AS fid, f.subject, f.fact, f.salience,"
            " f.created_at, bm25(facts_fts) AS rank"
            " FROM facts_fts JOIN memory_facts f ON f.id = facts_fts.rowid"
            " WHERE facts_fts MATCH ? AND f.valid_to IS NULL"
            " ORDER BY rank LIMIT ?",
            (fts, pool),
        )
        for r in await cur.fetchall():
            d = dict(r)
            h = slot(f"fact:{d['fid']}", {
                "source": "fact", "id": d["fid"],
                "text": (f"[{d['subject']}] " if d["subject"] else "")
                        + d["fact"],
                "created_at": d["created_at"],
            })
            h["score_bm25"] = 1.0 / (1.0 + abs(float(d["rank"])))
            h["salience"] = float(d["salience"])

        sql = (
            "SELECT m.id AS mid, m.session_key, m.role, m.content,"
            " m.created_at, bm25(messages_fts) AS rank"
            " FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid"
            " WHERE messages_fts MATCH ?"
        )
        params: list[Any] = [fts]
        if exclude_session:
            sql += " AND m.session_key <> ?"
            params.append(exclude_session)
        sql += " ORDER BY rank LIMIT ?"
        params.append(pool)
        cur = await self.db.execute(sql, params)
        for r in await cur.fetchall():
            d = dict(r)
            h = slot(f"message:{d['mid']}", {
                "source": "message", "id": d["mid"],
                "text": d["content"],
                "session_key": d["session_key"],
                "created_at": d["created_at"],
            })
            h["score_bm25"] = 1.0 / (1.0 + abs(float(d["rank"])))

        # --- nhánh vector (chỉ embed đúng 1 câu truy vấn — mục 4.2) ---
        if self.vec_ready and self.embedder is not None:
            try:
                qvecs = await asyncio.wait_for(
                    asyncio.to_thread(self.embedder.embed, [query]),
                    timeout=self.embed_timeout_s,
                )
                qvec = normalize(qvecs[0])
                if len(qvec) != int(self.embedder.dim):
                    raise ValueError("query vector sai số chiều")
                mode = "hybrid"
                for rid, cos in await self._knn("facts_vec", qvec, pool * 2):
                    fact = await self.get_fact(rid)
                    if fact is None or fact.get("valid_to") is not None:
                        continue
                    h = slot(f"fact:{rid}", {
                        "source": "fact", "id": rid,
                        "text": (f"[{fact['subject']}] " if fact["subject"]
                                 else "") + fact["fact"],
                        "created_at": fact["created_at"],
                    })
                    h["score_vec"] = max(h["score_vec"], cos)
                    h["salience"] = float(fact["salience"])
                for rid, cos in await self._knn("messages_vec", qvec,
                                                pool * 2):
                    msg = await self.get_message(rid)
                    if msg is None:
                        continue
                    if exclude_session and \
                            msg["session_key"] == exclude_session:
                        continue
                    h = slot(f"message:{rid}", {
                        "source": "message", "id": rid,
                        "text": msg["content"],
                        "session_key": msg["session_key"],
                        "created_at": msg["created_at"],
                    })
                    h["score_vec"] = max(h["score_vec"], cos)
            except Exception as exc:
                mode = "bm25_degraded"
                await self.log_trajectory(
                    "", "recall_degraded", {"error": str(exc)}
                )

        # --- hợp nhất theo trọng số ---
        wv, wb = self.recall_vector_weight, self.recall_bm25_weight
        for h in cand.values():
            score = wv * h["score_vec"] + wb * h["score_bm25"]
            if h["source"] == "fact":
                score += 0.05 * h["salience"]  # tie-break độ quan trọng
            h["score"] = score
        merged = sorted(cand.values(), key=lambda h: h["score"],
                        reverse=True)[:limit]
        ms = (time.perf_counter() - started) * 1000.0
        await self.log_trajectory(
            "", "recall",
            {"ms": round(ms, 2), "mode": mode, "hits": len(merged),
             "candidates": len(cand)},
        )
        return merged

    async def session_search(
        self,
        query: str,
        limit: int = 8,
        exclude_session: Optional[str] = None,
    ) -> list[dict]:
        """Tìm trong episodic: trả tin gốc NGUYÊN VĂN + session + thời
        gian (session search kiểu Hermes — không tóm tắt, không LLM)."""
        if not query.strip():
            return []
        fts = _fts_query(query)
        sql = (
            "SELECT m.id AS mid, m.session_key, m.role, m.content,"
            " m.created_at, bm25(messages_fts) AS rank"
            " FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid"
            " WHERE messages_fts MATCH ?"
        )
        params: list[Any] = [fts]
        if exclude_session:
            sql += " AND m.session_key <> ?"
            params.append(exclude_session)
        sql += " ORDER BY rank LIMIT ?"
        params.append(int(limit))
        cur = await self.db.execute(sql, params)
        return [
            {
                "message_id": int(r["mid"]),
                "session_key": r["session_key"],
                "role": r["role"],
                "content": r["content"],
                "created_at": r["created_at"],
            }
            for r in await cur.fetchall()
        ]

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

    async def list_tasks(self, limit: int = 20) -> list[dict]:
        """Các task gần nhất (mới nhất trước) — tab Việc của Mini App."""
        cur = await self.db.execute(
            "SELECT id, session_key, title, status, error, created_at,"
            " updated_at FROM tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]

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

    # ---------- kv_state (watermark, cấu hình bền) ----------
    async def kv_get(self, key: str) -> Optional[str]:
        cur = await self.db.execute(
            "SELECT value FROM kv_state WHERE key=?", (key,)
        )
        row = await cur.fetchone()
        return row["value"] if row else None

    async def kv_set(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO kv_state(key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self.db.commit()

    # ---------- corrections (mục 4.4 tầng 2) ----------
    async def add_correction(
        self,
        session_key: str,
        corrected: str,
        original_request: str = "",
        wrong_output: str = "",
        user_msg_id: Optional[int] = None,
        category: str = "",
        severity: str = "normal",
        explicit: bool = False,
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO corrections(session_key, user_msg_id,"
            " original_request, wrong_output, corrected, category,"
            " severity, explicit, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?, 'recorded', ?)",
            (session_key, user_msg_id, original_request, wrong_output,
             corrected, category, severity, 1 if explicit else 0, now_iso()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def get_correction(self, correction_id: int) -> Optional[dict]:
        cur = await self.db.execute(
            "SELECT * FROM corrections WHERE id=?", (correction_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def count_corrections(self, category: Optional[str] = None) -> int:
        """Đếm correction (trừ bản đã bị đánh dấu không hiệu lực)."""
        sql = "SELECT COUNT(*) AS n FROM corrections WHERE status <> 'ineffective'"
        params: list[Any] = []
        if category:
            sql += " AND category=?"
            params.append(category)
        cur = await self.db.execute(sql, params)
        row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def set_correction_lesson(self, correction_id: int,
                                    lesson_fact_id: int) -> None:
        await self.db.execute(
            "UPDATE corrections SET status='lesson_created', lesson_fact_id=?"
            " WHERE id=?",
            (lesson_fact_id, correction_id),
        )
        await self.db.commit()

    async def list_corrections(self, limit: int = 50) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM corrections ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in await cur.fetchall()]

    # ---------- turn digests (review fork, mục 4.3) ----------
    async def add_digest(
        self,
        session_key: str,
        user_msg_id: Optional[int],
        assistant_msg_id: Optional[int],
        digest: str,
        facts_saved: int = 0,
        correction_id: Optional[int] = None,
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO turn_digests(session_key, user_msg_id,"
            " assistant_msg_id, digest, facts_saved, correction_id,"
            " created_at) VALUES (?,?,?,?,?,?,?)",
            (session_key, user_msg_id, assistant_msg_id, digest,
             int(facts_saved), correction_id, now_iso()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def list_digests(self, session_key: Optional[str] = None,
                           limit: int = 50) -> list[dict]:
        if session_key:
            cur = await self.db.execute(
                "SELECT * FROM turn_digests WHERE session_key=?"
                " ORDER BY id DESC LIMIT ?",
                (session_key, limit),
            )
        else:
            cur = await self.db.execute(
                "SELECT * FROM turn_digests ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in await cur.fetchall()]

    # ---------- proactive notes (Phase 4, mục 7) ----------
    async def add_proactive_note(self, content: str, reason: str = "",
                                 topic: str = "") -> int:
        """Xếp 1 đề xuất chủ động vào hàng chờ (status='pending').

        Chỉ lưu DB — việc trình/gửi cho user thuộc bề mặt Phase 6.
        """
        ts = now_iso()
        cur = await self.db.execute(
            "INSERT INTO proactive_notes(content, reason, topic, status,"
            " created_at, updated_at) VALUES (?,?,?,'pending',?,?)",
            (content, reason, topic, ts, ts),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def list_proactive_notes(self, status: Optional[str] = "pending",
                                   limit: int = 50) -> list[dict]:
        if status:
            cur = await self.db.execute(
                "SELECT * FROM proactive_notes WHERE status=?"
                " ORDER BY id DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = await self.db.execute(
                "SELECT * FROM proactive_notes ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in await cur.fetchall()]

    async def set_proactive_note_status(self, note_id: int,
                                        status: str) -> bool:
        """status thuộc {pending, sent, dismissed}; khác -> không đổi."""
        if status not in {"pending", "sent", "dismissed"}:
            return False
        cur = await self.db.execute(
            "UPDATE proactive_notes SET status=?, updated_at=?"
            " WHERE id=?",
            (status, now_iso(), note_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ---------- schedules (Phase 3, mục 7) ----------
    async def create_schedule(self, schedule_id: str, cron: str,
                              timezone_name: str, payload: str,
                              session_key: str, next_run_at: str,
                              enabled: bool = True) -> dict:
        ts = now_iso()
        await self.db.execute(
            "INSERT INTO schedules(id, cron, timezone, payload,"
            " session_key, enabled, next_run_at, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (schedule_id, cron, timezone_name, payload, session_key,
             1 if enabled else 0, next_run_at, ts, ts),
        )
        await self.db.commit()
        return await self.get_schedule(schedule_id)  # type: ignore[return-value]

    async def get_schedule(self, schedule_id: str) -> Optional[dict]:
        cur = await self.db.execute(
            "SELECT * FROM schedules WHERE id=?", (schedule_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_schedules(self, enabled_only: bool = False) -> list[dict]:
        if enabled_only:
            cur = await self.db.execute(
                "SELECT * FROM schedules WHERE enabled=1 ORDER BY created_at"
            )
        else:
            cur = await self.db.execute(
                "SELECT * FROM schedules ORDER BY created_at"
            )
        return [dict(r) for r in await cur.fetchall()]

    async def due_schedules(self, now_utc_iso: str) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM schedules WHERE enabled=1 AND next_run_at!=''"
            " AND next_run_at<=? ORDER BY next_run_at",
            (now_utc_iso,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def mark_schedule_run(self, schedule_id: str, ran_at: str,
                                next_run_at: str) -> None:
        """Ghi lần chạy + lần kế tiếp (đặt TRƯỚC khi chạy để chống trùng)."""
        await self.db.execute(
            "UPDATE schedules SET last_run_at=?, next_run_at=?,"
            " updated_at=? WHERE id=?",
            (ran_at, next_run_at, now_iso(), schedule_id),
        )
        await self.db.commit()

    async def cancel_schedule(self, schedule_id: str) -> bool:
        cur = await self.db.execute(
            "UPDATE schedules SET enabled=0, updated_at=? WHERE id=?",
            (now_iso(), schedule_id),
        )
        await self.db.commit()
        return (cur.rowcount or 0) > 0

    async def set_schedule_enabled(self, schedule_id: str,
                                   enabled: bool) -> bool:
        """Bật/tắt 1 schedule tại chỗ (toggle ở tab Lịch Mini App).

        Bật lại KHÔNG tự tính next_run_at ở đây — vòng scheduler
        (khi đang chạy) sẽ quét theo hạn đã lưu; schedule chưa từng
        có next_run_at thì lần quét kế tiếp của SchedulerService
        xử lý như job mới.
        """
        cur = await self.db.execute(
            "UPDATE schedules SET enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, now_iso(), schedule_id),
        )
        await self.db.commit()
        return (cur.rowcount or 0) > 0

    # ---------- goals & tracked items (Phase 3, mục 7 + 16.6) ----------
    async def create_goal(self, title: str, description: str = "") -> dict:
        ts = now_iso()
        cur = await self.db.execute(
            "INSERT INTO goals(title, description, status, created_at,"
            " updated_at) VALUES (?,?, 'active', ?, ?)",
            (title, description, ts, ts),
        )
        await self.db.commit()
        return await self.get_goal(int(cur.lastrowid))  # type: ignore[return-value]

    async def get_goal(self, goal_id: int) -> Optional[dict]:
        cur = await self.db.execute(
            "SELECT * FROM goals WHERE id=?", (goal_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_goals(self, status: Optional[str] = None) -> list[dict]:
        if status:
            cur = await self.db.execute(
                "SELECT * FROM goals WHERE status=? ORDER BY id", (status,)
            )
        else:
            cur = await self.db.execute("SELECT * FROM goals ORDER BY id")
        return [dict(r) for r in await cur.fetchall()]

    async def log_goal_activity(self, goal_id: int, note: str) -> dict:
        ts = now_iso()
        cur = await self.db.execute(
            "INSERT INTO goal_activity(goal_id, note, created_at)"
            " VALUES (?,?,?)",
            (goal_id, note, ts),
        )
        await self.db.execute(
            "UPDATE goals SET updated_at=? WHERE id=?", (ts, goal_id)
        )
        await self.db.commit()
        return {"id": int(cur.lastrowid), "goal_id": goal_id, "note": note,
                "created_at": ts}

    async def list_goal_activity(self, goal_id: int,
                                 limit: int = 20) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM goal_activity WHERE goal_id=?"
            " ORDER BY id DESC LIMIT ?",
            (goal_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def close_goal(self, goal_id: int) -> Optional[dict]:
        ts = now_iso()
        cur = await self.db.execute(
            "UPDATE goals SET status='completed', closed_at=?,"
            " updated_at=? WHERE id=? AND status='active'",
            (ts, ts, goal_id),
        )
        await self.db.commit()
        if (cur.rowcount or 0) == 0:
            return None
        return await self.get_goal(goal_id)

    async def create_tracked_item(self, title: str, detail: str = "",
                                  goal_id: Optional[int] = None,
                                  due_at: str = "") -> dict:
        ts = now_iso()
        cur = await self.db.execute(
            "INSERT INTO tracked_items(goal_id, title, detail, status,"
            " due_at, created_at, updated_at) VALUES (?,?,?, 'open', ?, ?, ?)",
            (goal_id, title, detail, due_at, ts, ts),
        )
        await self.db.commit()
        item_id = int(cur.lastrowid)
        cur = await self.db.execute(
            "SELECT * FROM tracked_items WHERE id=?", (item_id,)
        )
        return dict(await cur.fetchone())  # type: ignore[arg-type]

    async def list_tracked_items(self, goal_id: Optional[int] = None,
                                 status: Optional[str] = None) -> list[dict]:
        sql = "SELECT * FROM tracked_items"
        conds, params = [], []
        if goal_id is not None:
            conds.append("goal_id=?")
            params.append(goal_id)
        if status:
            conds.append("status=?")
            params.append(status)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id"
        cur = await self.db.execute(sql, params)
        return [dict(r) for r in await cur.fetchall()]

    async def update_tracked_item(self, item_id: int,
                                  status: str) -> Optional[dict]:
        cur = await self.db.execute(
            "UPDATE tracked_items SET status=?, updated_at=? WHERE id=?",
            (status, now_iso(), item_id),
        )
        await self.db.commit()
        if (cur.rowcount or 0) == 0:
            return None
        cur = await self.db.execute(
            "SELECT * FROM tracked_items WHERE id=?", (item_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    # ---------- Phase 6: feed / ideas / library / bề mặt ký ức ----------

    async def recent_trajectory(self, kind: Optional[str] = None,
                                limit: int = 20) -> list[dict]:
        """Đọc ngược trajectory (mới nhất trước) — nền của /approvals
        và lịch sử hệ thống (mục 16.8). payload được parse sẵn."""
        if kind:
            cur = await self.db.execute(
                "SELECT * FROM trajectory WHERE kind=? ORDER BY id DESC"
                " LIMIT ?", (kind, limit),
            )
        else:
            cur = await self.db.execute(
                "SELECT * FROM trajectory ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        out = []
        for r in await cur.fetchall():
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload") or "{}")
            except Exception:
                d["payload"] = {}
            out.append(d)
        return out

    # --- feed ---
    async def add_feed_post(self, chat_id: int, message_id: int,
                            content: str, origin: str = "manual",
                            topic: str = "") -> int:
        cur = await self.db.execute(
            "INSERT INTO feed_posts(chat_id, message_id, content,"
            " origin, topic, created_at) VALUES (?,?,?,?,?,?)",
            (chat_id, message_id, content, origin, topic, now_iso()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def get_feed_post(self, chat_id: int,
                            message_id: int) -> Optional[dict]:
        cur = await self.db.execute(
            "SELECT * FROM feed_posts WHERE chat_id=? AND message_id=?",
            (chat_id, message_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def add_feed_signal(self, chat_id: int, post_message_id: int,
                              reaction: str) -> int:
        cur = await self.db.execute(
            "INSERT INTO feed_signals(chat_id, post_message_id, reaction,"
            " created_at) VALUES (?,?,?,?)",
            (chat_id, post_message_id, reaction, now_iso()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def feed_signal_counts(self) -> list[dict]:
        cur = await self.db.execute(
            "SELECT reaction, COUNT(*) AS n FROM feed_signals"
            " GROUP BY reaction ORDER BY n DESC, reaction"
        )
        return [dict(r) for r in await cur.fetchall()]

    # --- feed 1.4: bài gần đây / trần ngày / nguồn đã trích ---
    async def list_recent_feed_posts(self, limit: int = 10) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM feed_posts ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def count_feed_posts(self, origin: str, since_iso: str,
                               until_iso: str) -> int:
        """Đếm bài theo origin trong [since, until) — caller tính
        biên ngày ĐỊA PHƯƠNG rồi đổi sang UTC ISO."""
        cur = await self.db.execute(
            "SELECT COUNT(*) AS n FROM feed_posts WHERE origin=?"
            " AND created_at>=? AND created_at<?",
            (origin, since_iso, until_iso),
        )
        row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def add_feed_post_sources(self, post_id: int,
                                    items: list[dict]) -> None:
        """Ghi các URL tư liệu ngoài đã trích trong 1 bài (chống
        trùng + taste-theo-nguồn). items: {url, source,
        content_hash, fetched_at}."""
        for it in items or []:
            await self.db.execute(
                "INSERT INTO feed_post_sources(post_id, url,"
                " source, content_hash, fetched_at)"
                " VALUES (?,?,?,?,?)",
                (int(post_id), str(it.get("url") or ""),
                 str(it.get("source") or ""),
                 str(it.get("content_hash") or ""),
                 str(it.get("fetched_at") or "")),
            )
        await self.db.commit()

    async def recent_feed_source_uses(self, since_iso: str) -> list[dict]:
        """Mọi lần trích URL kể từ since (kèm ngày đăng bài) —
        nền của luật chống trùng URL 7 ngày."""
        cur = await self.db.execute(
            "SELECT s.url AS url, s.content_hash AS content_hash,"
            " p.created_at AS post_created_at"
            " FROM feed_post_sources s"
            " JOIN feed_posts p ON p.id = s.post_id"
            " WHERE p.created_at>=? ORDER BY p.id",
            (since_iso,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def feed_source_signal_stats(self, since_iso: str) -> list[dict]:
        """Reaction gộp THEO NGUỒN tư liệu (taste v2): join
        signals -> posts -> post_sources."""
        cur = await self.db.execute(
            "SELECT s.source AS source, fs.reaction AS reaction,"
            " COUNT(*) AS n FROM feed_signals fs"
            " JOIN feed_posts p ON p.chat_id = fs.chat_id"
            " AND p.message_id = fs.post_message_id"
            " JOIN feed_post_sources s ON s.post_id = p.id"
            " WHERE fs.created_at>=?"
            " GROUP BY s.source, fs.reaction",
            (since_iso,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def feed_topic_signal_stats(self, since_iso: str) -> list[dict]:
        """Reaction gộp THEO CHỦ ĐỀ bài (taste v2)."""
        cur = await self.db.execute(
            "SELECT p.topic AS topic, fs.reaction AS reaction,"
            " COUNT(*) AS n FROM feed_signals fs"
            " JOIN feed_posts p ON p.chat_id = fs.chat_id"
            " AND p.message_id = fs.post_message_id"
            " WHERE fs.created_at>=? AND p.topic != ''"
            " GROUP BY p.topic, fs.reaction",
            (since_iso,),
        )
        return [dict(r) for r in await cur.fetchall()]

    # --- feed 1.4: cache tư liệu + settings bền ---
    async def get_feed_material_cache(self, url: str) -> Optional[dict]:
        cur = await self.db.execute(
            "SELECT * FROM feed_material_cache WHERE url=?", (url,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def upsert_feed_material_cache(self, url: str,
                                         content_hash: str,
                                         payload: str) -> None:
        await self.db.execute(
            "INSERT INTO feed_material_cache(url, content_hash,"
            " fetched_at, payload) VALUES (?,?,?,?)"
            " ON CONFLICT(url) DO UPDATE SET"
            " content_hash=excluded.content_hash,"
            " fetched_at=excluded.fetched_at,"
            " payload=excluded.payload",
            (url, content_hash, now_iso(), payload),
        )
        await self.db.commit()

    async def get_feed_setting(self, key: str,
                               default: Optional[str] = None
                               ) -> Optional[str]:
        cur = await self.db.execute(
            "SELECT value FROM feed_settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default

    async def set_feed_setting(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO feed_settings(key, value, updated_at)"
            " VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET"
            " value=excluded.value, updated_at=excluded.updated_at",
            (key, str(value), now_iso()),
        )
        await self.db.commit()

    async def all_feed_settings(self) -> dict[str, str]:
        cur = await self.db.execute("SELECT key, value FROM feed_settings")
        return {r["key"]: r["value"] for r in await cur.fetchall()}

    async def sum_llm_tokens(self, purpose_prefix: str,
                             since_iso: str) -> int:
        """Tổng token (prompt+completion) của trajectory llm_call
        có purpose bắt đầu bằng prefix kể từ since — trần token
        của Feed đo bằng đường này (gateway không tính tiền)."""
        cur = await self.db.execute(
            "SELECT payload FROM trajectory WHERE kind='llm_call'"
            " AND created_at>=?", (since_iso,))
        total = 0
        for r in await cur.fetchall():
            try:
                p = json.loads(r["payload"] or "{}")
            except Exception:
                continue
            if str(p.get("purpose") or "").startswith(purpose_prefix):
                total += int(p.get("prompt_tokens") or 0)
                total += int(p.get("completion_tokens") or 0)
        return total

    async def kv_keys(self, prefix: str) -> list[str]:
        cur = await self.db.execute(
            "SELECT key FROM kv_state WHERE key LIKE ?",
            (prefix + "%",),
        )
        return [r["key"] for r in await cur.fetchall()]

    async def set_schedule_next_run(self, schedule_id: str,
                                    next_run_at: str) -> None:
        """Chỉ dời next_run_at (không đụng last_run_at) — Feed
        dùng khi hoãn lượt vì giờ yên lặng."""
        await self.db.execute(
            "UPDATE schedules SET next_run_at=?, updated_at=?"
            " WHERE id=?",
            (next_run_at, now_iso(), schedule_id),
        )
        await self.db.commit()

    async def update_schedule(self, schedule_id: str, cron: str,
                              timezone_name: str,
                              next_run_at: str) -> bool:
        """Đổi cron/múi giờ/lần kế tiếp tại chỗ (điều khiển Feed
        qua Mini App/chat dùng đường này cho job hệ thống)."""
        cur = await self.db.execute(
            "UPDATE schedules SET cron=?, timezone=?, next_run_at=?,"
            " enabled=1, updated_at=? WHERE id=?",
            (cron, timezone_name, next_run_at, now_iso(), schedule_id),
        )
        await self.db.commit()
        return (cur.rowcount or 0) > 0

    # --- ideas ---
    async def add_idea_card(self, title: str, description: str = "",
                            source: str = "",
                            expires_at: str = "") -> dict:
        ts = now_iso()
        cur = await self.db.execute(
            "INSERT INTO idea_cards(title, description, source, status,"
            " created_at, expires_at, updated_at)"
            " VALUES (?,?,?,'open',?,?,?)",
            (title, description, source, ts, expires_at or ts, ts),
        )
        await self.db.commit()
        return await self.get_idea_card(int(cur.lastrowid))  # type: ignore[return-value]

    async def get_idea_card(self, card_id: int) -> Optional[dict]:
        cur = await self.db.execute(
            "SELECT * FROM idea_cards WHERE id=?", (card_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_idea_cards(self, status: Optional[str] = "open",
                              limit: int = 50) -> list[dict]:
        if status:
            cur = await self.db.execute(
                "SELECT * FROM idea_cards WHERE status=? ORDER BY id"
                " LIMIT ?", (status, limit),
            )
        else:
            cur = await self.db.execute(
                "SELECT * FROM idea_cards ORDER BY id LIMIT ?", (limit,)
            )
        return [dict(r) for r in await cur.fetchall()]

    async def set_idea_card_status(self, card_id: int, status: str,
                                   goal_id: Optional[int] = None) -> bool:
        if status not in {"open", "done", "dismissed", "expired"}:
            return False
        cur = await self.db.execute(
            "UPDATE idea_cards SET status=?, goal_id=COALESCE(?, goal_id),"
            " updated_at=? WHERE id=?",
            (status, goal_id, now_iso(), card_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def expire_idea_cards(self, now: Optional[str] = None) -> list[dict]:
        """Thẻ open đã quá hạn -> expired. Trả các thẻ vừa hết hạn để
        bề mặt trả lời được "sao thẻ biến mất" (mục 16.5)."""
        now = now or now_iso()
        cur = await self.db.execute(
            "SELECT * FROM idea_cards WHERE status='open'"
            " AND expires_at<=?", (now,),
        )
        expired = [dict(r) for r in await cur.fetchall()]
        for card in expired:
            await self.set_idea_card_status(int(card["id"]), "expired")
        return expired

    # --- library ---
    async def add_library_item(self, name: str, kind: str, path: str,
                               source: str = "") -> dict:
        ts = now_iso()
        cur = await self.db.execute(
            "INSERT INTO library_items(name, kind, path, source, status,"
            " created_at, updated_at) VALUES (?,?,?,?,'active',?,?)",
            (name, kind, path, source, ts, ts),
        )
        await self.db.commit()
        return await self.get_library_item(int(cur.lastrowid))  # type: ignore[return-value]

    async def get_library_item(self, item_id: int) -> Optional[dict]:
        cur = await self.db.execute(
            "SELECT * FROM library_items WHERE id=?", (item_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_library_item_by_path(self, path: str) -> Optional[dict]:
        cur = await self.db.execute(
            "SELECT * FROM library_items WHERE path=? ORDER BY id DESC",
            (path,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_library_items(self, status: Optional[str] = "active",
                                 limit: int = 100) -> list[dict]:
        if status:
            cur = await self.db.execute(
                "SELECT * FROM library_items WHERE status=? ORDER BY id"
                " LIMIT ?", (status, limit),
            )
        else:
            cur = await self.db.execute(
                "SELECT * FROM library_items ORDER BY id LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in await cur.fetchall()]

    async def update_library_item(self, item_id: int, **fields) -> bool:
        allowed = {"name", "kind", "path", "trash_path", "source",
                   "status", "share_status", "share_expires_at",
                   "trashed_at"}
        clean = {k: v for k, v in fields.items() if k in allowed}
        if not clean:
            return False
        clean["updated_at"] = now_iso()
        cols = ", ".join(f"{k}=?" for k in clean)
        cur = await self.db.execute(
            f"UPDATE library_items SET {cols} WHERE id=?",
            (*clean.values(), item_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # --- forget (mục 16.11): tìm + vô hiệu, KHÔNG xóa cứng ---
    async def search_facts(self, topic: str, limit: int = 50,
                           active_only: bool = True) -> list[dict]:
        """Fact liên quan tới 1 chủ đề: khớp không dấu trên subject +
        nội dung. Quy mô cá nhân nên lọc trong bộ nhớ sau khi lấy các
        fact đang hiệu lực — chính xác quan trọng hơn tốc độ ở đây."""
        needle = fold_vi(topic or "")
        if not needle.strip():
            return []
        facts = await self.active_facts(limit=1000)
        if not active_only:
            cur = await self.db.execute(
                "SELECT * FROM memory_facts ORDER BY id DESC LIMIT 1000")
            facts = [dict(r) for r in await cur.fetchall()]
        out = []
        for f in facts:
            hay = fold_vi(f"{f.get('subject', '')} {f.get('fact', '')}")
            if needle in hay:
                out.append(f)
                if len(out) >= limit:
                    break
        return out

    async def forget_facts(self, fact_ids: list[int]) -> int:
        """Đóng vòng đời các fact (valid_to = now) — bản ghi vẫn còn
        để kiểm toán; đây là "quên" chứ không phải xóa dấu vết."""
        ts = now_iso()
        n = 0
        for fid in fact_ids:
            cur = await self.db.execute(
                "UPDATE memory_facts SET valid_to=? WHERE id=?"
                " AND valid_to IS NULL",
                (ts, int(fid)),
            )
            n += cur.rowcount or 0
        await self.db.commit()
        return n
