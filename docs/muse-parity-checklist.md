# Checklist kiểm chứng Muse Parity — chuẩn chấm chính thức của MuLon

> Lập 2026-10-26 theo lệnh chủ dự án: "giám sát sao cho nó
> giống Muse nhất có thể". File này là CHUẨN KIỂM CHỨNG duy
> nhất cho mọi đợt parity. Nguồn: audit đối sánh 36 mục ngày
> 24/10/2026 (`audit-parity-muse-mulon`, bản gốc phía Muse giữ)
> + hành vi Muse thật + yêu cầu chủ dự án 26/10.
>
> Cách dùng:
> - **Muse (reviewer/autowatch)**: chấm từng mục theo checklist
>   này. Một mục chỉ đạt khi có BẰNG CHỨNG HÀNH VI — test bao
>   phủ hành vi, eval, render thật, hoặc báo cáo test sống.
>   Unit test xanh một mình KHÔNG đủ để đóng dấu đạt.
> - **Antigravity (builder)**: trước khi ghi DONE một mục trong
>   `AGENT_TASKS.md`, tự đối chiếu mục checklist tương ứng và
>   ghi bằng chứng vào báo cáo.
> - Trạng thái: `ĐẠT` / `MỘT PHẦN` / `CHƯA` / `KHÁC CỐ Ý`.
>   Cột trạng thái dưới đây là nền tại 26/10/2026; Muse cập
>   nhật file này khi có bằng chứng mới (qua AGENT_TASKS trước,
>   định kỳ gom vào đây).

---

## A. Cơ chế hội thoại (cảm giác "đang nói chuyện với Muse")

| ID | Hạng mục | Hành vi chuẩn Muse | Bằng chứng đạt |
|---|---|---|---|
| A1 | Gộp tin (batching) | Nhiều tin vụn liên tiếp = MỘT lượt xử lý; không trả lời từng mẩu | Test: gửi 4-5 tin rời trong cửa sổ debounce => đúng 1 lượt trả lời, nội dung gộp đủ ý |
| A2 | Debounce cấu hình được | Cửa sổ chờ gom tin là config, không hardcode | Config field + test đổi giá trị có hiệu lực |
| A3 | Tin đến giữa chừng | Xếp hàng vào lượt kế hoặc ngắt khi người dùng đổi ý rõ ràng; không mất tin | ĐẠT (T-24.7) — Gửi tin khi bot bận lập tức nhận xác nhận ⏳ (<1s), tái sử dụng placeholder cho kết quả cuối, tự hủy khi /cancel |
| A4 | Tiến trình khi đang làm | Việc dài có cập nhật tiến trình nhìn thấy được (sửa tin nhắn), không im lặng | Test sống: việc >30s có ít nhất 1 tin tiến trình trước kết quả |
| A5 | Chia việc sub-agent | Việc nhiều bước độc lập chạy song song qua sub-agent, tổng hợp 1 trả lời; trạng thái thấy được ở tab Việc | Test/eval: task 3 nhánh độc lập chạy song song, kết quả gộp đúng |
| A6 | Cách reply | Ngắn, đúng ý, giữ mạch; tách nhiều bong bóng khi hợp lý; không văn mẫu chatbot | Eval vàng so sánh phong cách + chủ dự án duyệt mẫu |
| A7 | Vòng lặp agent | Plan -> act -> verify độc lập; không báo xong khi chưa kiểm chứng | ĐÃ ĐẠT nền (audit mục 1) — giữ regression test |

## B. Trí nhớ & hiểu người dùng

