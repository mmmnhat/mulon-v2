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
    """T-39.1: Khắc phục aiosqlite threads treo — đảm bảo writer/readers là daemon và close_sync/close_all_pools giải phóng sạch."""
    from mulon.db import close_all_pools, get_connection_thread

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_daemon.db"
        pool = await SqliteWALPool.create(db_path, pool_size=3)

        assert pool._writer is not None
        writer_th = get_connection_thread(pool._writer)
        reader_ths = [get_connection_thread(r) for r in pool._all_readers]

        assert writer_th is not None
        assert writer_th.daemon is True
        for rth in reader_ths:
            assert rth is not None
            assert rth.daemon is True

        # Test close_sync khẩn cấp đồng bộ
        pool.close_sync()
        assert pool._closed is True

        # Đợi thread thoát sau khi nhận STOP sentinel
        writer_th.join(timeout=2.0)
        assert not writer_th.is_alive()
        for rth in reader_ths:
            rth.join(timeout=2.0)
            assert not rth.is_alive()

        # Tạo pool mới và test close_all_pools
        db_path2 = Path(tmpdir) / "test_daemon2.db"
        pool2 = await SqliteWALPool.create(db_path2, pool_size=2)
        p2_writer_th = get_connection_thread(pool2._writer)
        p2_reader_ths = [get_connection_thread(r) for r in pool2._all_readers]
        assert p2_writer_th is not None
        assert p2_writer_th.daemon is True

        close_all_pools()
        assert pool2._closed is True
        p2_writer_th.join(timeout=2.0)
        assert not p2_writer_th.is_alive()
        for p2_rth in p2_reader_ths:
            if p2_rth is not None:
                p2_rth.join(timeout=2.0)
                assert not p2_rth.is_alive()


@pytest.mark.asyncio
async def test_pool_execute_fetchall_and_no_reader_leak_on_error():
    """Kiểm chứng execute_fetchall 1-hop trên Reader Pool và hoàn trả reader khi câu lệnh SQL lỗi."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fetchall.db"
        pool = await SqliteWALPool.create(db_path, pool_size=2)
        try:
            await pool.execute("CREATE TABLE notes(id INTEGER PRIMARY KEY, body TEXT);")
            for idx in range(5):
                await pool.execute("INSERT INTO notes(body) VALUES (?);", (f"note_{idx}",))
            await pool.commit()

            rows = await pool.execute_fetchall("SELECT body FROM notes ORDER BY id")
            assert [r["body"] for r in rows] == [f"note_{i}" for i in range(5)]
            assert pool._readers.qsize() == 2

            # Giữ bận 2 readers tạm thời để ép luồng chờ asyncio.wait_for, sau đó truyền SQL lỗi
            r1 = pool._readers.get_nowait()
            r2 = pool._readers.get_nowait()

            async def release_soon():
                await asyncio.sleep(0.02)
                pool._return_reader(r1)
                pool._return_reader(r2)

            rel_task = asyncio.create_task(release_soon())
            with pytest.raises(Exception):
                await pool.execute("SELECT * FROM bang_khong_ton_tai")
            await rel_task

            # Cả 2 readers đều phải trở về hàng đợi, không bị rò rỉ
            assert pool._readers.qsize() == 2
        finally:
            await pool.close()

