# Mulon Mini App — Design System

Ngôn ngữ thị giác: **"Ấm, tĩnh, tin cậy"** theo app Muse, cộng
nhận diện tím oải hương của Mulon. Nền giấy ấm, thẻ trắng viền
mảnh, gần như đơn sắc: MỘT họ hue duy nhất (tím Mulon hoặc hue
user chọn làm theme) — hành động chính dùng bậc đậm nhất của
chính hue đó. Không hue thứ hai (đất nung của Muse đã loại bỏ
hẳn theo yêu cầu user 2026-10-24). Không gradient lòe loẹt,
không emoji làm icon UI (SVG inline thống nhất: lưới 24px,
stroke 1.8, bo đầu nét).

## Token màu (lấy mẫu pixel từ ảnh nhân vật Mulon)

| Token | Giá trị | Dùng cho |
|---|---|---|
| `--paper` | #FAF9F7 | nền app (trung tính ấm) |
| `--surface` | #FFFFFF | thẻ |
| `--surface2` | #F3F1EC | track segmented, nền phụ |
| `--ink` / `--ink2` / `--ink3` | #1F1E1D / #6E6A61 / #A39E93 | chữ chính / phụ / mờ |
| `--line` | #E8E4DC | viền thẻ |
| `--lav` | #9598C4 | tím Mulon (lông nhân vật, chuẩn hoá) |
| `--lav-deep` | #5A5E94 | bậc đậm của hue — chữ/icon tím cần tương phản |
| `--accent` / `--accent-press` | suy từ hue (JS gán theo theme) | HÀNH ĐỘNG CHÍNH duy nhất — bậc đậm nhất của hue đang chọn |
| `--lav-tint` | #E9EAF4 | nền tint tím |
| `--cream` | #EFD8AE | mặt nhân vật — chỉ điểm xuyết nhận diện |
| `--rose` | #D17E78 | CHỈ 1 chấm nhỏ cạnh tiêu đề khối chờ duyệt |
| `--ok` / `--warn` / `--err` | #3E9B6C / #C9932B / #D95F57 | token ngữ nghĩa DỰ TRỮ — không sơn trạng thái danh sách; chỉ lỗi hệ thống thật (dải lỗi tải dữ liệu) mới dùng `--err` |

Dark: khi Telegram `colorScheme=dark`, map lại cùng cấu trúc
token (paper #17212B kiểu Telegram, surface sáng hơn nền 1 bậc,
ink đảo sáng) — không đổi layout.

## Quy tắc 60/30/10 (kỷ luật màu)

- **60% TRUNG TÍNH:** paper + thẻ trắng + surface2 — phần lớn
  mọi màn hình.
- **30% TÍM MULON:** bề mặt phụ + nhận diện — vòng/trạng thái
  avatar, mục đang chọn, liên kết, monogram Kết nối. Tab đang
  active KHÔNG dùng tint tím nữa (vòng 3, TB-2): segmented chỉ
  chữ, active = nền `--surface` trên track `--surface2` + chữ
  `--ink` — một tín hiệu trung tính duy nhất. Ô icon đã bỏ
  hẳn (KT-3): glyph trần `--ink2`, không ô chứa.
- **10% ĐIỂM NHẤN:** `--accent` — bậc đậm nhất của chính hue
  đang chọn — CHỈ cho hành động chính (Duyệt, CTA chính; tối
  đa 1 điểm nhấn mỗi màn hình). `--rose` thu về đúng 1 chấm
  nhỏ ở khối chờ duyệt. Màn nào accent xuất hiện quá 1 điểm
  nhấn chính thì hạ xuống ink/lav.

## Kỷ luật trạng thái & phân cấp (user chốt 2026-10-24)

Đối chiếu app Muse — gần như đơn sắc, trạng thái bằng chữ
trung tính, phân cấp rõ, kích thước gọn. Sáu điều KHÔNG
được phá:

1. **Không pill/tag trạng thái.** Không còn filled pill/tag
   cho kết quả hay trạng thái ở bất kỳ màn nào (đã duyệt,
   đang chạy, đang tắt…). Trạng thái = chữ thường theo
   thang mực (`--ink` / `--ink2` / `--ink3`) + tối đa 1 ký
   hiệu mảnh đi kèm (✓ / ✕ / ·).
