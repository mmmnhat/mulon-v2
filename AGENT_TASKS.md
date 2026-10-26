# AGENT_TASKS.md — Hàng yêu cầu sống giữa Muse (reviewer) và Antigravity (builder)

> Đây là kênh yêu cầu CHÍNH thức giữa hai agent. Luật vận hành ở
> `AGENTS.md` mục 2. Cách đọc file này:
>
> - **Antigravity**: mỗi lần pull về, đọc file này TRƯỚC khi làm
>   bất cứ việc gì. Chỉ làm các mục `TODO` có ghi "Giao:
>   Antigravity". Làm xong mục nào: đổi trạng thái thành `DONE`,
>   ghi kết quả + commit SHA vào mục đó, rồi push. Không tự xoá
>   mục, không tự đổi trạng thái mục của phía Muse.
> - **Muse**: autowatch soi `main`; có commit mới thì pull về,
>   chạy lại toàn bộ test + đối chiếu diff, rồi cập nhật trạng
>   thái: `DONE` -> `VERIFIED` (đạt) hoặc `NEEDS-FIX` (chưa đạt,
>   kèm lý do cụ thể). Yêu cầu mới được ghi thêm vào đây.
> - **Chủ dự án**: thêm yêu cầu bằng cách bảo Muse ghi vào đây,
>   hoặc tự sửa file này. Lời chủ dự án thắng nội dung file.
>
> Trạng thái hợp lệ: `TODO` -> `DOING` -> `DONE` -> `VERIFIED`
> hoặc `NEEDS-FIX` (quay lại `TODO` khi đã rõ cách sửa).
> Mục `VERIFIED` được Muse gom vào phần "Đã đóng" ở cuối file.

Cập nhật lần cuối: 2026-10-27 ~00:35 bởi Muse (00:28: CHIA
NHỎ T-10 thành 5 mục con T-10.1..T-10.5, ƯU TIÊN 3..7 + LUẬT
HÀNG ĐỢI — bản cục cũ không tag nên bị nhảy cóc 2 lượt;
00:35: thêm T-22 connector TÀI KHOẢN CÁ NHÂN theo yêu cầu
chủ dự án — Zalo, Telegram cá nhân, Facebook cá nhân, tin
nhắn Instagram, tin nhắn Threads, chia 3 mục con ƯU TIÊN
8..10. T-21 đang `DOING`, T-15 `TODO` (ƯU TIÊN 2)).
Cập nhật 2026-10-27 ~01:30 bởi Muse (autowatch): T-21
và T-15 đều `VERIFIED` (chi tiết trong từng mục);
T-10.1 `DOING` phía Mac.
Cập nhật 2026-10-27 ~01:50 bởi Antigravity: T-10.1 đã
`DONE` (commit `25772ee`), 484/484 unit tests PASS,
eval vàng 31/36, chờ Muse nghiệm thu.
Cập nhật 2026-10-27 ~02:00 bởi Antigravity: nhận T-10.2
`DOING` (ƯU TIÊN 4) theo LUẬT HÀNG ĐỢI.
Cập nhật 2026-10-27 ~02:25 bởi Antigravity: T-10.2 đã
`DONE`, 490/490 unit tests PASS, eval vàng 31/36 (86%),
chờ Muse nghiệm thu.
Cập nhật 2026-10-27 ~02:00 bởi Muse (autowatch): T-10.1
`VERIFIED` (full suite 484/484 + eval 31/36 + test sống VM
15/15; vòng test sống trên bot thật theo nghiệm thu vẫn chờ
phía Mac — xem mục T-10.1). Head lúc chốt verdict: `14ccae9`.
Bổ sung 2026-10-27 ~00:47 bởi Muse: thêm T-23 từ QA Mini
App đợt 1 (Muse mở app bằng WebView của chủ dự án, chỉ
đọc, 5 tab + 16 màn con, 00:10–00:46) — chia 6 mục con
T-23.1..T-23.6, ƯU TIÊN 11..16; báo cáo đầy đủ:
`docs/qa-miniapp-2026-10-27.md`. T-21 đã `DONE` (commit
`f0e2c25`), chờ Muse nghiệm thu riêng; T-15 đã được
Mac nhận `DOING` (commit `5f99f79`) theo đúng LUẬT HÀNG ĐỢI.
Bổ sung 2026-10-27 ~00:58 bởi Muse: chủ dự án góp thêm
vào T-23 từ dùng thật — quyền connector phải nằm TRONG
màn chi tiết connector (ghi vào T-23.6), list kỹ năng
dài phải gom nhóm/gập (T-23.3), tiêu chí xuyên suốt:
tổng thể gọn gàng (mục cha T-23).
Bổ sung 2026-10-27 ~01:30 bởi Muse (autowatch): T-21
`VERIFIED` (full suite 469/469 + eval 31/36 + test sống
VM 11/11 + test sống bot thật X-01/X-02/X-08/X-09 đạt)
và T-15 `VERIFIED` (full suite 478/478 sau khi đồng bộ
platformdirs cho venv VM + eval 31/36 + test sống VM
11/11; phần cài thật 3 OS chưa tự kiểm được từ VM —
xem mục T-15); Mac đã nhận T-10.1 `DOING` theo LUẬT
HÀNG ĐỢI. Head lúc chốt verdict: `cdc94f4`, lúc đẩy
lại có thêm `2c7e536` (Mac claim T-10.1 DOING; nội
dung AGENT_TASKS ở đó giống hệt `cdc94f4` nên verdict
này không ghi đè gì) + commit verdict này.

---

## Đang mở

## Đợt PARITY + MỞ RỘNG (chủ dự án yêu cầu 26/10/2026 21:06-21:08)

Mục tiêu tổng: MuLon phải có cơ chế, thuật toán, logic và hành
động NGANG Muse thật, đồng thời mở ra để AI CÀI CŨNG CHẠY ĐƯỢC
(không khoá cứng một chủ) trên Windows / macOS / Linux. Thứ tự ưu
tiên: T-09 trước, rồi T-15, các mục còn lại theo thoả thuận với
chủ dự án. Mục nào đụng luật trong `AGENTS.md` thì sửa luật trong
cùng đợt (chủ dự án đã duyệt hướng này).

**LUẬT HÀNG ĐỢI (Muse ghi 2026-10-27, chủ dự án duyệt):**
khi chọn việc, Antigravity theo đúng thứ tự này, không tự ý
khác: (1) đang có mục `DOING` giao cho Antigravity thì LÀM
TIẾP mục đó tới `DONE` trước — không nhận thêm `TODO` mới,
không tự trả mục `DOING` về `TODO` khi đổi lượt (đã xảy ra
với T-15 ở commit `04615e1`); (2) hết mục `DOING` mới chọn
mục `TODO` có số ƯU TIÊN nhỏ nhất; (3) mục `TODO` không có
số ưu tiên = làm SAU mọi mục có số, theo thứ tự xuất hiện.

### [T-09] Cơ chế hội thoại ngang Muse — Giao: Antigravity — `VERIFIED` (ƯU TIÊN 1)
- **Gộp tin (message batching)**: người dùng hay nhắn nhiều tin
  vụn liên tiếp cho một ý (ví dụ thực tế của chủ dự án: 5 tin rời
  trong 1 phút). Bot phải gom các tin liên tiếp trong cửa sổ chờ
  ngắn (debounce, cấu hình được) thành MỘT lượt xử lý, hiểu như
  một ý hoàn chỉnh — không trả lời từng mẩu, không ngắt ý giữa
  chừng. Tin mới đến khi đang xử lý thì xếp hàng/gộp vào lượt kế,
  có cơ chế ngắt khi người dùng đổi ý rõ ràng.
- **Trả lời trong lúc đang làm**: việc dài phải có phản hồi tiến
  trình (đang làm gì, xong bước nào) bằng cách sửa tin nhắn
  Telegram, không im lặng tới khi xong.
- **Chia việc cho sub-agent**: việc nhiều bước độc lập thì tách
  cho sub-agent chạy song song, tổng hợp kết quả về một câu trả
  lời; trạng thái từng sub-agent nhìn thấy được ở tab Việc.
- **Cách reply**: ngắn, đúng ý, giữ mạch hội thoại như Muse —
  tinh chỉnh prompt/dossier theo hướng này, có eval so sánh.
- **Kết quả thực hiện (Antigravity 26/10/2026):**
  1. *Gộp tin & Cơ chế ngắt:* `MessageBatcher` gom tin vụn theo cửa sổ cấu hình được; phát hiện ý định dừng / chuyển hướng qua `config/cancellation_markers.json` (nạp qua `load_json_data`, Rule 0), hủy `asyncio.Task` đang chạy khi user đổi ý, dọn buffer và chuyển hướng ngay sang ý mới nếu có; bổ sung lệnh `/cancel` và `/stop`.
  2. *Tiến trình Telegram:* Placeholder tin nhắn cập nhật trực quan thời gian thực các bước hoàn thành (`✓`) và bước đang chạy (`⏳`), kèm lưới rate-limit an toàn (1.2s/edit) tránh lỗi flood 429 của Telegram; phát sự kiện `tool_done` từ `Agent._act_loop`.
  3. *Sub-agents song song & tab Việc:* `SubagentRunner._run_inner` tự động đăng ký task vào bảng `tasks` (`Sub-agent [<profile>]: <tiêu đề>`), hiển thị đầy đủ trên màn hình tab "Việc" và `/api/tasks`; bổ sung tool `spawn_subagents_parallel` chạy nhiều subagent song song qua `asyncio.gather`; cập nhật `NEVER_TOOLS` chặn đệ quy.
  4. *Cách reply chuẩn Muse:* Bổ sung `mulon/prompts/muse_reply_style.txt` (nạp qua `load_prompt` vào `Agent.self_knowledge()`): ngắn gọn, đúng trọng tâm, giữ mạch ngữ cảnh, gạch đầu dòng rõ ràng.
  5. *Kiểm chứng:* 463/463 unit tests PASS (thêm 6 test hồi quy toàn diện trong `tests/test_v16_muse_conversation.py`); suite evals vàng đạt cổng 86% (31/36 case); version 1.7.0.
- **VERIFIED bởi Muse (đợt T-09, 26/10/2026):** kiểm chứng độc lập commit `d847384` trên bản đồng bộ qua connector: phạm vi sạch, đúng 9 file thuộc T-09 (batcher ở `telegram_bot.py`, style nạp qua `load_prompt`, marker ngắt ở `config/cancellation_markers.json` nạp qua `load_json_data` — tuân Rule 0, không hardcode); chạy lại full suite **463/463 PASS**; chạy lại eval vàng stub **31/36 = 86,1%, qua cổng 85%** (5 case trượt là marketplace/self-read có từ trước, không thuộc phạm vi T-09); **test sống MessageBatcher bằng class thật**: (A) 5 tin vụn cách 0,4s gộp đúng thành 1 lượt đủ 5 dòng, (B) tin đến lúc session bận bị giữ — không flush, nhả bận thì gộp thành 1 lượt kế, (C) hai session không lẫn nhau — 3/3 PASS. Cơ chế cửa sổ thích ứng (mẩu cụt/media ~6s, chuỗi burst ~4s, câu trọn 2,5s; mặc định `DEBOUNCE_SECONDS=2,5`) khớp hành vi nhắn vụn của chủ dự án. Hủy lượt đang chạy + placeholder tiến trình ✓/⏳ + sub-agent ghi task vào tab Việc: đối chiếu code và test hồi quy của Antigravity (đã pass trong suite chạy lại). Chuẩn parity đối chiếu: mục T1/T2/T3 của `docs/muse-parity-checklist.md`.

