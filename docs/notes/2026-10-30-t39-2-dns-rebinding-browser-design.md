# Ghi Chú Thiết Kế Kỹ Thuật: Chốt Chặn DNS-Rebinding TOCTOU và Redirect Pre-flight Cho Chromium Browser Worker [T-39.2]

> **Tài liệu**: `docs/notes/2026-10-30-t39-2-dns-rebinding-browser-design.md`  
> **Tác giả**: Antigravity (`agency-backend-architect`, `agency-privacy-engineer`, `agency-api-tester`)  
> **Người thẩm định**: Muse (reviewer, VM)  
> **Trạng thái**: Đã được Muse DUYỆT CÓ ĐIỀU KIỆN (31/10/2026 ~00:40 +07); Đã hoàn thành Spike kỹ thuật theo ĐK2 và cập nhật thiết kế chi tiết.

---

## 1. Bối cảnh & Hiện Trạng Lỗ Hổng (Root Cause Analysis)

### 1.1. Hiện trạng code `mulon/browser_worker.py` (v1.6.3 đến v1.7.48)
Hiện tại, trong các phương thức `_fetch_rendered`, `_capture_png`, `_act`:
```python
err = await assert_url_public(url)
if err:
    raise ValueError(err)
async with self._open_page() as page:
    await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
    err = await assert_url_public(page.url)
    if err:
        raise ValueError(f"URL cuối sau redirect bị chặn: {err}")
    ...
```

### 1.2. Hai khe hở an ninh cốt lõi:

1. **DNS Rebinding TOCTOU (Time-of-Check to Time-of-Use)**:
   - *Bước 1 (Check)*: Python gọi `assert_url_public(url)` → phân giải DNS của `attacker-rebind.com` ra IP công cộng hợp lệ (ví dụ `1.2.3.4`, TTL=0). Vượt qua kiểm tra an toàn.
   - *Bước 2 (Use)*: Python gọi `page.goto(url)` → Chromium khởi tạo kết nối mạng độc lập và tự phân giải DNS lần 2. Do TTL=0, máy chủ DNS của kẻ tấn công lập tức trả về IP loopback/nội bộ (`127.0.0.1` hoặc IP metadata đám mây `169.254.169.254`).
   - *Hậu quả*: Chromium kết nối thẳng tới dịch vụ nội bộ trên máy host mà Python không hay biết.
   - *Ranh giới kỹ thuật (Sửa theo ĐK1 của Muse)*: Việc chặn qua `page.route` là **giảm thiểu đáng kể cửa sổ TOCTOU**, không thể tuyên bố "triệt tiêu 100%" nếu không ghim IP ở tầng socket. Đối với URL điều hướng ban đầu, MuLon có thể ghim host ban đầu qua cờ launch `--host-resolver-rules="MAP <host> <pinned_ip>"`. Tuy nhiên, với các redirect cross-domain phát sinh động trong phiên duyệt mà không relaunch trình duyệt, tuyến phòng thủ chủ lực là cơ chế tiền kiểm soát IP từng hop qua Route Interception.

2. **Redirect SSRF Pre-flight Gap (Nhảy redirect trước khi URL cuối bị chặn)**:
   - Khi `page.goto("http://attacker.com/redirect")` chạy, máy chủ trả về `302 Found` kèm `Location: http://127.0.0.1:8320/secret` hoặc `http://169.254.169.254/latest/meta-data/`.
   - Chromium tự động theo redirect và gửi HTTP `GET` tới đích nội bộ đó.
   - Mặc dù sau `page.goto()`, code MuLon kiểm tra `assert_url_public(page.url)` và ném ngoại lệ (vứt bỏ HTML), nhưng **hành động gửi request GET tới dịch vụ nội bộ đã xảy ra trên mạng** (có thể kích hoạt các endpoint REST nhạy cảm hoặc ghi nhận probe nội bộ).

---

## 2. Kết Quả Thực Nghiệm Kỹ Thuật (Spike Findings theo ĐK2)

Theo chỉ thị bắt buộc ĐK2 của Muse, phía Antigravity đã thực hiện spike thực nghiệm Playwright thực tế trên máy Mac (`scratch/spike_*.py`) và ghi nhận 3 phát hiện cốt tử:

1. **Câu hỏi (a): Mỗi hop redirect có đi qua `page.route` handler không?**
   - **Kết quả thực nghiệm**: **KHÔNG**. Khi Chromium nhận response redirect 3xx (kể cả cùng origin lẫn cross-port/cross-origin), Chromium xử lý chuyển hướng bên trong C++ network stack của browser. Khi dùng `route.continue_()` hoặc `route.fulfill(response=3xx)`, các hop redirect kế tiếp **hoàn toàn bypass `page.route`**! Chromium tự động gửi GET tới đích tiếp theo mà handler không hề hay biết (đã kiểm chứng qua `spike_cross_port.py` và `spike_multi_hop.py`: Server 3 nội bộ bị chạm tới!).