2. **Không màu trạng thái xanh/vàng/đỏ trong danh sách.**
   Không ô icon, chữ hay chấm sơn `--ok` / `--warn` /
   `--err` cho trạng thái ở Việc, Phê duyệt, Lịch, Kết
   nối, Hệ thống, Quyền. Hai token tint đi kèm
   (`--tint-ok`, `--tint-warn`, `--tint-blue`) đã gỡ hẳn.
   `--err` chỉ còn ở dải lỗi tải dữ liệu — lỗi hệ thống
   thật, không phải trạng thái mục danh sách.
3. **Không dư sub text.** Mỗi hàng tối đa 1 dòng phụ và chỉ
   khi thật cần (bước đang chạy, chi tiết lỗi, giá trị dữ
   liệu như cron/giờ tới). Hàng mục lục Cài đặt không sub
   mô tả. Note ở màn con là chữ trần, tối đa 1 dòng dưới
   tiêu đề — giải thích dài để ở cuối màn, không lặp lại ý
   của hàng ngay dưới nó (TQ-2).
4. **Kích thước gọn.** Vòng 3 đo lại theo audit: header
   56pt (avatar 40), tab segmented 38pt, hàng 52, thẻ lớn
   88 — khối lượng thị giác giảm bằng bỏ ô icon, hạ weight
   nhãn hàng (600→500) và bỏ chrome lặp, không bằng thu
   nút/toggle (đã đúng chuẩn iOS: nút 44, toggle 51×31).
   Vùng chạm ≥44 giữ bằng padding trong suốt (swatch 28
   trong nút 44); ngoại lệ có chủ đích: nút segmented 32
   trong track 38 theo đúng mẫu control của Muse/iOS.
5. **Mỗi màn đúng 1 điểm neo thị giác.** Phê duyệt = tiêu
   đề hành động chờ duyệt + cụm nút; Việc = dòng trạng thái
   hiện tại ở header; màn con = tiêu đề màn. Tiêu đề
   section (`card-title`) 13/600 `--ink2` sentence-case —
   đọc như đầu mục của Muse, lùi sau điểm neo bằng cỡ +
   thang mực, không bằng viết hoa micro.
6. **Giấy và surface phân biệt bằng viền**, không bằng
   thêm màu nền; tint màu mè ngoài `--tint-lav` (nhận diện)
   và `--tint-gray` (đường chia trung tính) không quay lại.

## Màu chủ đề (theme) — Cài đặt → Giao diện

User chọn 1 trong 6 họ màu; swatch đang chọn có vòng bao theo
`--lav-deep` của chính họ đó + dấu tick trắng. Chọn là áp ngay
(localStorage) và lưu bền phía server (`kv: webapp_theme`, trả
qua `profile.theme` trong `/api/state`) để đồng bộ đa thiết bị.
(Theme "Đất nung" đã gỡ 2026-10-24 cùng đợt bỏ clay; theme đã
lưu là `clay` tự rơi về mặc định lavender nhờ kiểm tra
`stored in THEME_KEYS` phía server.)

**Nguyên tắc cứng:**

- Theme thay họ hue của lớp **30% nhận diện** VÀ suy ra
  **accent lớp 10%** từ chính hue đó: các token `--lav`
  (base), `--lav-deep` (deep), `--tint-lav` (tint, và biến
  thể tint tối khi dark), `--accent` / `--accent-press`. Mọi
  phần tử suy từ các token này (vòng/trạng thái avatar,
  monogram Kết nối, liên kết, mục đang chọn, nút hành động
  chính, vòng chọn swatch) tự đổi theo — không hardcode
  hue ở component, không hue thứ hai cho nút. (Tab active
  từ vòng 3 là trung tính — nền `--surface` + chữ `--ink`
  — nên không đổi theo theme, đúng mẫu Muse.)
- Accent theo scheme: sáng → `--accent` = deep, nhấn =
  press; tối → `--accent` = base (nền nút sáng lên, chữ nút
  chuyển tối), nhấn = deep. Chữ tím trên tint: sáng dùng
  deep (đã nới đậm để đạt tương phản ≥ ~4.5:1 trên tint),
  tối dùng base trên tint tối.
- `--rose` (chấm chờ duyệt) và ok/warn/err giữ nguyên theo
  theme. Giấy + trung tính (`--paper`, `--surface*`,
  `--ink*`, `--line`) không đổi → kỷ luật **60/30/10 giữ
  nguyên**, chỉ hue thay đổi.

