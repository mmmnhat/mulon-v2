# AUDIT CHUYÊN SÂU: SLASH COMMANDS + GIAO DIỆN MINI APP — chuẩn "100% chuyên nghiệp" (2026-10-27)

Người viết: Muse (reviewer/tester). Nguồn bằng chứng: rà code `mulon/telegram_bot.py` trên mirror,
probe sống 19 lệnh qua Telegram cá nhân trên bot thật, sitemap đo thật
(`docs/sitemap-miniapp-2026-10-27.md`) + cây IA đích (`docs/miniapp-ia-redesign-2026-10-27.md`).
Tài liệu này là YÊU CẦU CHI TIẾT cho Antigravity; các mục việc tương ứng: T-26 (slash), T-27 (UI).

## PHẦN 1 — SLASH COMMANDS: bề mặt lệnh thật vs bề mặt công bố

### 1.1 Ba tầng lệch nhau (đo từ code)
- Menu "/" chính thức (set_my_commands, user thấy khi gõ "/"): **8 lệnh** —
  start, menu, restart, model, status, vault, new, cancel.
- BOT_COMMANDS (khai trong code nhưng KHÔNG đăng ký vào menu): **+14** —
  memory, chatphu, setup_topics, quyen, approvals, goals, ideas, feed_now, library,
  feedbrief, feedsources, the_duyet, pin_item, rename_item.
- Handler có thật trong code nhưng không nằm ở cả 2 danh sách trên ("slash ngầm" đúng nghĩa): **24** —
  claim, setup, stop, topics, lich, saptol, upcoming, chatphu_mo, chatphu_dong, chatphu_list,
  dongchat, notes, note_ok, note_bo, idea_do, idea_bo, trash_item, restore_item, share_item,
  google_auth, forget, export_memory, voiceon, voiceoff.
- Tổng bề mặt thật: **46 lệnh**. **Không có /help** — user gõ /help không có lệnh nào đón.

### 1.2 Bệnh chính
1. **Trùng khái niệm:** /lich, /saptol, /upcoming cùng một nhà "sắp tới"; /stop trùng /cancel;
   /chatphu + /chatphu_mo + /dongchat + /chatphu_dong chồng nhau (mở/đóng chat phụ).
2. **Lệnh hành động lẻ tẻ theo id** (pin_item, rename_item, trash_item, restore_item, share_item,
   note_ok, note_bo, idea_do, idea_bo): bản chất là hành động trên item — chỗ đúng của chúng là
   nút/thẻ trong chat và trong app, không phải bắt user nhớ cú pháp slash kèm id.
3. **Lệnh nguy hiểm lẫn trong bề mặt thường:** /restart, /forget, /export_memory, /google_auth,
   /claim, /setup — không phân tầng, không có trang "lệnh nâng cao" nào giải thích.
4. **the_duyet** (gửi thẻ duyệt THỬ) là lệnh dev/test nhưng nằm trong bản chạy thật và đã để lại
   dữ liệu thử trong lịch sử phê duyệt của user.
5. Không nhất quán ngôn ngữ: tên lệnh Anh (upcoming, library, approvals) trộn Việt viết không
   dấu (saptol, lich, quyen, the_duyet) trộn viết tắt khó đoán (dongchat).

### 1.3 Kết quả probe sống (bot thật, 27/10/2026, qua Telegram cá nhân; log `slash-probe-results.jsonl`)
| Lệnh | Kết quả |
|---|---|
| /help | **KHÔNG có handler.** Trong cửa sổ chờ chỉ có placeholder "…"; câu trả lời tới MUỘN dưới dạng một lượt agent tự chế "Bảng hướng dẫn nhanh các lệnh..." (chậm, nội dung không ai kiểm chứng, tự liệt kê cả /help). |
| /upcoming | Chạy — bảng Sắp tới. |
| /saptol | Chạy — bảng **giống hệt** /upcoming. |
| /lich | Chạy — bảng **giống hệt** /upcoming. Ba lệnh một việc, kiểm chứng sống. |
| /memory | Chạy nhưng **đổ cả văn bản dossier thô** (gồm chỉ thị nội bộ kiểu "agent phải chủ động cập nhật ngay vào dossier...") — cần tóm tắt/cấu trúc lại thay vì dump nguyên văn. |
| /goals, /quyen, /approvals, /library, /topics, /chatphu_list, /notes, /feedsources, /feedbrief, /model | Đều chạy đúng việc. /approvals bản chat CÓ timestamp (bản app thì không — xem 2.2). /quyen xác nhận policy máy thật đang "full-auto" (khớp vụ T-10.1). |
| /voiceon → /voiceoff | Chạy; đã tắt lại ngay sau probe, trạng thái trở về cũ. |
| /export_memory | Chạy — gửi bản xuất dossier + facts. Lệnh nặng dữ liệu nhưng nằm phẳng trong bề mặt thường. |
| /xyz123khongco (lệnh bịa) | **Bot coi như việc chat thật**: hiện "⏳ Đang xử lý: ✓ Kế hoạch: /xyz123khongco" và chạy một lượt agent vô nghĩa. Lệnh lạ phải trả lời "không có lệnh này, xem /help" ngay, không tốn lượt model. |

