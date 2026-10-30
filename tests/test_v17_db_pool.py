"""Kiểm thử tầng quản lý kết nối SQLite WAL Pool (T-34)."""

import asyncio
import tempfile
from pathlib import Path

import aiosqlite
import pytest

from mulon.db import SqliteWALPool, is_read_only_query


def test_is_read_only_query():
    assert is_read_only_query("SELECT * FROM facts") is True
    assert is_read_only_query("select count(*) from sessions") is True
    assert is_read_only_query("  EXPLAIN QUERY PLAN SELECT 1") is True
    assert is_read_only_query("/* comment */ SELECT id FROM goals") is True
    assert is_read_only_query("-- line comment\nSELECT id FROM goals") is True
    assert is_read_only_query("PRAGMA table_info(facts)") is True
    assert is_read_only_query("PRAGMA user_version") is True

    # Write queries
    assert is_read_only_query("INSERT INTO facts(fact) VALUES ('test')") is False
    assert is_read_only_query("UPDATE goals SET status='done'") is False
    assert is_read_only_query("DELETE FROM sessions WHERE id=1") is False
    assert is_read_only_query("PRAGMA journal_mode=WAL") is False
    assert is_read_only_query("CREATE TABLE t(id INT)") is False
    assert is_read_only_query("DROP TABLE t") is False
    assert is_read_only_query("BEGIN IMMEDIATE") is False
    assert is_read_only_query("COMMIT") is False
    assert is_read_only_query("") is False
    assert is_read_only_query(None) is False  # type: ignore


@pytest.mark.asyncio
async def test_pool_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_pool.db"
        pool = await SqliteWALPool.create(db_path, pool_size=3)

        assert pool.pool_size == 3
        assert pool.path == db_path

        # Tạo bảng qua executescript
        await pool.executescript(
            "CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT);"
        )

        # Ghi qua execute
        await pool.execute("INSERT INTO items(name) VALUES (?)", ("item_1",))
        await pool.execute("INSERT INTO items(name) VALUES (?)", ("item_2",))
        await pool.commit()

        # Đọc qua execute
        cur = await pool.execute("SELECT name FROM items ORDER BY id")
        rows = await cur.fetchall()
        assert len(rows) == 2
        assert rows[0]["name"] == "item_1"
        assert rows[1]["name"] == "item_2"

        # Đọc qua read_connection context manager
        async with pool.read_connection() as rconn:
            rcur = await rconn.execute("SELECT COUNT(*) AS c FROM items")
            rrow = await rcur.fetchone()
            assert rrow["c"] == 2

        # Ghi qua write_connection context manager
        async with pool.write_connection() as wconn:
            await wconn.execute("INSERT INTO items(name) VALUES (?)", ("item_3",))
            await wconn.commit()

        cur2 = await pool.execute("SELECT COUNT(*) AS c FROM items")
        row2 = await cur2.fetchone()
        assert row2["c"] == 3

        await pool.close()
        assert pool._closed is True


@pytest.mark.asyncio
async def test_pool_concurrency_no_database_locked():
    """Chạy đồng thời nhiều readers và writers, bảo đảm không bị 'database is locked'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_concurrency.db"
        pool = await SqliteWALPool.create(db_path, pool_size=4)

        await pool.execute("CREATE TABLE counter(id INTEGER PRIMARY KEY, val INT);")
        await pool.execute("INSERT INTO counter(val) VALUES (0);")
        await pool.commit()

        async def reader_task(task_id: int):
            for _ in range(20):
                cur = await pool.execute("SELECT val FROM counter WHERE id=1")
                row = await cur.fetchone()
                assert row is not None
                await asyncio.sleep(0.001)

        async def writer_task(task_id: int):
            for _ in range(15):
                await pool.execute("UPDATE counter SET val = val + 1 WHERE id=1")
                await pool.commit()
                await asyncio.sleep(0.002)

        # Chạy 8 readers và 4 writers đồng thời
        readers = [reader_task(i) for i in range(8)]
        writers = [writer_task(i) for i in range(4)]
        await asyncio.gather(*readers, *writers)

        cur = await pool.execute("SELECT val FROM counter WHERE id=1")
        final_row = await cur.fetchone()
        assert final_row["val"] == 15 * 4

        await pool.close()


@pytest.mark.asyncio
async def test_pool_daemon_threads_and_gc_cleanup():
    """T-39.1: Khắc phục aiosqlite threads treo — đảm bảo writer và reader connections đều là daemon threads."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_daemon.db"
        pool = await SqliteWALPool.create(db_path, pool_size=3)

        assert pool._writer is not None
        assert pool._writer.daemon is True
        for r in pool._all_readers:
            assert r.daemon is True

        # Test safe __del__ without raising error
        pool.__del__()

        await pool.close()
        assert pool._closed is True
