# QA Mini App MuLon — báo cáo kiểm tra 2026-10-27 (đợt 1)

Nguồn: Muse mở Mini App bằng WebView đã xác thực của chủ
dự án, kiểm tra CHỈ ĐỌC toàn bộ 5 tab + 16 màn hình/bảng con
(00:10–00:46, giờ Asia/Saigon). Không phê duyệt, không đổi
cài đặt, không xoá, không gửi tin. Hạn chế: xem trên trình
duyệt desktop dạng cột đơn (không đặt được viewport
390x844) — nhận xét vùng chạm/ngón cái theo tỉ lệ hiển thị.
Phiên bản app quan sát: 1.7.1. Các lỗi dưới đây là cơ sở
của mục T-23 trong `AGENT_TASKS.md`.

## Khung chung
- Thanh điều hướng chính là segmented ở TRÊN (không phải
  tab đáy): cả 5 tab ngoài vùng ngón cái.
- Không màn hình con nào có nút quay lại — thoát bằng cách
  nhấn lại tab cha.
- Cụm chữ "Một lượt việc vừa hoàn tất." rò rỉ ở cuối gần
  như mọi màn hình (toast bị lọt ra DOM).
- Header: chấm trạng thái XANH LÁ + nhãn lúc "Đã kết nối"
  lúc "Sẵn sàng"; avatar có lần chỉ hiện chữ "M".

## Q-01 Điều hướng kẹt (nghiêm trọng nhất)
Nhấn 1 hàng trong Cài đặt thường mở lại màn hình con TRƯỚC
ĐÓ (nhấn "Kho lưu trữ an toàn" -> mở "Công cụ kết nối";
nhấn "Quyền" -> mở "Kho lưu trữ"; nhấn "Feed chủ động" ->
mở "Quyền"); nhấn lần hai mới đúng. Chỉ nhấn vào CHEVRON
mới chắc chắn mở; thân hàng lúc được lúc không. Cùng mẫu:
thân hàng lịch, thân hàng server chợ MCP, tên tài liệu
đều không có tác dụng. Hàng lịch sử chạy Heartbeat có
chevron nhưng nhấn không tác dụng (affordance chết); 7
hàng lịch không có màn chi tiết như Heartbeat.

## Q-02 Markdown thô + lộ thông tin máy
"Tóm tắt" chi tiết việc, màn con Hồ sơ, Bộ nhớ, chi tiết
kỹ năng đều hiện markdown THÔ (nguyên `###`, `---`), lộ
comment HTML, dính chữ do thiếu khoảng trắng ("toàn
bộ63/63 bài đăngcủa"). Chi tiết kỹ năng + chi tiết
connector LỘ ĐƯỜNG DẪN MÁY CỤC BỘ (`/Volumes/External/...`).
Màn "Thiết bị & hệ thống" hiện tên máy + ID Telegram
nguyên văn (chấp nhận cho chủ nhân, không nên lọt ảnh
chụp chia sẻ).

## Q-03 Mâu thuẫn trạng thái việc
Cùng 1 việc: danh sách ghi "✕ Đã lỗi" nhưng chi tiết kết
"Hoàn tất / Kiểm chứng: Đạt yêu cầu" và tóm tắt khẳng định
thành công. Nhiều việc "5/6 bước", "17/19 bước" vẫn "✓ Đã
xong". Mở chi tiết việc mới thì heading còn hiện tiêu đề
việc CŨ rồi mới đổi (stale heading). Định dạng giờ không
nhất quán ("00:06" vs "26/10/2026 23:56").

## Q-04 Tải chậm
Màn con Hồ sơ/Bộ nhớ/Kỹ năng tải 15–20 giây, chỉ hiện
"Đang tải…" (không skeleton). Danh sách Việc tự chèn việc
mới lên đầu khi đang xem (thứ tự nhảy dưới tay người dùng)
và bị chặn ở 20 mục, không phân trang/chỉ báo.

## Q-05 Tab Hồ sơ quá tải
Một trang cuộn chứa: 2 thẻ lớn cạnh tranh nhau (Hồ sơ tím
đậm vs Bộ nhớ navy đậm) + 91 kỹ năng (mô tả phần lớn
tiếng Anh, nhiều mô tả vỡ chỉ còn ">" hoặc ">-") + 100
tài liệu, mỗi tài liệu 4 nút lộ thiên (Chia sẻ/Ghim/Sửa
tên/Xoá) = ~400 nút; nhấn tên tài liệu lại KHÔNG mở xem
trước. ~82/100 tài liệu cùng mốc "26/10/2026 12:41".
Thùng rác là trạng thái thay thế tại chỗ, không tiêu đề
riêng. Bộ nhớ ghi "810 fact" nhưng màn con chỉ là 1 khối
văn bản — không tìm kiếm/lọc/đếm đối chiếu được.

## Q-06 Màu vỡ chuẩn 60/30/10
Chấm xanh lá header; tim Heartbeat ĐỎ; pill "Đã lên lịch"
xanh lá; pill lỗi hồng/đỏ; 5 ô biểu tượng Cài đặt 5 màu;
6 ô màu chủ đề có cả "Xanh lá"; nút Xoá đỏ lặp 17 lần
(Vault) tới ~100 lần (thư viện). Trạng thái phải thể hiện
bằng chữ + phân cấp trung tính, tím là điểm nhấn duy nhất,
đỏ chỉ cho hành động phá huỷ CÓ xác nhận.

## Q-07 Cắt chữ khắp nơi
Tiêu đề việc/lịch cắt giữa từ (3 lịch "Quét TẤT CẢ…" gần
như giống hệt nhau, không phân biệt được); mô tả danh mục
chợ tiếng Anh bị cắt; mã tham chiếu Vault bị cắt không
sao chép được; lệnh chạy connector bị cắt.

## Q-08 Dữ liệu thử + nhãn trùng/kỹ thuật
Lịch sử phê duyệt chỉ có 2 bản ghi THỬ "Gửi thẻ phê duyệt
thử"; nhãn kỹ thuật thô trên UI ("the_duyet", "ask", "Lớp
policy", "download_and_run", slug tool). "Giờ yên lặng"
xuất hiện 2 lần trong màn Feed; "Đang nối"/"Đang bật"
trùng ý ở Công cụ kết nối; ô "Cron 5 trường" nhưng giá
trị có 6 trường ("0 8,12,17,20 * * *"); "Trang 1 / 2.101"
dễ đọc nhầm thập phân; vài hàng chợ thiếu số tool.

## Q-09 Màn Quyền rủi ro cao
Toàn bộ ~100+ quyền đều "Cho phép" — gồm `delete_vault_
secret`, `run_command`, `restart_bot`, gửi Gmail/tin
nhắn. "Đổi là áp dụng ngay" + dropdown = chạm nhầm là đổi
quyền thật, không xác nhận, không tổng quan "X/Y quyền
đang mở", không tìm kiếm/thu gọn nhóm. Chuẩn dự án (mục
F4): đọc = cho phép, ghi/xoá = hỏi — mặc định hiện tại
lệch chuẩn này.

