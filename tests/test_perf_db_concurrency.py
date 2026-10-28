"""Kiểm thử hiệu năng và độ chịu tải đồng thời của SQLite WAL Pool (T-34, T-08)."""

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from mulon.memory import Memory


@pytest.mark.asyncio
async def test_concurrent_read_during_heavy_write():
    """Kiểm chứng Reader Pool: reader không bị writer block khi writer đang ghi liên tục.

    Mục tiêu theo T-08: Readers do not block writers, and writers do not block readers.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "bench_wal.db"
        mem = await Memory.open(db_path, reader_pool_size=4)

        # Chèn sẵn một số dữ liệu
        for i in range(10):
            await mem.add_fact(fact=f"Seed fact {i}", subject="user", source="init")

        write_started = asyncio.Event()
        write_finished = asyncio.Event()

        async def heavy_writer():
            write_started.set()
            for i in range(100):
                await mem.add_fact(
                    fact=f"Heavy fact {i}", subject="user", source="bench"
                )
                await asyncio.sleep(0.001)
            write_finished.set()

        async def fast_reader(reader_id: int) -> float:
            await write_started.wait()
            t0 = time.perf_counter()
            facts = await mem.active_facts(limit=50)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert len(facts) >= 10
            return elapsed_ms

        writer_task = asyncio.create_task(heavy_writer())
        await write_started.wait()

        # Bắn 25 readers đồng thời trong lúc writer đang ghi
        latencies = await asyncio.gather(*(fast_reader(i) for i in range(25)))
        await writer_task

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]

        # Khẳng định hiệu năng: Readers chạy song song trên pool, độ trễ cực thấp
        assert avg_latency < 25.0, f"Average latency quá cao: {avg_latency:.2f}ms"
        assert max_latency < 60.0, f"Max latency quá cao: {max_latency:.2f}ms"

        await mem.close()


@pytest.mark.asyncio
async def test_stress_mixed_read_write_parallel():
    """Stress test: 30 tác vụ đọc và ghi xen kẽ đồng thời, không lỗi 'database is locked'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "stress_wal.db"
        mem = await Memory.open(db_path, reader_pool_size=3)

        async def reader_worker(worker_id: int):
            for _ in range(15):
                facts = await mem.active_facts(limit=20)
                assert isinstance(facts, list)
                await asyncio.sleep(0.001)

        async def writer_worker(worker_id: int):
            for i in range(10):
                await mem.add_fact(
                    fact=f"Worker {worker_id} fact {i}",
                    subject=f"worker_{worker_id}",
                    source="stress",
                )
                await asyncio.sleep(0.002)

        readers = [reader_worker(i) for i in range(15)]
        writers = [writer_worker(i) for i in range(15)]

        # Chạy đồng thời toàn bộ
        await asyncio.gather(*readers, *writers)

        final_facts = await mem.active_facts(limit=500)
        # 15 writers * 10 facts = 150 facts
        assert len(final_facts) == 150

        await mem.close()


@pytest.mark.asyncio
async def test_memory_context_managers():
    """Kiểm thử read_conn và write_conn context managers của Memory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "ctx_test.db"
        mem = await Memory.open(db_path, reader_pool_size=2)

        # Sử dụng write_conn tường minh
        async with mem.write_conn() as wconn:
            await wconn.execute(
                "INSERT INTO goals(title, description, status, created_at, updated_at)"
                " VALUES (?, ?, ?, '2026-10-28', '2026-10-28')",
                ("Test Goal", "Test Desc", "active"),
            )
            await wconn.commit()

        # Sử dụng read_conn tường minh
        async with mem.read_conn() as rconn:
            cur = await rconn.execute("SELECT title, status FROM goals")
            row = await cur.fetchone()
            assert row is not None
            assert row["title"] == "Test Goal"
            assert row["status"] == "active"

        await mem.close()