### 1.4 Yêu cầu chốt bề mặt lệnh (nghiệm thu ở T-26)
- **Một nguồn sự thật duy nhất:** danh sách lệnh khai một chỗ; menu "/", /help, và tài liệu đều
  sinh từ đó. Lệnh có handler mà không có trong danh sách = lỗi kiểm tra (thêm test tĩnh: quét
  handler đối chiếu danh sách khai).
- **Menu "/" rút gọn còn lệnh cốt lõi** (đề xuất 10): start, menu, new, cancel, status, model,
  vault, upcoming, goals, help. Thêm **/help** thật: liệt kê lệnh theo nhóm (Cơ bản / Việc & dữ
  liệu / Nâng cao) kèm mô tả một dòng, render từ cùng danh sách khai.
- **Gộp alias:** /saptol và /lich thành alias ẩn của /upcoming (gõ vẫn chạy, không công bố);
  /stop là alias của /cancel. /dongchat là alias của /chatphu_dong. Alias ẩn phải có test.
- **Lệnh-theo-id chuyển thành hành động trên thẻ/item:** giữ handler làm đường nội bộ cho nút
  bấm, bỏ khỏi bề mặt "lệnh user phải nhớ"; /help không liệt kê chúng.
- **Tầng nâng cao:** restart, forget, export_memory, google_auth, claim, setup, voiceon/voiceoff,
  the_duyet — gom nhóm "Nâng cao" trong /help kèm cảnh báo một dòng cho lệnh phá huỷ/đổi trạng
  thái (forget, restart). the_duyet chỉ bật khi có cờ dev trong config, mặc định TẮT ở bản thật.
- **Lệnh lạ:** text bắt đầu bằng "/" mà không khớp lệnh/alias nào -> trả lời ngay một câu
  "Không có lệnh này — xem /help", KHÔNG đưa vào vòng agent (điểm dữ liệu /xyz123khongco ở 1.3).
- **/memory hết dump thô:** trả về dạng tóm tắt có cấu trúc (số fact, nhóm chủ đề, vài fact gần
  nhất + cách xem thêm), không in nguyên văn dossier/chỉ thị nội bộ.
- Đặt tên nhất quán: lệnh công bố dùng một ngôn ngữ (ưu tiên ngắn, không dấu như hiện tại nhưng
  một kiểu duy nhất), lệnh cũ giữ alias ẩn tối thiểu 1 phiên bản để không gãy thói quen.

## PHẦN 2 — GIAO DIỆN MINI APP: chuẩn chuyên nghiệp + thiếu/thừa từng màn

### 2.1 Chuẩn xuyên suốt (bắt buộc, nghiệm thu bằng render thật + chạm thật)
1. **Tích hợp native Telegram:** dùng WebApp.BackButton cho mọi màn con (thay nút tự chế/không có),
   MainButton cho hành động chính của màn khi hợp (Lưu, Cài đặt), HapticFeedback cho tap/duyệt/
   lỗi, mở app bằng themeParams của Telegram làm nền và ghi đè đúng MỘT màu nhấn (tím Mulon).
2. **Hệ thống thiết kế đo được:** lưới 8pt (padding màn 16, khoảng cách mục 8/16/24); tối đa 4 cỡ
   chữ + 2 weight; bán kính góc thống nhất (12 card / 8 nút); hàng danh sách một khuôn: cao tối
   thiểu 56, vùng chạm ≥44, cấu trúc [icon?] tiêu đề / phụ đề / chevron hoặc công tắc — không trộn
   kiểu trong cùng một danh sách.
3. **Trạng thái là một phần của thiết kế:** mọi màn có đủ 4 trạng thái — đang tải (skeleton theo
   đúng khung nội dung, không spinner trần), rỗng (một câu + một hành động), lỗi (một câu + Thử
   lại, nằm trong màn), có dữ liệu. Tải màn con phải < 1 giây cảm nhận (hiện tại 15–20s ở vài
   màn — coi là lỗi hiệu năng, không phải "đang tải lâu").