| Theme | base | deep | press | tint (sáng / tối) |
|---|---|---|---|---|
| Tím Mulon (mặc định) | #9598C4 | #5A5E94 | #4C4F80 | #E9EAF4 / #2E2A4A |
| Xanh dương | #86ABD8 | #40639A | #355584 | #E3EBF6 / #22344E |
| Hồng | #DF9FB8 | #A04A6E | #8C3E5E | #F9E8EF / #472733 |
| Đào | #EDB48C | #9A5A20 | #864D1B | #FAEEDF / #453014 |
| Xanh lá | #93C39B | #42704F | #386043 | #E6F2E8 / #1E3A2C |
| Chì | #A8A49C | #6E6A61 | #5D5952 | #EFEEE9 / #33322E |

Base/deep/tint của mọi họ giữ cùng độ sáng/bão hòa tương đối
như bộ tím gốc để tương phản chữ và tint nhất quán giữa các
theme. Thiếu API (server cũ) thì app vẫn chạy với theme local.

## Chữ, khoảng, bo, bóng, chuyển động

- Font: system stack. Thang chữ phân vai (vòng 3, PH-1):
  22 (điểm neo mỗi màn) / 20 (tiêu đề màn con) / 17 (tên
  định danh: header + tên thẻ lớn) / 15 (thân + nhãn hàng)
  / 13 (phụ, meta, giá trị) / 11 (nhãn micro). Weight phân
  vai: **600** chỉ cho tiêu đề, nút và điểm neo; **500**
  (`--fw-m`) cho nhãn hàng; **400** cho nội dung và sub —
  vòng 2 dùng 600 cho ~90% chữ nên mọi dòng "hét" ngang
  nhau, không còn phân cấp. Phân cấp bằng CẢ ba kênh: cỡ
  chữ, độ đậm, và thang mực `--ink` / `--ink2` / `--ink3`.
  Line-height 1.25 (tiêu đề, letter-spacing -0.01em) / 1.45
  (thân). Mono chỉ cho khối nội dung hồ sơ và số liệu.
  Không cỡ chữ nào dưới 11px.
- Khoảng: **lưới 8pt** — mọi padding/gap/margin là bội của 4
  hoặc 8 (thang token 4/8/12/16/20/24/32/48), không số lẻ
  (rà theo skill `spacing-audit`: giá trị ngoài thang chỉ
  còn ở ngoại lệ đã ghi). Padding màn hình 16 (≥640: 24),
  section cách nhau 12–16, hàng danh sách ≥52px, vùng chạm
  ≥44×44 (kể cả nút phụ và link mở rộng), nút chính/phụ cao
  44 với padding ngang gọn (12). Mật độ tổng thể ngang trang
  Cài đặt của Muse. Ngoại lệ: đệm track segmented 3px +
  nút 32 (mẫu control Muse/iOS, xem mục Segmented) và hình
  học nội bộ của component (tâm núm toggle, nét tick của
  swatch, viền 1–2px) — không phải khoảng bố cục.
- Bo góc: thang rút gọn vòng 3 — thẻ **20**, control **12**,
  chi tiết nhỏ **8**, tròn **full** (segmented 12/9 theo
  đồng tâm: 9 = 12 − đệm 3). Bóng: chỉ 1 mức cho phần tử
  nổi (`0 8px 24px rgba(31,30,29,.08)`); thẻ thường dùng
  viền, không bóng.
- Chuyển động: 120/200/320ms, easing `cubic-bezier(.2,0,0,1)`;
  chuyển tab fade + trượt nhẹ 200ms; avatar đổi state
  transition ~240ms; tôn trọng `prefers-reduced-motion`.
  HapticFeedback của Telegram cho Duyệt/đổi tab — nhẹ tay.

## Component chuẩn

- **Header dính** (sticky, nền giấy mờ blur) — hàng ngang
  gọn (KT-1): avatar 40px (ảnh phủ kín, bỏ viền; chữ cái dự
  phòng nằm dưới ảnh) + tên 17/600 + dòng trạng thái sống
  13 lời thường cùng trục; tổng 56pt (`--stick-top` là
  hằng số duy nhất — bỏ hẳn cơ chế co header/nhảy offset
  khi cuộn). **Màn con ẩn hẳn header**, chỉ còn hàng nav
  (back + tiêu đề màn 20/600) như app Muse. Avatar states
  (CSS thuần trên asset sẵn có): idle (thở nhẹ), working
  (rung nhịp + vòng sáng xoay), waiting (vòng nhấp nháy
  `--lav` — chờ duyệt), done (nảy 1 nhịp), error (lắc
  ngang 2 nhịp). Chấm trạng thái cạnh dòng trạng thái:
  `--ink3` khi rảnh, `--lav` khi bận.