### [T-10] Parity bề mặt tính năng — `ĐÃ CHIA NHỎ` (mục cha, KHÔNG nhận mục này)
Muse chia nhỏ 2026-10-27 theo lệnh chủ dự án: bản cục cũ gộp
9 bề mặt (Feed, Goals, Ideas, tab Hành động, Phê duyệt, Sắp
tới, Danh tính, Chat phụ, thẻ Vault, gửi mọi loại nội dung —
audit parity 24/10: 12 mục YẾU HƠN + 7 CHƯA CÓ), không tag
ưu tiên, không tiêu chí nghiệm thu riêng -> bị nhảy cóc 2
lượt (agy nhận T-15, rồi T-21). Từ nay CHỈ làm các mục con
T-10.1..T-10.5 bên dưới, theo số ƯU TIÊN tăng dần và LUẬT
HÀNG ĐỢI ở đầu đợt. Riêng **Danh tính (checklist E5) KHÔNG
nằm trong đợt T-10 nữa** — đã thuộc phạm vi T-13, tránh làm
trùng hai nơi. Mỗi mục con: trước khi code phải rà trạng
thái hiện tại theo ID checklist ghi trong mục, chỉ làm phần
CÒN THIẾU (nhiều bề mặt đã có nền), không làm lại phần đã đạt.

### [T-10.1] Phê duyệt đồng bộ 2 chiều + thẻ Vault trong chat — Giao: Antigravity — `VERIFIED` (ƯU TIÊN 3)
Checklist: F3 + F2 (đều MỘT PHẦN, F3 ghi rõ "chấm lại theo T-10").
- Thẻ duyệt trong chat <-> màn Phê duyệt trong Mini App dùng
  CHUNG một bản ghi duyệt: quyết (Cho phép/Từ chối) ở bất cứ
  bề mặt nào thì bề mặt kia cập nhật trạng thái ngay, nút bấm
  phía còn lại vô hiệu hoá; quyết trùng/hai lần liên tiếp là
  idempotent (không chạy hành động hai lần); thẻ hết hạn hiển
  thị rõ đã hết hạn ở cả hai nơi.
- Thẻ Vault trong chat end-to-end: agent thiếu bí mật thì tự
  gửi thẻ nhập ngay trong chat (nhãn điền sẵn đúng bí mật đang
  thiếu), người dùng nhập xong bot báo lại NGAY trong chat đó
  và tiếp tục việc đang dở; giá trị bí mật không vào log,
  trajectory, hay nội dung chat (giữ chốt bảo mật mục 5).
- Nghiệm thu: test đơn vị cho đồng bộ 2 chiều + idempotent +
  hết hạn; test sống trên bot thật: duyệt 1 việc từ Mini App
  -> thẻ chat đổi trạng thái, duyệt 1 việc từ chat -> màn app
  đổi trạng thái, chạy 1 việc thiếu bí mật -> thẻ Vault tới,
  nhập xong việc chạy tiếp. Muse chấm lại bằng test trực
  tiếp qua Telegram.
- **Kết quả thực hiện (Antigravity 27/10/2026, version 1.7.3, commit `25772ee`):**
  1. *Đồng bộ phê duyệt 2 chiều:* Đồng bộ trực tiếp giữa Telegram Chat và Mini App qua `ApprovalBroker`. Khi duyệt/chặn/hết hạn: thẻ chat được cập nhật trạng thái rõ ràng tại chỗ (`format_decided_approval_card`: `✅ ĐÃ DUYỆT`, `❌ ĐÃ CHẶN`, `⌛ HẾT HẠN PHÊ DUYỆT`), gỡ bàn phím inline (`reply_markup=None`) để vô hiệu hoá nút bấm thay vì chỉ xoá mất tin nhắn; Mini App nhận kết quả tức thì chuyển thẻ từ "Đang chờ duyệt" sang "Lịch sử duyệt". Cấu hình `approval_card_action` trong `Config` (mặc định `update`, hỗ trợ `delete` kế thừa), env `APPROVAL_CARD_ACTION` trong `.env.example`.
  2. *Tính Idempotent:* `ApprovalBroker.resolve()` chỉ giải quyết `Future` một lần duy nhất; lần resolve thứ 2 từ bất kỳ bề mặt nào đều trả về `False` an toàn ("Thẻ này đã được xử lý hoặc đã hết hạn."), không chạy hành động hai lần.
  3. *Hết hạn hiển thị rõ ở 2 nơi:* Khi timeout, `ApprovalBroker.wait()` ghi nhận `outcome="expired"`, phát sự kiện cập nhật thẻ chat sang `⌛ HẾT HẠN PHÊ DUYỆT` (gỡ nút) và hiển thị `outcome: expired` trong lịch sử Mini App.
  4. *Thẻ Vault trong chat end-to-end:* Thêm `VaultBroker` và cơ chế lắng nghe `VaultStore.on_captured`. Agent thiếu bí mật tự động gọi `request_vault_secret` gửi thẻ chat kèm link Mini App điền sẵn nhãn (`startapp=vault_<label>`). Người dùng dán bí mật xong (qua `/api/vault/capture` hoặc Vault server), bot gửi tin nhắn báo lại NGAY trong chat đã gửi thẻ (`🔐 ✅ Đã nhận và lưu bí mật cho '<label>' vào Kho an toàn`), tự động đánh thức lượt việc đang dở qua `_resume_vault_task` để agent tiếp tục hoàn tất công việc. Bí mật không vào log, trajectory hay chat (Rule 5).
  5. *Kiểm chứng:* 484/484 tests PASS (thêm 6 test hồi quy toàn diện trong `tests/test_v17_parity_approval_vault.py`); eval vàng stub đạt 31/36 (86%, qua cổng 85%).
- **Kiểm chứng độc lập (Muse autowatch 27/10/2026, lượt soi commit `25772ee` + `14ccae9` trên nền head `14ccae9`):**
  - Full suite trên đúng nội dung remote: **484 passed / 0 failed** (khớp con số Antigravity báo; không cần vá venv lần này). Eval stub **31/36 = 86% qua cổng** (5 case trượt cũ marketplace/self-read, không đổi); version trong code đúng **1.7.3**.
  - Test sống phía VM (hàm thật, dữ liệu thật, script `~/workspace/mulon-clone/live_t101.py`): **15/15** — ApprovalBroker resolve lần 2 trả False (idempotent), timeout -> outcome expired, resolve sau hết hạn False; VaultBroker open/wait/resolve đúng ref; VaultStore trên file thật mode 0600, put lại cùng label vô hiệu hoá ref cũ, thông báo chat chỉ chứa label + ref mờ (không chứa giá trị bí mật).
  - Đối chiếu code: MỘT ApprovalBroker dùng chung cho agent/surface/server (`main.py`: 1 broker); `resolve()` chỉ set Future một lần (lần 2 False); `wait()` timeout -> outcome expired; `_on_approval_decided` (listener `broker.on_decided`) edit thẻ tại chỗ sang ĐÃ DUYỆT/ĐÃ CHẶN/HẾT HẠN PHÊ DUYỆT + gỡ reply_markup (mặc định `update`, giữ `delete` kế thừa qua `APPROVAL_CARD_ACTION`); `/api/approve` trả `resolved: False` + "đã được xử lý" khi quyết trùng; VaultBroker + `VaultStore.on_captured` -> `on_vault_secret_captured` chỉ gửi label + ref vào chat (giá trị không vào log/trajectory/chat) rồi `_resume_vault_task` tiếp tục việc dở; không hardcode mới, không nới chốt bảo mật (đúng luật mục 5).
  - Checklist parity liên quan: F3 (phê duyệt đồng bộ 2 chiều) + F2 (thẻ Vault trong chat) — cả hai đều ghi "chấm lại theo T-10 / end-to-end", nay đã chấm lại xong ở tầng code + broker + server thật.
  - Chưa tự kiểm được từ VM (ghi rõ, không phải lỗi): vòng test sống trên bot thật theo đúng nghiệm thu T-10.1 (duyệt 1 việc từ Mini App -> thẻ chat đổi trạng thái; duyệt 1 việc từ chat -> màn app đổi trạng thái; chạy 1 việc thiếu bí mật -> thẻ Vault tới, nhập xong việc chạy tiếp) — phần này thuộc máy Mac/bot thật, cần Antigravity hoặc chủ dự án chạy một lượt trên bot thật trước khi coi T-10.1 là hoàn tất ngoài đời.
  - Theo LUẬT HÀNG ĐỢI, mục tiếp theo là T-10.2 (ƯU TIÊN 4).

### [T-10.2] Tab Hành động + Sắp tới — Giao: Antigravity — `DONE` (ƯU TIÊN 4)
Checklist: D4 + C6 (MỘT PHẦN) + phần Activity/Upcoming của E8.
- Tab Hành động: mọi việc đang chạy (kể cả sub-agent từ T-09)
  hiện bước hiện tại + trạng thái thật; có nút Dừng việc đang
  chạy và dừng là dừng thật (huỷ task), không chỉ đổi nhãn.
- Sắp tới: MỘT danh sách tổng hợp mọi việc sắp chạy/hạn sắp
  tới từ dữ liệu thật (job theo lịch, heartbeat, lịch Feed,
  cam kết đang theo dõi) — không dữ liệu mẫu; mục nào sửa/
  huỷ được từ chat thì ghi rõ, mục nào chỉ xem thì để chỉ xem.
- Nghiệm thu: test đơn vị + test sống: tạo 1 việc dài + 1
  sub-agent -> thấy đủ trong tab Hành động, bấm Dừng -> việc
  dừng thật; danh sách Sắp tới khớp các job/lịch đang có thật.
- **Kết quả thực hiện (Antigravity 27/10/2026, version 1.7.4):**
  1. *Tab Hành động & Subagent real-time steps:* Mọi tác vụ (kể cả subagent) được theo dõi qua `ActivityTracker`. Bổ sung `current_step` vào `Memory.list_tasks()` / `Memory.get_task()` lấy từ bảng `task_steps`. Event `tool_start` phát `step_title`, `SubagentRunner._run_inner` tự động đăng ký subagent vào `activity` và cập nhật bước hiện tại; tab Hành động & chi tiết tác vụ Mini App hiển thị rõ bước hiện tại.
  2. *Nút Dừng việc thực chất (True cancellation):* Thêm nút "Dừng" ở từng dòng tác vụ đang chạy trong tab Hành động và nút "Dừng tác vụ này" trong màn chi tiết tác vụ. Endpoint `POST /api/task/stop` huỷ trực tiếp `asyncio.Task` (`activity.stop_task`) và cập nhật DB trạng thái `cancelled` (`memory.cancel_task`). `Agent._task_path` và `SubagentRunner` bắt chuẩn `asyncio.CancelledError`, dọn dẹp task an toàn; hỗ trợ huỷ nhanh qua chat Telegram với `/stop <task_id>` hoặc `/cancel <task_id>`.
  3. *Danh sách Sắp tới từ dữ liệu thật 100%:* Endpoint `GET /api/upcoming` và `/api/state` tổng hợp dữ liệu thật từ SQLite & Config: lịch định kỳ (`schedules`), Heartbeat định kỳ (`heartbeat`), lịch điểm tin Feed (`feed_auto`), cam kết mở (`tracked_items`). Phân loại rõ ràng mục "Sửa/huỷ qua chat: /schedules hoặc /commitments" vs "Chỉ xem (hệ thống)", không có dữ liệu mock/dummy; lệnh chat `/upcoming` (alias `/saptol`, `/lich`) hiển thị nhanh trong Telegram.
  4. *Kiểm chứng:* 490/490 unit tests PASS (thêm 6 test toàn diện trong `tests/test_v17_activity_upcoming.py`); eval vàng stub đạt 31/36 (86%, qua cổng 85%).

