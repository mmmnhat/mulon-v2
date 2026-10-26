# Đề xuất kỹ thuật: Khảo sát & Phương án giải quyết nghẽn hiệu năng (T-08)

> **Tài liệu khảo sát theo yêu cầu T-08 trong `AGENT_TASKS.md` (Backlog Audit 26/10/2026)**
> **Người thực hiện:** Antigravity (Builder)  
> **Người duyệt:** Chủ dự án (mmmnhat)  
> **Quy định:** Tài liệu này CHỈ KHẢO SÁT VÀ ĐỀ XUẤT, KHÔNG TỰ TRIỂN KHAI CODE KHI CHƯA ĐƯỢC DUYỆT.

---

## 1. Điểm nghẽn A: Toàn bộ DB qua 1 connection `aiosqlite` (`mulon/memory.py`)

### 1.1. Hiện trạng & Bối cảnh
- `mulon/memory.py` mở một kết nối duy nhất:
  ```python
  db = await aiosqlite.connect(str(path))
  mem = cls(db)
  ```
- Toàn bộ các module trong hệ thống đều inject chung đối tượng `Memory` này:
  - Agent loop (lưu và đọc trajectory, memory facts, vector recall, BM25)
  - Scheduler / Goals / Topics / Library
  - Background workers (Consolidation, Idea generator, Feed auto runner)
  - WebApp Server / API REST của Mini App (đọc trạng thái, danh sách việc, approvals)
- **Cơ chế nội bộ của `aiosqlite`**: Mỗi `aiosqlite.Connection` chạy một luồng (thread) nền duy nhất (worker thread) với hàng đợi công việc tuần tự (`queue.Queue`). Bất kỳ truy vấn nào (kể cả SELECT đọc nhanh) cũng phải xếp hàng tuần tự qua thread này.

### 1.2. Phân tích rủi ro & Vấn đề hiệu năng
1. **Nghẽn Reader khi có Writer chạy lâu**:
   - Khi SQLite thực hiện một câu lệnh ghi dài (ví dụ: `executescript` migrate, batch insert facts, lưu trajectory lớn, hoặc hybrid search tính BM25/vector kết hợp transaction), thread worker của connection bị chiếm giữ.
   - Các request đọc tức thì từ Telegram UI hoặc Mini App (ví dụ: mở tab Việc, tải danh sách goals, load mini app profile) bị block hoàn toàn, dẫn đến UI lag, spinner quay dài trên điện thoại.
2. **Không tận dụng được chế độ SQLite WAL**:
   - SQLite WAL (Write-Ahead Logging) có ưu điểm cốt lõi: **"Readers do not block writers, and writers do not block readers"** (cho phép nhiều reader đọc đồng thời trong khi 1 writer đang ghi).
   - Tuy nhiên, việc ép tất cả qua 1 connection duy nhất làm vô hiệu hóa hoàn toàn lợi thế này của WAL.

### 1.3. Phương án đề xuất: Reader Pool + Dedicated Single Writer (WAL-safe)
SQLite có ràng buộc cứng: **Chỉ được phép có 1 transaction GHI tại một thời điểm** (nếu 2 connection cùng ghi sẽ gặp lỗi `sqlite3.OperationalError: database is locked`). Vì vậy, mô hình pool đối xứng đọc-ghi tự do là nguy hiểm.

**Mô hình chuẩn tối ưu cho SQLite WAL trong Async Python:**
1. **Một Writer Connection duy nhất (Single Writer)**:
   - Được bảo vệ bởi một `asyncio.Lock()` để tuần tự hóa các tác vụ ghi (INSERT, UPDATE, DELETE, Transaction).
   - Tránh hoàn toàn lỗi `database is locked`.
2. **Một Reader Pool gồm N connection (ví dụ: 3 - 5 connections)**:
   - Các kết nối chỉ thực hiện `SELECT` (Read-only hoặc mở với URI `file:...db?mode=ro`).
   - Các request đọc từ Mini App, WebApp server, search vector có thể mượn connection từ pool và chạy song song thật sự.
3. **Cơ chế nạp `sqlite-vec`**:
   - Vì `sqlite-vec` là dynamic extension được nạp theo connection (`load_extension`), mỗi connection trong Reader Pool khi khởi tạo cần chạy qua hàm nạp extension đồng bộ/bất đồng bộ một lần.

### 1.4. Rủi ro & Thách thức
- **Rủi ro vỡ tương thích API**: Hiện tại rất nhiều hàm trong `Memory` và test trực tiếp dùng `self.db.execute(...)` hoặc `async with self.db.cursor() as cur:`. Nếu đổi `self.db` thành pool mà không bọc adapter trong suốt sẽ làm gãy hàng chục module và ~450 tests.
- **Giải pháp chuyển đổi an toàn**:
  - Viết lớp bọc `SqliteWALEngine`: cung cấp `read_connection()` (context manager mượn reader) và `write_connection()` (mượn writer kèm lock).
  - Hoặc giai đoạn 1: Giữ nguyên `self.db` làm Writer, tạo thêm `self.reader_pool = asyncio.Queue()` cho các tác vụ SELECT nặng (hybrid search, Mini App data fetch).