- **Segmented tabs — Phương án A (TB-2):** chỉ chữ, đúng
  mẫu control "Hiện có / Đã kết nối" của Muse. Track
  `--surface2` bo 12, đệm 3; nút cao 32 bo 9, chữ 13 —
  inactive 500 `--ink2`; active 600 `--ink` trên nền
  `--surface` + bóng `0 1px 3px rgba(31,30,29,.12)`. KHÔNG
  icon, KHÔNG tint tím, KHÔNG viền inset — active chỉ có
  đúng 1 tín hiệu (nền sáng + chữ đậm). Tổng cao 38pt.
- **Hàng danh sách:** KHÔNG ô chứa icon (KT-3) — glyph SVG
  trần 22pt `--ink2` stroke 1.8, MỘT bộ SVG thống nhất cho
  mọi loại hàng (hết ký tự chữ `✓/◌/✕/◷/✦` và chữ cái trong
  ô); riêng Kết nối dùng monogram 12/600 `--lav-deep` trên
  vòng tròn `--tint-lav` 28pt. Nhãn hàng 15/**500**, phụ
  đề 13 `--ink2` (chỉ khi thật cần), phần tử cuối: chevron
  SVG 16 stroke 2 `--ink3` / trạng thái dạng chữ / toggle.
  Trạng thái Việc nằm ở cuối hàng dạng chữ (`.r-state`) như
  lịch sử duyệt. Đường chia hàng thụt theo lề nội dung
  (bắt đầu ở x=16), không chạy sát mép thẻ.
- **Toggle iOS:** track thị giác 51×31 nhưng vùng bấm cao
  44 (track căn giữa theo chiều dọc) để đạt chuẩn vùng
  chạm; bật = `--lav`; tắt = token `--tgl-off` (sáng
  #D8D3C8 / tối #3A4757 — dark không còn vệt be phát sáng).
  **Quyền (KT-2):** bỏ segmented 3 nấc trong hàng — hàng =
  nhãn 15/500 (tối đa 2 dòng, trọn bề ngang) + giá trị hiện
  tại dạng chữ 13 `--ink2` + chevron lên/xuống SVG 12pt;
  bấm hàng mở menu nổi bo 12 (3 dòng × 44pt: Cho phép /
  Hỏi / Chặn, tick ở nấc hiện tại, bóng `--shadow-pop`).
  Pitch hàng 52–56pt. Payload API giữ nguyên
  (scope/name/verdict/persist), không sơn màu theo verdict.
- **Thẻ duyệt:** KHÔNG viền màu, KHÔNG tag — điểm neo là
  tiêu đề hành động 22/600 với 1 chấm `--rose` nhỏ cạnh
  tiêu đề. Dưới tiêu đề đúng 2 khối chữ 13 `--ink2`: dòng
  gộp (Nhóm · công cụ · tóm tắt — không thông tin nào nói
  2 lần) và dòng phạm vi rút 1 dòng ("Áp cho lần này ·
  'Duyệt và nhớ' = nhớ cho công cụ này tới hết phiên";
  chi tiết phạm vi đầy đủ nằm ở thẻ duyệt trong chat) +
  hộp Lý do giữ nguyên. Cụm quyết 2 hàng (KT-7): hàng 1
  [Chặn soft 1fr] [Duyệt accent 1.3fr] cao 48 — đúng 1 nút
  đặc; hàng 2 "Duyệt và nhớ" nút chữ ghost không viền 44
  full-width. Cụm **dính đáy viewport** với nền mờ blur
  như header (hết cạnh cắt khi dính) — xem Vùng ngón cái.
- **Thẻ hồ sơ lớn:** cao 88 cố định, nội dung xếp từ trên
  một trục trái (nhãn micro + tên 17/600 + meta 13), hết
  khoảng chết `space-between`. Màu thuộc HỌ TÍM: dossier
  `#5A5E94` (= `--lav-deep`), memory `#43476F` — cấm hue
  ngoài palette (nâu đất/xanh rêu đã gỡ). Dòng cẩn trọng
  gộp thành 1 câu 11px `--ink3` dưới cụm thẻ.
- **Note ở màn con:** chữ trần 13 `--ink2`, không hộp nền;
  tối đa 1 dòng dưới tiêu đề, nội dung dài chuyển xuống
  cuối màn.
- **Timeline:** rail dọc 2px `--line`, chấm 8px trung tính
  (xong `--ink2`, đang chạy `--lav`, còn lại `--ink3`),
  đệm đáy thẻ 8 (hết khoảng chết cuối thẻ). Tên bước dùng
  nhãn hành động lời thường (cùng ánh xạ với header/thẻ
  duyệt); tên tool thô chỉ ở dòng meta của bước.
- **3 trạng thái bắt buộc mọi màn:** đang tải (skeleton xám
  nhấp nháy đúng khung), trống (icon + 1 câu + gợi ý hành
  động), lỗi (dải báo + nút Thử lại). Polling tạm dừng khi
  app ẩn (`visibilitychange`). Safe-area bằng
  `env(safe-area-inset-*)` + viewport ổn định của Telegram.

## Vùng ngón cái, Peak-End, micro-interaction

Chuẩn của skill `mobile-app-ui-design`, áp theo cách của
Telegram Mini App:

- **Vùng ngón cái:** hành động chính của mỗi màn nằm ở 1/3
  dưới hoặc luôn với tới được. Tab bar dạng segmented dính
  trên là quy ước nền tảng của Telegram Mini App (app chạy
  dạng sheet trên khung chat, thanh điều hướng của Telegram
  ở dưới) nên giữ trên — thay vào đó: cụm nút quyết của thẻ
  duyệt dính đáy viewport khi thẻ dài, nút CTA của màn Vault
  nằm cuối nội dung màn, và mọi quyết định đều có đường
  tương đương ngay trong chat (thẻ inline) ở cuối cuộc trò
  chuyện.
- **Peak-End:** khoảnh khắc kết thúc mỗi luồng phải có phản
  hồi hoàn tất rõ: duyệt xong → avatar chuyển state `done`
  (nảy 1 nhịp) + toast xác nhận; lượt việc vừa hoàn tất →
  avatar `done` + toast "Một lượt việc vừa hoàn tất."; lỗi
  → avatar `error` (lắc). Tab Phê duyệt khi không còn gì chờ
  hiện thẻ trống dạng khẳng định ("Không có yêu cầu nào
  đang chờ duyệt…") thay vì khoảng trắng.
- **Micro-interaction:** mọi phần tử bấm được có trạng thái
  pressed — nút co 0.98 + nền press theo biến thể, hàng danh
  sách và mục segmented chưa chọn highlight nền khi chạm,
  swatch co 0.92, thẻ lớn co 0.99, link "Mở rộng"/back mờ
  0.55. Chuyển tab fade + trượt 200ms theo token motion.
  Trạng thái focus bằng bàn phím (`:focus-visible`) có
  outline `--lav-deep` cho nút và toggle.
- **Anti-pattern đã rà theo skill:** thang chữ/weight phân
  vai cố định (không weight 600 cho nhãn hàng); không
  khoảng lẻ ngoài lưới 4/8 trừ ngoại lệ đã ghi (đệm
  segmented 3px); không chữ dưới 11px; không vùng chạm
  dưới 44px trừ nút segmented theo mẫu Muse; không CTA
  accent thứ hai trên cùng màn; không ô chứa icon, không
  tint/viền inset cho trạng thái active; empty state luôn
  có glyph + câu hướng dẫn; bóng chỉ dùng tint mực ấm
  `rgba(31,30,29,…)` — không bóng đen thuần trên nền màu.

## Responsive

- **360–430 (chuẩn điện thoại):** 1 cột, padding ngang 16.
- **≥640:** lưới thẻ (Kết nối, Hồ sơ) 2 cột; padding ngang 24.
- **≥769 (Telegram Desktop):** nội dung khóa max-width 600px
  canh giữa trên nền đậm hơn 1 bậc; **≥900** tab Việc mở 2 cột
  (danh sách | chi tiết) như modal desktop của Muse.
- Không scale font theo vw; thang chữ + vùng chạm ≥44 giữ
  nguyên mọi bề rộng. Header giữ nguyên 56pt ở mọi độ sâu
  cuộn (không còn cơ chế co).
- Checklist khi sửa design: rà 5 bề rộng 360/390/430/768/1024
  (không vỡ, không tràn ngang) + tỷ lệ 60/30/10 ở các tab
  chính + tương phản chữ + dark không vỡ.