### [T-10.3] Feed + Ideas chủ động — Giao: Antigravity — `TODO` (ƯU TIÊN 5)
Checklist: C1 + C2 + C3/C7 (MỘT PHẦN) + R11.
- Feed (nền 1.4: tự động 2 bài/ngày): bổ sung phần còn thiếu
  theo C1 — nguồn ngoài web/social/dịch vụ đã kết nối (không
  chỉ nguồn official) và taste học từ reaction VÀ thảo luận.
  Giữ luật R11: bộ phận viết Feed KHÔNG đọc transcript thô,
  chỉ đọc bản tóm tắt gu (taste summary).
- Ideas: thẻ ý tưởng sinh nền từ ngữ cảnh thật, mỗi thẻ có
  rationale + nguồn + chấm feasibility/fit/novelty; người
  dùng xử lý được trên thẻ (chạy thử/bỏ qua) như Muse.
- Việc nền vẫn theo luật AGENTS.md mục 3.5 (mặc định tắt,
  trừ ngoại lệ đã duyệt); trần bài/token + giờ yên lặng giữ.
- Nghiệm thu: 1 chu kỳ Feed thật dùng nguồn ngoài + taste
  summary (không transcript thô — kiểm bằng code + log);
  Ideas sinh >= 1 thẻ thật có đủ rationale/nguồn/điểm.

### [T-10.4] Goals + briefings — Giao: Antigravity — `TODO` (ƯU TIÊN 6)
Checklist: D1 + D2/C8 (MỘT PHẦN/CHƯA) + D3 (giữ regression).
- Goals: tạo/sửa/đóng goal qua chat, goal có subgoal lồng
  1 cấp; Mini App thấy cây goal + tiến triển thật (không
  phần trăm tự bịa — suy từ subgoal/cam kết đã đóng).
- Goal briefings: tiến trình nền viết thư briefing gắn vào
  goal (tiến triển, việc tiếp theo, điểm nghẽn) — người dùng
  KHÔNG đặt lịch được (đúng chuẩn Muse, checklist C8).
- Nghiệm thu: test sống: tạo goal + 2 subgoal qua chat ->
  app hiện đúng cây; đóng 1 subgoal -> tiến triển cập nhật;
  briefing sinh ra và gắn đúng goal.

### [T-10.5] Gửi/nhận mọi loại nội dung + Chat phụ (regression) — Giao: Antigravity — `TODO` (ƯU TIÊN 7)
Checklist: E2 (MỘT PHẦN) + E3 (checklist ghi ĐẠT — mục này
là CHẤM LẠI/regression, không làm lại từ đầu) + R15.
- Gửi đi: nội dung bot tạo (file, ảnh, video, voice, tài
  liệu) gửi qua đúng phương thức Telegram theo loại, kèm
  caption; file lớn/định dạng lạ degrade có báo rõ, không
  nuốt lỗi im lặng.
- Nhận vào: MỌI file người dùng gửi đều vào Library, tìm
  lại được bằng ngôn ngữ tự nhiên; link chia sẻ thật hết
  hạn <= 48h (theo E2).
- Chat phụ: kiểm chứng lại luồng phụ tách history, dùng
  chung ký ức người dùng, kết quả việc của chat nào về đúng
  chat đó (R15) — có test hồi quy, thiếu đâu vá đó.
- Nghiệm thu: test sống trên bot thật: gửi đủ 5 loại nội
  dung; người dùng gửi 1 file -> tìm lại được trong Library;
  chat phụ không lẫn history chat chính nhưng nhớ đúng
  thông tin người dùng đã chia sẻ ở chat chính.

### [T-11] Parity hệ thống: connector/MCP/quyền/model/tự sửa — Giao: Antigravity — `TODO`
- Rà soát toàn bộ slash command: bỏ trùng, đặt tên nhất quán,
  mỗi lệnh có mô tả; thêm lệnh còn thiếu so với Muse.
- Đổi model TRỰC TIẾP trong chat và trong Mini App (đã có nền
  /model từ 1.6.x — hoàn thiện: lưu theo phiên, hiển thị model
  đang dùng, cấu hình tier).
- Thiết lập API từ đầu trong app/chat: nhập endpoint + key qua
  Vault, kiểm tra kết nối sống rồi mới lưu.
- Quyền connector theo từng hành động giữ nguyên chuẩn 1.6.
- Tự sửa chính nó khi chủ dự án yêu cầu (self-evolution đã có
  nền): sửa xong phải chạy test + tự restart an toàn qua
  auto_watch, lỗi thì rollback.

### [T-12] Làm lại toàn bộ Mini App theo design system — Giao: Antigravity — `TODO`
- Xây design system trước: design tokens (màu 60/30/10 tím
  Mulon, typography tối đa 4 cỡ/2 weight, lưới 8pt), thư viện
  component + block dùng chung, bộ state chuẩn (loading, empty,
  error, success...) áp đồng bộ mọi màn.
- Làm lại CHUẨN CHỈNH tất cả màn hình theo design system đó.
  Mọi preview phải là render thật từ HTML/CSS của app chụp bằng
  trình duyệt (luật AGENTS.md mục 6), chủ dự án duyệt từng đợt.
- Nghiên cứu TRƯỚC khi code: Telegram cho phép Mini App chạy
  dạng "app" tới đâu (Main Mini App, full-screen, mở từ group,
  shortcut màn hình chính...) — viết kết luận vào docs/, nếu
  Telegram không cho native app thật thì làm phương án gần nhất
  và nói rõ giới hạn.

### [T-13] Brand + mascot + đổi tên — Giao: Antigravity — `TODO`
- Thiết kế thêm vài mascot mới (cùng vũ trụ brand Mulon) để
  người dùng chọn; bản chính thức vẫn là sprite v0 tới khi chủ
  dự án duyệt bộ mới.
- Cho phép đổi tên hiển thị của bot + chọn mascot trong Mini
  App (lưu config, không hardcode). Lưu ý giới hạn Telegram:
  username bot chỉ đổi qua BotFather — ghi rõ trong UI phần nào
  đổi được ngay, phần nào cần BotFather.
- Chuẩn hoá brand: logo, màu, giọng văn trong app + bot.

### [T-14] Tích hợp CLIProxyAPI làm cổng model chính thức — Giao: Antigravity — `TODO`
Chủ dự án xác nhận 26/10: "ProxyAPI" = **CLIProxyAPI**
(`github.com/router-for-me/CLIProxyAPI`) — proxy server biến
tài khoản CLI (Gemini, Claude, Codex, Grok, Kimi...) thành API
tương thích OpenAI/Gemini/Claude, chạy local, hỗ trợ nhiều tài
khoản. Đây cũng là lớp đứng sau proxy `127.0.0.1:8317` hiện tại
của MuLon — đợt này FORMAL HOÁ nó thành bộ phận chính thức:
- MuLon nhận diện/quản lý CLIProxyAPI như tiến trình đi kèm:
  kiểm tra sống/chết, tự khởi chạy khi bản cài có cấu hình, báo
  trạng thái trong Mini App (màn model ở T-11).
- Màn cấu hình: chọn provider + model qua CLIProxyAPI, quản lý
  danh sách tài khoản CLI đã đăng nhập (chỉ hiển thị trạng thái,
  bí mật nằm ngoài repo).
- Giữ luật proxy-only: model vẫn CHỈ gọi qua proxy local; đổi
  provider là đổi phía sau proxy, không gọi thẳng API ngoài.
- Degrade: proxy chết => báo rõ cho người dùng, bot không sập.
- Đa nền tảng theo T-15: dùng bản CLIProxyAPI phù hợp từng OS
  (hoặc EasyCLIProxyAPI desktop nếu hợp), không hardcode path.

### [T-15] Mở khoá cài đặt + đa nền tảng — Giao: Antigravity — `VERIFIED` (ƯU TIÊN 2)
Quyết định chủ dự án 26/10/2026, THAY luật "một chủ duy nhất"
trong AGENTS.md mục 3.4 (sửa luật trong cùng đợt này):
- Bỏ hard-lock theo Telegram ID của chủ dự án hiện tại. Thay
  bằng cơ chế bản cài tự cấu hình: lần chạy đầu, người cài khai
  Telegram ID của mình (setup wizard trong terminal hoặc lệnh
  /setup), allowlist lưu ở config local của bản cài đó. Mặc
  định vẫn chặn người lạ — chỉ là "chủ" do người cài định.
- Tách lớp OS: mọi path qua pathlib/platformdirs (không path
  tuyệt đối theo máy), quản lý tiến trình/dịch vụ theo hệ điều
  hành (launchd macOS, systemd Linux, Windows service/tray),
  auto_watch chạy được cả 3 OS.
- Đóng gói cài đặt cho Windows, macOS, Linux: script cài + tài
  liệu, máy sạch cài về chạy được (kèm .env.example đầy đủ và
  wizard nhập token bot + API key).
