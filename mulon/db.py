"""mulon.db — Tầng quản lý kết nối SQLite hiệu năng cao: Reader Pool + Writer Lock.

Hiện thực hóa đề xuất hiệu năng T-08 (docs/de-xuat-hieu-nang-2026-10-26.md, T-34):
- Tận dụng tối đa chế độ SQLite WAL (Write-Ahead Logging): 'Readers do not block
  writers, and writers do not block readers'.
- 1 Writer Connection duy nhất được bảo vệ bởi asyncio.Lock() để tuần tự hóa
  mọi câu lệnh GHI (INSERT, UPDATE, DELETE, DDL, COMMIT, ROLLBACK), loại bỏ
  hoàn toàn lỗi 'database is locked'.
- N Reader Connections trong asyncio.Queue (mặc định 4) mở chế độ query_only=ON,
  cho phép các tác vụ đọc (Mini App REST API, hybrid recall, bot queries) chạy
  đồng thời trên nhiều thread nền riêng biệt.
- Lớp SqliteWALPool bọc trong suốt (transparent wrapper), tương thích 100%
  với interface aiosqlite.Connection mà không làm gãy codebase hiện tại.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import re
import threading
import weakref
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional, Sequence

import aiosqlite

logger = logging.getLogger("mulon.db")

_ACTIVE_POOLS: weakref.WeakSet["SqliteWALPool"] = weakref.WeakSet()


def get_connection_thread(conn: Any) -> Optional[threading.Thread]:
    """Lấy thread worker thực sự điều khiển aiosqlite connection.
    - Ở aiosqlite >= 0.22: conn._thread (Connection chứa worker Thread).
    - Ở aiosqlite <= 0.20: conn (Connection kế thừa từ threading.Thread).
    """
    if conn is None:
        return None
    th = getattr(conn, "_thread", None)
    if th is not None and isinstance(th, threading.Thread):
        return th
    if isinstance(conn, threading.Thread):
        return conn
    return None


def _make_connection_daemon(conn: Any) -> None:
    """Thiết lập daemon=True cho worker thread trước khi start."""
    if conn is None:
        return
    th = getattr(conn, "_thread", None)
    if th is not None and isinstance(th, threading.Thread):
        try:
            if not th.is_alive():
                th.daemon = True
        except Exception:
            pass
    if isinstance(conn, threading.Thread):
        try:
            if not conn.is_alive():
                conn.daemon = True
        except Exception:
            pass


def _stop_connection_sync(conn: Any, timeout: float = 2.0) -> None:
    """Dừng triệt để worker thread của connection cả trên aiosqlite 0.20.x và >=0.22.x."""
    if conn is None:
        return

    # 1. Gọi stop() đồng bộ (aiosqlite >= 0.22.1)
    stop_fn = getattr(conn, "stop", None)
    if callable(stop_fn):
        try:
            stop_fn()
        except Exception as exc:
            logger.debug("conn.stop() error: %s", exc)

    # 2. Gọi _stop_running() đồng bộ (aiosqlite <= 0.20.x)
    stop_run_fn = getattr(conn, "_stop_running", None)
    if callable(stop_run_fn):
        try:
            stop_run_fn()
        except Exception as exc:
            logger.debug("conn._stop_running() error: %s", exc)

    # 3. Fallback: Đẩy sentinel trực tiếp vào transaction queue
    tx = getattr(conn, "_tx", None)
    if tx is not None and hasattr(tx, "put"):
        try:
            from aiosqlite.core import _STOP_RUNNING_SENTINEL  # type: ignore

            def _sentinel_cb():
                return _STOP_RUNNING_SENTINEL

            tx.put((None, _sentinel_cb))
        except Exception:
            pass

    # 4. Chờ join thread thật
    th = get_connection_thread(conn)
    if th is not None and hasattr(th, "join"):
        try:
            if th.is_alive():
                th.join(timeout=timeout)
        except Exception as exc:
            logger.debug("thread.join() error: %s", exc)


def close_all_pools() -> None:
    """Đóng khẩn cấp đồng bộ toàn bộ worker threads của mọi pool còn mở."""
    for pool in list(_ACTIVE_POOLS):
        try:
            pool.close_sync()
        except Exception:
            pass


atexit.register(close_all_pools)


_RE_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RE_LINE_COMMENT = re.compile(r"--[^\n]*")


def is_read_only_query(sql: str) -> bool:
    """Xác định nhanh một câu lệnh SQL có phải là câu lệnh CHỈ ĐỌC hay không.

    An toàn tuyệt đối: nếu phân vân hoặc không chắc, coi như câu lệnh GHI (trả False)
    để điều hướng sang Writer Connection có lock.
    """
    if not sql or not isinstance(sql, str):
        return False

    clean = _RE_BLOCK_COMMENT.sub(" ", sql)
    clean = _RE_LINE_COMMENT.sub(" ", clean).strip()
    if not clean:
        return False

    first_token = clean.split(None, 1)[0].upper()

    if first_token in ("SELECT", "EXPLAIN"):
        return True

    if first_token == "PRAGMA":
        # PRAGMA đọc: PRAGMA table_info(...), PRAGMA user_version, không có dấu '='
        return "=" not in clean

    if first_token == "WITH":
        # CTE có thể chứa INSERT/UPDATE/DELETE. Chỉ coi là đọc nếu không có các từ khoá ghi
        upper = clean.upper()
        write_keywords = (
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "REPLACE ",
            "DROP ",
            "ALTER ",
            "CREATE ",
        )
        if any(kw in upper for kw in write_keywords):
            return False
        return "SELECT " in upper

    return False


class PooledCursor:
    """Cursor bọc cursor thật của aiosqlite, tự động trả connection về Reader Pool."""

    def __init__(
        self,
        cursor: aiosqlite.Cursor,
        connection: aiosqlite.Connection,
        pool: "SqliteWALPool",
    ):
        self._cursor = cursor
        self._connection = connection
        self._pool = pool
        self._released = False

    def _release(self) -> None:
        if not self._released:
            self._released = True
            self._pool._return_reader(self._connection)

    def __del__(self) -> None:
        self._release()

    async def close(self) -> None:
        try:
            await self._cursor.close()
        finally:
            self._release()

    async def __aenter__(self) -> "PooledCursor":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def fetchone(self) -> Any:
        return await self._cursor.fetchone()

    async def fetchall(self) -> list[Any]:
        try:
            return await self._cursor.fetchall()
        finally:
            # Khi đã fetch toàn bộ rows vào bộ nhớ, có thể trả connection về pool ngay
            self._release()

    async def fetchmany(self, size: int = 1) -> list[Any]:
        return await self._cursor.fetchmany(size)

    def __aiter__(self) -> "PooledCursor":
        return self

    async def __anext__(self) -> Any:
        try:
            row = await self._cursor.fetchone()
        except Exception:
            self._release()
            raise

        if row is None:
            self._release()
            raise StopAsyncIteration
        return row

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> Optional[int]:
        return self._cursor.lastrowid

    @property
    def description(self) -> Any:
        return self._cursor.description

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class SqliteWALPool:
    """Engine SQLite WAL đa kết nối: 1 Writer Lock + N Readers Pool.

    Cung cấp giao thức tương thích aiosqlite.Connection để dùng như drop-in replacement.
    """

    def __init__(
        self,
        path: Path | str,
        pool_size: int = 4,
        busy_timeout_ms: int = 5000,
    ):
        self._path = Path(path)
        self._pool_size = max(0, pool_size)
        self._busy_timeout_ms = busy_timeout_ms
        self._writer: Optional[aiosqlite.Connection] = None
        self._write_lock = asyncio.Lock()
        self._readers: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue()
        self._all_readers: list[aiosqlite.Connection] = []
        self._closed = False
        self._row_factory: Any = aiosqlite.Row
        self._vec_ext_path: Optional[str] = None
        self._load_ext_enabled = False
        _ACTIVE_POOLS.add(self)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def pool_size(self) -> int:
        return len(self._all_readers)

    @property
    def row_factory(self) -> Any:
        return self._row_factory

    @row_factory.setter
    def row_factory(self, factory: Any) -> None:
        self._row_factory = factory
        if self._writer is not None:
            self._writer.row_factory = factory
        for r in self._all_readers:
            r.row_factory = factory

    @classmethod
    async def create(
        cls,
        path: Path | str,
        pool_size: int = 4,
        busy_timeout_ms: int = 5000,
    ) -> "SqliteWALPool":
        pool = cls(path, pool_size=pool_size, busy_timeout_ms=busy_timeout_ms)
        await pool.open()
        return pool

    async def open(self) -> None:
        """Khởi tạo kết nối Writer và các kết nối Reader."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Mở Writer Connection
        writer_conn = aiosqlite.connect(str(self._path))
        _make_connection_daemon(writer_conn)
        self._writer = await writer_conn
        _make_connection_daemon(self._writer)
        self._writer.row_factory = self._row_factory

        # Cấu hình WAL + Busy Timeout cho Writer
        await self._writer.execute("PRAGMA journal_mode=WAL;")
        await self._writer.execute("PRAGMA synchronous=NORMAL;")
        await self._writer.execute("PRAGMA foreign_keys=ON;")
        await self._writer.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms};")
        await self._writer.commit()

        # 2. Mở Reader Pool Connections (nếu pool_size > 0)
        for i in range(self._pool_size):
            try:
                reader_conn = aiosqlite.connect(str(self._path))
                _make_connection_daemon(reader_conn)
                r = await reader_conn
                _make_connection_daemon(r)
                r.row_factory = self._row_factory
                await r.execute("PRAGMA query_only=ON;")
                await r.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms};")
                await r.execute("PRAGMA foreign_keys=ON;")
                self._all_readers.append(r)
                self._readers.put_nowait(r)
            except Exception as exc:
                logger.warning(
                    "Không thể mở reader connection #%d cho %s: %s (chạy với pool thu hẹp)",
                    i,
                    self._path,
                    exc,
                )
                break

        logger.debug(
            "SqliteWALPool khởi tạo thành công: %s (1 writer, %d readers)",
            self._path.name,
            len(self._all_readers),
        )

    async def close(self) -> None:
        """Đóng sạch sẽ toàn bộ readers và writer."""
        if self._closed:
            return
        _ACTIVE_POOLS.discard(self)

        for r in list(self._all_readers):
            try:
                await r.close()
            except Exception as exc:
                logger.debug("Lỗi đóng reader: %s", exc)
                _stop_connection_sync(r, timeout=0.5)
        self._all_readers.clear()

        while not self._readers.empty():
            try:
                self._readers.get_nowait()
            except Exception:
                break

        if self._writer is not None:
            try:
                await self._writer.close()
            except Exception as exc:
                logger.debug("Lỗi đóng writer: %s", exc)
                _stop_connection_sync(self._writer, timeout=0.5)
            self._writer = None

        self._closed = True

    def close_sync(self) -> None:
        """Đóng khẩn cấp đồng bộ: ra lệnh dừng triệt để và join toàn bộ worker threads."""
        _ACTIVE_POOLS.discard(self)
        readers = list(getattr(self, "_all_readers", []))
        for r in readers:
            _stop_connection_sync(r, timeout=1.0)
        if hasattr(self, "_all_readers"):
            self._all_readers.clear()

        w = getattr(self, "_writer", None)
        if w is not None:
            _stop_connection_sync(w, timeout=1.0)
            self._writer = None

        self._closed = True

    def __del__(self) -> None:
        """Dọn dẹp an toàn các thread worker ngầm khi object bị GC."""
        self.close_sync()


    def _return_reader(self, conn: aiosqlite.Connection) -> None:
        """Đưa reader connection trở lại hàng đợi pool."""
        if not self._closed and conn in self._all_readers:
            self._readers.put_nowait(conn)

    @asynccontextmanager
    async def read_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Mượn một reader connection từ pool để thực thi câu lệnh đọc."""
        if self._closed:
            raise RuntimeError("SqliteWALPool đã đóng")

        conn: Optional[aiosqlite.Connection] = None
        # Thử lấy connection từ pool với timeout ngắn
        if not self._readers.empty():
            try:
                conn = self._readers.get_nowait()
            except Exception:
                conn = None

        if conn is None and self._all_readers:
            try:
                conn = await asyncio.wait_for(self._readers.get(), timeout=1.0)
            except (asyncio.TimeoutError, Exception):
                conn = None

        # Degrade an toàn: Nếu pool rỗng/bận quá lâu, fallback tạm sang writer
        if conn is None:
            if self._writer is None:
                raise RuntimeError("Writer connection không khả dụng")
            yield self._writer
            return

        try:
            yield conn
        finally:
            self._return_reader(conn)

    @asynccontextmanager
    async def write_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Mượn writer connection với asyncio.Lock để tuần tự hóa các lệnh ghi."""
        if self._closed or self._writer is None:
            raise RuntimeError("SqliteWALPool đã đóng hoặc chưa mở")

        async with self._write_lock:
            yield self._writer

    # ---------- Giao diện tương thích aiosqlite.Connection ----------

    async def execute(
        self, sql: str, parameters: Any = None
    ) -> aiosqlite.Cursor | PooledCursor:
        """Thực thi câu lệnh SQL, tự động điều hướng:
        - Câu lệnh ĐỌC (SELECT...): Mượn reader từ pool, chạy song song.
        - Câu lệnh GHI (INSERT, UPDATE...): Chạy trên writer với lock an toàn.
        """
        if self._closed or self._writer is None:
            raise RuntimeError("SqliteWALPool đã đóng")

        if is_read_only_query(sql) and self._all_readers:
            # Lấy reader từ pool
            conn: Optional[aiosqlite.Connection] = None
            if not self._readers.empty():
                try:
                    conn = self._readers.get_nowait()
                except Exception:
                    conn = None

            if conn is not None:
                try:
                    cur = await conn.execute(sql, parameters)
                    return PooledCursor(cur, conn, self)
                except Exception:
                    self._return_reader(conn)
                    raise

            # Nếu pool đang bận hết, thử chờ 0.5s
            try:
                conn = await asyncio.wait_for(self._readers.get(), timeout=0.5)
            except (asyncio.TimeoutError, Exception):
                conn = None

            if conn is not None:
                try:
                    cur = await conn.execute(sql, parameters)
                    return PooledCursor(cur, conn, self)
                except Exception:
                    self._return_reader(conn)
                    raise

        # Lệnh GHI hoặc fallback
        async with self._write_lock:
            return await self._writer.execute(sql, parameters)

    async def execute_fetchall(
        self, sql: str, parameters: Any = None
    ) -> list[Any]:
        """Thực thi câu lệnh SQL và nạp toàn bộ dòng kết quả trong 1 bước worker-thread
        duy nhất (tương thích aiosqlite.Connection.execute_fetchall), giải phóng ngay
        reader connection về pool mà không giữ qua nhiều vòng lặp event loop."""
        if self._closed or self._writer is None:
            raise RuntimeError("SqliteWALPool đã đóng")

        params = [] if parameters is None else parameters
        if is_read_only_query(sql) and self._all_readers:
            async with self.read_connection() as rconn:
                rows = await rconn.execute_fetchall(sql, params)
                return list(rows)

        async with self._write_lock:
            rows = await self._writer.execute_fetchall(sql, params)
            return list(rows)

    async def executemany(
        self, sql: str, seq_of_parameters: Sequence[Any]
    ) -> aiosqlite.Cursor:
        """Thực thi hàng loạt (luôn chạy trên Writer có lock)."""
        if self._closed or self._writer is None:
            raise RuntimeError("SqliteWALPool đã đóng")

        async with self._write_lock:
            return await self._writer.executemany(sql, seq_of_parameters)

    async def executescript(self, script: str) -> aiosqlite.Cursor:
        """Thực thi kịch bản SQL (luôn chạy trên Writer có lock)."""
        if self._closed or self._writer is None:
            raise RuntimeError("SqliteWALPool đã đóng")

        async with self._write_lock:
            return await self._writer.executescript(script)

    async def commit(self) -> None:
        """Commit giao dịch trên Writer."""
        if self._closed or self._writer is None:
            raise RuntimeError("SqliteWALPool đã đóng")

        async with self._write_lock:
            await self._writer.commit()

    async def rollback(self) -> None:
        """Rollback giao dịch trên Writer."""
        if self._closed or self._writer is None:
            raise RuntimeError("SqliteWALPool đã đóng")

        async with self._write_lock:
            await self._writer.rollback()

    async def cursor(self) -> aiosqlite.Cursor:
        """Tạo cursor trên Writer."""
        if self._closed or self._writer is None:
            raise RuntimeError("SqliteWALPool đã đóng")

        return await self._writer.cursor()

    async def enable_load_extension(self, enabled: bool) -> None:
        """Bật/tắt nạp dynamic extension trên Writer và tất cả Readers."""
        if self._closed or self._writer is None:
            raise RuntimeError("SqliteWALPool đã đóng")

        self._load_ext_enabled = enabled
        await self._writer.enable_load_extension(enabled)
        for r in self._all_readers:
            try:
                await r.enable_load_extension(enabled)
            except Exception as exc:
                logger.debug("Lỗi enable_load_extension trên reader: %s", exc)

    async def load_extension(self, path: str) -> None:
        """Nạp dynamic extension trên Writer và tất cả Readers."""
        if self._closed or self._writer is None:
            raise RuntimeError("SqliteWALPool đã đóng")

        self._vec_ext_path = path
        await self._writer.load_extension(path)
        for r in self._all_readers:
            try:
                await r.load_extension(path)
            except Exception as exc:
                logger.debug("Lỗi load_extension trên reader: %s", exc)

    @property
    def total_changes(self) -> int:
        if self._writer is None:
            return 0
        return self._writer.total_changes