## Q-10 Các màn con cần tách/gộp (bản đồ)
- Phê duyệt: tab chỉ giữ yêu cầu ĐANG CHỜ; Lịch sử thành
  màn con riêng có lọc theo kết quả.
- Lịch: mọi hàng lịch có màn chi tiết như Heartbeat (lịch
  sử chạy + chi tiết từng lượt, quyền, sửa, xoá có xác
  nhận); cron diễn giải tiếng Việt ("mỗi 5 phút").
- Hồ sơ -> 4 màn con (Hồ sơ agent theo từng file có mục
  lục; Bộ nhớ = danh sách fact tìm/lọc được; Kỹ năng giữ
  tìm kiếm đang tốt, dịch mô tả, ẩn đường dẫn; Thư viện =
  thẻ chỉ còn menu tràn ⋯, nhấn mở xem trước, Thùng rác
  thành màn con riêng).
- Chợ MCP: thêm TÌM KIẾM theo tên + lọc Local/remote/điểm
  bảo mật thay vì lật 2.101 trang; chi tiết connector là
  màn TỐT NHẤT app — lấy làm mẫu chuẩn.
- Vault: tách danh sách (chỉ xem) / chi tiết từng bí mật
  (sửa/xoá có xác nhận) / form thêm mới; tìm kiếm + nhóm
  theo dịch vụ.
- Feed: tách màn trạng thái (chỉ xem + "Chạy ngay" có xác
  nhận) khỏi form cài đặt; gộp các nút Lưu thành 1.
- Thiết bị & hệ thống: thêm lịch sử khởi động lại (app
  hiện "Đã chạy 2 phút" sau restart mà không giải thích).

## Hạ tầng ghi nhận trong buổi QA
Tunnel/app không ổn định: 1 lần trang chặn bot, 1 lần lỗi
502 phía host (00:36 UTC 17:36), bot khởi động lại nhiều
lần — khớp các việc "Đã lỗi: Tiến trình bị ngắt khi bot
khởi động lại". Một phần restart là do auto_watch nạp
commit AGENT_TASKS mới trong lúc QA đang chạy.

## Bổ sung của chủ dự án (27/10 ~00:58, từ dùng thật)
- Quyền của google-workspace nằm lăn lóc trong danh
  sách "Từng tool" phẳng của màn Quyền chung, thay vì
  nằm trong màn chi tiết của chính connector đó (bấm
  vào google-workspace là cấu hình được quyền của nó).
- Danh sách kỹ năng dài một cột, không nhóm/gập.
- Tổng thể chưa gọn gàng: nhiều màn là cột cuộn dài
  vô tận thay vì nhóm + màn con.

## Chưa kiểm chứng (ranh giới chỉ-đọc)
Hành vi công tắc lịch/connector/policy; hộp thoại xác
nhận sau các nút Xoá/Cài/Lưu/Chạy ngay; phân trang chợ
trang 2; chi tiết connector ở tab Đã cài; xem trước tài
liệu; chi tiết từng lượt chạy Heartbeat (chưa tồn tại).