2. **Câu hỏi (b): Xử lý 3xx redirect bằng cách nào an toàn tuyệt đối?**
   - **Kết quả thực nghiệm**: Áp dụng **Vòng lặp Manual Follow bằng `context.request.get(url, max_redirects=0)` có trần hop (≤10)**:
     - Với mỗi hop: Bắt buộc gọi `resolve_and_verify_url(cur_url)`. Nếu phát hiện IP private/loopback/metadata -> Lập tức gọi `await route.abort("blockedbyclient")`.
     - Nếu an toàn: Fetch hop đó với `max_redirects=0`. Nếu trả về 3xx kèm `Location` -> Lấy `Location`, resolve sang URL tuyệt đối, lặp tiếp hop sau.
     - Khi chạm trang đích cuối cùng (non-3xx: 200, 404...): Nạp toàn bộ body/headers vào route qua `await route.fulfill(...)`.
     - *Bằng chứng kiểm chứng*: Tại `spike_manual_follow.py`, chuỗi redirect 3 hop qua server nội bộ 18896 đã bị chặn đứng 100% tại hop 3, server nội bộ **hoàn toàn không bị chạm tới (0 request chạm tới)**.
3. **Câu hỏi (c): `context.request` có làm mất cookie/phiên không?**
   - **Kết quả thực nghiệm**: **KHÔNG**. `context.request` trong Playwright chia sẻ chung cookie store với `BrowserContext`. `Set-Cookie` ở các hop redirect được lưu vào context bình thường.
   - *Phân định phạm vi*: Manual follow loop chỉ áp dụng cho request điều hướng chính (`is_navigation_request()`). Với subresources (`<img>`, `<script>`, `css`...), chỉ cần kiểm tra URL nhanh qua `resolve_and_verify_url(url)` rồi `route.continue_()` để tối ưu hóa hiệu năng tải trang.

---

## 3. Thiết Kế Chi Tiết Giải Pháp (Phương Án A Nâng Cấp)

### 3.1. Vị trí tích hợp
Gắn tập trung duy nhất tại `BrowserWorker._open_page()` (theo ĐK3 của Muse), tự động bảo vệ mọi trang được mở cho cả 3 nghiệp vụ:
- `_fetch_rendered`
- `_capture_png`
- `_act`

### 3.2. Mã nguồn triển khai chi tiết
```python
async def _setup_route_guard(page, context):
    """Thiết lập guard route chống DNS-rebinding và redirect SSRF hop-by-hop."""
    from urllib.parse import urljoin
    from mulon.tools import resolve_and_verify_url

    async def _handle_route(route):
        req = route.request
        url = req.url

        # Bỏ qua các scheme nội bộ trình duyệt an toàn
        if url.startswith(("data:", "blob:", "about:", "chrome:")):
            await route.continue_()
            return

        # Kiểm tra URL hop đầu tiên
        err, _ = await resolve_and_verify_url(url)
        if err:
            logger.warning("Browser Guard chặn request không an toàn: %s (%s)", url, err)
            await route.abort("blockedbyclient")
            return

        # Với subresources (không phải navigation chính): kiểm tra an toàn URL rồi cho tiếp tục
        if not req.is_navigation_request():
            await route.continue_()
            return

        # Với navigation chính: Manual follow loop có trần hop ≤10 kiểm soát từng hop
        cur_url = url
        hop = 0
        max_hops = 10

        while hop < max_hops:
            hop += 1
            # Tiền kiểm tra IP của cur_url trước khi gửi bất kỳ byte nào
            hop_err, _ = await resolve_and_verify_url(cur_url)
            if hop_err:
                logger.warning("Browser Guard chặn redirect hop #%d tới IP nội bộ: %s (%s)", hop, cur_url, hop_err)
                await route.abort("blockedbyclient")
                return

            try:
                # Fetch bằng context.request chia sẻ cookie jar
                resp = await context.request.get(cur_url, max_redirects=0, timeout=15000)
            except Exception as exc:
                logger.warning("Browser Guard lỗi fetch hop #%d (%s): %s", hop, cur_url, exc)
                await route.abort("blockedbyclient")
                return

            status = resp.status
            loc = resp.headers.get("location")

            if 300 <= status < 400 and loc:
                next_url = urljoin(cur_url, loc)
                cur_url = next_url
                continue
            else:
                # Trang đích an toàn cuối cùng
                body = await resp.body()
                await route.fulfill(
                    status=resp.status,
                    headers=resp.headers,
                    body=body
                )
                return

        # Quá trần 10 hops redirect
        logger.warning("Browser Guard chặn chuỗi redirect vượt quá 10 hops: %s", url)
        await route.abort("blockedbyclient")

    await page.route("**/*", _handle_route)
```

---

## 4. Ghi Nhận Rủi Ro Đối Với ISSUE-11 (HMAC initData replay)

Theo đúng chỉ đạo của Muse:
- Rủi ro replay initData trong cửa sổ 3600s là **Accepted Risk** đã được chủ dự án chấp thuận đối với bot cá nhân một chủ, có mã hóa TLS đầu-cuối của Telegram và Cloudflare Tunnel bảo vệ. Không viết thêm code lưu trữ nonce phức tạp.

---

## 5. Tiêu Chí Nghiệm Thu Đầy Đủ (ĐK4 của Muse)

1. **3 bài test hồi quy bắt buộc**:
   - Test 1: Redirect từ URL công cộng sang `127.0.0.1` hoặc `169.254.169.254` bị `abort`, không có bất kỳ kết nối mạng nào chạm tới server mock nội bộ.
   - Test 2: URL công cộng tự phân giải ra IP private/loopback bị `abort` ngay tại hop 1 (`blockedbyclient`).
   - Test 3: Redirect an toàn giữa 2 URL công cộng (`public -> public`) follow thành công và load đầy đủ nội dung trang đích cuối (chống hồi quy kẹt 3xx).
2. **Suite test xanh 100%**: Không làm gãy bất kỳ test browser hay mock test nào hiện hữu.

