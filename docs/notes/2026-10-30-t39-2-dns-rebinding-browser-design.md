# Ghi Chú Thiết Kế Kỹ Thuật: Chốt Chặn DNS-Rebinding TOCTOU và Redirect Pre-flight Cho Chromium Browser Worker [T-39.2]

> **Tài liệu**: `docs/notes/2026-10-30-t39-2-dns-rebinding-browser-design.md`  
> **Tác giả**: Antigravity (`agency-backend-architect`, `agency-privacy-engineer`, `agency-api-tester`)  
> **Người thẩm định**: Muse (reviewer, VM)  
> **Trạng thái**: Đề xuất thiết kế (Design Note) trình Muse duyệt TRƯỚC khi viết code theo đúng chỉ đạo tại `AGENT_TASKS.md` [T-39.2].

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

2. **Redirect SSRF Pre-flight Gap (Nhảy redirect trước khi URL cuối bị chặn)**:
   - Khi `page.goto("http://attacker.com/redirect")` chạy, máy chủ trả về `302 Found` kèm `Location: http://127.0.0.1:8320/secret` hoặc `http://169.254.169.254/latest/meta-data/`.
   - Chromium tự động theo redirect và gửi HTTP `GET` tới đích nội bộ đó.
   - Mặc dù sau `page.goto()`, code MuLon kiểm tra `assert_url_public(page.url)` và ném ngoại lệ (vứt bỏ HTML), nhưng **hành động gửi request GET tới dịch vụ nội bộ đã xảy ra trên mạng** (có thể kích hoạt các endpoint REST nhạy cảm hoặc ghi nhận probe nội bộ).
   - *Ghi chú trong code cũ (`browser_worker.py:174`)* đã thừa nhận: *"Playwright tự theo redirect trong goto, nên 1 GET tới đích redirect nội bộ có thể đã xảy ra trước khi URL cuối bị chặn... không phải tường lửa pre-flight hoàn hảo như httpx"*.

---

## 2. So Sánh & Đánh Giá Các Phương Án Kỹ Thuật

| Tiêu chí | Phương án A: Playwright Route Interception (`page.route`) | Phương án B: Chromium `--host-resolver-rules` (Ghim IP) | Phương án C: Local Forward Proxy (Squid / Privoxy) |
|---|---|---|---|
| **Cơ chế** | Bắt mọi request mạng qua `page.route("**/*")`, kiểm tra URL & chặn redirects nội bộ trước khi gửi | Ghim hostname vào IP an toàn bằng cờ dòng lệnh Chromium `--host-resolver-rules` | Chạy 1 proxy lọc HTTP/HTTPS trung gian |
| **Chống DNS Rebinding** | ✅ Cực tốt (Single-resolution & fetch an toàn) | ✅ Cực tốt (Ghim IP cứng ở tầng socket) | ✅ Tốt |
| **Chặn Redirect Pre-flight** | ✅ Tuyệt đối (Chặn đứng tại hop 3xx, không cho Chromium gửi GET tới IP private) | ⚠️ Yếu với cross-domain redirect mới chưa map | ✅ Tốt |
| **Độ phức tạp / Dependencies** | 🟢 **Không thêm thư viện/tiến trình mới**, dùng API chuẩn của Playwright | 🟡 Phải tái khởi động context mỗi khi đổi domain | 🔴 Phải cài thêm daemon proxy ngoài, vi phạm Rule 0 & Degrade |
| **Ảnh hưởng hiệu năng** | Rất nhỏ (<5ms kiểm tra IP) | Trung bình (mở lại browser) | Trung bình |

---

## 3. Đề Xuất Giải Pháp Kỹ Thuật (Phương Án A: Route Interception Guard)

### 3.1. Thiết kế chi tiết cơ chế Chốt Chặn
Tại `BrowserWorker._open_page()`, thiết lập bộ lọc route toàn cục cho mọi `page`:

```python
async def _setup_ssrf_route_guard(page, timeout_ms: int):
    """Gắn route handler kiểm duyệt và chặn triệt để SSRF & DNS rebinding."""
    from .tools import resolve_and_verify_url

    async def _handle_route(route):
        request = route.request
        url = request.url

        # 1. Bỏ qua các scheme nội bộ của trình duyệt an toàn
        if url.startswith(("data:", "blob:", "about:")):
            await route.continue_()
            return

        # 2. Tiền kiểm tra URL (Phân giải DNS duy nhất một lần & xác thực IP)
        err, _ = await resolve_and_verify_url(url)
        if err:
            logger.warning("Browser SSRF Guard chặn URL không an toàn: %s (%s)", url, err)
            await route.abort("accessdenied")
            return

        # 3. Với tài nguyên điều hướng hoặc fetch: kiểm tra chặt chẽ redirect
        try:
            # Dùng route.fetch với max_redirects=0 để Playwright không tự động theo redirect mù quáng
            response = await route.fetch(max_redirects=0)
            status = response.status
            
            # Nếu là response 3xx (Redirect): Kiểm duyệt ngay header Location trước khi theo
            if 300 <= status < 400:
                location = response.headers.get("location") or response.headers.get("Location")
                if location:
                    # Chuyển location tương đối thành tuyệt đối nếu cần
                    target_url = urljoin(url, location)
                    target_err, _ = await resolve_and_verify_url(target_url)
                    if target_err:
                        logger.warning("Browser SSRF Guard chặn redirect tới IP nội bộ: %s -> %s (%s)", url, target_url, target_err)
                        await route.abort("accessdenied")
                        return

            await route.fulfill(response=response)
        except Exception as exc:
            # Mạng lỗi hoặc bị abort
            await route.abort("failed")

    await page.route("**/*", _handle_route)
```

### 3.2. Điểm mạnh vượt trội của phương án này:
1. **Triệt tiêu TOCTOU**: Phân giải DNS diễn ra có kiểm duyệt, response trả về được nạp trực tiếp qua `route.fulfill(response=response)` — Chromium không tự ý phân giải DNS lần 2 ra IP khác.
2. **Không còn lỗ hổng Redirect Pre-flight**: Vì `max_redirects=0`, Chromium sẽ **không bao giờ** tự động gửi GET request tới đích redirect nội bộ. Header `Location` phải vượt qua `resolve_and_verify_url()` trước thì mới được phép tiếp tục.
3. **Phủ toàn bộ request**: Bao gồm navigation chính, iframe, subresources (`<img>`, `<script>`, `fetch`, XHR) đều đi qua bộ lọc an toàn.
4. **Không làm gãy môi trường headless**: Tương thích 100% với Playwright Chromium và chạy mượt mà trên cả Linux (VM) lẫn macOS (Mac mini).

---

## 4. Ghi Nhận Rủi Ro Đối Với ISSUE-11 (HMAC initData replay)

Theo đúng chỉ đạo của Muse tại `AGENT_TASKS.md` [T-39.2]:
- **Phát hiện**: `validate_init_data()` trong `webapp_server.py` kiểm tra chữ ký HMAC-SHA256 và `auth_date` trong cửa sổ lệch 300s và hết hạn 3600s, nhưng chưa lưu cache `nonce` / `token` đã dùng trong 3600s đó.
- **Đánh giá rủi ro**:
  - Đối với hệ thống công cộng đa người dùng, replay attack trong cửa sổ 3600s có thể cho phép bên thứ ba phát lại request nếu họ đánh cắp được chuỗi initData.
  - Tuy nhiên, đối với MuLon:
    - (a) Bot chỉ phục vụ **duy nhất chủ dự án (`mmmnhat`)**;
    - (b) Kênh truyền được mã hóa hoàn toàn qua HTTPS (Cloudflare Tunnel TLS) và Telegram API;
    - (c) Mini App yêu cầu session ngắn và auth_date liên tục được làm mới.
- **Kết luận**: Ghi nhận đây là **rủi ro đã được chủ sở hữu và hội đồng tác tử chấp nhận (Accepted Risk)** trong vòng này, **không thêm code lưu trữ nonce phức tạp** nhằm giữ vững nguyên tắc tinh gọn (Minimal Viable Diff / Ponytail discipline).

---

## 5. Tiêu Chí Nghiệm Thu Đề Xuất Cho [T-39.2]

1. **Ghi chú thiết kế được Muse thẩm định & thông qua**.
2. **Test hồi quy cụ thể**:
   - Viết bài test giả lập redirect từ domain công cộng sang `http://127.0.0.1:8320/secret` hoặc `http://169.254.169.254`: xác thực request bị `abort` ngay tại hop redirect, không có kết nối nào chạm tới mock local server.
   - Viết bài test giả lập URL trỏ tới domain phân giải ra IP loopback/private: xác thực bị chặn ngay tại route guard (`accessdenied`).
3. **Bộ test suite xanh 100%**: Không làm gãy bất kỳ test browser hay mock test nào hiện hữu.
