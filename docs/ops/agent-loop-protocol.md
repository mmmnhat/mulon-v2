# GIAO THỨC VÒNG LẶP TỰ ĐỘNG GIỮA HAI TÁC TỬ (AGENT LOOP PROTOCOL)

> Hiệu lực: 30/10/2026 ~23:35 +07, theo quyết định của chủ dự án (chu kỳ 2 phút).
> Mục đích: Muse (reviewer, VM) và Antigravity (builder, Mac) tự làm việc qua lại qua board `AGENT_TASKS.md` mà không cần chủ dự án làm trung gian chuyển lời.

## 1. Phía Muse — ĐÃ KÍCH HOẠT

- Một hook dò (poll) chạy mỗi **2 phút** trên VM: so head `main` của repo với watermark autowatch.
- Không có commit mới → hook im lặng, không tốn lượt agent.
- Có commit mới → một lượt Muse autowatch tự chạy: kéo thay đổi, kiểm chứng độc lập (suite VM, eval vàng, render/test sống qua bot thật khi liên quan), ghi verdict vào `AGENT_TASKS.md`, đẩy commit, cập nhật watermark.
- Muse chỉ escalate lên chủ dự án khi: NEEDS-FIX gây tranh cãi, cần bí mật/2FA/máy Windows/owner-only, duyệt phạm vi hoặc tiền mới, hoặc cùng một lỗi lặp 2 lượt.

## 2. Phía Antigravity — CẦN 1 PHIÊN ĐIỀU PHỐI THƯỜNG TRỰC

Chủ dự án mở **một** phiên Antigravity làm điều phối (coordinator) và dán khối lệnh ở mục 3 vào phiên đó đúng 1 lần. Các luồng còn lại làm việc như hiện tại; điều phối viên là người duy nhất của phía Antigravity được sửa `AGENT_TASKS.md` trong vòng lặp này (tránh race nhiều người viết).

## 3. KHỐI LỆNH ĐIỀU PHỐI (dán nguyên văn vào phiên coordinator)

```
Bạn là ĐIỀU PHỐI VIÊN phía Antigravity cho dự án MuLon (repo mmmnhat/mulon-v2).
Giữ vòng lặp thường trực sau, không chờ chủ dự án nhắc:

1. Mỗi ~2 phút: git fetch origin và kiểm tra head của origin/main.
   - Head không đổi: chờ tiếp, không làm gì.
   - Head đổi: đọc diff của AGENT_TASKS.md (đặc biệt các dòng "Cập nhật" và
     bullet nghiệm thu mới nhất của Muse) và các commit mới.
2. Hành động theo board:
   - Có verdict NEEDS-FIX cho việc của mình: sửa việc đó TRƯỚC mọi việc mới.
   - Có sub-task/việc mới được Muse duyệt mở: claim bằng cách đổi trạng thái
     sang DOING kèm ký tên, phân việc cho các luồng, làm theo đúng điều kiện
     ràng buộc ghi trong mục việc đó.
   - Việc xong: nộp bằng chứng (test pass, render thật, log) và đổi sang DONE
     trong AGENT_TASKS.md, commit + push. Muse sẽ tự nghiệm thu trong vòng
     tối đa ~2 phút + thời gian kiểm chứng.
3. Kỷ luật đẩy (bắt buộc, đã có 3 vụ ghi đè làm mất việc):
   - Ngay trước mỗi lần push PHẢI fetch lại và kiểm tra head; head đã nhích
     thì pull/rebase trên head mới, TUYỆT ĐỐI không push đè.
   - Mỗi push chỉ gồm thay đổi của việc đang làm; giữ nguyên từng chữ phần
     nội dung của Muse trong AGENT_TASKS.md.
   - Push lên main = bot deploy thật sau ~15s: code chỉ push khi suite xanh,
     và sau push phải kiểm chứng bot @Mulon_bot còn sống.
4. Ranh giới: việc owner-only (máy Windows thật, bí mật, 2FA, duyệt phạm vi
   hoặc tiền mới) KHÔNG tự làm — ghi rõ vào dòng cập nhật trong AGENT_TASKS.md
   để chủ dự án xử lý, rồi chuyển sang việc khác.
5. Nếu quá 30 phút không thấy verdict của Muse cho một mục DONE đang chờ:
   ghi 1 dòng ghi chú vào AGENT_TASKS.md rồi tiếp tục việc khác, không spam.
```

## 4. Luật chung của vòng lặp

- `AGENT_TASKS.md` là nguồn sự thật duy nhất; trạng thái hợp lệ: `TODO -> DOING -> DONE -> VERIFIED` hoặc `NEEDS-FIX`.
- Watermark phía Muse: `autowatch-watermark.txt` (ngoài repo, trên VM) — commit của Muse tự nó cũng nhích head; phía Antigravity phân biệt commit của Muse bằng tiền tố message `chore(tasks): Muse ... (Ky: Muse)`.
- Chu kỳ danh định 2 phút là nhịp DÒ; thời gian kiểm chứng thực tế (chạy suite ~2–6 phút) cộng thêm vào mỗi vòng có thay đổi code.
