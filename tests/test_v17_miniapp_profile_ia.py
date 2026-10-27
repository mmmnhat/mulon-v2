"""Tests for T-23.3: Tách tab Hồ sơ thành 4 màn con, sửa mô tả kỹ năng tiếng Việt,
đồng bộ số lượng fact Bộ nhớ dài hạn, xem trước tài liệu Thư viện và Thùng rác riêng.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.library import LibraryService
from mulon.policy import PolicyEngine
from mulon.skills import SkillCatalog, parse_skill_md
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import INDEX_HTML, WebAppServer, _localize_skill_description
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import OWNER, TOKEN as _TOK, make_init_data


def _launch_chromium(p):
    last_err = None
    for channel in (None, "msedge", "chrome"):
        try:
            kwargs = {"headless": True}
            if channel:
                kwargs["channel"] = channel
            return p.chromium.launch(**kwargs)
        except Exception as e:
            last_err = e
    pytest.skip(f"Chromium/Edge not available for Playwright: {last_err}")


def test_parse_skill_md_multiline_yaml_description_no_broken_gt(tmp_path: Path):
    """QA Q-05: SKILL.md dùng YAML folded '>' hoặc '|-' không được trả về mô tả cụt '>'."""
    skill_dir = tmp_path / "demo-folded"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\n"
        "name: demo-folded\n"
        "description: >\n"
        "  Automatically inspect and transform audio files\n"
        "  with high precision.\n"
        "---\n\n"
        "# Demo Folded\n\n"
        "Body paragraph here.\n",
        encoding="utf-8",
    )
    meta, _body = parse_skill_md(skill_file.read_text(encoding="utf-8"))
    assert meta is not None
    assert meta["description"] != ">"
    assert "Automatically inspect and transform audio files" in meta["description"]

    # Trường hợp frontmatter chỉ có `description: >` rỗng nhưng body có nội dung
    skill_dir2 = tmp_path / "demo-empty-gt"
    skill_dir2.mkdir(parents=True)
    skill_file2 = skill_dir2 / "SKILL.md"
    skill_file2.write_text(
        "---\n"
        "name: demo-empty-gt\n"
        "description: >\n"
        "---\n\n"
        "# Heading\n\n"
        "Mô tả lấy từ dòng đầu tiên của thân tài liệu.\n",
        encoding="utf-8",
    )
    meta2, _body2 = parse_skill_md(skill_file2.read_text(encoding="utf-8"))
    assert meta2 is not None
    assert meta2["description"] == "Mô tả lấy từ dòng đầu tiên của thân tài liệu."


def test_localize_skill_description_vietnamese_and_clean():
    """Tất cả kỹ năng tiếng Anh phổ biến hoặc mô tả vỡ '>' đều ra tiếng Việt 1 dòng sạch."""
    assert _localize_skill_description("brainstorming", ">") != ">"
    assert "ý tưởng" in _localize_skill_description("brainstorming", ">").lower()
    # Giữ nguyên mô tả vốn đã là tiếng Việt
    vi_desc = "Kỹ năng mẫu để kiểm tra màn đọc kỹ năng."
    assert _localize_skill_description("custom-vi-skill", vi_desc) == vi_desc
    # Dịch mô tả tiếng Anh bất kỳ và ẩn đường dẫn máy
    en_desc = "Manage workspace environment variables in /Users/dev/project/skills/env."
    localized = _localize_skill_description("unknown-env-tool", en_desc)
    assert "/Users/dev" not in localized
    assert localized != ">"


async def test_profile_facts_library_preview_and_skills_endpoints(cfg, tmp_path: Path):
    """Kiểm tra các endpoint mới phục vụ 4 màn con của tab Hồ sơ."""
    cfg2 = replace(cfg, telegram_bot_token=_TOK, allowed_user_id=OWNER, webapp_port=0)
    memory = await open_memory(cfg2)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    registry = build_default_registry(cfg2, memory)

    (Path(cfg2.dossier_dir) / "IDENTITY.md").write_text("# Identity\nTôi là Mulon.\n", encoding="utf-8")
    (Path(cfg2.dossier_dir) / "SOUL.md").write_text("# Soul\nThẳng thắn, ấm áp.\n", encoding="utf-8")

    skills_dir = tmp_path / "skills"
    s1 = skills_dir / "brainstorming"
    s1.mkdir(parents=True)
    (s1 / "SKILL.md").write_text(
        "---\nname: brainstorming\ndescription: >\n  Use before creative work.\n---\n# Brainstorming\nChi tiết.",
        encoding="utf-8",
    )
    catalog = SkillCatalog.load(skills_dir, tool_names=registry.names())

    f1 = await memory.add_fact("Chủ nhân thích uống cà phê đen buổi sáng", salience=0.95)
    f2 = await memory.add_fact("Dự án Mulon chạy trên cổng 8317", salience=0.9)

    lib_service = LibraryService(cfg2, memory)
    ws_dir = Path(cfg2.workspace_dir)
    ws_dir.mkdir(parents=True, exist_ok=True)
    md_file = ws_dir / "bao_cao_tuan.md"
    md_file.write_text("# Báo cáo tuần\n\nNội dung **báo cáo** chi tiết.", encoding="utf-8")
    rec = await lib_service.index_file(md_file, caption="Báo cáo tuần 42")

    server = WebAppServer(
        cfg2,
        memory=memory,
        policy=policy,
        broker=ApprovalBroker(policy=policy, timeout_s=30),
        connectors=build_default_connectors(cfg2),
        mcp_manager=None,
        vault_store=VaultStore(cfg2.vault_path),
        registry=registry,
        dossier=Dossier.load(cfg2.dossier_dir),
        skills=catalog,
        library=lib_service,
    )
    assert await server.start()
    headers = {"X-Telegram-Init-Data": make_init_data()}
    base_url = f"http://127.0.0.1:{server.port}"

    try:
        async with ClientSession() as client:
            # 1. /api/state -> kiểm tra dossier_files có description, facts_active khớp
            async with client.get(f"{base_url}/api/state", headers=headers) as st_res:
                assert st_res.status == 200
                st = await st_res.json()
            assert st["profile"]["facts_active"] == 2
            d_files = st["profile"]["dossier_files"]
            assert any(f["name"] == "IDENTITY.md" and f.get("description") for f in d_files)

            # 2. /api/profile/facts -> khớp 100% với facts_active, tìm kiếm không dấu hoạt động
            async with client.get(f"{base_url}/api/profile/facts", headers=headers) as facts_res:
                assert facts_res.status == 200
                facts_data = await facts_res.json()
            assert facts_data["total_active"] == 2
            assert len(facts_data["facts"]) == 2

            async with client.get(f"{base_url}/api/profile/facts?q=ca+phe+den", headers=headers) as q_res:
                q_data = await q_res.json()
            assert q_data["filtered_count"] == 1
            assert q_data["facts"][0]["id"] == f1

            # 3. Xoá 1 fact -> facts_active giảm còn 1
            async with client.post(
                f"{base_url}/api/profile/facts/delete", json={"id": f2}, headers=headers
            ) as del_res:
                assert del_res.status == 200
                del_data = await del_res.json()
            assert del_data["ok"] is True
            assert del_data["facts_active"] == 1

            # 4. /api/skills -> mô tả tiếng Việt, có group & group_label
            async with client.get(f"{base_url}/api/skills", headers=headers) as sk_res:
                assert sk_res.status == 200
                sk_data = await sk_res.json()
            assert sk_data["count"] == 1
            sk_item = sk_data["skills"][0]
            assert sk_item["description"] != ">"
            assert sk_item.get("group")
            assert sk_item.get("group_label")

            # 5. /api/library/items/{id} -> trả về preview_text của file markdown
            lib_id = rec["id"]
            async with client.get(f"{base_url}/api/library/items/{lib_id}", headers=headers) as prev_res:
                assert prev_res.status == 200
                prev_data = await prev_res.json()
            assert "Báo cáo tuần" in prev_data["preview_text"]
            assert "văn bản" in prev_data["kind_label"].lower()

            # 6. Chuyển vào thùng rác rồi xoá hẳn
            async with client.post(
                f"{base_url}/api/library/items/{lib_id}/trash", json={}, headers=headers
            ) as tr_res:
                assert tr_res.status == 200
            async with client.post(
                f"{base_url}/api/library/items/{lib_id}/delete", json={}, headers=headers
            ) as purge_res:
                assert purge_res.status == 200
                purge_data = await purge_res.json()
            assert purge_data["ok"] is True
    finally:
        await server.stop()
        await memory.close()


def test_profile_four_subscreens_playwright():
    """Kiểm tra trên trình duyệt thật: tab Hồ sơ gọn 4 hàng, mở 4 màn con,
    nhóm kỹ năng & bộ nhớ gập mặc định, xem trước tài liệu & thùng rác riêng.
    """
    playwright = pytest.importorskip("playwright.sync_api")
    html = INDEX_HTML.read_text(encoding="utf-8")

    mock_state = {
        "status": {"busy": False, "current": None},
        "tasks": [],
        "approvals": {"pending": [], "history": []},
        "schedules": [],
        "upcoming": [],
        "heartbeat": {"enabled": True, "interval_minutes": 30, "runs": []},
        "goals": {"tree": [], "active_count": 0},
        "profile": {
            "theme": "lavender",
            "dossier_files": [
                {
                    "name": "IDENTITY.md",
                    "label": "IDENTITY.md",
                    "description": "Danh tính, vai trò và cách xưng hô của agent",
                    "updated_at": "2026-10-27T10:00:00+07:00",
                    "size_bytes": 512,
                },
                {
                    "name": "SOUL.md",
                    "label": "SOUL.md",
                    "description": "Tính cách, giọng điệu và nguyên tắc ứng xử cốt lõi",
                    "updated_at": "2026-10-27T10:05:00+07:00",
                    "size_bytes": 640,
                },
            ],
            "facts_active": 2,
            "skills": {"available": True, "count": 2, "names": ["brainstorming", "clean-cut"]},
        },
        "library": [
            {
                "id": "art_01",
                "title": "Báo cáo kiến trúc Mulon",
                "name": "Báo cáo kiến trúc Mulon",
                "filename": "architecture.md",
                "kind": "document",
                "kind_label": "Văn bản",
                "size_bytes": 2048,
                "word_count": 320,
                "pinned": True,
                "share_status": "private",
                "created_at": "2026-10-27T09:30:00+07:00",
            }
        ],
        "connectors": [],
        "vault": [],
        "policy": {"groups": {}, "tools": {}, "connectors": {}},
        "system": {"version": "1.7.15", "hostname": "mulon-box"},
    }

    with playwright.sync_playwright() as p:
        browser = _launch_chromium(p)
        page = browser.new_page(viewport={"width": 390, "height": 844})

        def handle_route(route):
            url = route.request.url
            if url.endswith("/app"):
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
            elif "/api/state" in url:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(mock_state))
            elif "/api/skills/" in url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "name": "brainstorming",
                        "description": "Phát triển ý tưởng, phác thảo giải pháp",
                        "source": "/Users/admin/.agents/skills/brainstorming/SKILL.md",
                        "content": "---\nname: brainstorming\ndescription: >\n---\n# Brainstorming\n\nNội dung hướng dẫn chi tiết.",
                    }),
                )
            elif "/api/skills" in url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "available": True,
                        "count": 2,
                        "skills": [
                            {
                                "name": "brainstorming",
                                "description": "Phát triển ý tưởng, phác thảo giải pháp trước khi bắt tay vào làm",
                                "source": "skills/brainstorming/SKILL.md",
                                "group": "writing",
                                "group_label": "Sáng tạo, Viết lách & Ý tưởng",
                            },
                            {
                                "name": "clean-cut",
                                "description": "Tách cảnh thông minh, cắt bỏ viền mờ và lọc đoạn thừa trong video",
                                "source": "skills/clean-cut/SKILL.md",
                                "group": "video",
                                "group_label": "Dựng phim, Video & Hình ảnh",
                            },
                        ],
                    }),
                )
            elif "/api/profile/content" in url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"kind": "dossier", "name": "IDENTITY.md", "content": "# IDENTITY\n\nTôi là **Mulon**."}),
                )
            elif "/api/profile/facts" in url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "total_active": 2,
                        "filtered_count": 2,
                        "topics": [{"id": "preference", "label": "Sở thích & Thói quen chủ nhân", "count": 2}],
                        "facts": [
                            {
                                "id": 101,
                                "text": "Chủ nhân thích giao diện tối giản chuẩn 60/30/10",
                                "confidence": 0.95,
                                "valid_from": "2026-10-27T08:00:00+07:00",
                                "topic": "preference",
                                "topic_label": "Sở thích & Thói quen chủ nhân",
                            },
                            {
                                "id": 102,
                                "text": "Thói quen uống cà phê đen không đường mỗi sáng",
                                "confidence": 0.9,
                                "valid_from": "2026-10-27T08:30:00+07:00",
                                "topic": "preference",
                                "topic_label": "Sở thích & Thói quen chủ nhân",
                            },
                        ],
                    }),
                )
            elif "/api/library/items/art_01" in url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        **mock_state["library"][0],
                        "preview_text": "# Kiến trúc Mulon\n\nHệ thống gồm **2 làn** độc lập.",
                    }),
                )
            elif "/api/library/items?status=trashed" in url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "items": [
                            {"id": "art_trash_1", "title": "Nháp cũ", "name": "Nháp cũ", "trashed_at": "2026-10-27T07:00:00+07:00"}
                        ]
                    }),
                )
            else:
                route.fulfill(status=200, content_type="application/json", body="{}")

        page.route("**/*", handle_route)
        page.goto("http://127.0.0.1:8765/app")
        page.wait_for_timeout(200)

        # Mở tab Hồ sơ: chỉ có đúng 4 hàng điều hướng trong #tab-hoso
        page.locator("#segbar button[data-tab='hoso']").click()
        page.wait_for_timeout(150)
        rows_in_hoso = page.locator("#tab-hoso .row").count()
        assert rows_in_hoso == 4
        buttons_in_hoso = page.locator("#tab-hoso button").count()
        assert buttons_in_hoso == 0  # Không còn hàng trăm nút bấm đổ thẳng ra tab Hồ sơ

        # 1. Màn con Hồ sơ của agent -> chọn IDENTITY.md -> đọc Markdown -> Quay lại
        page.locator("#card-dossier").click()
        page.wait_for_timeout(150)
        assert page.locator("#screen-sub-dossier").is_visible()
        assert page.locator("#dossier-files-list .row").count() == 2
        page.locator("#dossier-files-list .row[data-dossier-file='IDENTITY.md']").click()
        page.wait_for_timeout(150)
        assert page.locator("#screen-profile").is_visible()
        assert "Mulon" in page.locator("#profile-content").inner_text()
        page.locator("#screen-profile .backrow").click()
        page.wait_for_timeout(100)
        assert page.locator("#screen-sub-dossier").is_visible()
        page.locator("#screen-sub-dossier .backrow").click()
        page.wait_for_timeout(100)
        assert page.locator("#tab-hoso").is_visible()

        # 2. Màn con Bộ nhớ dài hạn -> nhóm chủ đề gập mặc định -> bấm mở -> xem chi tiết fact
        page.locator("#card-memory").click()
        page.wait_for_timeout(200)
        assert page.locator("#screen-sub-memory").is_visible()
        assert page.locator("#memory-groups-box .acc-group.open").count() == 0
        page.locator("#memory-groups-box .acc-head").first.click()
        page.wait_for_timeout(100)
        assert page.locator("#memory-groups-box .acc-group.open").count() == 1
        page.locator("#memory-groups-box .row[data-fact-id='101']").click()
        page.wait_for_timeout(150)
        assert page.locator("#screen-fact-detail").is_visible()
        assert "60/30/10" in page.locator("#fact-detail-text").inner_text()
        page.locator("#screen-fact-detail .backrow").click()
        page.wait_for_timeout(100)
        page.locator("#screen-sub-memory .backrow").click()
        page.wait_for_timeout(100)

        # 3. Màn con Kỹ năng -> nhóm gập mặc định -> gõ tìm kiếm tự bung & cập nhật x / tổng -> đọc kỹ năng không lộ frontmatter
        page.locator("#card-skills").click()
        page.wait_for_timeout(150)
        assert page.locator("#screen-sub-skills").is_visible()
        assert page.locator("#skills-box .acc-group.open").count() == 0
        page.locator("#skills-search").fill("video")
        page.wait_for_timeout(100)
        assert page.locator("#skills-card-title").inner_text() == "Kỹ năng (1 / 2)"
        assert page.locator("#skills-box .acc-group.open").count() == 1
        page.locator("#skills-search").fill("")
        page.wait_for_timeout(100)
        page.locator("#skills-box .acc-head").first.click()
        page.wait_for_timeout(100)
        page.locator("#skills-box .row[data-skill='brainstorming']").click()
        page.wait_for_timeout(150)
        assert page.locator("#screen-skill").is_visible()
        skill_text = page.locator("#skill-content").inner_text()
        assert "description:" not in skill_text
        assert "Nội dung hướng dẫn chi tiết" in skill_text
        assert "/Users/admin" not in page.locator("#skill-source").inner_text()
        page.locator("#screen-skill .backrow").click()
        page.wait_for_timeout(100)
        page.locator("#screen-sub-skills .backrow").click()
        page.wait_for_timeout(100)

        # 4. Màn con Thư viện tài liệu -> 1 nút ⋯ mỗi hàng -> bấm hàng mở Xem trước -> bấm Thùng rác mở màn riêng
        page.locator("#card-library").click()
        page.wait_for_timeout(150)
        assert page.locator("#screen-sub-library").is_visible()
        assert page.locator("#library-box .row[data-lib-item='art_01'] button").count() == 1
        # Bấm nút ⋯ mở menu tác vụ
        page.locator("#library-box .lib-more-btn").first.click()
        page.wait_for_timeout(100)
        assert not page.locator("#modal-lib-menu").evaluate("el => el.classList.contains('hidden')")
        page.locator("#btn-close-lib-menu").click()
        page.wait_for_timeout(100)
        # Bấm thân hàng mở Xem trước
        page.locator("#library-box .row[data-lib-item='art_01']").click()
        page.wait_for_timeout(150)
        assert page.locator("#screen-library-preview").is_visible()
        assert "Hệ thống gồm 2 làn độc lập" in page.locator("#lib-preview-body").inner_text()
        page.locator("#screen-library-preview .backrow").click()
        page.wait_for_timeout(100)
        # Bấm nút Thùng rác mở màn riêng
        page.locator("#lib-trash-view").click()
        page.wait_for_timeout(150)
        assert page.locator("#screen-library-trash").is_visible()
        assert "Nháp cũ" in page.locator("#lib-trash-box").inner_text()
        assert page.locator("#lib-trash-box [data-lib-purge]").count() == 1

        browser.close()