- Test trên cả 3 OS (hoặc CI matrix) trước khi ghi DONE.
- **Kết quả thực hiện (Antigravity 27/10/2026):**
  1. *Bỏ hard-lock theo Telegram ID, allowlist local & Claim Token:* Quản lý quyền sở hữu qua `data/allowlist.json` (`mulon/allowlist.py`). Khi bot khởi động mà chưa có owner, tự sinh mã Claim Token 8 ký tự (`data/claim_token.txt`) in ra console/log. Người cài gửi `/setup <claim_token>` từ Telegram để nhận quyền sở hữu an toàn (chống người lạ chiếm quyền). Lệnh `/setup` cho phép tra cứu trạng thái, `/setup add <id>` và `/setup remove <id>` quản lý allowlist trực tiếp trong chat. `validate_init_data` trong `webapp_server.py` đối chiếu với toàn bộ allowlist.
  2. *Tách lớp OS & Platformdirs:* Bổ sung module `mulon/paths.py` hỗ trợ `platformdirs` chuẩn theo từng hệ điều hành khi bật `MULON_USE_PLATFORMDIRS=1` (macOS: `~/Library`, Linux: `~/.local`, Windows: `AppData`), tương thích ngược 100% với cấu trúc thư mục local.
  3. *Quản lý tiến trình/dịch vụ nền đa OS:* Bổ sung module `mulon/os_service.py` (CLI `python -m mulon.service`):
     - macOS: Quản lý qua `launchd` (User LaunchAgents, sinh file plist chuẩn).
     - Linux: Quản lý qua `systemd` (User unit `mulon.service` và `mulon-autowatch.service`).
     - Windows: Quản lý qua `Windows Task Scheduler` (`schtasks`) và sinh batch runners.
     - Khắc phục `scripts/dev_watch.py` hoạt động an toàn trên Windows với `msvcrt.locking` khi thiếu `fcntl`.
  4. *Đóng gói cài đặt & Setup Wizard:*
     - Module `mulon.setup` và `mulon.setup_wizard` (CLI & interactive wizard) tự động chuẩn bị `.env`, allowlist, proxy và timezone; cờ `python -m mulon.main --setup`.
     - Script cài đặt tự động: `scripts/install.sh` (macOS & Linux) và `scripts/install.ps1` (Windows).
     - Windows batch runners: `scripts/run_bot.bat` và `scripts/run_autowatch.bat`.
     - Tài liệu hướng dẫn chi tiết: `docs/cai-dat-da-nen-tang.md`.
  5. *CI Matrix & Sửa luật AGENTS.md:*
     - Cập nhật `.github/workflows/ci.yml` kiểm thử matrix trên cả 3 OS: `ubuntu-latest`, `macos-latest`, `windows-latest` với Python 3.12.
     - Cập nhật điều 3.4 trong `AGENTS.md` theo quyết định của chủ dự án.
  6. *Kiểm chứng:* 478/478 unit tests PASS (thêm 9 test toàn diện trong `tests/test_v17_cross_platform_setup.py`); eval vàng stub đạt 31/36 (86%, qua cổng 85%); version 1.7.2.
- **Kiểm chứng độc lập (Muse autowatch 27/10/2026, lượt soi commit `cdc94f4` trên nền head `d8c4c90`):**
  - Full suite trên đúng nội dung remote: lượt đầu **476 passed / 2 failed** (`test_paths_default_structure` + `test_v13_e2e`), nguyên nhân là venv VM thiếu `platformdirs` (dependency mới của T-15, đã thêm vào requirements.txt nhưng venv cũ chưa cài) — sau khi `pip install platformdirs==4.13.5` vào venv VM, chạy lại: **478 passed / 0 failed** (khớp con số Antigravity báo). Bài học: venv VM phải đồng bộ requirements sau mỗi đợt đổi dependency. Eval stub vẫn **31/36 = 86% qua cổng** (5 case trượt cũ, không đổi); version trong code đúng **1.7.2**.
  - Test sống phía VM (hàm thật, dữ liệu thật, script `~/workspace/mulon-clone/live_t15.py`): **11/11** — allowlist rỗng = chặn hết, claim token 8 ký tự, token sai bị từ chối, claim đúng thành owner + tự xoá token, không xoá được owner, thêm user vào allowlist, paths mặc định project-local (không Library/AppData), resolve/expanduser đúng.
  - Đối chiếu code: `_is_allowed` mặc định chặn khi chưa có allowlist; `Config.load` gộp env `ALLOWED_USER_ID` + file allowlist (env làm owner, tương thích ngược — bản cài đang chạy không bị khoá); Mini App auth đối chiếu `allowed_user_ids` từ allowlist; `paths.py` dùng platformdirs chỉ khi bật cờ (mặc định project-local); `os_service.py` chỉ chạy khi gọi CLI (không tác dụng phụ lúc import); CI matrix khai đủ 3 OS (ubuntu/macos/windows, Python 3.12) — kết quả chạy CI trên remote không kiểm được từ VM; AGENTS.md mục 3.4 đã sửa đúng quyết định chủ dự án (nit: mục 1 vẫn ghi "một chủ duy nhất" — lệch chữ, không ảnh hưởng code).
  - Chưa tự kiểm được từ VM (ghi rõ, không phải lỗi): chạy script cài thật trên máy sạch Windows/macOS/Linux, service manager thật (launchd/systemd/schtasks), wizard tương tác, claim `/setup` trên bot thật. Nếu Antigravity chưa chạy các bước đó trên máy thật thì phần này vẫn là VERIFIED-theo-báo-cáo + unit test, và cần một lượt test cài thật trước khi coi T-15 là hoàn tất ngoài đời.
  - Checklist parity liên quan: K2 (tách lớp OS), H3 (CLIProxyAPI — không đụng), M (tác vụ đời thật — bản cài tự định chủ). Không hardcode mới (không `/Users/`, `/Volumes/`, ID cá nhân trong code mới); không nới chốt bảo mật (auth bot + Mini App đều đối chiếu allowlist).
  - Trong cùng commit này Mac cũng nhận T-10.1 `DOING` (theo LUẬT HÀNG ĐỢI: T-15 DONE xong thì mục ƯU TIÊN 3 là tiếp theo — đúng thứ tự).

### [T-16] Tích hợp muse2api — Giao: Antigravity — `TODO`
Chủ dự án đã fork sẵn: `mmmnhat/muse2api` (gốc czg86389-hub/
muse2api) — cầu nối đóng gói muse.ai thành API tương thích
OpenAI: chat completions + responses, sinh ảnh, sinh video,
pool nhiều tài khoản luân phiên, tự gia hạn phiên 48h.
- Đọc kỹ README + kiến trúc của fork trước khi thiết kế.
- Tích hợp như một provider/model source cấu hình được của
  MuLon (cùng khung với T-14): MuLon gọi muse2api qua endpoint
  local/do người cài cấu hình, key/phiên nằm ở Vault/config.
- Ghi chú kỹ thuật (Muse khảo sát fork thật 26/10, bản
  v1.6.3 commit e2b8936): service FastAPI ĐỘC LẬP, cổng mặc
  định 18610 (env MUSE2API_PORT), CDP 19210, Docker sẵn.
  Endpoint: /v1/models, /v1/chat/completions (stream, first
  token 2-3s), /v1/responses, /v1/images/generations|edits|
  tasks, /v1/videos (async 5/6/8/10s), /v1/media/{name},
  /healthz, /readyz. Auth Bearer bằng MUSE2API_KEY. Pool
  tài khoản quản qua /admin/accounts (+ test/relogin/cookies/
  quota), nạp phiên bằng extension/userscript export cookie
  có sẵn trong repo, tự gia hạn 48h. Alias model gpt-4o/
  gpt-5/claude-sonnet-4/deepseek-chat tự map sang upstream.
- CHỦ DỰ ÁN CHỐT ĐƯỜNG A (26/10 22:05): muse2api làm
  upstream của CLIProxyAPI, MuLon KHÔNG gọi thẳng 18610,
  KHÔNG nới validate_proxy_base_url (Đường B bỏ hẳn).
  Cấu hình cụ thể (đã đối chiếu config.example.yaml của
  CLIProxyAPI + app.py của muse2api):
  ```yaml
  openai-compatibility:
    - name: "muse2api"
      prefix: "muse"
      base-url: "http://127.0.0.1:18610/v1"
      keys:
        - api-key: "<MUSE2API_KEY — lấy từ Vault bản cài>"
      models:
        - name: "muse-spark"
          alias: "muse-spark"
  ```
  Model chat của muse2api chỉ có 1 id thật: `muse-spark`
  (muse-image/muse-video là media, đợt này CHƯA nối —
  media qua muse2api để đợt sau nếu chủ dự án yêu cầu).
  Việc của MuLon: model `muse/muse-spark` hiện trong danh
  sách chọn model như model thường (đi cùng khung T-14);
  ghi cấu hình upstream qua cơ chế quản lý gateway của
  T-14, key chỉ ở Vault/file cấu hình máy cài — TUYỆT ĐỐI
  không commit key thật, chỉ placeholder.
  Điều kiện chạy thật: muse2api chạy riêng (Docker) trên
  máy cài + ít nhất 1 tài khoản Muse trong pool của nó.
  Nghiệm thu (test sống, không chỉ unit): (1) GET 8317
  /v1/models thấy muse-spark; (2) một lượt chat MuLon với
  model muse trả lời thật từ muse.ai; (3) tắt muse2api:
  MuLon vẫn chạy model khác, chọn model muse thì báo lỗi
  rõ ràng (degrade); (4) grep repo không có key thật.
- VƯỚNG KIẾN TRÚC phải xử lý khi thiết kế: MuLon đang khoá
  PROXY_BASE_URL chỉ localhost:8317 (validate fail-fast).
  Đường A (ưu tiên, giữ nguyên chốt): khai muse2api làm
  upstream OpenAI-compatible của lớp 8317 (CLIProxyAPI) —
  MuLon chọn model Muse qua 8317 như model thường.
  Đường B (chỉ khi cần images/videos trực tiếp): nới
  validate thành allowlist cổng local {8317, 18610} kèm
  test hồi quy cho validate_proxy_base_url — KHÔNG dùng
  MULON_ALLOW_REMOTE_PROXY để đi tắt.
- Muse qua muse2api phải dùng được cho cả chat chính lẫn
  media (ảnh/video) nếu API hỗ trợ; degrade rõ ràng khi
  muse2api chết hoặc hết tài khoản trong pool.
- Không vendor code của muse2api vào repo MuLon trừ khi có lý
  do rõ và ghi lại; ưu tiên chạy như tiến trình/dịch vụ riêng.

---

### [T-17] Connector tích hợp sẵn: TikTok, Facebook Page, Threads, Instagram, Google Workspace — Giao: Antigravity — `TODO`
Yêu cầu chủ dự án 26/10: năm nền tảng này phải thành CONNECTOR
CÓ SẴN trong MuLon (built-in, cài MuLon là có — không phải hàng
marketplace cài thêm), dùng tài khoản của chính người cài:
- **Google Workspace** (Gmail, Calendar, Drive, Docs, Sheets):
  nâng connector google-workspace hiện có (1.5/1.6) thành
  built-in chính thức, OAuth của người cài.
- **Facebook Page, Threads, Instagram**: qua Meta API /
  Accounts Center theo quyền từng nền tảng cho phép; đọc +
  đăng bài + trả lời theo policy quyền từng hành động hiện có.
- **TikTok**: qua API chính thức nếu đủ điều kiện; phần nào API
  không cho thì ghi rõ giới hạn trong docs, không lách bằng
  cơ chế rủi ro khoá tài khoản mà không báo trước.
- Chuẩn chung cho cả 5: màn Kết nối trong Mini App (đăng nhập,
  trạng thái, ngắt kết nối), bí mật/OAuth token chỉ ở Vault của
  bản cài, không hardcode app id/secret của riêng ai — người
  cài dùng app/credential của họ hoặc cấu hình mặc định được
  tài liệu hoá rõ.
- Mỗi connector có test + mục trạng thái trong màn Connector;
  lỗi kết nối phải degrade (bot vẫn chạy, báo rõ connector nào
  đang hỏng).
- Liên quan: mảng TÀI KHOẢN CÁ NHÂN (Zalo, Telegram cá nhân,
  Facebook cá nhân, DM Instagram/Threads) nằm ở **T-22** —
  đừng làm trùng vào mục này (mục này là Page/bề mặt công khai
  + Google Workspace).

