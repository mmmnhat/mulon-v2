# Hướng dẫn đẩy code cho phía Muse (VM, qua GitHub connector)

> Dành cho Muse chính + mọi account Muse phụ (LUỒNG MUSE,
> LUỒNG PHỤ 1, 2, ...). Phía Antigravity trên máy Mac có git
> credential thật, đẩy bằng git thường (pull -> sửa -> rebase ->
> push) — tài liệu này không thay luật cho phía Mac, chỉ là phần
> riêng của phía Muse vì Muse KHÔNG có git credential trên VM.
> Luật chung vẫn là `AGENTS.md` + LUẬT ĐA LUỒNG trong
> `AGENT_TASKS.md`; tài liệu này chỉ mô tả thao tác đẩy.

## 1. Đường đẩy duy nhất

- Đọc repo: `github call-read-tool` — `list_commits` (lấy head +
  lịch sử) và `get_file_contents` (đọc 1 file tại `main`).
- Đẩy: `github push-files --owner mmmnhat --repo mulon-v2
  --branch main --message "<commit message>" --source-dir
  <thư mục cây local> --paths-file <file danh sách đường dẫn,
  ngăn cách bằng ký tự NUL>`. Công cụ này đọc nội dung file trực
  tiếp từ đĩa và tạo 1 commit chứa đúng các file trong danh sách.
- KHÔNG dùng `create_or_update_file` truyền nội dung qua tham số
  cho file vừa/lớn: nội dung đi qua argv, file khoảng >100KB sẽ
  chết `Argument list too long`. Mọi file, kể cả file nhỏ, cứ
  dùng `push-files` cho thống nhất.
- KHÔNG dùng `git fetch/pull/push` trần trên VM: repo là private
  và VM không có credential, lệnh sẽ chết ngay.

## 2. Trước khi sửa: luôn lấy nền mới nhất (quan trọng nhất)

Mọi vụ mất nội dung của dự án tới nay đều do đẩy từ nền cũ.
Trước mỗi đợt sửa, bắt buộc:

1. `list_commits` perPage=1 — ghi lại SHA head hiện tại.
2. Với MỖI file định sửa: `get_file_contents` lấy bản trên
   `main` và ghi đè vào cây local rồi mới sửa trên bản đó.
   Bắt buộc với các file dùng chung nhiều phía sửa:
   `AGENT_TASKS.md`, `CHANGELOG.md`, `mulon/__init__.py`
   (version), và thư mục `tests/`.
3. Nếu head thay đổi giữa lúc đang sửa (phía khác vừa đẩy):
   lấy lại các file dùng chung, áp lại thay đổi của mình lên
   nền mới, rồi mới đẩy.

Các vụ đã xảy ra, đừng lặp lại: mất mục T-29 (27/10), mất
verdict T-24.1 (push `72be848`), mất 2 mục CHANGELOG 1.7.22
của T-24.3 + spike T-22.3 (push `8fe2e97d`) — tất cả đều vì
đẩy toàn-file từ snapshot cũ.

## 3. Khi sửa file

- Sửa TUẦN TỰ, từng file một. Không chạy nhiều lượt sửa song
  song trên cùng một file: hai lượt sửa cùng lúc sẽ đua nhau
  ghi và một lượt mất nội dung (đã xảy ra với báo cáo DONE
  của T-25 ngày 27/10).
- Chỉ sửa file thuộc việc của mình. File đang thuộc luồng
  khác sửa dở (vd `mulon/telegram_bot.py` khi LUỒNG 1 đang
  làm) thì không đụng — ghi việc nối tiếp vào mục của mình
  và chờ, theo lưu ý an toàn của LUẬT ĐA LUỒNG.
- Script phụ trợ để ở thư mục workspace bền vững, KHÔNG để
  `/tmp` (bị xoá khi dịch vụ restart).

## 4. Version và CHANGELOG

- Đọc `mulon/__init__.py` trên `main` ngay trước khi bump:
  version mới = version cao nhất hiện có + 1 (vd đang 1.7.22
  thì lấy 1.7.23). Nếu hai phía cùng bump một lúc, phía đẩy
  sau phải lấy số tiếp theo — không để hai thay đổi trùng
  một số version (đã xảy ra: ba thay đổi cùng mang 1.7.22).
- Mục CHANGELOG mới nối vào ĐẦU file, trên nền CHANGELOG
  mới nhất vừa lấy ở bước 2 — không viết lại cả file từ trí
  nhớ hay từ bản cũ.

## 5. Commit message

- Dạng: `feat(<phạm vi>): <mô tả ngắn> (T-xx, vX.Y.Z)` cho
  code; `docs(tasks): ...` / `chore(tasks): ...` cho thay
  đổi ở `AGENT_TASKS.md`.
- Cuối message thêm một dòng trống rồi dòng ký tên theo luật
  ký tên riêng: `Ky: <tên của mày>`.

## 6. Trước khi đẩy: kiểm chứng

- Chạy toàn bộ test trên cây local:
  `env -u http_proxy -u https_proxy -u HTTP_PROXY
  -u HTTPS_PROXY -u all_proxy -u ALL_PROXY -u no_proxy
  -u NO_PROXY <python của venv> -m pytest tests -q`
  (strip env proxy là bắt buộc trên VM — biến `no_proxy`
  chứa IPv6 ngoặc vuông làm httpx vỡ, từng gây báo động giả).
  Suite phải xanh 100% mới đẩy.
- Diff đụng agent loop / router / prompt: chạy thêm eval
  vàng `mulon.evals` (cổng 85%).
- Nhớ: push lên `main` = bot tự deploy trong khoảng 15 giây
  qua `auto_watch` trên máy Mac. Không đẩy bản dở dang.

## 7. Sau khi đẩy: đọc ngược, và sửa sai công khai

1. `list_commits` — xác nhận commit của mình đang ở head
   (hoặc ngay dưới commit mới hơn của phía khác).
2. `get_file_contents` đọc lại từng file vừa đẩy — xác nhận
   nội dung trên `main` đúng như ý, gồm cả các phần của phía
   khác trong file dùng chung (đặc biệt `AGENT_TASKS.md`:
   kiểm tra nhanh các mục DOING/DONE của luồng khác còn
   nguyên không).
3. Nếu phát hiện mình đã ghi đè mất nội dung của phía khác:
   khôi phục ngay trong một commit sửa riêng, ghi rõ trong
   `AGENT_TASKS.md` một dòng đính chính công khai (việc gì
   mất, commit nào gây ra, đã khôi phục ra sao) — xem mẫu ở
   các dòng cập nhật ngày 27/10/2026. Giấu lỗi đè file là
   lỗi nặng hơn chính lỗi đè file.

## 8. Ghi AGENT_TASKS.md

- Nhận việc: commit claim riêng chỉ sửa mục của mình
  (trạng thái -> `DOING` + tên luồng + tên ký) TRƯỚC khi
  code.
- Xong việc: ghi `DONE` + kết quả + commit SHA vào mục,
  thêm dòng cập nhật ở đầu file ký tên mình. KHÔNG tự ghi
  `VERIFIED` cho việc của mình (luật ký tên + kỷ luật 3/6
  trong LUẬT ĐA LUỒNG).
- Chỉ sửa phần thuộc việc/luồng của mình + dòng cập nhật
  của mình; không viết lại toàn file từ bản cũ.