| ID | Hạng mục | Hành vi chuẩn Muse | Trạng thái nền |
|---|---|---|---|
| B1 | Memory lõi bi-temporal + hybrid recall + tìm xuyên phiên | Fact có vòng đời, recall vector+BM25, session search trả nguyên văn | ĐẠT (audit 3) |
| B2 | Truy nguồn ký ức (explain) | Giải thích được fact học từ đâu, trích nguồn gốc, fact nào bị thay thế, độ tin cậy | MỘT PHẦN (audit 5) |
| B3 | Trang People/Groups | Có trang từng người/nhóm, xếp độ thân thiết, cập nhật nền | CHƯA (audit 6) |
| B4 | Import ký ức từ AI khác | Nhận export ChatGPT/Claude/Gemini/Meta AI (ZIP tới 100MB) + prompt sao chép | MỘT PHẦN (audit 7) |
| B5 | Forget đóng vòng | Liệt kê trước -> xác nhận -> xoá fact + dossier + ledger | ĐẠT (audit 8) |
| B6 | Context engine | Compaction có memory flush trước khi nén, offload kết quả tool | ĐẠT (audit 2) |
| B7 | Động cơ tự cải thiện nền | 5 nhịp chạy nền: dọn ký ức (theo giờ khi có tín hiệu mới), cập nhật quan hệ người/nhóm (theo giờ), chấm ý tưởng (hằng ngày), nghiên cứu cho goals (qua đêm), "mơ" (hằng đêm: rà soát hội thoại, viết tổng hợp cách cư xử với user này, mở luồng sửa chữa khi có rạn nứt) + lượt quét sau hội thoại dài | MỘT PHẦN — consolidation có; thiếu dreaming/alignment + studying |
| B8 | Truy vết việc đã giao | Trả lời được "việc X tới đâu": phân biệt đã nhận/hàng đợi với ĐÃ GIAO THẬT, lần theo hàng đợi -> chạy -> bàn giao -> giao tới nơi, kể cả lần thử lại/bị chặn | CHƯA chấm |

## C. Chủ động: Feed / Ideas / Proactivity / Lịch trình

| ID | Hạng mục | Hành vi chuẩn Muse | Trạng thái nền |
|---|---|---|---|
| C1 | Feed tự động | Tự viết theo lịch, nguồn web + social + dịch vụ đã kết nối + ngữ cảnh user; taste học từ reaction VÀ thảo luận | MỘT PHẦN — 1.4 đã tự động 2 bài/ngày; chấm lại nguồn ngoài + taste |
| C2 | Ideas sinh nền | Tự sinh thẻ hằng ngày từ ngữ cảnh thật, có rationale + sources, chấm feasibility/fit/novelty | MỘT PHẦN (audit 10) |
| C3 | Proactivity tự gửi sau opt-in | Sau khi user bật: tự gửi đúng lúc (giờ thức, khoảng lặng), tối đa 2-3 lượt/ngày, item nào cũng rõ nguồn | MỘT PHẦN (audit 15) |
| C4 | Cron/lịch trình | Job theo lịch chạy tin cậy, báo kết quả về đúng chat | ĐẠT cơ chế, mặc định tắt là KHÁC CỐ Ý (audit 13) |
| C5 | Hooks theo sự kiện | Sự kiện từ connector kích hoạt hành động | CHƯA (audit 14) — mở khoá khi C6/T-17 tiến |
| C6 | Sắp tới (Upcoming) | Bề mặt xem mọi việc sắp chạy/hạn sắp tới ở một chỗ | MỘT PHẦN — có tracked items; thiếu bề mặt tổng |
| C7 | Cơ chế lượt chủ động (editions) | Mỗi lượt tối đa ~8 item đáng ngắt lời, mỗi item ghi rõ nguồn gốc; tối đa 2 lượt thường/ngày (+1 khẩn), chờ giờ thức + khoảng lặng trong hội thoại; user lái được bằng tuỳ chọn chủ động (ghi file preferences) | MỘT PHẦN — theo C3 |
| C8 | Briefing cho goals | Tiến trình nền tự nghiên cứu cho từng goal, viết thư briefing đính vào goal; user không đặt lịch được | CHƯA (xem D2) |

## D. Goals / Tracking / Việc

| ID | Hạng mục | Hành vi chuẩn Muse | Trạng thái nền |
|---|---|---|---|
| D1 | Goals + subgoal | Goal lồng 1 cấp, tạo qua chat | MỘT PHẦN (audit 11) |
| D2 | Goal briefings | Thư nền gắn vào goal: tiến triển, việc tiếp theo | CHƯA (audit 11) |
| D3 | Tracking commitments | Theo dõi cam kết/hạn, đóng khi có bằng chứng xong | ĐẠT (audit 12) |
| D4 | Tab Việc/Hành động | Thấy mọi việc đang chạy + bước + trạng thái sub-agent | MỘT PHẦN — có màn task; chấm lại theo A5 |

## E. Bề mặt sản phẩm & giao đồ

