"""Ký ức bi-temporal: fact bị thay thế thì đóng vòng đời chứ không xóa;
recall chỉ trả fact đang hiệu lực + đoạn chat nguyên văn; ledger có chuỗi hash."""

import hashlib

from mulon.memory import fold_vi
from tests.conftest import open_memory

SESSION = "agent:main:telegram:dm:1:topic:0"


def test_fold_vi():
    assert fold_vi("Cà phê Đắk Lắk") == "ca phe dak lak"


async def test_fact_supersession_bitemporal(cfg):
    memory = await open_memory(cfg)
    old_id = await memory.add_fact("User thích uống trà đá", subject="uống")
    hits = await memory.recall("trà đá")
    assert any(h["source"] == "fact" and h["id"] == old_id for h in hits)

    new_id = await memory.add_fact(
        "User thích uống cà phê đen", subject="uống", supersedes=[old_id]
    )
    old = await memory.get_fact(old_id)
    assert old["valid_to"] is not None
    assert old["superseded_by"] == new_id

    active = await memory.active_facts()
    assert [f["id"] for f in active] == [new_id]

    # Recall tìm được fact mới cả khi gõ không dấu, không trả fact đã chết.
    hits = await memory.recall("ca phe")
    fact_ids = [h["id"] for h in hits if h["source"] == "fact"]
    assert new_id in fact_ids and old_id not in fact_ids
    await memory.close()


async def test_recall_returns_verbatim_messages(cfg):
    memory = await open_memory(cfg)
    await memory.get_or_create_session(SESSION)
    await memory.append_message(SESSION, "user", "nhớ mua vé máy bay đi Đà Nẵng nhé")
    await memory.get_or_create_session("agent:main:telegram:dm:2:topic:0")
    hits = await memory.recall("vé máy bay Đà Nẵng")
    msg_hits = [h for h in hits if h["source"] == "message"]
    assert msg_hits and "vé máy bay đi Đà Nẵng" in msg_hits[0]["text"]
    await memory.close()


async def test_session_boundary_close(cfg):
    memory = await open_memory(cfg)
    await memory.get_or_create_session(SESSION)
    msg_id = await memory.append_message(SESSION, "user", "một tin nhắn")
    await memory.close_session(SESSION)
    session = await memory.get_or_create_session(SESSION)
    assert session["closed_at"] is not None
    assert session["summary_upto_id"] == msg_id
    assert session["flush_upto_id"] == msg_id
    await memory.close()


async def test_ledger_append_only_with_sha256(cfg):
    memory = await open_memory(cfg)
    id1 = await memory.append_ledger("a.txt", "write", "nội dung 1")
    id2 = await memory.append_ledger("a.txt", "edit", "nội dung 2")
    assert id2 > id1  # append-only: id tăng dần, không ghi đè
    cur = await memory.db.execute(
        "SELECT sha256 FROM ledger WHERE id=?", (id1,)
    )
    row = await cur.fetchone()
    assert row["sha256"] == hashlib.sha256("nội dung 1".encode()).hexdigest()
    await memory.close()
