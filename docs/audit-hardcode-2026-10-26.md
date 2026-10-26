# Audit hardcode MuLon — 2026-10-26

Phạm vi: bản vừa pull `mmmnhat/mulon-v2` HEAD `f05bd13` (v1.6.3) ở
`~/workspace/mulon-clone/repo-git`. Quét bằng grep/AST trên `mulon/*.py`,
`config/`, `scripts/`, `hooks/`, đối chiếu báo cáo
`codebase-audit-comprehensive.md` (user gửi 2026-10-26).

Kết luận: đúng như user nghi — hardcode nhiều, và nặng nhất không nằm ở
"hằng số rải rác" mà ở 3 chỗ: dữ liệu cá nhân/máy cá nhân lọt vào repo,
bảng từ khóa quyết định hành vi agent, và endpoint/tunnel chết cứng.

## A. Cứng + nguy hiểm (nên gỡ trước)

1. **93 symlink `skills/*` trỏ tuyệt đối `/Users/mmmnhat/.agents/skills/*`**
   Đường máy Mac của user commit thẳng lên repo. Sang máy khác toàn bộ
   gãy. Gỡ: bỏ khỏi repo (gitignore `skills/` symlink) hoặc thay bằng
   script cài skill theo máy.

2. **Email cá nhân hardcode trong code chạy**
   `mulon/telegram_bot.py:1511` — `{"user_google_email": "mmmnhat.1810@gmail.com", "query": "auth_probe"}`
   trong luồng probe Google auth. Đáng lẽ lấy từ Vault/config.

3. **Tunnel URL chết cứng trong `config/mcp_servers.json`**
   `GOOGLE_OAUTH_REDIRECT_URI=https://refinance-displayed-wing-approximate.trycloudflare.com/oauth2callback`
   — trycloudflare là URL tạm theo phiên tunnel, lần chạy sau là chết,
   mà OAuth redirect phải khớp tuyệt đối mới chạy. Đây là hardcode chắc
   chắn gây lỗi "tự nhiên OAuth hỏng". Gỡ: sinh từ WEBAPP_URL lúc
   start, không lưu chết trong config commit lên repo.