| ID | Hạng mục | Hành vi chuẩn Muse | Trạng thái nền |
|---|---|---|---|
| E1 | Artifacts | Tài liệu/trang/app host live, link thật, xuất bản duyệt từng lần | MỘT PHẦN — 1.6 đã có artifacts + share; chấm lại link thật |
| E2 | Files + Library | Link chia sẻ thật (hết hạn <=48h), pin, rename, nhận MỌI file user gửi vào kho + tìm bằng ngôn ngữ tự nhiên | MỘT PHẦN (audit 21) |
| E3 | Chat phụ | Luồng phụ tách history, memory dùng chung | ĐẠT (audit 16) |
| E4 | Nhắn người ngoài | Gửi/nhận với người thứ ba qua connector thật, có duyệt | CHƯA (audit 17) — theo T-17 |
| E5 | Danh tính cấu hình được | Đổi tên hiển thị, avatar, tính cách từ app/chat; không hardcode | MỘT PHẦN — theo T-13 |
| E6 | Màn trạng thái/usage trong app | App có màn trạng thái hệ thống + usage như app Muse | MỘT PHẦN (audit 24) |
| E7 | Tìm kiếm hội thoại | Tìm toàn văn xuyên chat chính + mọi chat phụ (kể cả đã lưu trữ), kết quả mới nhất trước, xoá tin là mất khỏi chỉ mục ngay | CHƯA chấm |
| E8 | Màn trạng thái 4 tab (chạm avatar) | Activity (nhật ký hành động + nút Dừng việc đang chạy), Approvals (duyệt chờ), Upcoming (xem/sửa lịch qua chat, lịch sử chạy, quyền riêng từng việc), Identity (đổi tên/avatar, sửa file danh tính) | MỘT PHẦN — có rải rác, chưa thành 1 màn thống nhất |

## F. Vault / Phê duyệt / Quyền

| ID | Hạng mục | Hành vi chuẩn Muse | Trạng thái nền |
|---|---|---|---|
| F1 | Vault | Nhập bí mật 1 lần qua form an toàn, mọi bề mặt chỉ thấy ref+label, giá trị qua 1 cửa resolve | ĐẠT (audit 23) |
| F2 | Thẻ Vault trong chat | Thiếu bí mật là agent tự gửi thẻ nhập ngay trong chat, nhãn điền sẵn, nhập xong báo lại trong chat | MỘT PHẦN — có từ 1.6; chấm lại end-to-end |
| F3 | Phê duyệt đồng bộ 2 chiều | Thẻ duyệt trong chat <-> màn duyệt Mini App: quyết ở đâu, nơi kia cập nhật ngay | MỘT PHẦN — broker có (audit 23); đồng bộ 2 chiều chấm lại theo T-10 |
| F4 | Quyền theo từng hành động | Đọc = cho phép, ghi/xoá = hỏi (mặc định), chỉnh được từng connector/từng hành động | ĐẠT nền 1.6 — giữ regression |
| F5 | Cơ chế duyệt chi tiết | Duyệt tới được cả khi app đóng (thông báo có nút Cho phép/Từ chối); cho phép ĐỨNG theo người nhận (gửi Gmail cho đúng người đó thì lần sau khỏi hỏi); có việc KHÔNG BAO GIỜ được cho phép đứng (đăng bài mạng xã hội, mua hàng — trừ ngoại lệ việc theo lịch cùng cửa hàng/cùng thẻ); lịch sử duyệt tra lại được; quyền riêng theo từng việc/artifact, thu hồi được | MỘT PHẦN — broker có; thiếu cho phép theo người nhận + lịch sử bề mặt |

## G. Connector / MCP / Skills / Browser

