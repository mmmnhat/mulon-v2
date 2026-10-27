"""Phase 2 — hybrid recall (mục 4.2): hợp nhất vector/BM25 theo
trọng số 70/30 sau khi chuẩn hoá điểm, đánh chỉ mục lúc ghi, và
degrade sạch xuống BM25-only khi embedder lỗi."""

import pytest

from mulon.memory import fold_vi
from tests.conftest import open_memory

SESSION = "agent:main:telegram:dm:1:topic:0"


class MarkerEmbedder:
    """Embedder tất định cho test: 'phang' -> trục y (trực giao),
    'xyz' -> trục x, còn lại -> vector chéo."""

    name = "marker-stub"
    dim = 2

    def embed(self, texts):
        out = []
        for t in texts:
            folded = fold_vi(t or "")
            if "phang" in folded:
                out.append([0.0, 1.0])
            elif "xyz" in folded:
                out.append([1.0, 0.0])
            else:
                out.append([0.6, 0.8])
        return out


class CatEmbedder:
    """'mèo'/'cat' -> trục x; còn lại -> trục y."""

    name = "cat-stub"
    dim = 2

    def embed(self, texts):
        out = []
        for t in texts:
            folded = fold_vi(t or "")
            if "meo" in folded or "cat" in folded:
                out.append([1.0, 0.0])
            else:
                out.append([0.0, 1.0])
        return out


class BoomEmbedder:
    name = "boom"
    dim = 2

    def embed(self, texts):
        raise RuntimeError("embedder sập theo kịch bản test")


async def _open_vec(cfg, embedder):
    memory = await open_memory(cfg)
    ok = await memory.set_embedder(embedder)
    if not ok or not memory.vec_ready:
        await memory.close()
        pytest.skip(
            "sqlite-vec extension không khả dụng trên môi trường này "
            "(Apple libsqlite3 thiếu loadable extension hoặc sqlite-vec chưa nạp được)"
        )
    return memory


async def test_hybrid_merge_weights(cfg):
    memory = await _open_vec(cfg, MarkerEmbedder())
    # Fact V: chỉ vector tìm thấy (token 'abcxyzdef' không khớp FTS 'xyz').
    v_id = await memory.add_fact(
        "mã abcxyzdef của user", subject="", salience=0.0
    )
    # Fact B: chỉ BM25 tìm thấy (vector trực giao với truy vấn).
    b_id = await memory.add_fact(
        "xyz phang là mã đặt chỗ cũ", subject="", salience=0.0
    )
    hits = await memory.recall("xyz", limit=8)
    by_id = {h["id"]: h for h in hits if h["source"] == "fact"}
    assert v_id in by_id and b_id in by_id
    # Điểm hợp nhất đúng trọng số 70% vector / 30% BM25.
    assert by_id[v_id]["score_vec"] == pytest.approx(1.0)
    assert by_id[v_id]["score_bm25"] == 0.0
    assert by_id[v_id]["score"] == pytest.approx(0.7)
    assert by_id[b_id]["score_vec"] == pytest.approx(0.0, abs=1e-6)
    assert by_id[b_id]["score_bm25"] > 0.0
    assert by_id[b_id]["score"] == pytest.approx(
        0.3 * by_id[b_id]["score_bm25"]
    )
    # Nhờ trọng số vector cao hơn, fact vector thắng dù BM25 = 0.
    assert hits[0]["id"] == v_id
    # Thời gian recall được ghi vào trajectory kèm mode hybrid.
    cur = await memory.db.execute(
        "SELECT payload FROM trajectory WHERE kind='recall'"
        " ORDER BY id DESC LIMIT 1"
    )
    row = await cur.fetchone()
    assert row is not None and '"hybrid"' in row["payload"]
    await memory.close()


async def test_recall_degrades_when_embedder_fails(cfg):
    memory = await _open_vec(cfg, BoomEmbedder())
    fid = await memory.add_fact("User thích uống cà phê đen", subject="uống")
    # Embed lúc ghi lỗi -> không có vector, nhưng FTS vẫn tìm thấy.
    hits = await memory.recall("cà phê", limit=8)
    assert any(h["source"] == "fact" and h["id"] == fid for h in hits)
    cur = await memory.db.execute(
        "SELECT COUNT(*) AS n FROM trajectory WHERE kind='recall_degraded'"
    )
    row = await cur.fetchone()
    assert int(row["n"]) >= 1
    await memory.close()


async def test_index_at_write_time(cfg):
    memory = await _open_vec(cfg, CatEmbedder())
    fid = await memory.add_fact(
        "User nuôi một con mèo mun tên Miu", subject="thú cưng"
    )
    # Vector đã được ghi ngay lúc add_fact.
    cur = await memory.db.execute("SELECT COUNT(*) AS n FROM facts_vec")
    assert int((await cur.fetchone())["n"]) == 1
    # Truy vấn 'cat' không có token nào trùng fact -> FTS mù, vector thấy.
    hits = await memory.recall("cat", limit=8)
    fact_hits = [h for h in hits if h["source"] == "fact" and h["id"] == fid]
    assert fact_hits
    assert fact_hits[0]["score_bm25"] == 0.0
    assert fact_hits[0]["score_vec"] > 0.9

    # Message cũng được đánh chỉ mục lúc ghi.
    await memory.get_or_create_session(SESSION)
    await memory.append_message(SESSION, "user", "con mèo nhảy qua hàng rào")
    cur = await memory.db.execute("SELECT COUNT(*) AS n FROM messages_vec")
    assert int((await cur.fetchone())["n"]) == 1
    hits = await memory.recall("cat", limit=8)
    assert any(h["source"] == "message" for h in hits)
    await memory.close()
