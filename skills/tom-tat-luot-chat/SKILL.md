---
name: tom-tat-luot-chat
description: Tóm tắt một đoạn hội thoại dài thành các ý chính, quyết định đã chốt và việc còn treo, theo đúng cấu trúc 3 phần.
requires:
  env: []
  tools: [now]
---

# Tóm tắt lượt chat

Khi user nhờ tóm tắt một đoạn hội thoại dài (hoặc một phiên làm
việc), trả lời đúng 3 phần, không thêm phần thứ tư:

1. **Ý chính**: tối đa 5 gạch đầu dòng, mỗi dòng một ý, giữ nguyên
   con số và tên riêng như trong hội thoại gốc.
2. **Đã chốt**: các quyết định/cam kết đã thống nhất, kèm ai là
   người chốt nếu biết.
3. **Còn treo**: việc chưa xong hoặc câu hỏi chưa được trả lời,
   ghi rõ đang chờ ai.

Quy tắc:

- Không suy diễn thêm sự kiện ngoài hội thoại được đưa.
- Câu nào không chắc là "đã chốt" thì để ở phần "Còn treo".
- Độ dài tổng: dưới 300 chữ trừ khi user yêu cầu chi tiết hơn.