4. **Màu kỷ luật:** 60/30/10, một màu nhấn; trạng thái bằng CHỮ + phân cấp trung tính (không
   xanh lá/vàng/đỏ); màu chỉ dành cho hành động chính và liên kết.
5. **Nhãn = đích đến:** tiêu đề màn con khớp 100% nhãn hàng đã chạm; không lộ markdown thô,
   comment HTML, đường dẫn máy, id kỹ thuật ở bất kỳ màn nào.
6. **An toàn thao tác:** hành động phá huỷ (xoá, ngắt kết nối, quên bộ nhớ) luôn có bước xác nhận
   tóm tắt hậu quả; đổi quyền áp dụng có thông báo đã lưu; không thao tác nào "bấm là xong không
   dấu vết".

### 2.2 Thiếu / thừa theo từng màn (đối chiếu sitemap 27/10)
- **Việc:** THỪA — khối "…" placeholder và markdown thô ở tóm tắt; THIẾU — bộ lọc trạng thái +
  tìm kiếm (đã ghi ở IA), số liệu tổng quan đầu tab (đang chạy/chờ/lỗi hôm nay), skeleton khi mở
  chi tiết, nút thử-lại-từ-bước-lỗi. Chi tiết việc hiện KHÔNG TẢI ĐƯỢC (initData, T-24.5) —
  chữa xong mới nói chuyện đẹp.
- **Phê duyệt:** THỪA — 2 bản ghi "Gửi thẻ phê duyệt thử" (xoá dữ liệu thử + tắt nguồn sinh,
  xem 1.4); lịch sử không có mốc thời gian (THIẾU timestamp + nhóm theo ngày); THIẾU trạng thái
  "đang chờ" dạng thẻ hành động ngay đầu tab (hiện chỉ là câu chữ khi rỗng).
- **Lịch:** THIẾU màn chi tiết lịch trình (đang là sheet chôn 3 cấp cho Heartbeat, còn 7 lịch hẹn
  là hàng chết); THIẾU lịch sử chạy có phân trang; THỪA sự mơ hồ: cùng một "Heartbeat" xuất hiện
  ở tab Lịch lẫn ngữ cảnh khác — gom một nhà theo IA.
- **Hồ sơ:** THỪA LỚN — ~400 nút lộ thiên ở danh sách tài liệu (mỗi tài liệu 4 nút ngay trên
  hàng) → chuyển hành động vào màn xem trước; bộ nhớ xuất hiện 2 nơi trùng nhau → một nhà duy
  nhất (fact list, IA); THIẾU tìm kiếm tài liệu/fact, xem trước tài liệu, nhóm kỹ năng (91 kỹ
  năng phẳng + 12 mô tả hỏng chỉ còn ">" — dọn dữ liệu mô tả).
- **Cài đặt:** THỪA — danh sách "Từng tool" 90 hàng phẳng ở màn Quyền (chuyển vào chi tiết
  connector), tên connector xuất hiện 2 nơi 2 nghĩa ("Đã cài" vs "Quyền") gây hiểu nhầm;
  bộ chọn 6 màu chủ đề phá kỷ luật một-màu-nhấn (chờ user chốt giữ/bỏ — T-23.5); THIẾU chi
  tiết connector (trạng thái, tài khoản, tool, quyền, cấu hình, ngắt kết nối), chevron/bấm-được
  nhất quán (hàng connector dùng công tắc thay chevron lẫn lộn), xác nhận khi đổi quyền nhạy cảm.
- **Kho:** THIẾU chi tiết bí mật (hàng chết trừ nút Sửa), tìm kiếm khi >15; GIỮ NGUYÊN chuẩn
  đang đúng: không hiện giá trị ở đâu cả.
- **Chợ MCP:** THIẾU tìm kiếm + danh mục + phân trang (2.101 trang cuộn tay là không thể dùng);
  THIẾU chi tiết server trước khi cài; hiện còn lỗi tải (T-24.5).
- **Feed (trong Cài đặt):** THỪA trường cron thô cho người dùng cuối → preset là chính + cron
  là phụ; nhãn giờ hiển thị đang SAI so với cron thật (T-25) — hiển thị phải sinh từ cấu hình,
  không hardcode; bỏ emoji trạng thái (🌙) khỏi nhãn trường.

### 2.3 Định nghĩa "xong" cho đợt UI (nghiệm thu T-27)
Mỗi màn con: render thật trước/sau đặt cạnh nhau trong báo cáo; chạm thử toàn bộ hàng (0 hàng
chết); đủ 4 trạng thái; thời gian mở màn đo lại; đối chiếu checklist 2.1 từng dòng. Không nghiệm
thu bằng lời — chỉ bằng render + số đo + chạm thật, như chuẩn các đợt trước.
