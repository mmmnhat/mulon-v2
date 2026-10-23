# THIẾT KẾ KỸ THUẬT — MUSE CLONE (Mulon xây lại từ zero)

Ngày: 2026-10-23. Phạm vi: thiết kế một personal AI agent ngang cảm giác dùng với Meta Muse, chạy trên hạ tầng của user (Mac cá nhân / VPS), chỉ dùng Telegram (chốt của user 2026-10-23: Telegram-only, không đa kênh). Mulon cũ chỉ dùng làm bài học: giữ ý tưởng tốt (gateway Telegram, tool registry, học skill, pipeline media), bỏ toàn bộ code lõi.

---

## 0. NGUYÊN TẮC BẤT BIẾN (xếp theo thứ tự ưu tiên khi xung đột)

1. **Cảm giác không phụ thuộc model (chốt của user 2026-10-23).** Chất lượng trải nghiệm do kiến trúc (harness) bảo đảm: ngữ cảnh sạch, việc chia nhỏ, kiểm chứng trước khi báo cáo, đầu ra được định hình nhất quán. Bất kỳ model nào cắm vào — kể cả Gemini 3.8 Flash — cũng phải cho cảm giác sướng; model mạnh hơn chỉ làm nó sướng hơn (sâu hơn, ít vòng sửa hơn), không bao giờ là điều kiện để hết tệ. Model là linh kiện thay thế được; harness mới là sản phẩm.
2. **Latency budget — nhanh là một tính năng.** Mỗi loại tương tác có ngân sách thời gian cứng (mục 2.4). Vượt ngân sách thì hệ thống tự hạ phạm vi việc, không để user chờ mù.
3. **Việc dài không khóa hội thoại.** Mọi việc >20 giây chạy nền qua hàng đợi tác vụ; agent chính luôn phản hồi được.
4. **Nhớ như hồ sơ, không lục rác.** Ký ức dài hạn là dossier đã chắt lọc, có vòng tổng hợp nền. Recall theo ngữ nghĩa + độ quan trọng, không OR từng từ khóa.
5. **Không bao giờ báo xong khi chưa kiểm chứng.** Mọi tác vụ kết thúc bằng bước verify độc lập (đọc lại kết quả, chạy test, đối chiếu yêu cầu) rồi mới báo cáo. Thất bại thì nói thất bại, kèm phần đã xong.
6. **Tự chủ theo cấu hình của user.** Mặc định full-auto trong phạm vi user cấp (user đã chốt: không cần phê duyệt). Policy engine vẫn tồn tại để user siết lại từng nhóm hành động khi muốn, nhưng không mặc định chặn.
7. **Model-agnostic.** Không hardcode một nhà cung cấp nào vào lõi. Toàn bộ truy cập model qua một gateway (LiteLLM) để đổi model bằng cấu hình khi leaderboard thay đổi hàng tháng.

## 1. KIẾN TRÚC TỔNG THỂ

```
┌──────────────── CHANNELS ────────────────┐
│ Telegram (aiogram) │ Zalo │ Messenger │ Web │ (Phase 1 chỉ Telegram)
└──────────────────┬─────────────────────────┘
│ message events (chuẩn hóa)
┌──────────────────▼─────────────────────────┐
│ ORCHESTRATOR (agent chính) │
│ session router · ack ngay · phân loại ý định │
└──────┬───────────────┬──────────────┬──────┘
│ │ │
┌──────────▼───┐ ┌────────▼───────┐ ┌───▼──────────────┐
│ FAST PATH │ │ AGENT LOOP │ │ TASK QUEUE │
│ chat thường │ │ plan-act- │ │ việc dài chạy nền │
│ (streaming) │ │ verify │ │ + subagents │
└──────┬───────┘ └───────┬────────┘ └───┬──────────────┘
│ │ │
┌──────────────────▼──────────────────▼───────────────▼──────────────────┐
│ CONTEXT ENGINE │
│ token budget · dossier loader · hybrid recall · compaction · trim │
└──────────────────┬───────────────────────────────────────────────────┘
│
┌──────────────────▼───────────────────────────────────────────────────┐
│ MODEL GATEWAY (LiteLLM): routing theo tier · fallback ngang tier │
│ prompt caching · streaming · retry/backoff · đo cost/latency │
└───────────────────────────────────────────────────────────────────────┘

┌── SERVICES DÙNG CHUNG ───────────────────────────────────────────────┐
│ Tool layer (MCP client + native tools) · Policy engine · Memory svc │
│ Scheduler · Proactivity engine · Goals/Tracking · Artifact store │
│ Voice (STT/TTS) · Browser worker · Media pipeline · Langfuse tracing │
└───────────────────────────────────────────────────────────────────────┘

┌── BACKGROUND WORKERS (ngoài vòng chat) ──────────────────────────────┐
│ Consolidation (tổng hợp ký ức) · Alignment synthesis · Feed scanner │
│ Scheduler runner · Eval định kỳ │
└───────────────────────────────────────────────────────────────────────┘
```

Luồng 1 lượt chat: tin nhắn vào → orchestrator gắn reaction ack trong <300ms → context engine dựng prompt (dossier + recall + history đã nén) → model gateway route theo tier → nếu cần tool: loop plan-act-verify, tool độc lập chạy song song → stream câu trả lời về kênh → ghi trajectory + history → consolidation xử lý sau (bất đồng bộ, không chặn lượt).

### Vì sao không dùng nguyên một framework agent có sẵn (LangGraph/CrewAI/AutoGen)?
Các framework này mạnh về orchestration đồ thị nhưng áp đặt mô hình tư duy của chúng, khó tùy biến lớp cảm giác (persona, kỷ luật chú ý, dossier) và dễ biến dự án thành "nô lệ của framework" giống cách Mulon cũ thành nô lệ của catalog Hermes. Quyết định: **tự viết lõi loop mỏng (~1.500 dòng) trên LiteLLM + MCP SDK chính thức**, mượn ý tưởng có chọn lọc: checkpoint/resume kiểu LangGraph cho trạng thái tác vụ, phân biệt rạch ròi *runtime state* (trạng thái việc đang chạy, cần resume khi crash) với *knowledge memory* (ký ức về user) — trộn hai thứ này là lỗi thiết kế kinh điển. Letta (MemGPT) là tài liệu tham khảo cho cơ chế paging ký ứcnhưng không nhúng nguyên server vì nặng và khó gỡ rối.

## 2. MODEL LAYER — "chỉ sướng và sướng hơn"