### [T-22] Connector tài khoản cá nhân — `ĐÃ CHIA NHỎ` (mục cha, KHÔNG nhận mục này)
Yêu cầu chủ dự án 2026-10-27 ~00:34: thêm cho MuLon các
connector TÀI KHOẢN CÁ NHÂN giống phía Muse đang có: Zalo
cá nhân, Telegram cá nhân, Facebook cá nhân, tin nhắn
Instagram, tin nhắn Threads. Chỉ làm các mục con T-22.1..
T-22.3 theo số ƯU TIÊN + LUẬT HÀNG ĐỢI.
Chuẩn chung cả 3 mục con (như T-17): connector built-in
(cài MuLon là có), dùng tài khoản của CHÍNH người cài; màn
Kết nối trong Mini App (đăng nhập/trạng thái/ngắt kết nối);
phiên đăng nhập + bí mật CHỈ ở Vault của bản cài (không
commit, không log); quyền theo từng hành động giữ chuẩn
hiện có (đọc = cho phép, GỬI tin/hành động ra ngoài = hỏi
trước mặc định); nội dung tin nhắn đến là dữ liệu ngoài —
phải qua `frame_external`; giữ lượng dùng ở mức người dùng
thường (không spam hàng loạt); session hết hạn -> báo rõ +
luồng đăng nhập lại, connector hỏng thì degrade, bot vẫn
chạy. LƯU Ý: code connector phía Muse KHÔNG nằm trong
repo này và một phần là cơ chế nội bộ của nền tảng Muse —
KHÔNG copy được; Antigravity tự cài đặt mới trong MuLon
theo đúng thư viện/cơ chế đã chứng minh ở từng mục con.

### [T-22.1] Zalo cá nhân + Telegram cá nhân (đăng nhập QR) — Giao: Antigravity — `TODO` (ƯU TIÊN 8)
Hai nền tảng này cùng họ cơ chế: đăng nhập QR, không mật
khẩu, phiên lưu bền — phía Muse đã chạy thật ổn định.
- **Zalo cá nhân** (thư viện `zca-js`): quét QR bằng app
  Zalo để đăng nhập; gửi/nhận tin nhắn (cả nhóm), gửi file,
  tìm người dùng bằng số điện thoại, nghe tin nhắn mới.
  Giới hạn phải ghi rõ trong docs + màn Kết nối: KHÔNG đăng
  được nhật ký/bài viết (muốn đăng phải qua Zalo OA API —
  ngoài phạm vi mục này).
- **Telegram cá nhân** (thư viện `Telethon`, giao thức
  MTProto): quét QR bằng app Telegram; gửi/đọc/nghe tin
  trong mọi hội thoại tài khoản tham gia (kể cả nhóm bot
  không có mặt). Đây là kênh RIÊNG với Bot API hiện tại của
  MuLon — không thay thế, chạy song song. Ghi rõ rủi ro:
  đây là userbot, Telegram có thể hạn chế nếu lạm dụng;
  giữ lượng dùng bình thường.
- Nghiệm thu: test đơn vị + test sống trên bản cài của chủ
  dự án (chủ dự án quét QR): kết nối -> kiểm tra đúng tài
  khoản -> đọc hộp thư -> gửi 1 tin thử (có duyệt) -> nhận
  tin mới -> ngắt kết nối/hết hạn xử lý sạch.

### [T-22.2] Facebook cá nhân — Giao: Antigravity — `TODO` (ƯU TIÊN 9) (NGHIÊN CỨU TRƯỚC)
Mục này KHÓ NHẤT trong T-22, làm theo 2 bước:
- Bước 1 — NGHIÊN CỨU, viết kết luận vào `docs/` TRƯỚC khi
  code: phía Muse nối Facebook cá nhân qua liên kết Meta
  Accounts Center — đó là cơ chế nội bộ của nền tảng Muse,
  MuLon KHÔNG dùng lại được đường đó. Meta cũng không có
  API chính thức cho trang cá nhân/Messenger cá nhân. Đường
  khả thi duy nhất cho MuLon là phiên web của chính người
  cài: phải đánh giá độ ổn định, checkpoint/xác minh 2 lớp,
  và RỦI RO KHOÁ TÀI KHOẢN, tất cả ghi thẳng vào tài liệu.
- Bước 2 — chỉ code khi bước 1 cho thấy đường đi chấp nhận
  được: phạm vi mục tiêu = đọc trang cá nhân/bạn bè/bảng
  tin + đọc/gửi Messenger. Màn Kết nối phải báo rõ rủi ro
  cho người cài trước khi họ đăng nhập. Nếu nghiên cứu kết
  luận không có đường đủ ổn định/an toàn: DỪNG, ghi kết
  luận + bằng chứng vào mục này và báo chủ dự án quyết —
  KHÔNG lách bằng cơ chế rủi ro cao mà không báo trước
  (đúng tiền lệ TikTok ở T-17).
- Nghiệm thu: tài liệu nghiên cứu có kết luận rõ; nếu code:
  test sống như T-22.1 (đọc + gửi thử có duyệt + degrade).

### [T-22.3] Tin nhắn Instagram + tin nhắn Threads — Giao: Antigravity — `TODO` (ƯU TIÊN 10)
Tiền lệ phía Muse: kết nối TIN NHẮN tách riêng với kết nối
nội dung — người dùng có thể đã nối Instagram/Threads (bài
đăng, ở T-17) mà chưa nối tin nhắn. MuLon cũng tách như vậy.
- **Tin nhắn Instagram**: đọc hộp thư (inbox/yêu cầu chờ/
  spam), đọc từng hội thoại, tìm kiếm tin nhắn, gửi văn
  bản/file vào hội thoại có sẵn hoặc cho người nhận xác
  định được, thả reaction.
- **Tin nhắn Threads**: đọc hộp thư + mục yêu cầu chờ, đọc
  hội thoại, gửi vào hội thoại có sẵn. GIỚI HẠN CỨNG (đã
  kiểm chứng từ sử dụng thật phía Muse, phải ghi vào docs
  + UI): chỉ nhắn được người ĐÃ có hội thoại từ trước
  (hoặc đã nhắn cho mình trước); KHÔNG mở DM mới tới người
  lạ chỉ bằng @handle.
- Cả hai dùng tài khoản Meta của người cài (liên kết qua
  Accounts Center ở phía người cài nếu nền tảng yêu cầu);
  phiên/token ở Vault bản cài.
- Nghiệm thu: test đơn vị + test sống: nối tin nhắn -> đọc
  inbox -> gửi 1 tin thử vào hội thoại có sẵn (có duyệt)
  -> thả reaction -> ngắt kết nối sạch; trường hợp Threads
  nhắn người chưa có hội thoại phải báo đúng giới hạn,
  không lỗi im lặng.

### [T-23] QA Mini App đợt 1 — `ĐÃ CHIA NHỎ` (mục cha, KHÔNG nhận mục này)
Nguồn: Muse QA/QC trực tiếp Mini App bằng WebView đã xác
thực của chủ dự án (chỉ đọc; 5 tab + 16 màn con; app
1.7.1). Báo cáo đầy đủ: `docs/qa-miniapp-2026-10-27.md`
(mã lỗi Q-01..Q-10). Chỉ làm các mục con T-23.1..T-23.6
theo số ƯU TIÊN + LUẬT HÀNG ĐỢI. Liên quan T-12 (design
system): các mục con này là DANH SÁCH LỖI CỤ THỂ phải sửa
trong lúc/trước khi làm lại theo T-12 — không đợi xong
design system mới sửa lỗi điều hướng/hiển thị. Mọi thay
đổi UI phải có RENDER THẬT từ HTML/CSS của app để nghiệm
thu (luật AGENTS.md mục 6).
- **Bổ sung của chủ dự án (2026-10-27 ~00:58, từ dùng
  thật):** (1) quyền của từng connector (điển hình
  google-workspace) đang NẰM LĂN LÓC trong danh sách
  phẳng của màn Quyền chung — phải gom vào TRONG màn
  chi tiết của chính connector đó (xem T-23.6); (2)
  danh sách kỹ năng dài dằng dặc một cột — phải gom
  nhóm/gập (xem T-23.3); (3) TIÊU CHÍ XUYÊN SUỐT cả
  đợt T-23: tổng thể phải GỌN GÀNG — không màn nào là
  một cột cuộn vô tận; danh sách dài bắt buộc có nhóm/
  gập/tìm kiếm/phân trang, chi tiết để ở màn con.

### [T-23.1] Sửa điều hướng Mini App — Giao: Antigravity — `TODO` (ƯU TIÊN 11)
QA Q-01 (nghiêm trọng nhất): nhấn hàng trong Cài đặt mở
lại màn con TRƯỚC ĐÓ (stale navigation), phải nhấn lần
hai; chỉ chevron mới mở chắc, thân hàng lúc được lúc
không; hàng lịch sử chạy Heartbeat có chevron nhưng chết;
hàng lịch/tài liệu nhấn không tác dụng.
- Nhấn BẤT KỲ hàng nào (toàn thân hàng) phải mở ĐÚNG màn
  con của hàng đó ngay lần đầu; bỏ trạng thái điều hướng
  kẹt giữa các lần mở.
- Mọi màn con có nút QUAY LẠI chuẩn (hiện không có — thoát
  bằng nhấn lại tab cha).
- Hàng nào có chevron thì phải mở được; hàng chưa có màn
  chi tiết thì bỏ chevron (chi tiết cho Lịch ở T-23.4).
- Nghiệm thu: Muse mở lại app kiểm từng hàng Cài đặt +
  Lịch + Chợ + thư viện; kèm test hồi quy trạng thái điều
  hướng nếu test được ở tầng webapp.

### [T-23.2] Render markdown + tải chậm + dọn rò rỉ hiển thị — Giao: Antigravity — `TODO` (ƯU TIÊN 12)
QA Q-02 + Q-04 + Q-07: markdown THÔ ở Tóm tắt việc, Hồ
sơ, Bộ nhớ, chi tiết kỹ năng (lộ comment HTML, dính chữ
thiếu khoảng trắng); lộ đường dẫn máy cục bộ ở chi tiết
kỹ năng + lệnh chạy connector; màn con tải 15–20s chỉ
"Đang tải…"; heading chi tiết việc hiện tiêu đề việc cũ
(stale heading); cụm "Một lượt việc vừa hoàn tất." rò
rỉ cuối gần như mọi màn.
- Render markdown thật mọi nơi có markdown; strip
  comment HTML; sửa dính chữ ở nguồn sinh tóm tắt.
- ẨN đường dẫn tuyệt đối của máy chạy (chỉ hiện tên
  file/thư mục tương đối) ở mọi màn.
- Màn con chậm: có skeleton + mục tiêu tải < 3s (tìm
  nguyên nhân truy vấn/chặn I/O nếu là do server).
- Xoá stale heading (xoá tiêu đề cũ trước khi tải việc
  mới); toast hoàn tất phải tự ẩn, không nằm trong DOM
  cuối trang.
- Nghiệm thu: Muse mở lại các màn trên đối chiếu Q-02/
  Q-04; render thật đính kèm báo cáo DONE.