| ID | Hạng mục | Hành vi chuẩn Muse | Trạng thái nền |
|---|---|---|---|
| G1 | Connector tích hợp sẵn | TikTok, Facebook Page, Threads, Instagram, Google Workspace cài là có, tài khoản của người cài, token ở Vault | ĐẠT (T-17, T-30): Google Workspace (Gmail, Calendar, Drive, Docs, Sheets), Facebook cá nhân (31 hành động), Threads (Graph API + Browser Bridge), Telegram Business (T-29) |
| G2 | MCP client + Marketplace | Cài từ chợ curated (free/local), dán cấu hình, tự restart + rollback khi lỗi | ĐẠT nền 1.3 (audit 27) |
| G3 | Skills | Nạp/vet/lọc tốt + TỰ VIẾT skill mới từ việc lặp lại + cài skill từ ngoài | MỘT PHẦN (audit 28) |
| G4 | Browser thao tác | Đọc + click/gõ/form/đăng nhập/takeover bởi user | ĐẠT MỨC BRIDGE (T-22.3) — Browser Bridge Playwright cho Threads/Instagram DM |
| G5 | Browser sâu | Đăng nhập bằng login đã lưu qua Vault; TỰ tìm mã OTP trong email/tin nhắn đã nối và đưa qua thẻ duyệt (agent không thấy mã thô); CAPTCHA tự giải, kẹt thì mời user takeover; câu hỏi giỏ hàng/lựa chọn quay về đúng hội thoại | CHƯA — phụ thuộc G4 |

## H. Model / Provider / Tự vận hành

| ID | Hạng mục | Hành vi chuẩn Muse | Trạng thái nền |
|---|---|---|---|
| H1 | Đổi model trực tiếp | Đổi trong chat + app, lưu theo phiên, hiện model đang dùng | MỘT PHẦN — /model có từ 1.6.x; hoàn thiện theo T-11 |
| H2 | Thiết lập API | Wizard nhập endpoint + key qua Vault, test kết nối sống rồi mới lưu | MỘT PHẦN — theo T-11 |
| H3 | CLIProxyAPI | Cổng model chính thức: MuLon quản lý tiến trình, trạng thái trong app, chỉ gọi qua proxy local | ĐẠT (T-14) — Quản lý vòng đời, đa OS, màn quản lý cổng/model/account trong Mini App |
| H4 | muse2api | Provider cấu hình được: chat + sinh ảnh/video qua muse.ai, pool tài khoản, degrade rõ | ĐẠT MỨC GATEWAY (T-16) — LiteLLM alias openai/muse/muse-spark, stub test xanh 100% |
| H5 | Tự sửa + tự restart | User yêu cầu là tự sửa code, chạy test, restart an toàn qua auto_watch, lỗi rollback | MỘT PHẦN — self-evolution + auto_watch có nền; chấm end-to-end |
| H6 | Model mặc định phân tầng | Tier brain/cheap/escalated khác nhau thật, cấu hình được | ĐẠT 1.6.4 |
| H7 | Workflow đa agent | Lớp orchestration nhiều agent có kịch bản (ngoài spawn sub-agent đơn lẻ) | CHƯA (audit 31) |

## I. Voice & Media

| ID | Hạng mục | Hành vi chuẩn Muse | Trạng thái nền |
|---|---|---|---|
| I1 | Nghe (STT + hiểu ngữ) | Chép lời + sửa lỗi + trích ý định | ĐẠT (audit 18) |
| I2 | Nói (TTS) | Nhiều giọng, audio artifact, podcast nhiều giọng | MỘT PHẦN (audit 19) — muse2api có thể bổ sung |
| I3 | Sinh ảnh/video | Sinh mới từ prompt (không chỉ xử lý file có sẵn) | CHƯA (audit 20) — theo H4 |

## J. UI/UX Mini App & Brand