### 1.5. Kế hoạch kiểm thử (Testing Strategy)
1. **Concurrency Benchmark (`tests/test_perf_db_concurrency.py`)**:
   - Giả lập 1 background task đang ghi 500 records trong 2 giây.
   - Đồng thời bắn 20 request đọc qua Mini App API.
   - Tiêu chí đạt: Thời gian phản hồi của request đọc giảm từ >2000ms xuống <20ms (P99 < 50ms).
2. **Stress Test & Race Condition**:
   - Chạy 50 tác vụ đọc-ghi xen kẽ đồng thời, kiểm tra không xuất hiện ngoại lệ `sqlite3.OperationalError: database is locked`.
   - Toàn bộ suite test hiện tại (457 test) phải pass 100%.

---

## 2. Điểm nghẽn B: `ClientSession` tạo mới mỗi request (`mulon/google_conn.py`)

### 2.1. Hiện trạng & Bối cảnh
- Trong `mulon/google_conn.py`:
  ```python
  async def _aiohttp_transport(method, url, params=None, json_body=None, headers=None):
      import aiohttp
      async with aiohttp.ClientSession() as session:
          async with session.request(...) as resp:
              ...
  ```
- Mỗi lần gọi `_aiohttp_transport` (đọc email, đọc lịch, lấy access token), một instance `aiohttp.ClientSession` mới được khởi tạo và đóng ngay lập tức.

### 2.2. Đánh giá mức độ sử dụng trong hệ thống
Khảo sát toàn bộ repo cho thấy:
1. **Google Connectors đời cũ (`GmailConnector`, `GCalendarConnector`)**:
   - Theo tài liệu kỹ thuật (`docs/technical-reference.md`), đường này là **LEGACY**, mặc định **TẮT**. Chỉ chạy khi người dùng bật cờ `GOOGLE_LEGACY_CONNECTORS=1`.
   - Đường kết nối Google chính thống hiện nay của MuLon là **MCP `google-workspace`** (chạy qua MCP Python SDK, độc lập hoàn toàn với `google_conn.py`).
2. **Luồng OAuth (`GoogleAuth`)**:
   - `GoogleAuth` trong `google_conn.py` vẫn đang được sử dụng ở endpoint webapp `/oauth2callback` và lệnh bot `/google_auth` để đổi mã code lấy refresh token và xác thực email.

### 2.3. Đánh giá & Phương án đề xuất
- **Đánh giá mức độ ưu tiên**:
  - Luồng `/google_auth` và đổi token chỉ diễn ra 1 lần khi người dùng thiết lập kết nối (tần suất cực thấp, vài ngày hoặc vài tuần một lần).
  - Nếu `GOOGLE_LEGACY_CONNECTORS=0` (mặc định), không có request lặp nào đi qua `_aiohttp_transport`.
  - Hơn nữa, theo yêu cầu mới **T-17** trong `AGENT_TASKS.md`, Google Workspace (Gmail, Calendar, Drive, Docs, Sheets) sẽ được nâng cấp thành **Built-in Connector chính thức** (chuẩn hoá OAuth, dùng `httpx` hoặc `google-workspace MCP` native).

- **Phương án đề xuất tối ưu (2 bước)**:
  1. **Bước 1 (Giữ nguyên hoặc vá nhẹ nếu bật legacy)**:
     - Nếu chủ dự án muốn tối ưu ngay cho legacy: Cho `GoogleAuth` và connectors nhận một `session: aiohttp.ClientSession | None` dùng chung (được đóng khi bot shutdown).
  2. **Bước 2 (Khuyến nghị chuẩn - Hợp nhất theo T-17)**:
     - **KHÔNG đầu tư tối ưu sâu cho `google_conn.py`** vì đây là code legacy sắp được thay thế.
     - Dồn nguồn lực vào **T-17**: Xây dựng built-in connector Google Workspace hoàn chỉnh với `httpx.AsyncClient` tái sử dụng connection pool (tương thích kiến trúc chung của MuLon, không phụ thuộc aiohttp cho connector bên ngoài).

### 2.4. Kế hoạch kiểm thử (Testing Strategy)
- Chạy toàn bộ `tests/test_v15_google.py` và `tests/test_google_oauth_callback.py`.
- Xác nhận OAuth handshake và token refresh pass 100% không bị rò rỉ session (`Unclosed client session`).

---

## 3. Tổng kết & Đề xuất gửi Chủ dự án
1. **Về Điểm nghẽn A (SQLite connection)**:
   - **Đánh giá**: ĐÂY LÀ ĐIỂM NGHẼN THỰC SỰ CẦN LÀM, đặc biệt khi triển khai message batching (T-09) và Mini App mở rộng (T-12).
   - **Khuyến nghị**: Chủ dự án duyệt triển khai theo kiến trúc **Reader Pool (3 connections) + Single Locked Writer**, bọc qua interface trong suốt để không làm gãy codebase hiện tại.
2. **Về Điểm nghẽn B (`google_conn.py`)**:
   - **Đánh giá**: Không cấp bách do connector này là legacy và tần suất OAuth rất thấp.
   - **Khuyến nghị**: Giữ nguyên `google_conn.py`, chuyển việc tối ưu session sang triển khai connector Google Workspace chính thức ở **T-17**.