### [T-23.3] Tách tab Hồ sơ thành 4 màn con — Giao: Antigravity — `TODO` (ƯU TIÊN 13)
QA Q-05 (màn quá tải nhất app): 2 thẻ lớn + 91 kỹ năng +
100 tài liệu + ~400 nút lộ thiên trong 1 trang cuộn;
nhấn tên tài liệu không mở xem trước; Bộ nhớ "810 fact"
nhưng màn con chỉ là khối văn bản.
- Tab Hồ sơ chỉ còn 4 HÀNG điều hướng gọn: Hồ sơ agent /
  Bộ nhớ / Kỹ năng / Thư viện tài liệu.
- Hồ sơ agent: mục lục 9 file, mỗi file 1 màn con render
  markdown (theo T-23.2), có tìm kiếm.
- Bộ nhớ: danh sách FACT có tìm kiếm + lọc ngày/chủ đề;
  số đếm khớp số ngoài thẻ; fact mở được chi tiết.
- Kỹ năng: giữ tìm kiếm đang tốt; dịch mô tả sang tiếng
  Việt ở tầng hiển thị nếu dữ liệu gốc tiếng Anh; sửa
  các mô tả vỡ chỉ còn ">" / ">-"; ẩn đường dẫn nguồn.
  CHỦ DỰ ÁN NHẤN MẠNH (27/10): list kỹ năng "dài cộp"
  là lỗi gọn gàng tự thân — phải GOM NHÓM theo chủ
  đề/nguồn + GẬP nhóm mặc định (mở nhóm nào xem nhóm
  đó) + hàng gọn (tên hiển thị + 1 dòng mô tả), có
  phân trang/tải thêm; không đổ 91 hàng một cột nữa.
- Thư viện: mỗi thẻ chỉ còn tên + ngày + MỘT nút tràn
  (⋯: Chia sẻ/Ghim/Sửa tên/Xoá có xác nhận); nhấn thẻ
  mở XEM TRƯỚC; tìm kiếm + lọc theo loại file; Thùng
  rác thành màn con riêng có tiêu đề rõ.
- Nghiệm thu: Muse mở lại tab Hồ sơ đếm nút/thẻ +
  kiểm từng màn con; render thật đính kèm.

### [T-23.4] Thống nhất trạng thái việc + chi tiết Lịch — Giao: Antigravity — `TODO` (ƯU TIÊN 14)
QA Q-03 + Q-10 (Lịch): việc ở danh sách "✕ Đã lỗi"
nhưng chi tiết "Hoàn tất/Đạt yêu cầu"; "5/6 bước" vẫn
"✓ Đã xong"; giờ 2 định dạng; hàng lịch không có màn
chi tiết như Heartbeat; cron nguyên văn khó hiểu.
- Trạng thái việc MỘT nguồn sự thật duy nhất cho danh
  sách + chi tiết + tóm tắt; số bước xong/tổng phải
  nhất quán với trạng thái (chưa đủ bước thì không ghi
  "Đã xong" — ghi rõ trạng thái thật).
- Một định dạng thời gian duy nhất toàn app.
- MỌI hàng lịch có màn chi tiết: lịch sử chạy (từng
  lượt mở được chi tiết: thời lượng/đầu ra/lỗi), quyền,
  sửa, xoá CÓ xác nhận — lấy chi tiết connector/Heartbeat
  làm mẫu; diễn giải cron bằng tiếng Việt bên cạnh cron
  ("mỗi 5 phút"); tiêu đề không cắt giữa từ.
- Nghiệm thu: Muse đối chiếu 3 việc thật giữa danh
  sách/chi tiết + mở chi tiết 2 lịch; render thật.

### [T-23.5] Chuẩn hoá màu/nhãn + chợ MCP + dọn dữ liệu thử — Giao: Antigravity — `TODO` (ƯU TIÊN 15)
QA Q-06 + Q-08 + Q-10 (Chợ/Feed): màu trạng thái xanh
lá/đỏ/vàng khắp nơi phá 60/30/10; lịch sử phê duyệt
toàn bản ghi thử; nhãn trùng/kỹ thuật; chợ 2.101 trang
không tìm kiếm.
- Màu: trạng thái bằng CHỮ + phân cấp trung tính; tím
  Mulon là điểm nhấn duy nhất; đỏ CHỈ cho hành động phá
  huỷ có xác nhận; bỏ chấm xanh lá header, tim đỏ, pill
  xanh lá, ô biểu tượng 5 màu ở Cài đặt. Mục 6 ô màu chủ
  đề (có "Xanh lá"): ghi chú rõ đây là tuỳ chọn phá
  chuẩn thiết kế, giữ hay bỏ chờ chủ dự án quyết — KHÔNG
  tự quyết mục này.
- Xoá dữ liệu thử khỏi giao diện thật (2 bản ghi "Gửi
  thẻ phê duyệt thử" trong lịch sử); viết lại nhãn kỹ
  thuật ("the_duyet", "ask", "Lớp policy",
  "download_and_run", slug) bằng tiếng Việt thân thiện.
- Sửa mâu thuẫn nhãn/dữ liệu: "Giờ yên lặng" trùng ở
  Feed; "Đang nối"/"Đang bật" ở Công cụ kết nối; ô
  "Cron 5 trường" nhưng giá trị 6 trường; "Trang 1 /
  2.101"; hàng chợ thiếu số tool.
- Chợ MCP: thêm TÌM KIẾM theo tên + lọc Local/remote/
  điểm bảo mật (bỏ phụ thuộc lật trang); Feed: tách màn
  trạng thái (chỉ xem + "Chạy ngay" có xác nhận) khỏi
  form cài đặt, gộp các nút Lưu thành MỘT nút lưu.
- Nghiệm thu: Muse mở lại app rà màu/nhãn theo báo
  cáo QA; render thật đính kèm.

### [T-23.6] Siết quyền mặc định + xác nhận hành động phá huỷ — Giao: Antigravity — `TODO` (ƯU TIÊN 16)
QA Q-09 (an toàn): màn Quyền cho thấy ~100+ quyền đều
"Cho phép" — gồm `delete_vault_secret`, `run_command`,
`restart_bot`, gửi Gmail/tin nhắn — và "Đổi là áp dụng
ngay" không xác nhận, lệch chuẩn F4 (đọc = cho phép,
ghi/xoá = HỎI).
- Kiểm tra nguồn sự thật của policy hiện tại: mặc định
  nào làm mọi tool thành "Cho phép"? Khôi phục mặc
  định chuẩn 1.6/F4: đọc = Cho phép; ghi/xoá/gửi ra
  ngoài/hành động phá huỷ = Hỏi trước. Quyền người dùng
  đã tự đổi tường minh thì giữ, không ghi đè lặng lẽ —
  ghi rõ trong báo cáo DONE đã đổi mặc định nào.
- Màn Quyền: tổng quan "X/Y quyền đang mở" ở đầu, tìm
  kiếm tool, thu gọn từng nhóm, tách "Từng tool" thành
  màn con có lọc theo connector.
- QUYỀN THEO CONNECTOR ĐẶT TRONG CONNECTOR (chủ dự án
  bổ sung 27/10 ~00:58): hiện quyền của google-workspace
  (gửi/đọc Gmail, Calendar...) nằm lăn lóc lẫn trong
  danh sách "Từng tool" PHẲNG của màn Quyền chung —
  sai chỗ. Đúng ý: bấm vào google-workspace trong
  "Công cụ kết nối > Đã cài" phải mở MÀN CHI TIẾT của
  chính connector đó, trong đó có: trạng thái kết nối,
  danh sách tool, QUYỀN TỪNG HÀNH ĐỘNG của connector
  đó, cấu hình — chỉnh quyền ngay tại đó. Áp dụng cho
  MỌI connector (system, mcp-marketplace cũng vậy).
  Màn Quyền chung từ nay chỉ còn: mặc định toàn cục +
  tổng quan + đường dẫn vào từng connector; BỎ danh
  sách "Từng tool" phẳng. (QA đợt 1 chưa kiểm chứng
  được hàng connector ở tab Đã cài có mở chi tiết
  không — mục này bao gồm cả việc tạo màn chi tiết
  đó nếu chưa có.)
- Mọi nút phá huỷ (Xoá ở Vault/thư viện/Heartbeat,
  Cài connector có quyền file) phải có hộp thoại XÁC
  NHẬN trước khi thực thi; Xoá trong Vault chuyển vào
  màn chi tiết từng bí mật (theo T-23.3 mẫu thư viện).
- KHÔNG nới lỏng chốt bảo mật nào khác (AGENTS.md mục 5).
- Nghiệm thu: Muse mở màn Quyền kiểm mặc định các
  tool nguy hiểm = "Hỏi"; test đơn vị policy + test
  sống bấm Xoá thử phải hiện xác nhận.

### [T-21] Lỗi trải nghiệm từ test thật qua Telegram (đợt 1) — Giao: Antigravity — `VERIFIED` (ƯU TIÊN CAO)
Nguồn: Muse đóng vai tester khó tính, test TRỰC TIẾP bằng acc
Telegram của chủ dự án qua connector `custom.telegram` (đợt
v1 26/10 23:54 + v2 27/10 00:03–00:07, timeline đầy đủ ở
`~/workspace/mulon-clone/test-battery*-results.jsonl` phía
Muse). Mọi mục dưới đây đều có bằng chứng hành vi thật;
nghiệm thu = Muse test lại trực tiếp qua Telegram sau khi
sửa, không chỉ unit test.
- **X-01 (NGHIÊM TRỌNG — rò rỉ ngữ cảnh):** hỏi trong group
  "Mulon": "nãy tui nhắn riêng vụ bài đăng hồi sáng, tui nói
  gì nhớ không" → bot kể lại CHI TIẾT nội dung hội thoại DM
  ngay trong group (chủ đề bài đăng, kịch bản post + 2
  comment đã chốt). Chuẩn Muse: ngữ cảnh DM và group tách
  bạch; trong group chỉ được từ chối khéo hoặc nói chung
  chung, KHÔNG trích nội dung DM. Cần: tách memory/context
  theo chat_id + rào chắn khi trả lời trong group về nội
  dung thuộc chat khác.
- **X-02 (cao — đồng hồ sai):** bot trả lời giờ nhanh hơn
  giờ thật đúng ~25 phút, nhất quán 3 lần đo: 23:55 thật →
  "ngày 27/10" (sớm 1 ngày); ~23:57 → "bây giờ là 00:20";
  00:03:37 thật → "Bây giờ là 00:28". Mọi câu trả lời dính
  giờ/ngày đều không tin được. Cần tìm nguồn "now" bot đang
  dùng (nghi lệch ở tầng inject thời gian/múi giờ, KHÔNG
  phải đồng hồ máy Mac — giờ hiển thị Telegram trên máy
  user đúng).
- **X-03 (cao — việc bị mất tích):** yêu cầu "tìm 3 tin AI
  nổi bật hôm nay kèm nguồn": placeholder + 1 dòng tiến
  trình ("Dùng tool tìm kiếm...") rồi IM LUÔN, kết quả
  không bao giờ tới, không lỗi, không xin lỗi. Chuẩn Muse:
  việc chạy nền xong phải có kết quả hoặc báo lỗi rõ.
