"""Mulon — Muse clone 1.4.0 (Phase 1 + 2 + 3 + 4 + 5 + 6 + Mini App + Chợ MCP + Feed chủ động).

Lõi agent mỏng tự viết theo tài liệu thiết kế
``thiet-ke-ky-thuat-muse-clone.md``: gateway model qua LiteLLM trỏ vào
proxy OpenAI-compatible, context engine chống context rot, vòng lặp
plan-act-verify, ký ức SQLite bi-temporal, bề mặt Telegram duy nhất.
Phase 2 thêm ký ức sống: hybrid recall (vector + BM25), consolidation
worker, học từ correction, background review fork.
Phase 3 thêm tay chân: MCP client thật (SDK chính thức), subagents
(agent loop đầy đủ, toolset thu hẹp), scheduler + goals/tracking,
browser worker (Playwright), khung connector trung tính.
Phase 4 thêm chủ động + tiếng nói + media: proactivity engine
(heartbeat gom việc, mặc định tắt, chỉ xếp hàng đề xuất), voice hai
chiều (faster-whisper + hiểu ngữ / TTS qua proxy), media pipeline
tools (ffmpeg), MCP streamable HTTP, browser profile bền, skills
system SKILL.md (progressive disclosure + vet tĩnh).
Phase 5 thêm cứng hóa: bộ eval vàng chạy thật (golden + case từ
correction, cổng pass rate), CI GitHub Actions, Langfuse tracing
tuỳ chọn (chỉ metadata, không nội dung), backup/restore có
checksum, báo cáo sức khỏe + đường cong học theo tuần.
Phase 6 hoàn thiện bề mặt group (mục 16): topic = tab trong
supergroup forum (setup + ghim mục lục), Feed tự viết từ tư liệu
nội bộ + taste học từ reaction, thẻ Ideas hết hạn 14 ngày và
'làm luôn' thành goal + task, trình duyệt proactive notes,
Library có thùng rác 30 ngày + chia sẻ <=48h chờ host, Secure
Vault bằng form một lần (giá trị không qua chat/log), bộ nhớ có
bề mặt (truy nguồn, quên có kế hoạch + xác nhận, export/import),
quyền bằng lời thường + lịch sử duyệt.
Bản 1.2.0 thêm mặt quản trị kiểu Muse: menu lệnh Telegram
(set_my_commands), policy 3 nấc allow/ask/deny với thẻ duyệt TỰ
GỠ sau quyết định (ApprovalBroker), và Mini App (Telegram Web
App qua Direct Link) phong cách "tờ hồ sơ agent" — 5 tab Việc /
Phê duyệt / Lịch / Hồ sơ / Cài đặt; cấu hình connector, Vault
(chỉ nhãn) và quyền đều nằm trong app, API khóa bằng chữ ký
initData + đúng ALLOWED_USER_ID.
Bản 1.3.0 thêm Chợ MCP (Marketplace) trong Mini App: cài MCP
server local stdio MIỄN PHÍ từ danh mục tuyển chọn đóng gói
hoặc dán cấu hình thủ công — chuẩn hoá + phân tích rủi ro,
chạy thử (probe) tách rời, 2 lần duyệt (probe rồi commit),
bí mật chỉ qua Vault ref, tool vào group policy ở nấc ask,
bot TỰ khởi động lại để áp dụng kèm đối chiếu lúc boot và tự
khôi phục cấu hình trước đó khi áp dụng thất bại; catalog tự
cập nhật dữ kiện từ repo (kiểm checksum, không bao giờ tự cài).
Bản 1.4.0 biến Feed thành FEED CHỦ ĐỘNG (quyết định owner
0.2b: luôn tự động, không công tắc tổng, không lệnh
/feed_auto; /feed_now rút khỏi menu lệnh, giữ handler ẩn):
lịch hệ thống nội bộ trên SchedulerService (cô lập tick —
lịch thường vẫn tắt khi SCHEDULER_ENABLED=0), collector tự
tìm kiếm web theo chủ đề nóng + chấm độ tin cậy ưu tiên
nguồn official/chính thống, kiểm trích dẫn tất định sau
sinh (sai là bỏ bài), chống trùng 3 lớp, trần bài/ngày +
trần token/ngày + giờ yên lặng, lỗi 3 lượt liên tiếp thì tự
tạm dừng và báo owner đúng 1 tin; điều khiển ở Mini App
(Cài đặt → Feed chủ động) và /feedsources.
Bản 1.4.1 là đợt vá theo phản ánh thật của owner sau 1.4:
công tắc heartbeat THẬT trong Mini App (kv thắng env, áp
dụng ngay, hết cảnh "bị khoá" vì PROACTIVITY_ENABLED); theme
nhuộm đủ 3 tầng 60/30/10 + thẻ hồ sơ theo hue; Chợ MCP mở
màn con theo danh mục, bỏ ô tìm kiếm, bỏ card Giá, nhãn
quyền tiếng Việt; bỏ 2 connector mẫu example/example-http;
màn Quyền có mục riêng từng connector (connector:<tên>,
server MCP mcp:<tên> — cài thêm là tự xuất hiện); ô nhập
.field-input đầy bề ngang (Kho hết "chưa responsive"); tab
Việc chỉ còn TASK THẬT (timeline các bước kế hoạch + tóm
tắt), lượt chat trở về đúng chỗ của nó: trong chat.

Bản 1.5.0 (2026-10-24): connector thật đầu tiên — Gmail
(tìm/đọc/gửi) + Google Calendar (xem/tạo/xoá sự kiện)
qua OAuth2 ủy quyền 1 lần từ Mini App, refresh token
ở Vault, client id/secret qua env hoặc Vault. Xem
docs/google-connector-setup.md.

Bản 1.6.0 (2026-10-24): Thư viện Artifacts + Link chia sẻ
công khai thật (/share/{token}) có thời hạn 48h; Thẻ nhập
bí mật Vault an toàn tương tác trong chat (request_vault_secret);
Phân quyền chi tiết từng hành động cho connector (Action-Level
Connector Policy); Cài đặt MCP 1-Click từ Mini App.
"""

__version__ = "1.7.16"

# Shim cho LiteLLM 1.106+ khi dùng với thư viện mcp
try:
    import mcp.types as _mcp_types

    if not hasattr(_mcp_types, "CacheableResult"):
        class _CacheableResult:
            pass

        _mcp_types.CacheableResult = _CacheableResult  # type: ignore[attr-defined]
except Exception:
    pass
