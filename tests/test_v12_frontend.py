"""1.2.0 Khối 4 (đặc tả design mới): index.html là "tờ hồ sơ
agent" — header + 5 tab (Việc/Phê duyệt/Lịch/Lồ sơ/Cài đặt) +
3 màn con Cài đặt + bảng màu Muse; không CDN ngoài ngoài
script telegram-web-app chính thức."""

from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "mulon" / "webapp"
        / "index.html").read_text(encoding="utf-8")


def test_five_tabs_present():
    for label in ("Việc", "Phê duyệt", "Lịch", "Hồ sơ", "Cài đặt"):
        assert label in HTML
    for tab in ("viec", "pheduyet", "lich", "hoso", "caidat"):
        assert f'data-tab="{tab}"' in HTML
        assert f'id="tab-{tab}"' in HTML


def test_settings_subscreens_present():
    for screen in ("screen-connectors", "screen-vault",
                   "screen-policy"):
        assert f'id="{screen}"' in HTML
    for label in ("Công cụ kết nối", "Kho lưu trữ an toàn", "Quyền"):
        assert label in HTML


def test_detail_and_profile_screens():
    assert 'id="screen-task"' in HTML       # chi tiết lượt việc
    assert 'id="screen-profile"' in HTML    # xem nội dung hồ sơ
    assert "HỒ SƠ" in HTML and "BỘ NHỚ" in HTML
    assert "CẨN TRỌNG KHI TRUY CẬP" in HTML
    assert "Kỹ năng" in HTML


def test_approval_ui_and_deep_link_routing():
    # Vòng sửa design theo feedback user (2026-10-24): thẻ chờ
    # duyệt KHÔNG còn tag pill "Cần duyệt" + viền rose — điểm
    # neo là tiêu đề hành động lớn, rose chỉ còn 1 chấm nhỏ.
    assert "appr-tag" not in HTML
    assert "Cần duyệt" not in HTML
    assert "appr-dot" in HTML
    assert "Duyệt và nhớ" in HTML
    assert "approve_" in HTML            # startapp=approve_<id>
    assert "initDataUnsafe" in HTML     # đọc start_param
    assert "start_param" in HTML
    assert "/api/approve" in HTML
    assert "X-Telegram-Init-Data" in HTML


def test_muse_palette_and_components():
    assert "#FAF9F7" in HTML  # nền giấy (mẫu từ ảnh Mulon)
    assert "#1F1E1D" in HTML  # chữ mực
    assert "#E8E4DC" in HTML  # viền thẻ
    # Đất nung là màu của Muse, không phải của Mulon — user
    # yêu cầu XÓA hẳn (2026-10-24). Accent nút chính = bậc đậm
    # nhất của hue nhận diện đang chọn (--accent từ --lav-deep).
    assert "#D97757" not in HTML
    assert "btn-accent" in HTML
    assert ".btn-accent{background:var(--accent)" in HTML
    assert '"--accent"' in HTML  # JS gán --accent theo theme
    assert "tg.ready()" in HTML or "Telegram.WebApp" in HTML
    # Segmented control: tab active là tint tím, không phải accent.
    assert ".segbar button.active" in HTML


def test_no_status_pills_or_state_colors_in_lists():
    # Kỷ luật design mới (feedback user 2026-10-24): không pill
    # trạng thái, không ô icon sơn màu xanh/vàng/đỏ trong danh
    # sách; trạng thái là chữ thường theo thang mực + ký hiệu.
    assert 'class="pill' not in HTML
    assert ".pill{" not in HTML
    assert "outcomePill" not in HTML
    for variant in (".ric.green", ".ric.amber", ".ric.red",
                    ".ric.blue", ".ric.purple"):
        assert variant not in HTML
    assert "--tint-ok" not in HTML
    assert "--tint-warn" not in HTML


def test_no_external_cdn_besides_telegram():
    import re

    srcs = re.findall(r'src="https?://[^"]+"', HTML)
    assert srcs == ['src="https://telegram.org/js/telegram-web-app.js"']
    assert 'href="http' not in HTML