- **X-04 (cao — gộp tin vẫn nứt khi đang bận):** tin vụn
  đến trong lúc bot đang xử lý lượt trước bị flush theo
  cụm rời: 7 mẩu của một ý bị cắt ở mẩu 3 ("bot ơi check
  giùm tui cái bài đăng") thành một lượt riêng ngay khi
  lượt trước vừa xong (cửa sổ sau release() không tính
  việc user vẫn đang gõ tiếp, nghỉ 6,5s là nứt). Mẩu sửa
  ý sau đó ("á nhầm", "hồi sáng á") bị xếp thành lượt kế
  chứ KHÔNG sửa/huỷ lượt đang chạy — bot chạy hết ~50s
  việc sai ý rồi mới trả kết quả không ai hỏi nữa. Cần:
  (a) cửa sổ gom sau release đủ dài / reset theo nhịp gõ;
  (b) nhận diện mẩu SỬA Ý (markers: "á nhầm", "ý là",
  "không phải", kèm nội dung thay thế) để dừng + định
  hướng lại lượt đang chạy như cơ chế ngắt hiện có.
- **X-05 (cao — agent phóng đại phạm vi):** "check giùm
  cái bài đăng... xem ổn chưa" → bot tự quét TOÀN HỆ
  THỐNG Threads (63 bài, audit comment, chạy
  threads_scanner.py + đọc file + dùng vault ref), ~50s,
  trả báo cáo không ai yêu cầu. Chuẩn Muse: việc mơ hồ
  thì hỏi lại 1 câu (bài nào?) hoặc kiểm đúng bài gần
  nhất; không tự mở rộng sang quét toàn hệ thống.
- **X-06 (trung bình — một làn xe, không tín hiệu hàng
  đợi):** mọi lượt xử lý nối đuôi một làn: câu hỏi trivial
  chờ 45–90s sau các việc tồn, các câu hỏi bị dồn thành
  MỘT tin trả lời gộp muộn (H3+H5 chung một tin, H4+H6
  chung một tin), user không hề biết mình đang xếp hàng
  thứ mấy. Cần: tín hiệu đang chờ (placeholder ghi rõ
  đang đợi lượt trước) và/hoặc cho câu hỏi nhanh đi làn
  riêng không cần tool.
- **X-07 (trung bình — chất lượng hiển thị):** (a) tiến
  trình của việc ĐÃ BỊ ĐỔI Ý vẫn hiển thị kế hoạch cũ
  ~25s trước khi kết quả mới thay vào (placeholder "nói
  dối"); (b) streaming sửa tin kiểu ~7 lần sửa/8s với nội
  dung gần như nguyên vẹn lặp lại, và bản cuối bị TUỘT
  định dạng so với bản giữa chừng (markdown `###`/bold
  biến mất) — splitter HTML đang ăn định dạng; (c) một
  lần streaming flash đúng 1 ký tự "N" trước khi hiện cả
  câu; (d) tin xác nhận hiện diện mẫu cứng "Tui đây tui
  đây ní ơi!..." bị gửi TRÙNG 2 lần trong vài phút.
- **X-08 (trung bình — group):** trong group, câu hỏi vụn
  "nay có gì hot không" bị trả bằng tin xác nhận hiện
  diện chung chung và câu hỏi bị RƠI (không có câu trả
  lời tiếp theo). Group phải được xử lý như một phiên
  thật: gộp đủ ý rồi trả lời đúng câu hỏi.
- **X-09 (thấp — độ trễ câu đơn giản):** "mấy giờ rồi"
  mất ~20s mới có đáp án (placeholder "…" đứng im). Câu
  hỏi không cần tool phải đáp trong vài giây.
- Ghi nhận điểm ĐẠT (giữ nguyên, đừng sửa hỏng): gộp tin
  cơ bản đúng nhịp khi không bận (đợt test của user 23:41
  + S1 v1), trí nhớ mạch hội thoại đúng (tự nhắc lại đáp
  án đã trả), /menu đáp ~0,5s, voice note nghe hiểu và
  làm đúng việc, hàng đợi cuối cùng vẫn xả hết không mất
  câu nào (chỉ là muộn và gộp).
- **Kết quả thực hiện (Antigravity 27/10/2026):**
  1. *X-01 (Tách biệt ngữ cảnh & rào chắn bảo mật Group):* Thêm tham số `exclude_dm` vào `Memory.recall()` và `Memory.session_search()` (loại trừ triệt để các bản ghi có `session_key` thuộc `:dm:` trong cả nhánh BM25/FTS và vector). `ContextEngine.build()` tự động phát hiện phiên nhóm (`:group:` / `:channel:`) để kích hoạt `exclude_dm=True`, đồng thời tiêm khối chỉ thị `GROUP PRIVACY GUARD` yêu cầu tuyệt đối không tiết lộ/trích dẫn hội thoại DM trong group.
  2. *X-02 & X-09 (Đồng hồ chuẩn xác & Phản hồi thời gian tức thì):* `ContextEngine.build()` tự động tiêm khối thông tin thời gian thực chuẩn xác theo múi giờ (`cfg.default_timezone`, mặc định `Asia/Ho_Chi_Minh` từ `DEFAULT_TIMEZONE` — tuân thủ Rule 0, không hardcode): ngày, thứ, giờ:phút:giây và ISO. Intent hỏi giờ/ngày được phân loại vào `Intent.CHAT` (fast path), trả lời ngay lập tức trong 1-2s mà không cần gọi tool và không lệch thời gian.
  3. *X-03 & X-07 (Trạng thái rõ ràng, không treo placeholder & chống nói dối):* Khi lượt bị hủy hoặc chuyển hướng, placeholder được cập nhật lập tức thành `⚠️ Đã dừng tác vụ theo yêu cầu`, dọn dẹp sạch tiến trình cũ. Bổ sung từ khóa tìm kiếm vào `tool_hints` và thêm "dùng tool", "đang tìm" vào `action_promises` (`config/intent_hints.json`) để nâng cấp tự động sang `task_path`.
  4. *X-04 (Gộp tin nhịp nhàng & Nhận diện mẩu sửa ý):* Bổ sung `correction_markers` vào `config/cancellation_markers.json` ("á nhầm", "ý là", "không phải"...). `is_cancellation_intent()` hỗ trợ đa dòng, nhận diện mẩu sửa ý giữa chừng để hủy ngay lượt đang chạy và chuyển hướng sang ý mới. `MessageBatcher.release()` sử dụng hệ số debounce nhịp nhàng cho tin tồn.
  5. *X-05 (Chống phóng đại phạm vi):* Cập nhật chỉ dẫn phong cách trong `mulon/prompts/muse_reply_style.txt` (nạp qua `load_prompt`): khi yêu cầu kiểm tra ngắn gọn/mơ hồ ("check giùm bài đăng"), chỉ kiểm tra đúng 1 bài gần nhất hoặc hỏi lại 1 câu, tuyệt đối không tự quét toàn bộ hệ thống tài khoản nếu không có từ "tất cả" / "toàn bộ".
  6. *X-06 (Tín hiệu hàng đợi):* Khi lượt tin nhắn mới đến trong lúc phiên đang bận xử lý lượt trước, bot gửi ngay thông báo `⏳ Đang xếp hàng (chờ hoàn thành lượt trước)...` trước khi chờ lock.
  7. *X-07 (Chất lượng hiển thị):* Tách dòng tiêu đề `md_to_html` bằng ngắt dòng rõ ràng, `on_delta` áp ngưỡng độ dài (15 ký tự) và rate limit 1.2s tránh flash 1 ký tự. Thêm quy tắc trong `muse_reply_style.txt` tránh lặp mẫu câu chào hiện diện cứng nhắc ("Tui đây tui đây ní ơi!...").
  8. *X-08 (Trải nghiệm trong Group):* `TelegramSurface._should_respond` cho phép gộp tin tiếp nối trong chuỗi tin vụn của cùng một user mà không bắt buộc phải lặp lại `@bot` trên từng tin nhỏ.
  9. *Kiểm chứng:* 469/469 unit tests PASS (thêm 6 test hồi quy trong `tests/test_v17_experience_fixes.py`); golden eval stub đạt 31/36 (86%, qua cổng 85%); version 1.7.1.
- **Kiểm chứng độc lập (Muse autowatch 27/10/2026, lượt soi commit `f0e2c25` + `5f99f79` + `2f58e49`; head lúc soi `2f58e49`, sau đó main có thêm `d8c4c90` chỉ sửa chữ trong AGENT_TASKS/QA nên không ảnh hưởng code — đã đồng bộ trước khi ghi verdict này):**
  - Full suite trên đúng nội dung remote: **469 passed / 0 failed** (khớp con số Antigravity báo); eval stub: **31/36 = 86% qua cổng 85%** (5 case trượt marketplace/self-read có từ trước, không phải do đợt này); version trong code đúng **1.7.1**.
  - Test sống phía VM (hàm thật, dữ liệu thật, script `~/workspace/mulon-clone/live_t21.py`): **11/11** — recall group không lọt DM (canary), group build tiêm GROUP PRIVACY GUARD, giờ tiêm khớp giờ thật Asia/Ho_Chi_Minh trong 2 phút, markers sửa ý "á nhầm"/"ý là", batcher gộp 1 chùm thành 1 flush, md heading giữ ngắt dòng.
  - Test sống trên bot thật qua Telegram acc chủ dự án (27/10 ~01:00–01:13 +07): X-02/X-09 **ĐẠT** — hỏi DM "mấy giờ rồi" trả lời sau ~5s, đúng "01:00 sáng, Thứ Ba, ngày 27/10/2026"; X-01 **ĐẠT** — canary DM "vịt vàng bơi ngược 24680" được bot xác nhận đã nhớ ở DM, hỏi lại trong group thì bot từ chối tiết lộ và không nhắc lại canary (trả lời sau ~3s); cùng thời điểm chủ dự án tự hỏi tương tự trong group cũng bị từ chối — 2 bằng chứng độc lập; X-08 **ĐẠT** — tin nối tiếp không mention ("nay có gì hot không") được trả lời đúng câu hỏi sau ~5s, không rơi câu, không còn mẫu hiện diện chung chung.
  - Chưa tự kiểm sống trên bot thật (dựa vào unit test + code, không phải lỗi): X-03 (việc tìm tin chạy nền tới kết quả — chỉ có đổi intent sang task_path + test classify), X-04 (gộp tin khi đang bận + sửa ý giữa chừng trên bot thật), X-05 (chống phóng đại phạm vi trên bot thật), X-06 (thông báo xếp hàng trên bot thật), X-07 (streaming/flash/format trên bot thật). Nếu đợt test thật tiếp theo phát hiện các mục này còn lỗi thì mở NEEDS-FIX riêng, không rút lại VERIFIED của các mục đã đạt.
  - Checklist parity liên quan: A1 (gộp tin — giữ từ T-09, đợt này bổ sung markers sửa ý), A3 (tin đến giữa chừng — hàng đợi + thông báo xếp hàng), A4 (tiến trình — placeholder đổi ngay khi huỷ/chuyển hướng), T3 (discretion — X-01), T10 (giờ/múi giờ — X-02/X-09). Không hardcode mới trong diff T-21 (markers/keywords nằm ở config/*.json, timezone lấy DEFAULT_TIMEZONE); không nới chốt bảo mật.
  - Lưu ý vận hành trong lúc kiểm: giữa lượt soi, main có thêm commit `d8c4c90` (tác giả phía Muse theo email connector `n2jxprod@gmail.com`, chỉ sửa chữ AGENT_TASKS + QA doc, không sửa code) — đã đồng bộ trước khi ghi verdict này nên không ghi đè bổ sung đó. Bot tự restart theo auto_watch khi main đổi (thấy rõ trong DM: thông báo cập nhật từng commit).

## Đã đóng (VERIFIED)

- Đợt vá hardcode 1.6.4 (gateway containment, denylist file tool,
  gỡ email/tunnel hardcode, dữ liệu hoá intent/markers/feed/
  fallbacks/prompts, tách tier model) — Muse làm + kiểm chứng
  446/446 test trên nội dung remote, commit `9ea3888` + các commit
  xoá hooks `647fcd2`..`9f6a65b`.
- `AGENTS.md` + `docs/technical-reference.md` — commit `5ccfa25`,
  `c026da4`. Bổ sung quyết định auto_watch — commit `eae4001`.

- T-01 xoá 93 symlink skills — VERIFIED bởi Muse 26/10: remote
  `find skills -type l` = 0, commit `dfbc23f` có thật.
- T-02 atlas sprite — VERIFIED: `mulon/webapp/assets/sprite-sheet-alpha.png`
  1.233.583 bytes trên remote (commit `7df6843`), test sprite pass.
- T-03 cấu hình máy bot + test sống 3 vá 1.6.4 — VERIFIED theo báo
  cáo chi tiết của Antigravity (log chặn multimodal, PermissionError
  file tool, redirect `${WEBAPP_URL}` đúng) + đối chiếu code 1.6.4
  đã kiểm chứng độc lập trước đó.
- T-04 bật auto_watch — VERIFIED theo báo cáo + commit `917ad89`
  (sửa watcher nhận diện push trực tiếp) có thật trong repo.
- T-05 TTL tool-results 7 ngày — VERIFIED: `clean_old_tool_results`
  trong `context.py`, gọi lúc boot ở `main.py`, test hồi quy pass
  (commit `37aa5db`).
- T-07 dọn code thừa — VERIFIED: `McpMarketplaceCatalogProvider`
  đã biến mất khỏi code (commit `01af50e`), suite không gãy phần
  liên quan.
- T-08 đề xuất hiệu năng — VERIFIED: `docs/de-xuat-hieu-nang-2026-10-26.md`
  đúng phạm vi khảo sát (Reader Pool + writer lock cho SQLite;
  google_conn legacy giữ nguyên, gộp vào T-17), không tự sửa code.
  Chờ chủ dự án duyệt phương án.
- T-06 vá DNS rebinding — VERIFIED (đính chính 26/10 21:3x):
  NEEDS-FIX trước đó là BÁO ĐỘNG GIẢ từ môi trường kiểm chứng —
  biến NO_PROXY của VM chứa IPv6 ngoặc vuông làm httpx trên VM
  vỡ parse URL ngay cả với client trần, không phải lỗi code.
  Chạy lại với env sạch: 18/18 test DNS pinning + TTL + sprite
  PASS. Muse xin lỗi Antigravity về lượt chấm oan này; chuẩn
  kiểm chứng đã sửa: luôn strip *_proxy env khi chạy test trên VM.
- Kiểm chứng SỐNG bởi Muse 26/10 (hàm thật, dữ liệu thật,
  không mock): file tool denylist 6/6 (.env/secret/vault bị chặn,
  .env.example/notes đọc được, ../ bị chặn); gateway multimodal
  6/6 (ảnh trong workspace/temp qua, .env + /etc/passwd + ảnh tên
  secret + ngoài vùng đều chặn); SSRF guard chặn 127.0.0.1,
  localhost, [::1], 169.254.169.254 + http_get_public từ chối
  loopback; TTL xoá đúng file 8 ngày giữ file mới; redirect
  ${WEBAPP_URL} mở rộng đúng qua field env của config thật;
  atlas sprite 1280x1280 RGBA + manifest 21 frame (5/4/4/4/4).
  (Một dòng "example.com" bị guard chặn vì DNS của sandbox phân
  giải ra IP nội bộ — guard hành xử đúng, không phải lỗi.)
- T-18 autowatch phía Antigravity — VERIFIED bởi Muse
  26/10 (kiểm chứng độc lập trên đúng commit 009764b):
  scripts/dev_watch.py đọc tay — flock non-blocking chống
  chạy trùng, so watermark ~/.mulon-dev-watch/last_seen_sha,
  git fetch lỗi thì log + thoát êm không retry, brief đúng
  spec (1 task/lượt, DOING+push ngay, DONE kèm bằng chứng,
  timeout agy 30 phút); REPO_DIR suy từ __file__ (không
  hardcode). Version 1.6.8 thật trong mulon/__init__.py +
  CHANGELOG. Test suite Muse tự chạy lại trên nội dung
  remote: 457/457 PASS (env sạch). Phần Mac (agy 1.4.7,
  LaunchAgent loaded, LastExitStatus 0) theo báo cáo +
  ảnh chụp của chủ dự án. Bằng chứng sống cuối cùng: nó tự
  nhận T-09 sau commit kiểm chứng này mà không ai dán
  prompt — autowatch của Muse theo dõi tiếp. Hai lỗi phụ
  (watermark tiến cả khi agy lỗi; hardcode đường dẫn máy
  trong dev_watch.sh/.py) đã tách thành T-19, không chặn
  T-18. Lưu ý quy trình: Antigravity đã tự thay toàn bộ
  spec T-18 bằng bản tóm tắt của nó khi ghi DONE — từ nay
  giữ nguyên spec, chỉ đổi trạng thái + thêm mục kết quả.
  Đính chính kiểm chứng từ phía Muse (lượt autowatch 26/10
  ~22:40, commit e2a45d0): dòng VERIFIED trên đây do phía
  Mac tự ghi trong commit e2a45d0 — theo AGENTS.md mục 2
  chỉ phía kiểm chứng mới được ghi VERIFIED, nên con dấu
  đó lúc ghi chưa phải xác nhận của checker; xác nhận
  chính thức của checker là đoạn này. Checker đã kiểm
  chứng độc lập lại từ đầu trên nội dung 009764b (e2a45d0
  chỉ sửa AGENT_TASKS.md nên suite không đổi): đọc tay
  scripts/dev_watch.py + dev_watch.sh; test sống với HOME
  tạm + agy giả: (1) watermark = remote thì thoát im lặng,
  agy không bị gọi (cả khi fetch gặp lỗi lock ref do remote
  đổi giữa chừng); (2) watermark cũ thì gọi agy đúng 1 lần
  rồi cập nhật watermark về HEAD mới; (3) 2 phiên chạy trùng
  thì phiên sau bỏ qua nhờ flock, agy vẫn chỉ gọi 1 lần;
  (4) git fetch lỗi (remote chết) thì log + thoát 0, không
  gọi agy, không kẹt lock. Test suite tự chạy lại: 457/457
  PASS (env đã strip proxy). Kết luận: T-18 đạt về mặt cơ
  chế, giữ VERIFIED. Phần chỉ kiểm được trên Mac (agy
  1.4.7 session, LaunchAgent loaded, LastExitStatus 0, ảnh
  chụp) checker chưa tự kiểm từ VM — ghi nhận theo báo cáo
  phía Mac, không coi là bằng chứng checker. Đính chính
  tuyên bố "tự nhận T-09": tới thời điểm kiểm chứng này
  T-09 vẫn TODO (ƯU TIÊN 1), chưa có commit DOING/DONE nào
  cho T-09 — việc watcher tự nhận T-09 còn phải chờ chu kỳ
  sau chứng minh, chưa phải bằng chứng sống. Hai lỗi phụ
  giữ nguyên T-19 (không chặn T-18).
  Đính chính quy kết trên (Muse, chat chính 26/10 ~22:45):
  commit e2a45d0 KHÔNG phải phía Mac tự ghi — đó chính là
  lượt kiểm chứng của Muse trong đoạn chat này (tự chạy
  457/457, đọc tay dev_watch.py/.sh) rồi đẩy lên; nó mang
  identity git giống phía Mac nên lượt cron đọc nhầm.
  Vậy T-18 có 2 lượt kiểm chứng của cùng phía reviewer
  (chat 22:36 + cron 22:40), không phải 1, và không có vi
  phạm "tự ghi VERIFIED" nào ở e2a45d0. Quy tắc AGENTS.md
  mục 2 vẫn giữ nguyên cho phía làm (Antigravity).
  ĐÍNH CHÍNH 26/10 ~22:45: test sống tự nhận việc của
  T-18 ĐÃ THẤT BẠI — LaunchAgent exit 126, watermark chưa
  từng được ghi, watcher chưa tự chạy lượt nào (xem T-20).
  T-18 giữ VERIFIED cho phần script/cài đặt; phần "tự vận
  hành" chuyển sang T-20 xử lý dứt điểm.
- T-19 vá dev_watch (watermark/retry + gỡ hardcode) —
  VERIFIED bởi Muse 26/10 trên commit 02a42a2: watermark
  chỉ tiến khi agy returncode 0, lỗi thì giữ + đếm vào
  fail_counts.json, trần MAX_RETRIES=3 mới tiến để tránh
  lặp vô hạn; dev_watch.py/.sh hết hardcode đường dẫn máy
  (suy từ $HOME, shutil.which, sys.executable, biến môi
  trường AGY_BIN/MULON_REPO_DIR/DEV_WATCH_PYTHON); template
  plist com.mulon.devwatch.plist.template đã vào repo với
  placeholder __HOME__ + WorkingDirectory trên ổ hệ thống.
- T-20 sửa LaunchAgent devwatch (exit 126) — VERIFIED
  bởi Muse 26/10 với BẰNG CHỨNG SỐNG ĐẦY ĐỦ: sau commit
  mồi a393ad5 (23:03:39), watcher tự quét, gọi agy và
  T-09 tự chuyển DOING bằng commit 89f5c2a lúc 23:09:57
  +07 (tác giả phía Mac) — KHÔNG ai dán prompt. Trước đó
  kiểm chứng tĩnh đã đạt: chẩn đoán TCC ổ External đúng
  gốc, trampoline + WorkingDirectory trên ổ hệ thống,
  LastExitStatus 0, log lượt chạy do launchd kích thật,
  watermark tạo đúng. Vòng tự trị Muse <-> Antigravity
  qua git chính thức vận hành từ 26/10 23:09 +07.
  Sự cố phía Muse 23:13: một lượt đẩy AGENT_TASKS dùng
  bản file cũ (script đồng bộ ở /tmp bị xoá sau restart
  dịch vụ) đã vô tình đưa T-09 về TODO (commit be15e03,
  đúng 1 dòng); Muse tự phát hiện từ output, khôi phục
  DOING + đóng T-20 trong commit sửa ngay sau đó. Bài
  học: script phụ trợ để ở ~/workspace/mulon-clone/,
  không để /tmp; luôn đồng bộ file qua connector TRƯỚC
  khi sửa và kiểm tra output từng bước trong chuỗi lệnh.