4. **Gateway multimodal chưa có containment (audit P0 #2 — CHƯA sửa ở bản mới nhất)**
   `mulon/gateway.py` `_prepare_multimodal_messages`: gặp tag
   `[Người dùng gửi kèm ảnh: <path>]` là đọc bất kỳ file nào ≤15MB,
   base64 gửi lên model — không kiểm workspace, không denylist.
   `.env` vẫn đọc được qua đường này. Audit nêu đúng, bản `f05bd13`
   chưa vá.

5. **`read_file`/`write_file` chưa có denylist `.env` (audit P1 — CHƯA sửa)**
   `mulon/tools.py` `_resolve_for_file_tool`: cho neo vào project_root
   (phục vụ self-evolution) nhưng không chặn `.env*`, `*.pem`,
   `*secret*`. 1.6.3 mới thêm denylist ở scan/share, chưa ở file tool.

## B. Cứng ở tầng hành vi agent (audit nêu nhưng ĐẾM THIẾU)

6. **`_TOOL_HINTS` = 155 chuỗi con** (`mulon/agent.py:45`), không phải
   85 như báo cáo audit ghi. Cộng `_LONG_HINTS` 9 + `_ACTION_PROMISES`
   12 (định nghĩa lồng trong hàm, `agent.py:424`) = router intent chạy
   bằng 176 mẫu câu cứng tiếng Việt/Anh. Đây là hardcode lớn nhất của
   dự án: thêm/bớt một cách nói của user là sửa code.

7. **Bảng marker học tập** (`mulon/learning.py`): `STRONG_MARKERS` 31 +
   `WEAK_MARKERS` 28 + `CRITICAL_HINTS` 17 = 76 mẫu cứng quyết định
   cái gì được học vào memory.

8. **Feed chạy bằng bảng cứng** (`mulon/feed.py`): `_NEWS_DOMAINS` 21
   domain, `_STOPWORDS` 34, `_OFFICIAL_SUFFIXES`, `_LOW_SIGNAL_TLDS`,
   `_TRUST_WEIGHT`. Đổi nguồn tin = sửa code thay vì sửa brief/config.

9. **Prompt hệ thống nhúng trong code**: `VERIFY_SYSTEM` (agent.py),
   `EXTRACT_SYSTEM` (consolidation.py), `CLASSIFY_SYSTEM`
   (learning.py), `_CHECK_SYSTEM` (proactivity.py),
   `_UNDERSTAND_SYSTEM` (voice.py), `DEFAULT_BRIEF` + `_FEED_TEMPLATE`
   + `_LEGACY_SYSTEM` + `_PIPELINE_SYSTEM` (feed.py). Trong khi dự án
   đã có cơ chế dossier để tách persona ra file — phần này chưa tách.

## C. Cứng ở tầng config (có env override nhưng default sai lệch)

10. **Cả 3 tier model cùng một default** (`mulon/config.py:123-125,351-353`):
    `model_brain = model_cheap = model_escalated = "gemini-3.8-flash"`.
    Phân tầng chỉ còn là hình thức; escalate không đổi model.
    Thêm bảng alias cứng ở `gateway.py:131-136`.

11. **Catalog MCP nhân đôi**: `KNOWN_MCP_FALLBACKS` ~33 entry hardcode
    trong `mulon/marketplace.py` (file 2.932 dòng, to nhất repo) trong
    khi đã có `config/marketplace_curated.json` (6 listings). Hai nguồn
    sự thật dễ lệch nhau.

12. **Endpoint Agnes chết cứng** (`mulon/media_tools.py:299`):
    `https://apihub.agnes-ai.com/v1/images/generations` + model mặc
    định `"agnes-image-2.1-flash"` (dòng 296) không qua env/config như
    các key khác.

13. **Hook cá nhân commit vào repo product**: `hooks/shopee_price_watch/`
    (ngưỡng giảm giá 20% ghi trong instruction, log.jsonl có cả lỗi
    `poll.sh: No such file or directory` từ máy user). Đây là dữ liệu
    vận hành cá nhân, không thuộc codebase.

14. Rải rác mức nhẹ: `bot_username` fallback `"Mulon_bot"`
    (`vault.py:472`), catalog URL trỏ repo cá nhân
    `raw.githubusercontent.com/mmmnhat/mulon-v2` (`config.py:327,460`),
    timezone `Asia/Ho_Chi_Minh` làm default ở 6+ chỗ (memory schema,
    planning, surfaces) thay vì một hằng config duy nhất.

## D. Không tính là hardcode xấu (đã kiểm, để khỏi gỡ nhầm)

- URL API Google/Bing/DuckDuckGo trong `google_conn.py`/`websearch.py`:
  endpoint chuẩn của nhà cung cấp, để trong code là bình thường.
- Proxy `127.0.0.1:8317` (11 chỗ): đây là ràng buộc kiến trúc cố ý
  (proxy-only), đã có `PROXY_BASE_URL` env + validate fail-fast.
- Sentinel `"local-proxy"` (`config.py:122`): audit P0 #1 — bản
  `f05bd13` ĐÃ sửa (`media_tools.py:283-285` loại `"local-proxy"` khỏi
  key hợp lệ). Kiểm chứng: test suite ở bản pull về chạy 442/442 pass,
  gồm cả `test_generate_image_tool_no_key_returns_structured_error`
  mà báo cáo audit (chạy trên Mac) ghi là fail. Báo cáo đó được viết
  trước commit sửa này.

## Thứ tự gỡ đề xuất

1. Vá A4 + A5 (an toàn, audit đã xếp P0/P1, chưa ai sửa).
2. A3 (OAuth redirect sinh từ WEBAPP_URL) + A2 (email lấy từ Vault) +
   A1 (dọn symlink khỏi repo) — một đợt "dọn dữ liệu cá nhân".
3. B6: thay router `_TOOL_HINTS` bằng cho model thấy tool definitions
   ngay từ đầu (audit mục 5 đã đề xuất cùng hướng) — đợt lớn nhất,
   đổi hành vi, cần eval vàng chạy lại.
4. C10/C11/C12: gom default về config/env một nguồn.
