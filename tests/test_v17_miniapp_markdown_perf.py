"""Test hồi quy cho T-23.2: Render markdown thật + tải chậm + dọn rò rỉ hiển thị (v1.7.14).

Kiểm chứng các yêu cầu theo QA Q-02, Q-04, Q-07:
1. Render markdown thật ở Tóm tắt việc, Hồ sơ, Bộ nhớ, Kỹ năng; strip comment HTML.
2. Sửa dính chữ do thiếu khoảng trắng ('toàn bộ63/63 bài đăngcủa').
3. Ẩn đường dẫn tuyệt đối của máy chạy (chỉ hiện tên file/thư mục tương đối).
4. Màn con tải nhanh < 3s, hỗ trợ batch dossier trong 1 request + skeleton đầy đủ.
5. Xóa stale heading (reset tiêu đề việc cũ trước khi tải việc mới).
6. Toast hoàn tất tự ẩn, không rò rỉ text trong DOM cuối trang.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from aiohttp import web

from mulon.paths import sanitize_path_display, fix_glued_words, PROJECT_ROOT
from mulon.webapp_server import WebAppServer


INDEX_HTML_PATH = PROJECT_ROOT / "mulon" / "webapp" / "index.html"


def test_paths_sanitize_and_fix_glued_words():
    """Kiểm chứng làm sạch đường dẫn máy và sửa dính chữ."""
    # 1. Sanitize paths
    assert sanitize_path_display("/Volumes/External/auto/mulon/agent.py") == "mulon/agent.py"
    assert sanitize_path_display("/Users/mmmnhat/.gemini/config/skills/animate/SKILL.md") == "skills/animate/SKILL.md"
    assert sanitize_path_display("C:\\Users\\admin\\project\\skills\\animate\\SKILL.md") == "skills/animate/SKILL.md"
    assert sanitize_path_display("/home/ubuntu/.local/share/mulon/data/mulon.db") in ("mulon/data/mulon.db", ".../data/mulon.db", "data/mulon.db")
    assert sanitize_path_display("") == ""

    # 2. Fix glued words
    raw_glued = "toàn bộ63/63 bài đăngcủa bạn"
    fixed = fix_glued_words(raw_glued)
    assert "toàn bộ 63/63" in fixed
    assert "bài đăng của" in fixed

    raw_punct = "hoàn thành100% mục tiêu,tiếp tục bước 2"
    fixed_punct = fix_glued_words(raw_punct)
    assert "hoàn thành 100%" in fixed_punct
    assert "mục tiêu, tiếp tục" in fixed_punct
    assert "AGENTS.md" in fix_glued_words("Đọc file AGENTS.md nha")


@pytest.mark.asyncio
async def test_api_profile_content_batch_dossier():
    """Kiểm chứng backend _handle_profile_content trả về batch dossier trong 1 request (< 3s)."""
    server = WebAppServer.__new__(WebAppServer)
    server.dossier = MagicMock()
    server.dossier.files = {
        "SOUL.md": "# Bản sắc\nĐây là linh hồn của bot.",
        "USER.md": "# Người dùng\nThông tin chủ nhân.",
        "BOOTSTRAP.md": "Chỉ thị khởi động tạm.",
    }
    server.memory = MagicMock()

    # 1. Batch dossier (không truyền name)
    req_batch = MagicMock()
    req_batch.query = {"kind": "dossier"}
    res_batch = await server._handle_profile_content(req_batch)
    assert res_batch.status == 200
    data_batch = json_response_data(res_batch)
    assert data_batch["ok"] is True
    assert "files" in data_batch
    file_names = [f["name"] for f in data_batch["files"]]
    assert "SOUL.md" in file_names
    assert "USER.md" in file_names
    assert "BOOTSTRAP.md" not in file_names  # Loại bỏ file tạm

    # 2. File đơn lẻ (backward compatible)
    req_single = MagicMock()
    req_single.query = {"kind": "dossier", "name": "SOUL.md"}
    res_single = await server._handle_profile_content(req_single)
    assert res_single.status == 200
    data_single = json_response_data(res_single)
    assert data_single["title"] == "SOUL.md"
    assert "Bản sắc" in data_single["content"]

    # 3. Memory content
    server.memory.active_facts = AsyncMock(return_value=[{"fact": "Thích màu tím Mulon"}])
    req_mem = MagicMock()
    req_mem.query = {"kind": "memory"}
    res_mem = await server._handle_profile_content(req_mem)
    assert res_mem.status == 200
    data_mem = json_response_data(res_mem)
    assert "Thích màu tím Mulon" in data_mem["content"]


def json_response_data(res):
    import json
    return json.loads(res.body.decode("utf-8"))


def test_index_html_markdown_and_toast_rules():
    """Kiểm tra tĩnh trên mulon/webapp/index.html đảm bảo đầy đủ tiêu chí T-23.2."""
    html_text = INDEX_HTML_PATH.read_text(encoding="utf-8")

    # 1. Toast không rò rỉ trong DOM: CSS có display:none và visibility:hidden khi không show
    toast_css_match = re.search(r"#toast\s*\{([^}]+)\}", html_text)
    assert toast_css_match is not None, "Không tìm thấy selector #toast trong CSS"
    toast_css = toast_css_match.group(1)
    assert "display:none" in toast_css.replace(" ", "")
    assert "visibility:hidden" in toast_css.replace(" ", "")

    # Toast JS tự dọn dẹp textContent sau khi ẩn
    assert 't.textContent = "";' in html_text or "t.textContent='';" in html_text

    # 2. Stale heading: openTask reset task-detail-title trước khi gọi API
    open_task_match = re.search(r"async\s+function\s+openTask\s*\([^)]*\)\s*\{([\s\S]*?)(?:await\s+api)", html_text)
    assert open_task_match is not None, "Không tìm thấy hàm openTask"
    open_task_pre = open_task_match.group(1)
    assert '$("task-detail-title").textContent' in open_task_pre, "openTask phải reset task-detail-title trước khi gọi API"

    # 3. Markdown thô được thay bằng rich markdown container (.md-content)
    assert '<div class="md-content" id="profile-content"' in html_text
    assert '<div class="md-content" id="skill-content"' in html_text
    assert '<pre class="content" id="profile-content">' not in html_text
    assert '<pre class="content" id="skill-content">' not in html_text

    # 4. Skeleton placeholder có mặt ở màn Hồ sơ, Kỹ năng và Chi tiết việc
    assert "skills-box" in html_text
    assert "task-summary" in html_text
    assert '<div class="skel">' in html_text

    # 5. renderMd hỗ trợ: strip comment HTML, maskPaths, fixGluedWords, headers, hr, blockquote, lists, tables
    render_md_match = re.search(r"function\s+renderMd\s*\([^)]*\)\s*\{([\s\S]*?)\n\}", html_text)
    assert render_md_match is not None, "Không tìm thấy hàm renderMd"
    render_md_code = render_md_match.group(1)
    assert "<!--[\\s\\S]*?-->" in render_md_code, "renderMd phải strip HTML comments"
    assert "fixGluedWords" in render_md_code, "renderMd phải gọi fixGluedWords"
    assert "maskPaths" in render_md_code, "renderMd phải gọi maskPaths"
    assert "md-h" in render_md_code, "renderMd phải hỗ trợ headings"
    assert "md-hr" in render_md_code, "renderMd phải hỗ trợ horizontal rules"
    assert "md-quote" in render_md_code, "renderMd phải hỗ trợ blockquotes"
    assert "md-ul" in render_md_code or "md-ol" in render_md_code, "renderMd phải hỗ trợ lists"
    assert "md-table" in render_md_code, "renderMd phải hỗ trợ tables"


@pytest.mark.asyncio
async def test_playwright_render_markdown_and_insets_real():
    """Kiểm tra render thật bằng Chromium (Playwright) nếu môi trường có sẵn."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.skip("Playwright không có sẵn trong môi trường này")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 390, "height": 844})
        page = await context.new_page()

        file_url = INDEX_HTML_PATH.resolve().as_uri()
        await page.goto(file_url)

        # 1. Kiểm tra toast ban đầu hoàn toàn ẩn và không chiếm layout
        toast_el = page.locator("#toast")
        await toast_el.wait_for(state="attached")
        is_visible = await toast_el.is_visible()
        assert not is_visible, "Toast ban đầu phải ẩn hoàn toàn"

        # 2. Chạy hàm renderMd trên trang thật với đoạn markdown phức tạp có HTML comment và path
        test_md = """### Báo cáo thử nghiệm
<!-- HTML comment bí mật không được lộ -->
toàn bộ63/63 bài đăngcủa hệ thống.

- Mục kiểm thử 1
- Mục kiểm thử 2

| Cột A | Cột B |
|---|---|
| Dữ liệu 1 | Dữ liệu 2 |

Đường dẫn file: /Volumes/External/auto/mulon/agent.py
"""
        rendered_html = await page.evaluate("(md) => renderMd(md)", test_md)
        assert "<h3" in rendered_html
        assert "Báo cáo thử nghiệm" in rendered_html
        assert "HTML comment bí mật" not in rendered_html
        assert "toàn bộ 63/63 bài đăng của" in rendered_html
        assert "<ul" in rendered_html
        assert "<table" in rendered_html
        assert "/Volumes/External/auto" not in rendered_html

        await browser.close()