### 2.1 Thực tế thị trường (tháng 10/2026)
- **Claude Opus 5.5** đứng đầu các bảng tổng hợp (AA Intelligence Index 58, BenchLeader #1) — model mạnh nhất mua được.
- **Claude Sonnet 5.5** là lựa chọn agentic tốt nhất theo giá: điểm Terminal-Bench 4.0 cao nhất trong nhóm có công bố (64–70%), giá ngang Sonnet đời trước.
- **GPT-6.1 Sol** ($2/$10 mỗi 1M token) là phương án frontier cân bằng, không rào cản truy cập.
- **Gemini 4 Argon** mạnh (dẫn LMArena, vô địch long-context) nhưng còn gated, chưa mua rộng rãi được.
- **Gemini 3.8 Flash** đạt AA Index ~41 so với 58 của top — nhưng chỉ số này đo model trần trong harness chung chung. Mulon cũ tệ không phải vì Flash tự nó tệ, mà vì Flash bị thả vào một harness bằng 0: ngữ cảnh toàn rác, không chia việc, không kiểm chứng, kết quả tool thô. Theo nguyên tắc 1, bản clone phải làm cho cả tầng Flash cũng sướng nhờ harness (cơ chế ở mục 2.5); tầng frontier là để sướng hơn, không phải để cứu tệ.

### 2.2 Phân tầng model (tier) và routing
| Tier | Model mặc định | Vai trò | Ghi chú |
|---|---|---|---|
| **T0 — Não chính** | Claude Sonnet 5.5 | Mọi hội thoại với user, lập kế hoạch, điều phối, viết lách, tổng hợp cuối | Frontier, agentic tốt nhất theo giá |
| **T0+ — Leo thang** | Claude Opus 5.5 | Việc khó: suy luận sâu, code kiến trúc, phân tích dài, việc mà T0 verify fail 1 lần | Tự leo thang, user không cần biết |
| **T0' — Fallback ngang tầng** | GPT-6.1 Sol → Gemini 4 Argon (khi mở bán) | Khi T0 lỗi rate-limit/sập: chuyển ngang, **không hạ tầng** | Chất lượng tương đương, user không cảm nhận được |
| **T1 — Công nhân** | Sonnet 5.5 hoặc GPT-6.1 Sol | Subagent nghiên cứu, đọc tài liệu dài, chạy việc nền nhiều bước | Vẫn frontier; output qua T0 kiểm chứng |
| **T2 — Nội bộ** | Claude Haiku 5.5 / Gemini 3.8 Flash | Phân loại ý định, trích xuất fact, tóm tắt nháp cho consolidation, gắn nhãn | Output KHÔNG bao giờ tới thẳng user; lỗi ở tầng này vô hại vì T0/T1 lọc lại |

Quy tắc cứng:
- Não chính có thể là bất kỳ model nào từ tầng Flash trở lên — harness (mục 2.5, 3.1, 3.2) luôn bật đầy đủ, đó mới là thứ bảo đảm cảm giác. Tier trong bảng chỉ là mặc định tối ưu chi phí/độ sâu, không phải cổng cấm.
- Router phân loại độ khó bằng T2 nhưng **phân loại sai thì sai lên trên** (fail upward): không chắc → đẩy T0/T0+. Model yếu ở vai trò não chính thì router tự leo thang ở những tác vụ nó verify fail, thay vì cấm nó toàn cục.
- Mỗi cấu hình model phải qua bộ eval (mục 10) trước khi dùng thật: đo correction rate và tỷ lệ verify-fail theo loại việc. Số liệu quyết định model nào gánh việc nào, không quyết bằng định kiến.

**Cấu hình triển khai thực tế của user (chốt 2026-10-23): user chỉ có Gemini.** Vì vậy bản build chạy 100% Gemini qua proxy local sẵn có: não chính = Gemini 3.8 Flash + harness đầy đủ; leo thang nội bộ dòng Gemini (lên bản Pro/Argon của Gemini cho tác vụ khó ngay khi user có quyền truy cập); việc nội bộ T2 cũng là Gemini bản nhẹ. Bảng tier ở trên giữ nguyên vai trò là *bản đồ khả năng*: nhờ gateway LiteLLM, khi nào user có thêm Claude/GPT thì chỉ đổi cấu hình để cắm vào đúng tier, không sửa một dòng code nào trong lõi.
- Nguồn model thực tế cho user (chốt 2026-10-23 ~20:09): **chỉ qua proxy local tương thích OpenAI (`127.0.0.1:8317/v1`, kiểu CLI-Proxy-API như Mulon cũ) — không dùng API chính thức của bất kỳ hãng nào.** Hệ quả kỹ thuật: (a) LiteLLM trỏ vào proxy như một provider OpenAI-compatible, mọi tier đều là model mà proxy route được (thực tế là Gemini); (b) tính năng gắn với tài khoản API chính thức (Batch API giảm giá, explicit prompt caching, embedding API của hãng) **không được giả định là có** — thiết kế phải sống khỏe khi chúng vắng mặt, mục 15.5 đã sửa theo điều này; (c) "tiết kiệm" trong hệ này nghĩa là tiết kiệm *quota/rate-limit của proxy* và độ trễ, không phải tiền API; (d) độ ổn định phụ thuộc proxy → retry/backoff + circuit breaker ở gateway là bắt buộc, và khi proxy nghẽn thì hệ thống hạ tải việc nền trước, giữ đường chat.

### 2.3 Kỹ thuật bắt buộc ở gateway
- **Streaming toàn tuyến**: token đầu tiên về user càng sớm càng tốt; tool call cũng stream trạng thái tối thiểu.
- **Ổn định prefix**: dossier + system prompt + tool schemas luôn giữ ổn định từng byte ở đầu prompt. Nếu upstream qua proxy có hỗ trợ prompt caching thì đây là điều kiện để trúng cache; nếu không, prefix ổn định vẫn giúp cache phía mình (LiteLLM exact cache) và giữ hành vi nhất quán. Cấm nhét giờ hiện tại/timestamp vào system prompt.
- **Retry có backoff + jitter**, timeout từng lời gọi (mặc định 60s cho T0, 120s cho T0+), circuit breaker theo provider.
- **Đo mọi lời gọi**: model, token vào/ra, latency, cost → Langfuse. Không đo thì không tối ưu được, và "cảm giác chậm" phải truy được ra số.
- **Structured output** cho mọi chỗ cần máy đọc (phân loại, trích xuất, plan dạng JSON schema) — hết chuyện parse text tự do rồi lỗi JSON thay `{}` như Mulon cũ.

### 2.4 Ngân sách độ trễ (SLO nội bộ)
| Tình huống | Ngân sách |
|---|---|
| Reaction ack sau tin nhắn user | < 300ms |
| Token đầu tiên của câu trả lời chat thường | < 1.5s |
| Câu trả lời chat thường hoàn chỉnh | < 6s |
| Lượt có tool đơn giản (1–3 tool) | < 15s |
| Việc nền: cập nhật tiến độ lần đầu | < 20s sau khi nhận việc |
| STT voice note 1 phút | < 4s |

### 2.5 Vì sao model tầm trung vẫn sướng — 5 cơ chế bù của harness
Đây là phần kỹ thuật trả lời trực tiếp yêu cầu "thay model nào, kể cả Gemini 3.8, cảm giác vẫn sướng". Model yếu thua model mạnh ở suy luận dài và tự định hướng; harness bù đúng 5 điểm đó:
1. **Chia việc nhỏ tới mức model nào cũng làm đúng.** Não không bao giờ nhận một cục việc mơ hồ lớn; planner bẻ thành bước nhỏ, mỗi bước một mục tiêu, một đầu ra kiểm được. Model tầm trung làm việc nhỏ rất tốt — nó chỉ tệ khi phải tự giữ cả bức tranh lớn trong đầu.
2. **Ngữ cảnh tinh tuyển.** Model chỉ thấy dossier đã chắt lọc + đúng đoạn ký ức liên quan + kết quả tool đã tiêu hóa (mục 3.2). Phần lớn cảm giác "ngu" ngoài đời đến từ ngữ cảnh bẩn, không đến từ model; dọn ngữ cảnh là nâng cấp miễn phí cho mọi model.
3. **Kiểm chứng độc lập + sửa có chẩn đoán.** Lỗi của model yếu bị bắt ở vòng verify và sửa lại với chẩn đoán cụ thể trước khi user thấy. User cảm nhận chất lượng của *hệ thống*, không phải của lần gọi model đầu tiên.
4. **Tool trả dữ liệu đã tiêu hóa.** Tool/API wrapper chuẩn hóa kết quả thành cấu trúc gọn, đúng trọng tâm (ví dụ: tra nguồn hàng trả về giá + tồn + trạng thái, không phải nguyên cục JSON của nhà cung cấp). Model càng yếu càng hưởng lợi vì gánh nặng suy luận giảm.
5. **Định hình đầu ra.** Lớp cuối (persona + format theo kênh, mục 5) chuẩn hóa giọng và bố cục mọi câu trả lời, nên sự thất thường về văn phong giữa các model không lộ ra user.
Đánh đổi thành thật: harness bù được phần lớn khoảng cách ở tác vụ cá nhân thường ngày (chat, tra cứu, viết, điều phối tool), nhưng ở suy luận rất sâu (kiến trúc code lớn, phân tích dài nhiều lớp) model mạnh vẫn hơn rõ — vì vậy router mới leo thang ở đúng những tác vụ đó (mục 2.2), và eval (mục 10) đo khoảng cách này bằng số cho từng cấu hình model.

## 3. AGENT CORE

### 3.1 Vòng lặp plan–act–verify (thay loop 15 vòng mù của Mulon cũ)
1. **Hiểu**: orchestrator + T2 phân loại: chat thường / việc có tool / việc dài. Chat thường đi fast path (1 lời gọi T0, streaming, xong).
2. **Plan** (chỉ khi việc ≥3 bước): T0 sinh kế hoạch ngắn dạng danh sách bước có trạng thái, lưu vào task state (DB). Kế hoạch này là xương sống để resume và để báo cáo.
3. **Act**: thực thi từng bước; các tool call độc lập trong cùng bước chạy **song song bằng asyncio.gather**; kết quả tool qua bộ lọc của context engine trước khi vào prompt (mục 3.2).
4. **Verify**: sau bước cuối, một lượt kiểm chứng riêng (T0, prompt khác vai "người kiểm tra"): đối chiếu kết quả với yêu cầu gốc + bằng chứng (output tool, file, test). Fail → quay lại Act với chẩn đoán cụ thể, tối đa 2 vòng; vẫn fail → báo cáo trung thực phần xong/phần hỏng. **Cấm câu mẫu "đã hoàn thành" khi verify chưa qua** (bệnh của Mulon cũ).
5. **Report**: tổng hợp từ task state + bằng chứng verify, không tổng hợp từ trí nhớ của model về những gì nó "định" làm.

Giới hạn an toàn: ngân sách theo tác vụ (số lời gọi LLM, tổng token, thời gian tường) cấu hình được; chạm trần thì dừng ở trạng thái lưu được + báo cáo, không loop vô hạn.

### 3.2 Context engine — chống context rot
Ngân sách cửa sổ làm việc hiệu dụng: **200K token** (dù model có 1M, chất lượng suy luận thực tế tốt nhất trong vùng này; phần còn lại để dự phòng output và tool). Phân bổ mặc định:

| Thành phần | Ngân sách | Cách quản lý |
|---|---|---|
| System + persona (SOUL) | ~4K | Cache cố định |
| Dossier (USER + MEMORY + alignment synthesis) | ~8K | Cache; consolidation cập nhật nền |
| Tool schemas | ~10K | Chỉ nạp tool theo nhóm liên quan ý định (toolset động), không nạp cả 100 tool mỗi lượt |
| Recall (ký ức liên quan) | ~6K | Hybrid search, tối đa 8 đoạn, có điểm liên quan |
| History hội thoại | ~30K | 10 lượt gần nhất nguyên văn + bản tóm tắt nén của phần cũ hơn |
| Kết quả tool trong lượt | còn lại | Mỗi kết quả bị **cắt trần 8K**: giữ đầu + cuối + ghi chú "[đã cắt X ký tự, bản đầy đủ ở artifact F]"; dữ liệu lớn đi đường file/artifact, model đọc lại từng đoạn khi cần |

Cơ chế bắt buộc:
- **Đếm token thật** (tokenizer của model đích) trước mỗi lời gọi; vượt ngân sách thì compaction chạy trước, không đợi API báo lỗi.
- **Compaction**: khi history vượt trần, T1 tóm tắt phần cũ thành bản nén có cấu trúc (quyết định đã chốt, việc đang dở, cam kết) rồi thay thế. Bản gốc vẫn ở DB, chỉ không nằm trong prompt.
- **Memory flush trước khi nén (mượn OpenClaw — Phụ lục 17)**: khi ngữ cảnh chạm ngưỡng (ngân sách làm việc trừ phần dự trữ), chạy trước một lượt agent *im lặng* để model tự trích fact bền và ghi vào file ký ức, rồi mới compaction; không có gì đáng lưu thì trả `NO_REPLY` và bỏ qua; có bộ đếm chống flush trùng. Đây là chốt chặn để "nén" không đồng nghĩa "quên".
- **Trace KHÔNG vào prompt**: nhật ký thực thi chỉ ghi log/trajectory; history lưu câu trả lời sạch cho user. (Mulon cũ lưu cả khối HTML trace vào history → ô nhiễm vĩnh viễn.)
- **Tool result là dữ liệu, không phải chỉ thị**: nội dung lấy từ web/file/email được đóng khung rõ là dữ liệu ngoài; chỉ thị nằm trong dữ liệu không có hiệu lực (chống prompt injection).

### 3.3 Task state & khả năng sống sót
- Mọi việc dài là một bản ghi task: id, kế hoạch, trạng thái từng bước, artifact đã sinh, lỗi. Ghi DB **sau mỗi bước** (checkpoint kiểu LangGraph).
- Daemon restart/crash → task đang dở được resume từ checkpoint hoặc báo user đúng trạng thái, không biến mất lặng lẽ.
- Idempotency cho hành động ra ngoài (gửi tin, đăng bài, đặt hàng): mỗi hành động có khóa chống trùng; trước khi lặp lại một hành động không chắc kết quả, bắt buộc kiểm tra trạng thái thật trước (đọc lại nguồn) — bài học từ vận hành bán hàng của chính user.
- Concurrency: mỗi session tối đa 1 lượt active; tin nhắn mới trong lúc đang chạy được xếp hàng hoặc chèn làm chỉ thị bổ sung, không spawn 2 loop giành nhau cùng history (Mulon cũ không có khóa nào).

### 3.4 Subagents
- Subagent = một agent loop đầy đủ (cùng engine, toolset thu hẹp theo vai trò, model T1), không phải 1 lời gọi LLM trần như Mulon cũ.
- Agents-as-tools: orchestrator giao việc kèm bản tóm tắt ngữ cảnh tự chứa (subagent không thấy toàn bộ hội thoại), nhận về kết quả đã cấu trúc + bằng chứng.
- Giới hạn đồng thời mặc định 4; việc của user đang chờ luôn ưu tiên hơn việc nền.
- Subagent không có quyền nói chuyện trực tiếp với user; mọi output qua T0 tổng hợp/kiểm chứng.

## 4. MEMORY SYSTEM

### 4.1 Ba lớp ký ức (tách bạch theo đúng bài học runtime state ≠ knowledge memory)
1. **Working memory**: task state + scratchpad của lượt hiện tại (DB + RAM). Sống theo tác vụ.
2. **Episodic**: toàn bộ history hội thoại thô (SQLite WAL), FTS5 index. Chỉ để truy vết và làm nguyên liệu consolidation; không nhét thẳng vào prompt ngoài cửa sổ history đã nén.
3. **Semantic/Dossier**: file có cấu trúc do hệ thống tự duy trì:
- `SOUL.md` — persona, giọng, nguyên tắc ứng xử (user sửa tay được, hệ thống không tự sửa).
- `USER.md` — hồ sơ user: tên, múi giờ, sở thích, kênh liên lạc.
- `MEMORY.md` — sự kiện/quyết định/cam kết bền vững đã chắt lọc.
- `people/*.md`, `groups/*.md` — hồ sơ từng người/nhóm + INDEX.
- `alignment.md` — bản tổng hợp "agent hiểu user tới đâu": phong cách làm việc, điểm ma sát hiện tại, ranh giới đã thỏa thuận. Cập nhật bởi worker nền hằng ngày.
   - `TOOLS.md` — quy ước local (ID group/topic, biệt danh, workflow riêng của máy này); không điều khiển quyền tool.
   Kỷ luật ghi (mượn Hermes): mỗi lớp dossier có **trần dung lượng cứng** — ghi vượt trần thì hệ thống trả lỗi kèm danh sách mục hiện tại, buộc agent tự gộp/xóa trong cùng lượt rồi mới ghi tiếp; bản nạp vào prompt là **snapshot đóng băng theo phiên** (giữ prefix ổn định); entry chứa mẫu injection/bốc dữ liệu bị chặn ngay lúc ghi.

### 4.2 Hybrid recall (thay FTS OR từng từ của Mulon cũ)
- **FTS5** (SQLite) cho khớp chính xác tên/mã/số — có gấp dấu tiếng Việt (bảng phụ lưu bản không dấu).
- **Vector**: `sqlite-vec` + embedding model (Voyage/OpenAI hoặc local multilingual-e5) cho khớp ngữ nghĩa.
- **Hợp nhất**: reciprocal rank fusion + rerank nhẹ theo độ mới và độ quan trọng (salience ghi lúc consolidation). Tỷ lệ trộn khởi điểm ~70% vector / 30% BM25 (số thực tế của OpenClaw), tinh chỉnh bằng eval. Nếu embedding lỗi, recall tự degrade xuống BM25-only thay vì sập (fallback chain kiểu OpenClaw). Riêng việc tìm lại đoạn hội thoại cũ: trả **tin gốc nguyên văn** kiểu session search của Hermes (~20ms, không tóm tắt bằng LLM).
- Recall luôn loại trừ session hiện tại (đang có sẵn trong history) và có trần ngân sách token (mục 3.2).

**Tốc độ truy vấn là yêu cầu cứng (bổ sung 2026-10-23 theo câu hỏi của user):** recall nằm trên đường đi của mọi lượt chat — truy vấn chậm 1 giây là mọi câu trả lời chậm 1 giây, nên nó có ngân sách riêng: **toàn bộ bước dựng ngữ cảnh (dossier + recall + history) p95 < 300ms, riêng recall p95 < 150ms** trên máy của user. Kỹ thuật đạt ngân sách:
- **Chạy song song**: FTS và vector search chạy đồng thời (asyncio), hợp nhất bằng RRF; bước truy vấn bắt đầu ngay khi tin nhắn tới, song song với ack và phân loại ý định — không xếp hàng chờ nhau.
- **Đánh chỉ mục lúc ghi, không lúc đọc**: embedding của ký ức được tính tại thời điểm consolidation ghi vào; lúc truy vấn chỉ phải nhúng đúng 1 câu hỏi của user (và kết quả nhúng này được cache theo phiên).
- **Quy mô cá nhân không cần hạ tầng nặng**: vài chục nghìn vector thì sqlite-vec quét tại chỗ đã đủ nhanh ở mức mili-giây; chỉ khi kho vượt ~500K đoạn mới cân nhắc ANN (HNSW) — tránh bệnh over-engineering của Mulon cũ.
- **Dossier giữ ở RAM**: SOUL/USER/MEMORY/alignment nạp 1 lần lúc boot và khi consolidation cập nhật, mỗi lượt chat đọc từ bộ nhớ, không truy vấn đĩa/DB lại.
- **Cache recall theo phiên**: cùng một chủ đề trong một phiên không truy vấn lại từ đầu; chỉ truy vấn bổ sung khi hội thoại chuyển hướng (phát hiện bằng độ lệch embedding của tin mới nhất).
- **Rerank giới hạn**: chỉ rerank tối đa 20 ứng viên bằng chấm điểm nhẹ tại chỗ; cấm gọi LLM ra ngoài để rerank trong đường chat (đó là cách biến recall 150ms thành 2 giây).
- Đo liên tục trong Langfuse: p50/p95 của từng thành phần truy vấn; vượt ngân sách 2 chu kỳ đo liên tiếp thì tự báo cáo kèm thành phần thủ phạm.

### 4.3 Consolidation worker (hồi sinh đúng nghĩa phần dead code của Mulon cũ)
- Chạy nền theo lịch (sau mỗi N lượt chat và 1 lần/ngày): đọc history mới + trajectory → T1 trích xuất fact/quyết định/cam kết → đối chiếu dossier hiện tại (thêm mới, sửa cái đã thay đổi, đánh dấu cái bị thay thế — giữ lịch sử thay thế để truy nguồn) → cập nhật MEMORY.md/people/groups.
- **Review fork sau mỗi lượt (mượn Hermes — Phụ lục 17):** ngoài lịch định kỳ, sau mỗi lượt chat một fork nhẹ chạy nền (model rẻ, bản digest nén của lượt, trần token vào cố định) trích fact/bài học ngay khi ngữ cảnh còn tươi — rẻ hơn 3–5× so với dùng model chính mà giữ gần nguyên chất lượng ghi nhận.
- **Memory nudges:** nhắc định kỳ theo khoảng để agent chủ động lưu fact/quyết định quan trọng ngay trong phiên thay vì chờ cuối phiên (chữa bệnh quên lưu).
- Mọi fact đều có nguồn (message id + ngày) — trả lời được câu "sao mày biết".
- Học từ sửa sai: khi user sửa/phàn nàn, sự kiện được gắn nhãn correction, consolidation bắt buộc rút thành quy tắc bền trong MEMORY/alignment. Đây là cơ chế biến "bị sửa một lần" thành "không lặp lại".
- Tham khảo kiến trúc: Mem0 cho pattern trích xuất fact + tự sửa trùng lặp khi ghinhưng tự cài đặt mỏng trên SQLite để tránh phụ thuộc nền tảng (graph memory của Mem0 đã rút khỏi bản open-source); Zep/Graphiti là phương án B nếu sau này cần suy luận theo dòng thời gian phức tạp.

### 4.4 Cơ chế học lỗi & rút kinh nghiệm (vòng kín — mỗi lỗi chỉ được xảy ra 1 lần vì cùng 1 nguyên nhân)
Nguyên tắc: lỗi không được xử lý bằng lời xin lỗi mà bằng một thay đổi bền trong hệ thống. Bốn tầng:
1. **Trong tác vụ (tức thời):** verify fail → hệ thống tự chẩn đoán loại nguyên nhân (thiếu dữ kiện / chọn sai tool / thiếu ngữ cảnh / model hiểu sai yêu cầu) → thử lại với prompt đã gắn chẩn đoán. Fail lần 2 → leo thang model (mục 2.2) hoặc dừng và báo cáo trung thực. Chẩn đoán được ghi vào trajectory, không mất theo lượt.
2. **Trong phiên (khi user sửa):** mọi lần user sửa, phàn nàn hoặc làm thay phần việc của agent đều được ghi ngay thành sự kiện `correction` kèm bộ ba (yêu cầu gốc — output sai — bản đúng theo user). Đây là dữ liệu học giá trị nhất, ghi tại chỗ chứ không đợi tổng hợp.
3. **Xuyên phiên (worker nền, cùng nhịp consolidation 4.3):** phân loại mọi correction + lỗi trong trajectory vào taxonomy cố định (lỗi dữ kiện / lỗi quy trình / lỗi giọng-format / lỗi chọn tool / lỗi trí nhớ) → rút thành **bài học** có cấu trúc: điều kiện áp dụng + hành vi đúng + cặp ví dụ sai/đúng + nguồn correction sinh ra nó. Bài học ghi vào `MEMORY.md`/`alignment.md` (phần hệ thống được quyền sửa, tách khỏi SOUL do user giữ). Mọi thay đổi hệ thống tự ghi (bài học, skill, thủ tục) đều vào **sổ cái append-only kèm SHA-256 từng file, rollback được theo từng mục** (kiểu curator của Hermes); thao tác sửa/xóa ký ức do worker nền tự ý làm luôn hoàn tác được 1 chạm trong topic Lịch sử — full-auto nhưng luôn có đường lui. Bài học mới mâu thuẫn bài học cũ thì thay thế, giữ lịch sử thay thế để truy nguồn.
4. **Đóng vòng bằng eval:** mỗi correction nghiêm trọng tự sinh 1 test case vào bộ eval vàng (mục 10). Lỗi cùng taxonomy tái diễn trong eval hoặc ngoài đời → bài học bị đánh dấu "không hiệu lực" và leo thang xử lý (đổi prompt của loại việc đó, đổi tool wrapper, hoặc đổi routing model cho loại việc đó). Chỉ số theo dõi: recurrence rate theo taxonomy và correction rate theo tuần — hai số này phải giảm theo thời gian, đó là bằng chứng hệ thống đang thật sự học.
Chống học bậy (overfit): một sự kiện thoáng qua không thành quy tắc. Bài học chỉ được thăng thành quy tắc bền khi có ≥1 correction rõ ràng của user hoặc ≥2 lần lặp cùng một lỗi; ngoại lệ duy nhất là lỗi đụng tới tiền bạc/an toàn thì 1 lần là đủ. Mọi bài học đều truy vết được: user hỏi "sao mày làm vậy" thì agent chỉ ra được bài học và correction đã sinh ra nó.

### 4.5 Vòng tăng trưởng: càng làm càng khôn, càng khôn càng nhanh (chốt của user 2026-10-23)
Học lỗi (4.4) mới là nửa dưới của vòng — không lặp lại cái sai. Nửa trên là biến kinh nghiệm thành tốc độ: hệ thống phải tiến hóa theo hướng việc quen thì chạy ít suy luận hơn mà đúng hơn. 4 cơ chế:
1. **Thủ tục hóa (procedural memory).** Khi một loại việc đã chạy thành công ≥3 lần với cùng một khung bước, worker nền chưng cất trajectory thành một *thủ tục* (plan template + skill/script đóng gói, có tham số). Lần sau gặp lại, agent nạp thủ tục và thực thi, chỉ dùng suy luận ở các điểm rẽ — thay vì bẻ việc và dò đường từ đầu. Đây là nguồn tăng tốc lớn nhất: số lời gọi LLM cho một loại việc quen giảm dần theo số lần đã làm. Ngưỡng kích hoạt xét chưng cất: 1 tác vụ dùng ≥5 lần gọi tool (số của Hermes) hoặc cùng khung việc thành công ≥3 lần. Thủ tục đóng gói dạng script được gọi qua một lần thực thi duy nhất (scripted tools) để tốn ~0 ngữ cảnh cho các bước quen.
2. **Ký ức tốt làm ngắn đường đi.** Dossier/recall càng chính xác thì càng ít câu hỏi làm rõ, ít lần làm sai hướng, ít vòng verify-retry. Mỗi vòng retry tiết kiệm được là thời gian thật trả lại cho user.
3. **Routing học từ lịch sử.** Hệ thống ghi nhận theo từng loại việc: model nào, mức suy luận nào, thủ tục nào cho kết quả đạt verify với chi phí thấp nhất → router cập nhật bảng chọn lựa. Việc dễ không còn bị xử lý bằng mức suy luận của việc khó (overthinking là một dạng chậm), việc khó không bị giao cho cấu hình đã từng fail.
4. **Chuẩn bị trước (pre-computation).** Proactivity engine (mục 7) dùng thời gian rảnh chuẩn bị sẵn những việc có khả năng cao sắp được yêu cầu (tổng hợp sẵn dữ kiện, nháp sẵn) — độ trễ user cảm nhận tiến về 0 với việc đã đoán đúng.
Lực cản phải khóa cứng: ký ức tăng không được làm prompt phình (đó là con đường càng dùng càng chậm của Mulon cũ). Tri thức tích lũy phải chảy vào dossier đã nén, thủ tục và chỉ mục tìm kiếm — không chảy vào ngữ cảnh thô. Ngữ cảnh mỗi lượt giữ ở ngân sách cố định (mục 3.2) bất kể hệ thống đã chạy bao lâu.
An toàn của vòng: thủ tục/skill sinh tự động phải qua eval + chạy thử sandbox trước khi được tin dùng (mục 6), có phiên bản và rollback; thủ tục nào gây correction thì bị giáng cấp về chế độ suy luận đầy đủ ngay lập tức.
Đo bằng số (mục 10): theo từng họ việc quen thuộc — số lời gọi LLM trung bình, tỷ lệ retry, thời gian hoàn thành — cả ba phải giảm dần theo tuần chạy thật. Đường cong không đi xuống thì vòng tăng trưởng chỉ là khẩu hiệu, và hệ thống phải tự báo cáo điều đó.

## 5. PERSONA & LỚP TƯƠNG TÁC (phần tạo "cảm giác Muse")

- **Ngôn ngữ tự nhiên là đường chính.** Slash command chỉ còn là lối tắt tùy chọn cho power-user; mọi tính năng đều gọi được bằng lời thường.
- **Persona là file, không hardcode trong code.** SOUL.md nạp qua context engine; giọng thích ứng theo ngữ cảnh (việc gấp thì ngắn, việc khó thì sâu) thay vì luật cứng kiểu "cấm emoji tuyệt đối". Quy tắc viết do user chốt (humanizer: nói thẳng, cắt chatbot residue) nằm trong SOUL, sửa không cần đụng code.
- **Kỷ luật chú ý**: phân loại mọi hành động thành 3 mức: tự làm luôn / hỏi 1 câu ngắn / làm nền và chỉ báo khi xong hoặc khi kẹt. Đây là khác biệt cảm giác lớn: agent "biết điều" chứ không phải agent "vâng lời máy móc".
- **Progress UX không spam**: việc ngắn không hiện trạng thái; việc dài hiện đúng 1 tin tiến độ được cập nhật tại chỗ (edit) theo mốc bước, không gửi tin mới cho từng tool. Trace chi tiết chỉ xem khi user hỏi.
- **Định dạng theo kênh**: Telegram dùng HTML an toàn + cơ chế chia tin theo thẻ cân bằng (kế thừa ý tưởng chunking của gateway Mulon cũ, phần hiếm hoi làm tốt); câu trả lời dài tự tách đoạn; file/media gửi dạng đính kèm native.
- **Voice là công dân hạng nhất**: nhận voice → trả lời text hoặc voice theo ngữ cảnh (user gửi voice thì ưu tiên trả voice khi đang di chuyển — suy ra từ tín hiệu, hỏi lại khi không chắc).

## 6. TOOL LAYER & CONNECTORS (MCP-first)

- Chuẩn 2026 là MCP: "nếu bạn viết tool hôm nay, bạn viết MCP server". Dùng **MCP Python SDK chính thức** làm client (stdio + streamable HTTP + OAuth) — 68 manifest vô chủ của Mulon cũ trở thành connector chạy thật thay vì catalog chết.
- Tool registry tự viết mỏng: đăng ký tool native (file, shell, web, memory, schedule, goals) + tool từ MCP server; mỗi tool có: schema, nhóm, mức rủi ro, timeout, giới hạn output. Toolset động theo ý định (mục 3.2).
- **Policy engine** (thay sentinel cũ): quyết định theo cấu hình user — mặc định full-auto đúng lệnh user; vẫn ghi trajectory đầy đủ để truy vết. Phân tầng rủi ro giữ lại cho mục đích *ghi log + cảnh báo mềm*, không chặn mặc định. Cấu trúc 2 lớp mượn OpenClaw: file chính sách ở tầng máy (host) thắng mọi cấu hình trong phiên — prompt hay session không tự nới được chính sách của host.
- **Shell**: chạy qua subprocess có timeout, cwd tường minh, env lọc; lệnh dài chạy nền trả job id. (Không còn lỗ "cwd rỗng = trong workspace".)
- **Browser worker**: Playwright (giữ session đăng nhập thật, profile bền) + thư viện **browser-use** cho tác vụ web nhiều bước do LLM lái; chế độ đọc nhanh bằng fetch text cho việc đơn giản. Phân biệt rõ "đọc để biết" (fetch) với "vào web làm việc" (browser worker) để không lãng phí độ trễ.
- **Google Workspace**: bỏ binary `gog` arm64 đóng gói trong git; thay bằng MCP server Google Workspace hoặc API client chính thức (google-api-python-client) + OAuth chuẩn, chạy được mọi máy.
- **Connector sẵn có của user** (đã chạy thật trong hệ Muse hiện tại): Gmail, Calendar, Drive, Sheets, Threads, Instagram, Messenger, Facebook, Zalo, Canboso, NLM — bọc lại thành MCP server hoặc native tool theo cùng registry. Đây là lợi thế lớn: clone không bắt đầu từ 0 connector.
- **Học skill mới** (giữ ý tưởng tốt nhất của Mulon): agent viết skill dạng SKILL.md + script → kiểm tra cú pháp + chạy thử trong sandbox → đăng ký nóng. Bổ sung so với bản cũ: có bước eval tối thiểu trước khi skill được tin dùng, và skill lỗi bị cách ly thay vì nuốt lỗi rồi ghi đè registry.

## 7. HỆ NỀN: SCHEDULER, GOALS, PROACTIVITY

- **Scheduler**: APScheduler + biểu thức cron đầy đủ + múi giờ tường minh (mặc định Asia/Ho_Chi_Minh). Job có owner, điều kiện dừng, nơi nhận kết quả. Chống chạy trùng bằng khóa theo job (bài học heartbeat Mulon cũ bắn trùng task >15s). Lưu ý vận hành: user từng ra lệnh xóa toàn bộ job tự động (2026-10-22) — hệ mới mặc định **không** job nào chạy khi chưa được user bật đích danh.
- **Goals & tracking**: bảng goals (mục tiêu dài hạn + workspace riêng) và tracked items (cam kết cụ thể: đặt chỗ, đơn hàng, hạn chót). Agent cập nhật tiến độ từ hội thoại và nguồn kết nối; goal không bao giờ tự đóng chỉ vì 1 bước xong.
- **Proactivity engine** (thứ Mulon cũ hứa trong docstring nhưng không có): pipeline quét nguồn (tin nhắn mới, lịch, hạn goal, thay đổi ở connector) → chấm điểm đáng chú ý (khẩn / thay đổi / user đang theo dõi / cơ hội) → kiểm tra lại tính tươi mới trước khi nhắn → nhắn gọn kèm lựa chọn hành động. Có file preferences để user dạy hệ thống nên chủ động về cái gì, lúc nào. Im lặng là mặc định đúng: thà thiếu còn hơn spam. Hiện thực tham chiếu là heartbeat kiểu OpenClaw: một lượt quét định kỳ đọc checklist `HEARTBEAT.md` (agent tự ghi được), gom nhiều kiểm tra nhỏ vào 1 lượt với ngữ cảnh nhẹ + model rẻ riêng + khung giờ hoạt động; không có gì đáng thì trả `HEARTBEAT_OK` và im lặng. Khác biệt giữ nguyên theo lệnh user: của clone là opt-in đích danh, không mặc định bật.
- **Feed**: bản tin biên tập định kỳ do agent viết từ nguồn của user (không phải tin ngoài), là sản phẩm của proactivity pipeline ở chế độ tổng hợp theo lịch.

## 8. VOICE & MEDIA — tách bạch hai vai trò (chốt của user 2026-10-23)

### 8.1 Lớp tương tác giọng nói với user (đây mới là "giọng của agent")
- **Nghe (STT) = Whisper + LLM.** faster-whisper (large-v3, chạy bất đồng bộ ngoài event loop — Mulon cũ transcribe chặn cả loop) chép lời tiếng Việt; bản chép thô sau đó đi qua một lượt LLM hiểu ngữ: sửa lỗi nhận diện theo ngữ cảnh hội thoại, khôi phục dấu câu/tên riêng, và trích ý định. User nói tự nhiên, nói tắt, nói lẫn tiếng Anh đều được hiểu đúng — cảm giác "nó hiểu mình nói gì" đến từ lượt LLM này, không phải từ Whisper đơn độc.
- **Nói (TTS) = OpenAI Voice.** Phản hồi bằng giọng qua API giọng nói của OpenAI (dòng tts/gpt-4o-mini-tts, giọng kiểu nova/alloy như Mulon cũ đã dùng qua proxy) — giọng tự nhiên, có ngữ điệu hội thoại. Đầu ra chuẩn hóa định dạng cho kênh (OGG/Opus cho Telegram voice note) và âm lượng.
- Quy tắc tương tác: user gửi voice thì agent trả lời theo đúng ngữ cảnh sử dụng (mặc định text nếu nội dung cần đọc lại/tra cứu, voice khi hội thoại qua lại nhanh); agent chủ động nói bằng voice qua tool `speak` khi user yêu cầu.

### 8.2 Công cụ làm việc (KHÔNG phải lớp tương tác)
- **SenseVoice** (ASR có timecode, sherpa-onnx) và **Piper** (TTS offline theo model giọng local) chỉ là *công cụ trong pipeline media*: chép lời video nguồn để dịch/lồng tiếng, đọc voiceover cho video affiliate. Chúng không bao giờ là giọng giao tiếp với user.
- **Media pipeline** (kế thừa thiết kế của Mulon cũ, viết lại sạch): yt-dlp tải nguồn → SenseVoice ASR timecode → LLM dịch/viết lại kịch bản → Piper (hoặc TTS được chỉ định) đọc → ffmpeg dựng (reframe, hardsub ASS, ducking, loudnorm ~0dB theo chuẩn user đã chốt ở pipeline affiliate). Khai báo đủ dependency ngay từ đầu (bản cũ thiếu 6 gói trong requirements). Module độc lập, agent gọi như một tool/MCP server riêng.

## 9. DỮ LIỆU & LƯU TRỮ

- SQLite (WAL) là kho chính, một file, sao lưu dễ: bảng `sessions`, `messages`, `tasks`, `task_steps`, `jobs`, `goals`, `tracked_items`, `memory_facts` (có nguồn + trạng thái thay thế), `trajectory`, `artifacts`.
- File trên đĩa theo cây thư mục rõ ràng: `data/` (DB + media), `workspace/` (file làm việc), `dossier/` (SOUL/USER/MEMORY/people/groups), `skills/`, `logs/`.
- Mọi đường dẫn qua config/env — **cấm hardcode đường dẫn máy cá nhân** (bài học `/Volumes/External`).
- Secrets: biến môi trường + file `.env` không commit, hoặc vault của hệ điều hành; không bao giờ ghi secret vào log/trajectory (có bộ lọc redaction).

## 10. QUAN TRẮC & ĐÁNH GIÁ (để "sướng" là đo được, không phải cảm tính)

- **Langfuse** (self-host, open-source) thu trace mọi lời gọi model/tool: latency, token, cost, lỗi. Dashboard xem theo ngày/model/loại việc.
- **Bộ eval vàng**: ~40 tác vụ mẫu lấy từ việc thật của user (trả lời khách theo quy trình 2 bước, tra giá nguồn hàng, dựng kịch bản video, tóm tắt hội thoại dài, nhớ lại cam kết cũ...) chạy tự động sau mỗi thay đổi lớn ở core/prompt/model. Chỉ số: tỷ lệ hoàn thành, tỷ lệ phải sửa lại (correction rate), độ trễ p50/p95.
- **Ngân sách lỗi cảm giác**: nếu correction rate tăng 2 chu kỳ liên tiếp sau một thay đổi → rollback thay đổi đó. Quyết định bằng số, không bằng cảm giác.
- Test tối thiểu: unit test cho context engine (đếm token, compaction, trim), contract test cho từng tool (chữ ký ↔ schema — diệt tận gốc lỗi kiểu `/tasks add` của Mulon cũ), smoke test boot + 3 luồng chính trong CI (GitHub Actions).

## 11. TRIỂN KHAI & VẬN HÀNH

- Đóng gói **Docker Compose** (agent + langfuse + browser worker) để chạy giống hệt trên Mac của user và VPS; không phụ thuộc binary lạ theo kiến trúc máy.
- Quản lý tiến trình: systemd (Linux) / launchd (Mac) + tự khởi động lại khi crash; health endpoint + watchdog nhẹ.
- Cập nhật: git pull + chạy migration DB tự động + smoke test trước khi nạp bản mới; agent tự sửa code (nếu user bật) phải qua đúng pipeline này, không sửa nóng trực tiếp vào bản đang chạy như Mulon cũ.
- Sao lưu: DB + dossier sao lưu hằng ngày, giữ 14 ngày.

## 12. BẢNG TECH STACK

| Lớp | Lựa chọn | Lý do | Phương án B |
|---|---|---|---|
| Ngôn ngữ/runtime | Python 3.12 + asyncio | Kế thừa hệ sinh thái của user (aiogram, ffmpeg, yt-dlp) | — |
| Model gateway | **LiteLLM** | 100+ model, routing/fallback/cost tracking trong 1 lớp | Tự viết adapter mỏng |
| Não chính | **Claude Sonnet 5.5** (T0), **Opus 5.5** (T0+) | Agentic + tổng thể mạnh nhất mua được hiện nay | GPT-6.1 Sol |
| Việc nội bộ | Haiku 5.5 / Gemini 3.8 Flash | Rẻ, nhanh, lỗi vô hại vì có tầng lọc | — |
| Tool protocol | **MCP Python SDK** (chính thức) | Chuẩn chung 2026, hệ sinh thái server sẵn có | Native tools thuần |
| Kênh | aiogram 3 (Telegram) | Đã quen thuộc, ổn định | Telethon |
| DB | SQLite WAL + FTS5 + **sqlite-vec** | Một file, đủ cho personal agent, hybrid search tại chỗ | Postgres + pgvector nếu đa người dùng |
| Scheduler | APScheduler | Cron đầy đủ, jobstore SQLite | systemd timers |
| Browser | Playwright + **browser-use** | Session thật + LLM lái tác vụ web | Chỉ Playwright thủ công |
| STT (tương tác user) | faster-whisper large-v3 + LLM hiểu ngữ | Nghe tốt tiếng Việt; LLM sửa lỗi nhận diện + hiểu ý định | Whisper API |
| TTS (tương tác user) | OpenAI Voice (TTS API) | Giọng tự nhiên, đúng chất hội thoại | Giọng cloud khác qua gateway |
| Media tools | SenseVoice (ASR timecode) + Piper (TTS offline) | Công cụ làm việc cho pipeline video, không phải lớp tương tác | — |
| Quan trắc | **Langfuse** self-host | Trace/cost/latency, open-source | Log JSONL + dashboard tự viết |
| Đóng gói | Docker Compose | Hết phụ thuộc máy cá nhân | venv + systemd |

## 13. ROADMAP (mỗi phase có nghiệm thu đo được)

**Phase 1 — Não và khung chat (nền của cảm giác)**
Gateway LiteLLM + tier routing + streaming; agent core plan–act–verify; context engine (budget, trim, compaction); Telegram channel + fast path; dossier tĩnh nạp qua cache.
*Nghiệm thu*: SLO mục 2.4 đạt trên eval chat; 0 câu trả lời nào chứa trace/log nội bộ; việc 5 tool chạy song song nhanh hơn tuần tự ≥40%.

**Phase 2 — Ký ức sống**
Hybrid recall; consolidation worker + correction learning; people/groups; alignment synthesis.
*Nghiệm thu*: bộ câu hỏi kiểm tra trí nhớ xuyên phiên (hỏi lại quyết định/cam kết cũ sau 7 ngày mô phỏng) đạt ≥90%; bị sửa 1 lần thì lần sau không lặp lại lỗi tương tự trong eval.

**Phase 3 — Tay chân đầy đủ**
MCP client + bọc các connector hiện có của user; browser worker; scheduler + goals/tracking; subagents.
*Nghiệm thu*: 40 tác vụ vàng đạt ≥85% hoàn thành không cần can thiệp; task dài sống sót qua restart daemon ở 100% lần thử.

**Phase 4 — Chủ động & hoàn thiện trải nghiệm group**
Proactivity engine + feed; voice 2 chiều hoàn chỉnh; side chats/workers trong Telegram; media pipeline.
*Nghiệm thu*: proactivity precision (tỷ lệ tin chủ động được user đánh giá hữu ích) ≥70% sau 2 tuần chạy thật; độ trễ voice đạt SLO.

**Phase 5 — Cứng hóa**
Eval tự động trong CI, dashboard cost/latency, sao lưu/khôi phục diễn tập, tài liệu vận hành.
*Nghiệm thu*: đổi model T0 sang model khác chỉ bằng config và eval không tụt quá 3 điểm.

**Phase 6 — Bề mặt tương tác đầy đủ (chi tiết ở mục 16)**
Group forum Telegram làm sân khấu cho mọi bề mặt (topic = tab: Feed, Ideas, Goals, Library, Lịch sử & Hệ thống); gom tin liên tiếp + reply/quote + reaction; side chats/workers; bộ nhớ có bề mặt người dùng (xem/truy nguồn/quên/import/export). KHÔNG build Mini App.
*Nghiệm thu*: mọi bề mặt ở mục 16 đều sống đúng topic của nó trong group và gọi được bằng ngôn ngữ tự nhiên; gửi 3 tin liên tiếp trong 5 giây chỉ sinh đúng 1 lượt xử lý với đủ ý cả 3 tin; người khác trong group ra lệnh thì agent không thực thi.

## 15. PHỤ LỤC — BẢN ĐỒ REPO OPEN-SOURCE ÁP DỤNG (quét + kiểm chứng GitHub 2026-10-23)

Nguyên tắc chọn: repo phải còn sống, license sạch (MIT/Apache), và giải quyết đúng một lớp của kiến trúc. Ba mức áp dụng: **NHÚNG** = dùng làm dependency thật; **MƯỢN** = tự cài lại pattern, không phụ thuộc code; **TRÁNH** = ghi rõ lý do để khỏi quay lại.

### 15.1 Học lỗi & rút kinh nghiệm
| Repo | Mức | Áp vào đâu / lưu ý sống còn |
|---|---|---|
| **gepa-ai/gepa** (~7,1k★, MIT) | NHÚNG | Tiến hóa prompt + mô tả tool MCP bằng reflection trên trace lỗi thật, chạy batch nền theo tuần trên kho case correction (hiện thực hóa mục 4.4 tầng 3–4). Lưu ý: vai reflection phải dùng model Gemini mạnh nhất đang có — reflection yếu thì không sinh được cải tiến. |
| **stanfordnlp/dspy** (~38,7k★, MIT) | NHÚNG | Cho các module có metric rõ (phân loại ý định, trích xuất fact, tóm tắt): tự sinh few-shot từ trace thành công. Chỉ chạy nền (optimizer tốn hàng trăm lượt gọi LLM), không chạy trong đường chat. |
| Reflexion / Self-Refine (pattern) | MƯỢN | Vòng verify → chẩn đoán → retry trong tác vụ (mục 3.1/4.4 tầng 1). Tự cài vài chục dòng, repo gốc là notebook nghiên cứu. |
| Voyager → chuẩn skill library (agentskills.io) | MƯỢN | Skill chỉ vào kho sau khi kiểm chứng chạy thành công — đúng cơ chế thủ tục hóa ở mục 4.5. |
| **567-labs/instructor** (~11k★, MIT) | NHÚNG | Mọi output cần cấu trúc đều qua Pydantic + tự retry kèm lỗi validation. Diệt tận gốc bệnh parse JSON fail rồi thay `{}` của Mulon cũ. Chi phí tích hợp gần 0, hỗ trợ Gemini. |
| LangMem (langchain-ai) | MƯỢN | Thiết kế background memory manager cho consolidation (mục 4.3), không nhúng vì kéo theo trừu tượng LangGraph. |
| TextGrad | TRÁNH | Research code đang chậm lại, tốn call cho mỗi bước; GEPA đã vượt cùng ý tưởng. |
| Outlines | TRÁNH (giai đoạn API) | Constrained decoding cần điều khiển logits — không tồn tại qua API Gemini. Chỉ xét lại nếu tự host model. |

### 15.2 Khôn hơn (trí nhớ có vòng đời)
| Repo | Mức | Áp vào đâu / lưu ý sống còn |
|---|---|---|
| **mem0ai/mem0** (~67,7k★, Apache-2.0) | NHÚNG (có điều kiện) | Trích xuất fact + khử trùng lặp + retrieval đa tín hiệu cho consolidation/recall. Chấp nhận: benchmark công bố là của bản cloud, graph memory đã rút khỏi bản OSS — vì vậy chỉ dùng nó ở tầng trích xuất/tìm kiếm, vòng đời fact vẫn do schema của mình giữ. |
| **getzep/graphiti** (~32,2k★, Apache-2.0) | MƯỢN schema (nhúng khi cần) | Chuẩn bi-temporal cho fact: `valid_from/valid_to` + `superseded_by` + truy vết nguồn — đưa nguyên schema này vào SQLite (`memory_facts` ở mục 9). Chỉ nhúng lib thật (cần Neo4j/FalkorDB) nếu nhu cầu suy luận quan hệ phức tạp xuất hiện. |
| A-MEM (~1,0k★, MIT) | MƯỢN | Schema note kiểu Zettelkasten + cơ chế ký ức mới kích hoạt cập nhật ký ức cũ (memory evolution) cho consolidation. |
| Supermemory | MƯỢN | Pattern user profile tĩnh/động (static/dynamic profile) cho USER.md + alignment. Không nhúng (TypeScript, cloud-first). |
| Letta (server Python) | TRÁNH | Dự án đã pivot sang TypeScript, code Python vào nhánh archive. Chỉ mượn kiến trúc memory blocks. |
| Cognee | TRÁNH (giai đoạn này) | Nền tảng nặng, phần production dùng license riêng. Pattern `remember/recall/improve/forget` đáng tham khảo trên giấy. |

### 15.3 Nhanh hơn & xử lý nhanh hơn
| Repo | Mức | Áp vào đâu / lưu ý sống còn |
|---|---|---|
| **aurelio-labs/semantic-router** (~4,0k★, MIT) | NHÚNG | Thay các lượt LLM phân loại ý định/chọn toolset bằng quyết định vector ~4ms (so với ~3,9 giây một lượt LLM). Đây là đòn tăng tốc lớn nhất cho vòng lặp. Cần bộ câu mẫu cho từng route + luôn có đường "không chắc → hỏi LLM". Ghim version (đang chuyển 0.x → 1.x). |
| **taskiq** (~2,4k★, MIT) | NHÚNG | Hàng đợi async cho việc nền (consolidation, batch, eval) — đường chat không bao giờ bị việc nặng chặn. Tránh arq (đã maintenance-only). |
| Pattern offload tool result (LangChain Deep Agents) | MƯỢN | Kết quả tool quá ~20K token tự đổ ra file, context chỉ giữ tham chiếu — cơ chế cụ thể cho mục 3.2. Không nhúng framework. |
| vLLM / SGLang | ĐỂ DÀNH | Chỉ khi tự host GPU. SGLang (RadixAttention cache prefix dạng cây) hợp workload agent nhiều lượt dùng chung dossier hơn vLLM thuần throughput. |

### 15.4 Truy vấn nhanh hơn
| Repo | Mức | Áp vào đâu / lưu ý sống còn |
|---|---|---|
| **asg017/sqlite-vec** (~8,2k★, MIT/Apache) | NHÚNG | Lớp vector chính, chung file DB với FTS5 (hybrid trong 1 câu SQL). Số đo: ~105ms ở 100K vector 1536 chiều; bản int8 + preload xuống ~4–17ms — đủ ngân sách 150ms tới ~100K vector, xa hơn thì chia partition theo thời gian. Đang pre-v1: ghim version + bọc interface tự viết. |
| **qdrant/fastembed** (~3k★, Apache-2.0) | NHÚNG | Runtime embedding local thuần ONNX (không torch): chạy bge-m3/bge-reranker tại chỗ, 0 round-trip mạng trong đường chat. |
| **BAAI bge-m3** (model, MIT) | NHÚNG | Embedding đa ngữ có tiếng Việt: 1 model cho dense + sparse. **Bản local là mặc định cho cả đường chat lẫn index** (vì user chỉ dùng proxy, không giả định có embedding API chính thức); nếu proxy có phơi endpoint embedding thì dùng bổ trợ cho việc nền, không phụ thuộc. |
| **FlashRank** (~1,0k★, Apache-2.0) | NHÚNG | Rerank local top-20, model MultiBERT ~150MB, thứ tự chục mili-giây trên CPU. Khe nâng cấp: bge-reranker-v2-m3 (tiếng Việt tốt hơn, nặng hơn) cho việc nền. Dự án nhỏ 1 maintainer → bọc interface. |
| LanceDB | ĐỂ DÀNH | Đường thoát khi vector vượt ~100–200K (ANN p95 ~14ms ở 100K). Chưa cần ngay. |
| Qdrant server / Redis Stack / GPTCache | TRÁNH | Thêm service để giải bài toán brute-force trong SQLite đã xong; GPTCache đã chững phát triển và tự thừa nhận không theo API mới (chỉ mượn pattern). |
| Jina Reranker API trong đường chat | TRÁNH | Cộng 100–300ms mạng mỗi lượt = phá ngân sách recall; weights local của Jina là CC-BY-NC (phi thương mại). |

### 15.5 Tiết kiệm hơn
| Repo / cơ chế | Mức | Áp vào đâu / lưu ý sống còn |
|---|---|---|
| Prompt caching của provider (implicit/explicit) | ĐIỀU KIỆN | User chỉ dùng proxy nên KHÔNG giả định là có. Thiết kế giữ prefix ổn định từng byte (mục 2.3) để nếu upstream có cache thì trúng, không có thì cũng không mất gì. Phần tiết kiệm chắc chắn phải đến từ cơ chế phía mình ở các dòng dưới. |
| Gemini Batch API (−50%) | KHÔNG ÁP DỤNG | Là tính năng của API chính thức — user chỉ dùng proxy nên bỏ. Thay thế bằng cơ chế phía mình: hàng đợi Taskiq gom việc nền của vòng học (consolidation, sinh test case, backfill, eval) chạy vào khung giờ thấp điểm + giới hạn tốc độ theo quota proxy. Mục tiêu đổi từ "rẻ hơn 50%" thành "không tranh quota với đường chat". |
| **google-genai LocalTokenizer** (SDK chính thức) | NHÚNG | Đếm token Gemini chính xác tại local, miễn phí. Cấm dùng tiktoken ước lượng cho Gemini (lệch đủ phá mọi tính budget). |
| LiteLLM budget + exact cache (đã có trong stack) | BẬT NGAY | Chặn chi theo key/loại việc (agent chạy nền ban đêm tự bị chặn khi vượt ngân sách); exact-match cache an toàn. **Semantic cache: chỉ bật cho sub-query ổn định, tuyệt đối không cache dữ liệu biến động (giá, tồn kho, lịch) — cache hit giả trong bán hàng là báo giá cũ cho khách.** Chính docs của LiteLLM cũng cảnh báo semantic cache "goes badly wrong" trên traffic agentic. |
| Cascade kiểu FrugalGPT (pattern) | MƯỢN | Flash trả trước → verify rẻ → fail mới leo thang. Số 98% của paper là tác vụ hẹp năm 2023; hiệu quả thật đo bằng correction rate trên traffic của chính user (kỳ vọng thực tế ~20–45% theo phân tích RouteLLM). RouteLLM nguyên bản: TRÁNH (0 release, train cho cặp model khác, cần OpenAI key). |
| **promptfoo** (~26,3k★, MIT) | NHÚNG | Cổng kiểm chứng mọi chiêu tiết kiệm: cùng bộ test vàng đo quality + cost + latency trước/sau. Đường chặn chỉ dùng assertion xác định (schema/regex/cost/latency); assertion bằng LLM-judge tốn tiền và hay flake. |
| **microsoft/LLMLingua** (~6,8k★, MIT) | CÂN NHẮC (Phase sau) | Nén tới 20x cho tài liệu dài/tool output lớn. Cảnh báo: nén là mất mát — dễ nuốt số tiền, mã, phủ định; chưa ai benchmark tiếng Việt; không bao giờ nén system prompt/dossier/chỉ thị user; prompt ngắn thì chi phí nén còn đắt hơn phần tiết kiệm. Chỉ bật sau khi promptfoo chứng minh không tụt chất lượng trên eval của chính dự án. |
| Ngữ cảnh dài của Gemini | LƯU Ý GIÁ | Vượt ~200K token input là giá tăng mạnh (tới x2) — "cửa sổ 1M" không phải lời mời nhét 1M. Đây là lý do ngân sách làm việc 200K ở mục 3.2 cũng là một quyết định tiết kiệm. |

### 15.6 Cập nhật stack sau vòng quét này
Bổ sung vào bảng mục 12: Instructor (structured output), semantic-router (phân loại ý định), FastEmbed + bge-m3 (embedding local), FlashRank (rerank), google-genai LocalTokenizer (đếm token), GEPA + DSPy (tiến hóa prompt ở việc nền), Taskiq (hàng đợi nền), promptfoo (cổng eval), schema bi-temporal kiểu Graphiti cho bảng memory_facts. Các lựa chọn cũ giữ nguyên: LiteLLM, MCP SDK, SQLite WAL + FTS5 + sqlite-vec, APScheduler, Playwright + browser-use, faster-whisper, Langfuse.

## 14. NHỮNG GÌ *KHÔNG* LÀM (chống phình như Mulon cũ)
- Không catalog tính năng trên giấy: mọi mục trong tài liệu này phải có phase và nghiệm thu, xong phase mới ghi "có".
- Không nhúng framework agent nguyên con; lõi tự viết và giữ < ~3.000 dòng cho core.
- Không đa người dùng, không UI web ở Phase 1–3: Telegram là bề mặt chính cho tới khi lõi đạt nghiệm thu.
- Không job tự động nào bật sẵn: mọi lịch chạy do user bật đích danh.

## 16. BẢN ĐỒ BỀ MẶT TƯƠNG TÁC — clone toàn bộ trải nghiệm Muse (bổ sung 2026-10-23 theo yêu cầu của user)

Muse không chỉ là một agent loop; nó là một *bề mặt sản phẩm* gồm nhiều tab và cơ chế tương tác. Clone phải phủ hết, nếu không cảm giác vẫn là "con bot Telegram khôn" thay vì "Muse". Nguyên tắc bề mặt:
- **Sân khấu là group Telegram forum — không build Mini App (chốt của user 2026-10-23).** Toàn bộ trải nghiệm sống trong một supergroup riêng tư bật forum: mỗi topic là một "phòng" tương ứng một bề mặt của Muse (Chat chính, Feed, Ideas, Goals, Library, Lịch sử & Hệ thống) — topic chính là tab. Đầu mỗi topic ghim một tin mục lục có nút điều hướng; thẻ hành động bằng inline keyboard; file gửi native trong topic Library. Mọi tính năng đều gọi được bằng ngôn ngữ tự nhiên ngay trong chat, ở bất kỳ topic nào.
- **Bot cần quyền quản trị group** để tự tạo/ghim topic khi một bề mặt được bật. DM giữ vai trò kênh riêng tư bổ trợ cho việc nhạy cảm (vault, quyền, ký ức cá nhân) khi group có người khác.

### 16.0 Mô hình vận hành trong group
- **Ai được ra lệnh:** chỉ user (allowlist theo Telegram ID, mặc định đúng 1 người). Tin nhắn của người khác trong group là dữ kiện/ngữ cảnh, không phải chỉ thị — kể cả khi họ nhắc tên bot hay nói giọng ra lệnh. Đây là tuyến phòng thủ đầu tiên cho agent sống trong group.
- **Khi nào bot lên tiếng:** trong group chỉ có user + bot thì trả lời mọi tin. Trong group có thêm người khác thì bot chỉ xử lý khi được nhắc tên, được reply trực tiếp, hoặc đúng keyword đã cấu hình — còn lại im lặng quan sát (vẫn được ghi ngữ cảnh nếu user cho phép). Không bao giờ chen vào mọi cuộc trò chuyện: đó là cách nhanh nhất bị ghét và bị kick.
- **Session theo (group × topic):** mỗi topic là một dòng hội thoại riêng (Feed không lẫn Goals), chat chính là session điều phối. Recall ký ức gắn scope: ngữ cảnh group dùng cho việc trong group; dossier cá nhân của user chỉ tự động mang vào DM và các topic đã đánh dấu riêng tư — ở topic có người khác, agent phải ý thức khán giả và không tự tiện lộ thông tin cá nhân của user (ai, việc gì, đã mua gì) trước mặt họ.
- **Nhiều bot cùng group:** mỗi bot một danh tính, một allowlist, một bộ topic phụ trách riêng; bot này không trả lời thay bot kia và không tranh lượt xử lý cùng một tin. (Liên quan dự án đội bot của user nhưng clone này tự nó là 1 bot hoàn chỉnh.)
- **Ranh giới phiên chủ động (bài học từ Hermes):** chat Telegram là phiên liên tục không bao giờ tự kết thúc, nên trong mỗi topic, phiên được *chốt* khi việc xong hoặc sang ngày mới — điểm chốt này là lúc review fork/consolidation kích hoạt và là mốc cắt cho session search; thiếu nó thì vòng học không bao giờ chạy và chi phí nén phình.
- **Topic chuẩn lúc khởi tạo:** Chat chính (General), Feed, Ideas, Goals, Library, Lịch sử & Hệ thống. Bật tính năng nào thì bot tạo topic tương ứng — không tạo sẵn một rừng topic chết (bài học catalog phình của Mulon cũ áp dụng cả cho bề mặt).

### 16.1 Hội thoại — lớp tương tác cốt lõi
- **Gom tin liên tiếp (message batching):** user gửi 2–3 tin ngắn dồn dập (thói quen chat thật) → gateway giữ một cửa sổ gom (mặc định ~2,5 giây, tự học theo nhịp gõ của user) rồi mới chạy 1 lượt xử lý với đủ ý của cả chùm. Tin tới trong lúc agent đang xử lý một việc khác được phân loại: *chỉ thị lái* (sửa ý/bổ sung cho việc đang chạy → chèn vào task state, không spawn loop mới) hoặc *việc mới* (xếp hàng). Đây là cơ chế bắt buộc phải có — thiếu nó, agent trả lời từng mảnh và hiểu sai ý là chuyện hằng ngày.
- **Reply/quote:** tin reply vào một tin cụ thể mang theo ngữ cảnh của tin được trích; agent hiểu "cái này" là chỉ vào nội dung được quote/đính kèm gần nhất.
- **Reaction:** reaction của user vừa là ack (thay tin trạng thái thừa), vừa là tín hiệu: 👍/❤️ trên bài Feed là dữ kiện taste; reaction tiêu cực trên output của agent được ghi nhận như correction nhẹ cho vòng học lỗi (mục 4.4).
- **Sửa/rút tin:** user sửa tin (edit) trước khi agent xử lý xong → dùng bản mới nhất; user xóa tin → hủy ý tương ứng nếu tác vụ chưa chạy, đã chạy thì báo rõ trạng thái thay vì giả vờ chưa xảy ra.
- **Hiển thị:** streaming bằng sửa tin tại chỗ; tin dài chia chunk an toàn theo thẻ (kế thừa chunking của gateway Mulon cũ); việc dài chỉ có đúng 1 tin tiến độ được cập nhật tại chỗ.
- **Thẻ hành động trong chat:** inline keyboard cho lựa chọn/ duyệt 1 chạm; thẻ Letter cho briefing; file/media gửi native. Mọi thẻ bấm được đều map về một hành động có bản ghi (mục 16.9).
- **Side chats & workers:** agent có thể nói chuyện thay user với người/nhóm khác trong các group/chat Telegram khác qua cơ chế worker: user ra lệnh và nhận báo cáo đầy đủ qua chat chính; mỗi side chat có file quy tắc riêng tư riêng (cái gì được nói, cái gì không) do user đặt, worker áp dụng khi giao tiếp; tin từ worker không tự quyết thay user — việc cần quyết được đưa về chat chính.

### 16.2 Cổng kết nối (Connectors)
- Connector là một gói khai báo: tài liệu khả năng + luồng xác thực + ánh xạ tool. Luồng kết nối bằng link OAuth/QR gửi trong chat (mở trong trình duyệt) — không bao giờ xin mật khẩu qua chat.
- Mỗi connector có trạng thái sức khỏe hiển thị được (đã kết nối / cần cấp thêm quyền / bị giới hạn tốc độ / hỏng) và agent **tự kiểm tra trạng thái trước khi hứa** một việc phụ thuộc vào nó.
- Cấp thêm quyền (scope) là một link riêng cho đúng phần quyền thiếu; ngắt kết nối do user chủ động. Connector tự chế: gặp dịch vụ chưa có sẵn, agent tự viết connector (doc + helper) theo mẫu chuẩn rồi mới dùng — không bịa luồng kết nối.
- Hệ connector có sẵn của user (Gmail, Calendar, Drive, Sheets, Threads, Instagram, Messenger, Facebook, Zalo, Canboso, NLM...) được đóng gói lại theo chuẩn này ở Phase 3.

### 16.3 Skills — Plugins — MCP
- **Skills:** định dạng SKILL.md (name, description, hướng dẫn, script kèm theo). Nạp theo cơ chế *progressive disclosure*: lúc thường chỉ nạp mục lục (tên + mô tả), skill nào liên quan tới việc hiện tại mới nạp toàn văn — giữ prompt nhẹ. User thêm skill bằng cách gửi file hoặc link repo; agent tự tạo skill từ việc lặp lại (mục 4.5) và skill nào cũng qua eval + sandbox trước khi được tin dùng (mục 6). Skill có phiên bản và tắt được từng cái.
- **Đủ điều kiện mới được chọn (eligibility, mượn OpenClaw):** frontmatter của skill khai `requires` (env/binary/config cần có); skill thiếu phụ thuộc bị loại khỏi danh sách cân nhắc ngay từ đầu. Thứ tự ưu tiên khi trùng tên: workspace của user > skill agent tự học > bộ cài sẵn. Skill tải từ registry bên ngoài bắt buộc qua bước vet (đọc source + scan + chạy sandbox) mới được tin — bài học chiến dịch skill độc hại ClawHavoc 02/2026 (Phụ lục 17).
- **Plugins:** định nghĩa dứt khoát để không lặp lại thảm họa catalog của Mulon cũ — plugin là một *gói cài đặt được* gồm skills + MCP servers + connector + hooks, có manifest **và code chạy được và một loader thật**. Quy tắc thép: plugin nào không nạp chạy được thì không xuất hiện trong danh mục. Cài/gỡ/nâng cấp plugin bằng chat, trạng thái từng plugin xem trong topic Hệ thống.
- **MCP hai chiều:** client dùng server ngoài (mục 6, Phụ lục 15) — và chính agent cũng phơi bộ tool lõi của mình thành một MCP server để agent con hoặc hệ khác dùng lại. Registry MCP có cấu hình riêng từng server (lệnh/env/OAuth), log riêng, tắt/bật không cần restart toàn hệ.

### 16.4 Feed
- Feed là các bài viết **do agent tự viết** (không phải aggregator, không đăng lại từ nguồn ngoài): nguồn gồm web, mạng xã hội, các connector của user, goals + memory + brief. **Brief** là một đoạn prompt văn bản thuần user sửa được bằng lời thường ("ít crypto, nhiều F1 hơn") — sửa brief thật sự thì sinh ngay một bài mới trên cùng.
- Lịch sinh bài do hệ thống nền quyết (tần suất theo mức hoạt động của user), thứ tự hiển thị theo độ hữu ích: chưa xem → có việc cần user làm → sắp đến hạn lên trước, quá hạn chìm xuống.
- **Taste summary:** gu của user được học từ reaction và những lần thảo luận về bài trong chat chính (chỉ đọc là không tính), writer đọc bản tóm tắt gu này chứ không đọc transcript thô; bài viết không bao giờ trích đoạn chat làm nguồn.
- User tạo/sửa/xóa/sắp xếp từng bài ngay trong topic Feed bằng chat. User mới có sẵn bộ bài giới thiệu (Getting started) viết sẵn, không dựa trên dữ liệu của họ.

### 16.5 Ideas
- Thẻ ý tưởng là các đề xuất việc agent có thể làm cho user, do tiến trình nền sinh từ goals, memory và ngữ cảnh gần. Mỗi thẻ có nút **"Làm luôn"**: bấm là chạy ngay trong chat, hiện tiến độ tại chỗ.
- User bỏ qua thẻ bằng thao tác của mình (agent không tự nhận là đã bỏ qua thay). Thẻ tự biến mất khi: hết hạn (~2 tuần), việc đã được làm, hoặc hệ thống phát hiện việc không còn đúng nữa. User hỏi "sao ý tưởng kia biến mất" thì agent trả lời được đúng lý do.

### 16.6 Goals & Tracking (bề mặt)
- Goal có đúng 2 trạng thái: đang chạy / đã hoàn thành (không có tạm dừng; muốn nghỉ thì tắt đẩy chủ động cho goal đó + ghi chú, hoặc đóng rồi mở lại). Subgoal đúng 1 cấp.
- Mỗi goal có workspace riêng, nhật ký tiến độ (progress entries có ngày tháng, sửa/xóa được khi sai/trùng) và **briefing dạng Letter** do worker nền viết theo lịch của hệ thống, đính vào goal; không hứa briefing theo yêu cầu tức thời.
- Xóa goal là xóa kèm subgoal + nhật ký + các job thuộc goal — luôn có xác nhận trước. Việc nền thật cho goal chỉ chạy qua job gắn với goal đó.
- Tracked items (cam kết cụ thể: đơn hàng, đặt chỗ, hạn chót) là lớp riêng dưới goals, có trạng thái mở/đóng rõ ràng và được agent tự cập nhật khi có bằng chứng kết quả.

### 16.7 Library & Artifacts
- **Library** là catalog mọi thứ tạo ra/lưu cho user: tài liệu, media, artifact, file user gửi lên (file gửi trong chat được lưu vào kho user và lập chỉ mục để tìm lại bằng ngôn ngữ tự nhiên). Thao tác: ghim (pin), chia sẻ, tải về, đổi tên, xóa vào thùng rác giữ 30 ngày khôi phục được.
- **Artifacts** có 3 loại: tài liệu (file tải về được), trang tĩnh (host live từ máy của agent), app tương tác (có cơ sở dữ liệu riêng, sống qua restart). Xuất bản ra link công khai: chỉ artifact tĩnh, **duyệt 1 chạm cho từng lần xuất bản và từng lần cập nhật** — không có chế độ duyệt sẵn vĩnh viễn. Xóa artifact là vĩnh viễn (khác thùng rác của file thường) và phải cảnh báo trước.
- Chia sẻ file cho người ngoài bằng link tải tạm có hạn (tối đa 48h), mỗi lần tạo link là một lần duyệt riêng.

### 16.8 Lịch sử task & lịch sử phê duyệt
- **Task history:** mọi tác vụ đều có hồ sơ truy lại được: yêu cầu gốc, kế hoạch, các bước, tool đã dùng, kết quả, bằng chứng, lỗi nếu có. User hỏi "hôm qua mày làm gì cho tao" là trả lời từ hồ sơ này, không từ trí nhớ mơ hồ của model. Xem trong topic Lịch sử & Hệ thống (danh sách dài thì xuất thành file), hoặc hỏi qua chat.
- **Approval history:** mọi yêu cầu duyệt từng được đưa ra: nội dung, quyết định (duyệt/từ chối/hết hạn), thời điểm, từ chat nào. Mọi grant quyền còn hiệu lực được liệt kê kèm phạm vi + ngày hết hạn, thu hồi được ngay.
- Dù mặc định vận hành là full-auto theo lệnh user (mục 0.6), hai lớp lịch sử này vẫn ghi đầy đủ — đây là nền của sự minh bạch và là nơi user siết quyền lại khi muốn, không phải cơ chế chặn mặc định.

### 16.9 Cron — Hooks — Services (bề mặt người dùng)
- User chỉ nói ý định ("nhắc tao...", "mỗi sáng kiểm tra...", "khi nào có X thì báo") — agent chọn cơ chế: **cron** cho việc cần suy luận/tool theo lịch (kể cả chạy 1 lần), **hook** cho detector nhẹ chạy script thăm dò và chỉ đánh thức agent khi có điều kiện đúng, **service** cho chương trình phải chạy liên tục. Mỗi job có: chủ sở hữu (chat chính hoặc goal), phạm vi, điều kiện dừng/hoàn thành, nơi nhận kết quả.
- Quản lý bằng chat: xem danh sách, xem lần chạy gần nhất (kết quả thật, lỗi thật), sửa, xóa. **Mặc định không job nào tự bật** — mọi lịch chạy đều do user bật đích danh (bài học từ lần user ra lệnh xóa toàn bộ job 2026-10-22: hệ thống phải tôn trọng trạng thái "tắt hết" đó cho tới khi được bảo khác).
- Trung thực vận hành: lịch chạy được kiểm chứng bằng lịch sử chạy thật, không báo "đã đặt" như thể đã chạy; job lỗi phải tự sửa trong phạm vi của nó hoặc tắt + báo rõ kết quả nào sẽ không còn tới.

### 16.10 Tâm hồn & danh tính
- **SOUL.md** là file tính cách (giọng, nguyên tắc ứng xử) — user sửa tay hoặc ra lệnh sửa; hệ thống không tự ý viết lại SOUL.
- **Nghi lễ khởi tạo (mượn BOOTSTRAP.md của OpenClaw):** lần chạy đầu tiên, agent dẫn một cuộc hỏi đáp ngắn ngay trong group để sinh IDENTITY/SOUL/USER từ chính câu trả lời của user, xong thì xóa file bootstrap — không bắt user điền form cài đặt. **IDENTITY**: tên do user đặt qua một bước onboarding ngắn, avatar do agent tự tạo/cập nhật được, emoji chữ ký. **USER.md** là hồ sơ user.
- Lớp alignment (bản tổng hợp "agent hiểu user tới đâu") do hệ thống tự duy trì ở tầng ký ức (mục 4.1) — đây là phần "tâm hồn lớn lên theo thời gian", tách khỏi SOUL gốc để user luôn giữ quyền cuối với tính cách của agent.

### 16.11 Bộ nhớ — bề mặt người dùng
- User xem được agent đang nhớ gì về mình (hỏi qua chat hoặc xem trong topic Ký ức thuộc cụm Lịch sử & Hệ thống), **hỏi nguồn** bất kỳ ký ức nào ("sao mày biết" → trả lời ký ức đó sinh từ đâu, khi nào, thay thế ký ức nào).
- Sửa/quên theo yêu cầu: quên là một quy trình có kế hoạch phạm vi (tìm mọi bản sao + hệ quả) → user xác nhận → thực thi → kiểm chứng, không phải xóa một dòng rồi báo xong.
- Import ký ức từ AI khác (prompt xuất Markdown mang sang + nhập file export ZIP để tóm tắt vào ký ức) và export toàn bộ dữ liệu của agent về user (ký ức, hồ sơ, lịch sử) khi user cần.

### 16.12 Kho lưu trữ bảo mật (Secure Vault)
- Mật khẩu, API key, token **không bao giờ đi qua nội dung chat**: user nhập qua form web bảo mật dùng một lần (trang nhập tối giản do chính agent host, mở bằng link một lần từ chat — không phải Mini App) ghi thẳng vào vault mã hóa (khóa trong OS keychain hoặc file mã hóa bằng khóa riêng của máy). Agent chỉ kiểm tra được "có tồn tại hay không", không bao giờ đọc thấy giá trị.
- Dùng một lần (không lưu) hay lưu để dùng lại là lựa chọn của user trên chính form đó. Xóa một đăng nhập đã lưu do user tự thao tác trong phần cài đặt.
- Mã một lần (OTP): khi một tác vụ đăng nhập cần mã vừa gửi tới email/tin nhắn đã kết nối, agent tra cứu qua đường đọc được bảo vệ, giữ mã dưới dạng tham chiếu mờ (~10 phút), user duyệt trên thẻ thì mã mới được đưa vào nơi đang chờ. Mã không vào vault, không vào ký ức.
- Redaction bắt buộc: giá trị bí mật bị che trong mọi log, trajectory và báo cáo — kể cả khi nó xuất hiện trong output của tool.

### 16.13 Quyền (Permissions) — nhìn từ phía người dùng
- Quyền được cấp theo phạm vi (hành động × dịch vụ × đối tượng) và có thời hạn; mỗi lần mở rộng phạm vi là một quyết định riêng — quyền cũ không tự suy ra quyền mới, và "đã từng đồng ý" không phải giấy phép vĩnh viễn.
- Thẻ duyệt 1 chạm cho hành động ngoài phạm vi đã cấp; trong phạm vi đã cấp thì mức tự chủ theo cấu hình của user (mặc định full-auto như user đã chốt). Mọi quyết định vào approval history (mục 16.8).
- Thanh toán là lớp duyệt riêng, không gộp với duyệt hành động thường: ví/thẻ do nhà cung cấp thanh toán giữ, agent không lưu số thẻ; mọi lần trả tiền đều qua thẻ duyệt thanh toán riêng của nó.

### 16.14 Proactivity & sở thích chủ động
- File `PROACTIVE_PREFERENCES` bằng ngôn ngữ thường: nên chủ động về chủ đề gì, tình huống nào, khung giờ nào (mặc định 09:00–21:30), trình bày dạng gì. User sửa bằng cách nói chuyện bình thường ("đừng nhắc vụ đó nữa" là một cập nhật preference, không phải xóa vĩnh viễn trừ khi user nói vậy).
- Mọi tin chủ động đều qua kỷ luật chọn lọc (mục 7): kiểm tra lại tính tươi mới trước khi gửi, im lặng khi không có gì thật sự đáng; user phản hồi "đã xử lý rồi" là tín hiệu đóng vòng được tôn trọng ngay.

### 16.15 Phạm vi kênh: Telegram là tất cả (chốt của user 2026-10-23)
- Sản phẩm này **chỉ sống trên Telegram**: DM + group forum là toàn bộ bề mặt. Không lớp trừu tượng đa kênh, không Zalo/Messenger/WhatsApp/Web — lõi vì thế nhẹ hơn và mọi quyết định tương tác (topic, reaction, inline keyboard, forum) được thiết kế sâu cho đúng một nền tảng thay vì nông cho nhiều nền tảng.
- "Side chats" trong thiết kế này nghĩa là các cuộc trò chuyện Telegram khác (group có người khác, DM với người khác) nơi bot hoạt động thay user theo cơ chế worker ở mục 16.1 — vẫn nằm hoàn toàn trong Telegram.
- Các dịch vụ ngoài (Gmail, Threads, Facebook, Zalo của user...) chỉ xuất hiện dưới vai trò **connector/tool mà agent dùng để làm việc**, không phải kênh để user nói chuyện với agent.

## 17. PHỤ LỤC — OPENCLAW & HERMES: áp dụng và tham khảo gì (quét + kiểm chứng 2026-10-23)

Mulon cũ lấy cảm hứng từ cả hai dự án này nhưng chỉ mượn được cái vỏ. Vòng quét này kiểm chứng trực tiếp GitHub/docs của cả hai để rút phần ruột. Kết luận chung trước: **không nhúng nguyên vẹn bất kỳ framework nào** — OpenClaw là TypeScript (392K★, MIT, do OpenClaw Foundation quản trị), Hermes Agent của Nous Research là Python (256K★, MIT) nhưng là hệ sinh thái khổng lồ 58K commit. Cả hai đều xung đột quyết định "lõi mỏng tự viết". Vai trò đúng của chúng: **thư viện pattern đã kiểm chứng ở quy mô thật**.

### 17.1 Từ OpenClaw — MƯỢN pattern
| Cơ chế | Áp vào đâu trong thiết kế này |
|---|---|
| **Pre-compaction memory flush** ⭐ | Lượt agent im lặng trích fact bền ghi vào file ký ức *trước khi* compaction nén ngữ cảnh, tại ngưỡng (ngân sách − phần dự trữ), quy ước NO_REPLY khi không có gì đáng lưu, đếm số lần chống flush trùng. Đã bổ sung vào mục 3.2 — đây là mảnh clone thiếu rõ nhất: thiếu nó thì "nén" = "quên". |
| **Bộ file workspace theo vai** + private git làm backup "bộ não" | AGENTS/SOUL/USER/IDENTITY/MEMORY + `TOOLS.md` (quy ước local) + `memory/YYYY-MM-DD.md` (nhật ký ngày append-only). Trùng và khẳng định lại mục 4.1; bổ sung: USER.md có ngân sách ký tự + directive ghi ngày; chỉ số (index) là dẫn xuất, mất thì rebuild từ file — file mới là sự thật. |
| **Quy tắc riêng tư của MEMORY.md** | MEMORY.md chỉ nạp trong session riêng tư (main/DM), không nạp ở group — khớp và củng cố quy tắc khán giả ở mục 16.0. |
| **Hybrid search 70/30** | Trộn ~70% vector / 30% BM25 là điểm khởi điểm thực tế của OpenClaw → đưa vào mục 4.2, tinh chỉnh tiếp bằng eval. Kèm fallback chain: embedding lỗi thì degrade xuống BM25-only, recall không sập. |
| **BOOTSTRAP.md — nghi lễ khởi tạo** | Lần chạy đầu: agent hỏi đáp ngay trong group để sinh IDENTITY/SOUL/USER, xong thì **xóa file bootstrap** (để lại chỉ tốn token). Đã bổ sung vào mục 16.10. |
| **Heartbeat gom việc** | Một lượt quét đọc checklist HEARTBEAT.md (agent tự ghi được), gom nhiều kiểm tra nhỏ vào 1 lượt, ngữ cảnh nhẹ (lightContext), model rẻ riêng, khung giờ hoạt động (activeHours), không có gì thì trả `HEARTBEAT_OK` và im lặng. Hiện thực tham chiếu cho mục 7 — với khác biệt giữ nguyên: của clone là **opt-in đích danh**, không mặc định bật như OpenClaw. |
| **Cron isolated-session** | Job chạy trong session riêng với ngữ cảnh tươi, xong trích summary gửi về đúng kênh/topic gốc; thêm kiểu custom-session cho job cần trí nhớ liên tục. Bổ sung vào mục 16.9. |
| **SKILL.md `requires` + eligibility + precedence** | Frontmatter khai phụ thuộc (env/bins/config); skill thiếu phụ thuộc bị loại khỏi cân nhắc ngay; thứ tự ưu tiên khi trùng tên. Đã bổ sung vào mục 16.3. |
| **Vet skill ngoài — bài học ClawHavoc** | 02/2026, hàng trăm skill độc hại trên registry ClawHub cài mã đánh cắp dữ liệu. Bằng chứng thực tế cho quy tắc đã chốt: skill ngoài bắt buộc đọc source + scan + sandbox trước khi tin. Registry mở là bề mặt tấn công thật, không phải lý thuyết. |
| **Policy 2 lớp (exec-approvals)** | File chính sách tầng máy thắng mọi cấu hình trong phiên; prompt/session không tự nới được. Đã bổ sung vào mục 6 (giữ default full-auto theo lệnh user — mượn kiến trúc, không mượn default của họ). |
| **Session key có cấu trúc** | `agent:main:telegram:group:<id>:topic:<id>` — map thẳng sang mô hình (group × topic) ở mục 16.0. |

### 17.2 Từ Hermes Agent — MƯỢN pattern
| Cơ chế | Áp vào đâu trong thiết kế này |
|---|---|
| **Background review fork sau mỗi lượt** ⭐ | Sau mỗi lượt chat, một fork nhẹ chạy nền với bản *digest* nén của lượt + trần token cố định, trích bài học/fact ngay khi ngữ cảnh còn tươi; rẻ hơn 3–5× so với dùng model chính mà giữ gần nguyên chất lượng ghi nhận. Đã bổ sung vào mục 4.3, nâng cấp mô hình "worker theo lịch" cũ. |
| **Memory nudges** | Nhắc định kỳ theo interval để agent chủ động lưu fact/quyết định và xét tạo skill ngay trong phiên, thay vì chờ cuối phiên. Đã bổ sung vào mục 4.3. |
| **Trần cứng khi ghi ký ức + frozen snapshot + quét injection** | Ghi vượt trần từng lớp → lỗi kèm danh sách hiện tại, buộc tự gộp/xóa trong cùng lượt; bản prompt là snapshot đóng băng theo phiên (giữ prefix ổn định); entry chứa pattern injection/bốc dữ liệu bị chặn khi ghi. Đã bổ sung vào mục 4.1. |
| **Session search trả nguyên văn (~20ms, 0 LLM)** | Phần "tìm lại đoạn hội thoại cũ" của recall trả **tin gốc nguyên văn + cuộn xem**, không tóm tắt bằng LLM. Kèm cảnh báo sống còn của chính Hermes: trên Telegram, chat là phiên liên tục không tự kết thúc → phải có **ranh giới phiên chủ động** (chốt theo việc xong/ngày mới trong từng topic) thì vòng học mới kích hoạt được. Đã bổ sung vào mục 16.0. |
| **Ngưỡng tạo skill ≥5 tool call** | Tác vụ dùng ≥5 lần gọi tool thì xét chưng cất thành skill; việc quen đóng gói thành **script gọi qua 1 lần thực thi** (scripted tools) tốn ~0 ngữ cảnh. Đã bổ sung vào mục 4.5. Giữ khác biệt của clone: skill vẫn phải qua eval/sandbox mới được tin (Hermes ghi tự do hơn). |
| **Sổ cái skill/bài học (curator ledger)** | Mọi thay đổi tự động vào append-only ledger kèm SHA-256 từng file, rollback theo từng mục; thao tác sửa/xóa ký ức của worker nền luôn hoàn tác được 1 chạm. Đã bổ sung vào mục 4.4. |
| **Bề mặt "hành trình học" (`/journey`)** | Timeline những gì agent đã học (skill, ký ức, bài học) để user xem/sửa/xóa — map vào topic Lịch sử & Hệ thống, là mặt minh bạch của vòng học (mục 16.8/16.11). |
| **Dialectic user modeling (ý tưởng của Honcho)** | So sánh điều user *nói* với điều user *làm* (stated vs revealed preference) trong prompt của alignment worker nhà mình — chỉ mượn ý tưởng, không dùng dịch vụ Honcho. |
| **Bài học phản diện** | Chính Hermes ghi nhận: model yếu hay *nói* "đã nhớ" mà không ghi thật → tầng verify của clone phải kiểm tra file/DB sau khi ghi, không tin lời báo cáo. Và nghiên cứu skill poisoning (skill tự sinh nhiễm injection mang sang mọi phiên sau) → cổng sandbox/ledger là bắt buộc, không nới. |

### 17.3 TRÁNH — nói rõ để khỏi quay lại
- **Chạy thẳng OpenClaw hoặc Hermes làm nền**: sai ngôn ngữ (OpenClaw) hoặc quá nặng và khóa vào hệ sinh thái của họ; toàn bộ logic group-forum/allowlist/bán hàng tùy biến sẽ phải đánh nhau với framework. Cả hai đã được cân nhắc và loại có lý do, không phải chưa biết.
- **Honcho-as-a-service** (dữ liệu user rời máy/tự host thêm hệ), **repo Hermes self-evolution** (mức demo 8 commit — GEPA nhúng lib độc lập ở Phụ lục 15 vẫn là lựa chọn đúng), **trajectory/training pipeline của Nous** (user không train model), **nodes/companion apps/đa kênh của OpenClaw** (ngoài phạm vi Telegram-only).
- **Mọi default "tiện trước, an toàn sau"** của OpenClaw (exec toàn quyền không hỏi, sandbox tắt mặc định) — clone giữ default theo lệnh user nhưng kiến trúc policy phải chặt hơn của họ.
- **Đốt quota kiểu OpenClaw**: heartbeat/cron dày đặc từng bị ghi nhận chi 30–300 USD/ngày tiền API ở người dùng thật — với clone chạy Gemini qua proxy quota hữu hạn, kỷ luật lightContext + model rẻ + activeHours + opt-in là bắt buộc.