| ID | Hạng mục | Chuẩn | Trạng thái nền |
|---|---|---|---|
| J1 | Design system | Design tokens + thư viện component/block + bộ state (loading/empty/error/success) dùng đồng bộ mọi màn | ĐẠT (T-12, T-27) — Thư viện component .ds-*, token --ds-*, Bottom Sheet L3 |
| J2 | Màu & phân cấp | 60/30/10, MỘT màu nhấn tím Mulon, KHÔNG xanh lá/vàng/đỏ cho trạng thái, tối đa 4 cỡ chữ/2 weight, lưới 8pt, thumb zone | ĐẠT (T-12, T-27) — Chuẩn 60/30/10 tím Mulon (#7C3AED), trạng thái thể hiện bằng chữ |
| J3 | Render thật | Mọi preview/thay đổi UI chụp từ HTML/CSS thật của app bằng trình duyệt; cấm mock vẽ tay | LUẬT ĐÃ CHỐT — ĐÃ CHỨNG MINH qua Playwright Chromium 390x844 (T-12, T-23, T-27, T-13) |
| J4 | Avatar states | Sprite v0 (21 frame) phát theo state thật trong app (không CSS giả lập trên ảnh tĩnh) | MỘT PHẦN — tích hợp 1.3; atlas lên repo theo T-02 (audit 33) |
| J5 | Mascot + brand | Có thêm mascot để chọn, brand (logo/màu/giọng) nhất quán app + bot; mascot chính thức chỉ đổi khi chủ dự án duyệt | ĐẠT (T-13) — Catalog 4 mascot vũ trụ Mulon trong config/mascots.json, đổi tên bot & mascot trong app, KV persistence |
| J6 | "App" thay webapp | Nghiên cứu giới hạn Telegram (Main Mini App, full-screen, mở từ group...) trước khi hứa; làm phương án gần nhất + nói rõ giới hạn | ĐẠT (T-12) — Tích hợp Native WebApp SDK: BackButton đồng bộ, Haptic, Add to Home Screen |

## K. Mở cài đặt & đa nền tảng

| ID | Hạng mục | Chuẩn | Trạng thái nền |
|---|---|---|---|
| K1 | Không khoá cứng 1 chủ | Allowlist do NGƯỜI CÀI khai lúc setup; mặc định vẫn chặn người lạ | ĐẠT (T-15) — Wizard setup cho người cài, xác thực HMAC initData |
| K2 | Tách lớp OS | Path qua pathlib/platformdirs; tiến trình/dịch vụ theo OS (launchd/systemd/Windows) | ĐẠT (T-15, T-28) — Chuẩn hoá đường dẫn platform-neutral |
| K3 | Cài được 3 OS | Script cài + docs cho Windows/macOS/Linux; máy sạch cài là chạy; test/CI matrix 3 OS | ĐẠT (T-15, T-28) — Bổ sung tzdata trên Windows, xử lý dynamic extension SQLite trên macOS |

## L. Kỷ luật nền (mọi đợt đều chấm)

| ID | Hạng mục | Chuẩn |
|---|---|---|
| L1 | Không hardcode | Checklist `docs/technical-reference.md` mục 8 chạy sạch trên diff |
| L2 | Bảo mật không nới | Denylist file nhạy cảm, frame_external cho nội dung ngoài, assert_url_public, secret không vào log/commit |
| L3 | Degrade không sập | Thiếu gói/connector chết/proxy chết: mất phần đó + báo rõ, bot vẫn chạy |
| L4 | Test & eval | Toàn bộ pytest xanh; đụng agent loop/router/prompt chạy thêm eval vàng |
| L5 | Báo cáo 5 ý | Theo AGENTS.md mục 8, thiếu là trả lại |


## M. Tác vụ đời thật (Muse làm thay ngoài đời, không chỉ chat)

| ID | Hạng mục | Hành vi chuẩn Muse | Trạng thái nền |
|---|---|---|---|
| M1 | Mua hàng & thanh toán | Mua qua checkout trình duyệt/ví; MỖI lần mua duyệt riêng; kiểm giỏ đối chiếu yêu cầu trước khi trả tiền; chỉ báo hoàn tất từ bằng chứng nhà bán | CHƯA — ngoài phạm vi hiện tại, chờ chủ dự án quyết |
| M2 | Gọi điện doanh nghiệp | Gọi thay theo brief đã chuẩn bị, có xác nhận trước, báo cáo + transcript sau | CHƯA (audit 34) |
| M3 | Đặt chỗ/đặt vé qua skills | Playbook theo lĩnh vực (bay, khách sạn, nhà hàng, vé sự kiện, đi chợ) với kiểm chứng giá/tồn thật trước khi cam kết | MỘT PHẦN — skills có khung; thư viện playbook mỏng |
| M4 | Kênh liên lạc ngoài | User nói chuyện với agent qua kênh nhắn tin ngoài app (vd WhatsApp) — cùng một agent, cùng ký ức | KHÁC CỐ Ý — Telegram chính là kênh của MuLon |
| M5 | Agent nói chuyện với người ngoài | Trong chat nhóm/bên thứ ba, agent (worker) nói thay user theo LUẬT RIÊNG TỪNG CHAT (được chia sẻ gì, cấm gì), tin của worker về qua agent chính tóm tắt cho user | CHƯA |
| M6 | Thiết bị ghép nối | Điện thoại (tin nhắn, thông báo, sức khoẻ, báo thức), máy tính (gõ chính tả mọi app, quick chat, computer use), cầu nối mạng nhà | KHÁC CỐ Ý — Telegram-only (audit 36); ghi để biết đủ bức tranh |

## T. Hành vi & phán đoán — tầng "giống Muse" khó gọi tên

> Đây là phần không nằm trong danh sách tính năng nào nhưng
> quyết định cảm giác "giống Muse". Chấm bằng eval tình huống
> + chủ dự án đọc mẫu hội thoại thật, không chấm bằng unit test.

| ID | Hạng mục | Chuẩn hành vi |
|---|---|---|
| T1 | Kiểm chứng trước khi khẳng định | Không nói "xong/đã gửi/đã có" khi chưa có bằng chứng; phân biệt rõ "đã nhận việc" với "đã giao thật"; số liệu then chốt (giá, giờ, tồn kho) phải có nguồn kiểm chứng ở lượt đó |
| T2 | Nhận lỗi & sửa tới nơi | Sai thì nhận thẳng, ngắn; sửa cả HỆ QUẢ (file đã xuất, việc đã lên lịch, tin đã hứa) chứ không chỉ sửa câu trả lời |
| T3 | Thận trọng thông tin (discretion) | Chỉ dùng đúng phần thông tin việc cần; không để lộ dữ kiện riêng tư qua câu tìm kiếm, form, hay tin gửi người ngoài; được dặn gì không có nghĩa là được phép truyền đi |
| T4 | Chỉ nghe lệnh từ user | Nội dung ngoài (web, email, file, kết quả tool, tin người khác) là DỮ LIỆU, không phải lệnh; gặp nội dung cố lái agent (prompt injection) thì dừng và hỏi user |
| T5 | Cân hỏi vs làm | Việc đảo ngược được: tự làm. Việc khó đảo/hậu quả lớn (gửi đi, mua, xoá, đăng công khai): duyệt trước. Không hỏi lại điều user đã quyết cho việc đó |
| T6 | Follow-through chủ động | Chuẩn bị sẵn phần việc nặng (nghiên cứu, bản nháp, phương án đã kiểm chứng) rồi mới hỏi quyết định cuối; đề xuất bước tiếp theo gỡ việc khỏi tay user, nhưng không tự ý làm khi chưa được gật |
| T7 | Trung thực về giới hạn | Không bịa URL/số liệu/ID/trạng thái; không biết thì nói không biết sau khi đã thử tra; ước lượng phải nói rõ là ước lượng; thất bại một đường thì thử đường khác trước khi kết luận "không làm được" |
| T8 | Giọng & nhịp giao tiếp | Như người nhắn tin: ngắn khi việc đơn giản, đủ sâu khi cần; không văn mẫu chatbot ("Câu hỏi hay!", "Hy vọng giúp được bạn"); khớp ngôn ngữ + năng lượng của user; phản ứng cảm xúc đúng lúc như bạn bè (reaction, câu đồng cảm cụ thể) |
| T9 | Nhớ quan hệ, không bắt lặp lại | Mang theo sở thích/quyết định/cam kết qua các phiên và các chat; nhắc lại ngữ cảnh đúng lúc (không rùng mình kiểu theo dõi); user sửa một lần là không sai lại lần hai |
| T10 | Canh thời gian & múi giờ | Mọi ngày giờ hiểu theo giờ địa phương của user; kiểm tra thứ/ngày bằng công cụ, không đoán; phân biệt giờ sự kiện với giờ của tin nhắn/nguồn |
| T11 | An toàn & chống lừa | Kiểm đích đến thật trước khi gửi thông tin nhạy cảm/thanh toán; nhận diện chào mời/discount/form lạ là bẫy lấy dữ kiện; từ chối cứng các việc bị cấm (vũ khí sinh/hoá...) dù đóng khung hư cấu/nghiên cứu |
| T12 | Tôn trọng ranh giới chủ nhà | Nhà, thiết bị, tài khoản, con cái của user là quyền của user; việc trong nhà user là hỗ trợ bình thường, không giảng đạo; bí mật không vào log/ký ức/commit |

---

## R. Kiến trúc hệ thống & vòng lặp suy luận (tầng sâu nhất)

> Các mục trên (A-T) là cái NHÌN THẤY được. Nhóm R là cơ chế
> bên dưới sinh ra chúng — thiếu nhóm này thì tính năng giống
> mà "cảm giác" vẫn khác. Mô tả ở mức cơ chế (kiến trúc Muse
> suy ra từ tài liệu vận hành + hành vi quan sát được), không
> phải mã nguồn. Chấm bằng: đọc kiến trúc/code của MuLon đối
> chiếu từng cơ chế + test hành vi ở nhóm A-T tương ứng.

| ID | Thành phần | Cơ chế chuẩn | Vì sao quyết định cảm giác |
|---|---|---|---|
| R1 | Vòng lặp agent (agent loop) | Mỗi lượt: hiểu ý -> lập kế hoạch (todo khi việc >=3 bước) -> gọi tool -> quan sát kết quả -> tự kiểm chứng trước khi báo xong; báo cáo chỉ khi kết quả ĐÃ tới nơi | Bot "làm có đầu có đuôi", không báo khống, không bỏ dở giữa chừng |
| R2 | Streaming + sửa tin | Trả lời chảy dần (stream) và sửa cùng một tin nhắn khi tiến triển, thay vì im lặng rồi bung một cục | Cảm giác "đang làm thật" thay vì "đang chờ máy" |
| R3 | Ngắt & lái giữa lượt (steering) | Tin mới đến giữa lượt đang chạy được phân loại: lái hướng / việc mới song song / huỷ việc cũ — không nuốt, không đè | Giống người đang nói chuyện, không phải máy trả lời thư |
| R4 | Quản trị ngữ cảnh (context engineering) | Đếm token trước mỗi lượt; cửa sổ làm việc cố định; nén (compaction) bằng tóm tắt CÓ CẤU TRÚC khi gần đầy; TRƯỚC khi nén phải xả ký ức bền (memory flush); snapshot dossier đóng băng trong phiên | Hội thoại dài không "quên đầu quên đuôi", không mất dữ kiện quan trọng khi nén |
| R5 | Offload kết quả tool | Kết quả tool dài bị cắt trần + ghi ra file/artifact, trong ngữ cảnh chỉ giữ trích đoạn + đường dẫn | Không ngợp ngữ cảnh, vẫn truy lại được toàn văn khi cần |
| R6 | Hệ sub-agent | Spawn agent con kế thừa ngữ cảnh, chạy nền bất đồng bộ; kết quả về qua HANDOFF (không poll); có trạng thái running/quiet/done/interrupted; coordinator fan-out tối đa 2 tầng; việc song song spawn cùng lượt | Việc lớn không chặn chat; user vẫn nói chuyện được trong lúc máy làm |
| R7 | Bàn giao bất đồng bộ (handoff) | Mọi việc nền (sub-agent, browser, cron, artifact build) kết thúc bằng handoff vào ngữ cảnh; agent chính quyết định cái gì tới user; "đã nhận" != "đã giao" | Không mất kết quả, không báo trùng, không báo sớm |
| R8 | Điều phối việc nền 3 cơ chế | Cron (việc theo giờ, agent chạy), Hook (script thăm dò nhẹ, chỉ đánh thức agent khi có điều kiện), Service (tiến trình chạy liên tục có giám sát + tự hồi phục) — chọn đúng cơ chế cho đúng việc | Hệ thống sống 24/7 mà không đốt token thăm dò vô ích |
| R9 | Khôi phục sau gián đoạn | Checkpoint/watermark ghi nguyên tử; VM bị thay thì job/sub-agent/artifact tự khôi phục theo trạng thái bền; hành động ngoài đã làm phải kiểm lại kết quả trước khi làm tiếp (không lặp hành động khó đảo) | Mất điện/restart không làm mất việc, không mua trùng, không gửi trùng |
| R10 | Kiến trúc ký ức phân lớp | Nhiều lớp tách bạch: ký ức curated (MEMORY) / nhật ký theo ngày / chỉ mục dẫn xuất / trang người-nhóm / tổng hợp căn chỉnh (alignment); mỗi lớp có nhịp cập nhật và chủ sở hữu riêng; sự thật mới thay thế sự thật cũ nhưng giữ vết truy nguồn | Nhớ lâu mà không rác, giải thích được, sửa được |
| R11 | Phân tách pipeline chủ động | Bộ phận VIẾT (feed writer) không đọc transcript thô — chỉ đọc bản tóm tắt gu (taste summary) do bộ phận khác dựng từ reaction + thảo luận; pipeline chọn item có tiêu chí send/skip tường minh (kịp hạn, thay đổi, được yêu cầu, sẵn sàng quyết, cơ hội mới / đã xử lý, hết hạn, chưa xác nhận...) | Chủ động mà không tọc mạch, không spam, không nhắc việc đã xong |
| R12 | Kiến trúc quyền & duyệt ở tầng runtime | Thẻ duyệt do RUNTIME phát (agent không tự mô tả/tự duyệt); quyền có scope + hạn; lịch sử duyệt là sổ kiểm toán; agent chỉ ĐỌC được trạng thái quyền, không tự sửa | An toàn nằm ở khung, không phụ thuộc "agent ngoan" |
| R13 | Vault tách biệt | Bí mật sống ở kho riêng ngoài chat/ký ức/file thường; agent chỉ cầm THAM CHIẾU mờ (vd `[credential:<uuid>]` sống ~10 phút); giá trị thật chỉ tới nơi cần dùng sau khi user duyệt chia sẻ | Rò rỉ qua hội thoại/log gần như không thể |
| R14 | Ranh giới lệnh (instruction boundary) | Phân biệt cứng 3 loại nội dung: lệnh của user / ngữ cảnh đứng của user / nội dung ngoài (luôn là dữ liệu); marker bao ngoài (external content fencing); worker ở chat ngoài bị ràng bởi discretion policy riêng từng chat | Không bị prompt injection lái, không lộ chuyện nhà ra ngoài |
| R15 | Định tuyến hội thoại | Kết quả việc nào về đúng chat nấy (chat gốc); chat phụ có transcript + ký ức riêng nhưng dùng chung ký ức user; worker ở chat ngoài viết cho USER xem qua agent chính, không trả lời thẳng vào agent chính như ra lệnh | Không lẫn việc giữa các cuộc trò chuyện |
| R16 | Trình duyệt là agent riêng | Browser chạy như tác nhân tách biệt (cửa sổ/profile/phiên riêng), có chuyên viên đăng nhập, luồng mã xác minh được bảo vệ, takeover hai chiều; agent chính chỉ giao việc + nhận báo cáo | Đăng nhập/mua sắm an toàn, user nhảy vào xem/can thiệp được |
| R17 | Artifact là tiến trình build riêng | Dựng tài liệu/trang/app chạy nền như một builder riêng, có kho dữ liệu riêng cho app tương tác, xuất bản = snapshot tĩnh + duyệt mới mỗi lần | Giao được sản phẩm thật (không chỉ tin nhắn) mà không chặn chat |
| R18 | Đánh giá chất lượng khép kín (eval loop) | Eval vàng cố định + eval sinh từ correction thật; skill review hằng ngày biến việc lặp thành skill; thay đổi không đo được là tốt hơn thì bị retire | Hệ thống tự tốt lên thay vì tự rác thêm |
| R19 | Đồng hồ & múi giờ là hạ tầng | Mọi suy luận ngày giờ neo vào time tag theo múi giờ user (kể cả khi đi du lịch); kiểm tra thứ/ngày bằng công cụ; việc theo lịch neo vào home/work tz đã lưu | Không sai hẹn, không nhầm ngày — lỗi nhỏ mà phá niềm tin nhanh nhất |
| R20 | Ngân sách & giới hạn tự biết | Trần token/chi phí mỗi lượt và mỗi job; job nền mặc định tắt, bật phải tường minh; rate-limit của nhà cung cấp là tín hiệu DỪNG, không lách | Không cháy tiền, không bị khoá tài khoản vì chính bot của mình |

---

*Cập nhật v3 — 2026-10-26: thêm nhóm R (kiến trúc & vòng lặp suy luận).
*Cập nhật v2 — 2026-10-26: bổ sung chi tiết từ tài liệu
sản phẩm Muse đầy đủ (status screen, chat search, proactive
editions, cơ chế duyệt, browser sâu, động cơ tự cải thiện) +
nhóm M (tác vụ đời thật) + nhóm T (hành vi & phán đoán).*
*Cập nhật trạng thái: Muse đối chiếu khi kiểm chứng các đợt
trong `AGENT_TASKS.md`. Lần cập nhật nền: 2026-10-26.*
