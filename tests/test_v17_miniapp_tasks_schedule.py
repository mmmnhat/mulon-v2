"""Kiểm thử hồi quy T-23.4 (QA Q-03 + Q-07 + Q-10):
1. Một nguồn sự thật duy nhất cho trạng thái việc giữa Danh sách (/api/state),
   Chi tiết (/api/task), Dòng thời gian và Tóm tắt:
   - Việc failed (dù có result nháp hay bước 'Kiểm chứng: Đạt yêu cầu' cũ) -> '✕ Đã lỗi' ở mọi nơi.
   - Việc chưa đủ bước (vd 5/6 bước) -> 'partial' ('· Xong 5/6 bước'), KHÔNG ghi '✓ Đã xong'.
   - Việc đủ bước (6/6 bước) -> '✓ Đã xong'.
2. Một định dạng thời gian duy nhất toàn app (DD/MM/YYYY HH:MM).
3. Diễn giải cron tiếng Việt + phân biệt các lịch trùng phần mở đầu theo ranh giới từ.
4. Màn chi tiết Lịch (#screen-schedule-detail): lịch sử chạy (thời lượng/đầu ra/lỗi),
   quyền hạn, sửa lịch, xoá lịch có xác nhận.
5. Kiểm chứng E2E bằng trình duyệt Chromium (Playwright 390x844).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer

from mulon.approvals import ApprovalBroker
from mulon.config import Config
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.memory import Memory
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import (
    WebAppServer,
    _describe_cron_vi,
    _disambiguate_schedule_items,
    _format_cron_display,
    _normalize_task_view,
)

BOT_TOKEN = "123456:ABCDEF_test_token_for_t23_4"
OWNER_ID = 424242


def _make_server(cfg2: Config, mem: Memory) -> WebAppServer:
    policy = PolicyEngine(cfg2.policy_path, memory=mem)
    registry = build_default_registry(cfg2, mem)
    return WebAppServer(
        cfg2,
        memory=mem,
        policy=policy,
        broker=ApprovalBroker(policy=policy, timeout_s=30),
        connectors=build_default_connectors(cfg2),
        mcp_manager=None,
        vault_store=VaultStore(cfg2.vault_path),
        registry=registry,
        dossier=Dossier.load(cfg2.dossier_dir),
    )


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


def make_init_data(bot_token: str = BOT_TOKEN, user_id: int = OWNER_ID) -> str:
    user_json = json.dumps({"id": user_id, "first_name": "Nhat"}, separators=(",", ":"))
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": user_json,
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    pairs["hash"] = sig
    return urlencode(pairs)


def test_normalize_task_view_single_source_of_truth():
    # 1. Task failed nhưng có result nháp tự nhận thành công + bước Kiểm chứng: Đạt yêu cầu
    failed_raw = {
        "id": "t_fail_1",
        "title": "Đăng bài lên Threads tự động",
        "status": "failed",
        "result": "Đã đăng thành công toàn bộ bài viết lên Threads!",
        "error": "Chưa xác thực phiên Threads (HTTP 401)",
        "created_at": "2026-10-27T00:01:00+00:00",
        "updated_at": "2026-10-27T00:06:00+00:00",
        "steps": [
            {"idx": 0, "title": "Đã bắt đầu", "status": "done", "detail": "", "updated_at": "2026-10-27T00:01:00+00:00"},
            {"idx": 1, "title": "Gọi dịch vụ ngoài: threads", "status": "doing", "detail": "", "updated_at": "2026-10-27T00:03:00+00:00"},
            {"idx": 2, "title": "Kiểm chứng: Đạt yêu cầu", "status": "done", "detail": "OK", "updated_at": "2026-10-27T00:05:00+00:00"},
        ],
    }
    norm_fail = _normalize_task_view(failed_raw)
    assert norm_fail["status"] == "failed"
    assert norm_fail["status_label"] == "✕ Đã lỗi"
    assert norm_fail["final_step"]["title"] == "✕ Đã lỗi"
    assert norm_fail["final_step"]["status"] == "failed"
    assert all(s["status"] != "doing" for s in norm_fail["steps"])
    assert any("Kiểm chứng: Không đạt" in s["title"] for s in norm_fail["steps"])
    assert norm_fail["summary_markdown"].startswith("**Trạng thái: ✕ Đã lỗi")
    assert "Chưa xác thực phiên Threads" in norm_fail["summary_markdown"]

    # 2. Task done nhưng chỉ hoàn thành 5/6 bước -> partial, không được ghi "✓ Đã xong"
    partial_raw = {
        "id": "t_part_1",
        "title": "Tổng hợp báo cáo 6 nguồn dữ liệu",
        "status": "done",
        "result": "Đã tổng hợp xong 5 nguồn dữ liệu chính.",
        "error": "",
        "created_at": "2026-10-26T23:50:00+00:00",
        "updated_at": "2026-10-26T23:56:00+00:00",
        "steps": [
            {"idx": i, "title": f"Đọc nguồn #{i+1}", "status": "done" if i < 5 else "failed", "detail": ""}
            for i in range(6)
        ],
    }
    norm_part = _normalize_task_view(partial_raw)
    assert norm_part["steps_done"] == 5
    assert norm_part["steps_total"] == 6
    assert norm_part["status"] == "partial"
    assert norm_part["status_label"] == "· Xong 5/6 bước"
    assert "Đã xong" not in norm_part["status_label"]
    assert norm_part["final_step"]["title"] == "· Hoàn tất một phần (5/6 bước)"
    assert norm_part["summary_markdown"].startswith("**Trạng thái: · Hoàn tất 5/6 bước")

    # 3. Task done đủ 4/4 bước -> "✓ Đã xong"
    done_raw = {
        "id": "t_done_1",
        "title": "Kiểm tra sức khoẻ hệ thống",
        "status": "done",
        "result": "Hệ thống hoạt động bình thường.",
        "error": "",
        "created_at": "2026-10-27T01:00:00+00:00",
        "updated_at": "2026-10-27T01:02:00+00:00",
        "steps": [
            {"idx": i, "title": f"Bước {i+1}", "status": "done", "detail": ""}
            for i in range(4)
        ],
    }
    norm_done = _normalize_task_view(done_raw)
    assert norm_done["status"] == "done"
    assert norm_done["status_label"] == "✓ Đã xong"
    assert norm_done["final_step"]["title"] == "✓ Hoàn tất"


def test_cron_vietnamese_and_schedule_disambiguation():
    assert _describe_cron_vi("*/5 * * * *") == "Mỗi 5 phút"
    assert _format_cron_display("*/5 * * * *")[1] == "Mỗi 5 phút (*/5 * * * *)"
    assert _describe_cron_vi("0 8 * * *") == "Hằng ngày lúc 08:00"
    assert _describe_cron_vi("0 8,12,20 * * *") == "Hằng ngày lúc 08:00, 12:00, 20:00"
    assert _describe_cron_vi("30 9 * * 1-5") == "Thứ 2 – Thứ 6 lúc 09:30"

    # 3 lịch trùng phần mở đầu "Quét TẤT CẢ..."
    items = [
        {
            "id": "s1",
            "name": "Quét TẤT CẢ các nguồn tin công nghệ để tìm bài viết về AI Agent",
            "prompt": "Quét TẤT CẢ các nguồn tin công nghệ để tìm bài viết về AI Agent trên HackerNews và Reddit",
        },
        {
            "id": "s2",
            "name": "Quét TẤT CẢ các nguồn tin công nghệ để tìm bài viết về bảo mật",
            "prompt": "Quét TẤT CẢ các nguồn tin công nghệ để tìm bài viết về bảo mật và lỗ hổng CVE mới",
        },
        {
            "id": "s3",
            "name": "Quét TẤT CẢ các nguồn tin công nghệ để tổng hợp điểm tin buổi tối",
            "prompt": "Quét TẤT CẢ các nguồn tin công nghệ để tổng hợp điểm tin buổi tối gửi vào kênh",
        },
    ]
    _disambiguate_schedule_items(items, title_key="name", full_key="prompt")
    names = [it["name"] for it in items]
    assert len(set(names)) == 3, f"3 lịch trùng đầu phải được phân biệt rõ: {names}"


@pytest.mark.asyncio
async def test_tasks_and_schedules_api_consistency(cfg: Config):
    cfg2 = replace(cfg, telegram_bot_token=BOT_TOKEN, allowed_user_id=OWNER_ID, webapp_port=0)
    mem = await Memory.open(cfg2.db_path)

    try:
        # Tạo 3 tasks: 1 done đủ bước, 1 partial 5/6 bước, 1 failed có result nháp
        await mem.create_task("task_done", "s1", "Kiểm tra kết nối máy chủ", ["Đã bắt đầu", "Ping máy chủ"])
        await mem.update_step("task_done", 0, "done", "OK")
        await mem.update_step("task_done", 1, "done", "OK")
        await mem.finish_task("task_done", "done", result="Máy chủ phản hồi tốt (12ms).")

        await mem.create_task("task_partial", "s1", "Đồng bộ 6 kho dữ liệu", [f"Kho #{i+1}" for i in range(6)])
        for i in range(5):
            await mem.update_step("task_partial", i, "done", "Đã đồng bộ")
        await mem.update_step("task_partial", 5, "failed", "Quá thời gian chờ ở kho #6")
        await mem.finish_task("task_partial", "done", result="Đã đồng bộ 5/6 kho dữ liệu.")

        await mem.create_task("task_failed", "s1", "Gửi báo cáo tự động qua cổng ngoài", ["Đã bắt đầu", "Kiểm chứng: Đạt yêu cầu"])
        await mem.update_step("task_failed", 0, "done", "OK")
        await mem.update_step("task_failed", 1, "done", "OK")
        await mem.finish_task("task_failed", "failed", result="Báo cáo đã được gửi thành công!", error="Mất kết nối tới cổng SMTP (timeout)")

        # Tạo 2 lịch cá nhân + ghi trajectory chạy lịch
        await mem.create_schedule(
            "sched01", "0 8 * * *", "Asia/Ho_Chi_Minh",
            "Kiểm tra kết nối máy chủ mỗi sáng và gửi tóm tắt", "s1",
            "2026-10-28T01:00:00+00:00", title="Kiểm tra máy chủ sáng",
        )
        await mem.log_trajectory("s1", "schedule_fired", {"schedule_id": "sched01", "cron": "0 8 * * *"})

        srv = _make_server(cfg2, mem)
        headers = {"X-Telegram-Init-Data": make_init_data()}

        async with TestClient(TestServer(srv.build_app())) as client:
            r_state = await client.get("/api/state", headers=headers)
            assert r_state.status == 200
            st_data = await r_state.json()
            tasks_map = {t["id"]: t for t in st_data["tasks"]}

            for tid in ("task_done", "task_partial", "task_failed"):
                r_detail = await client.get(f"/api/task?id={tid}", headers=headers)
                assert r_detail.status == 200
                detail_task = (await r_detail.json())["task"]
                list_task = tasks_map[tid]
                assert list_task["status"] == detail_task["status"]
                assert list_task["status_label"] == detail_task["status_label"]
                assert list_task["steps_done"] == detail_task["steps_done"]
                assert list_task["steps_total"] == detail_task["steps_total"]

            assert tasks_map["task_done"]["status_label"] == "✓ Đã xong"
            assert tasks_map["task_partial"]["status_label"] == "· Xong 5/6 bước"
            assert tasks_map["task_failed"]["status_label"] == "✕ Đã lỗi"

            # Chi tiết lịch trình
            r_sched = await client.get("/api/schedules/sched01", headers=headers)
            assert r_sched.status == 200
            s_det = (await r_sched.json())["schedule"]
            assert s_det["id"] == "sched01"
            assert "Hằng ngày lúc 08:00" in s_det["cron_display"]
            assert len(s_det["permissions"]) >= 2
            assert len(s_det["runs"]) >= 1
            assert s_det["runs"][0]["duration_label"]

            # Sửa lịch trình
            r_upd = await client.post(
                "/api/schedules/sched01/update",
                headers=headers,
                json={"id": "sched01", "title": "Kiểm tra máy chủ 9h", "cron": "0 9 * * *", "payload": "Kiểm tra máy chủ lúc 9h sáng"},
            )
            assert r_upd.status == 200
            upd_det = (await r_upd.json())["schedule"]
            assert upd_det["cron"] == "0 9 * * *"
            assert "Hằng ngày lúc 09:00" in upd_det["cron_display"]

            # Xoá lịch trình
            r_del = await client.post("/api/schedules/sched01/delete", headers=headers, json={"id": "sched01"})
            assert r_del.status == 200
            assert (await r_del.json())["ok"] is True
            assert await mem.get_schedule("sched01") is None
    finally:
        await mem.close()


def test_playwright_e2e_tasks_and_schedules(cfg: Config):
    """Kiểm thử E2E trên Chromium (390x844):
    - Đối chiếu 3 việc (done, partial 5/6, failed) giữa Danh sách và Chi tiết.
    - Kiểm tra định dạng thời gian duy nhất DD/MM/YYYY HH:MM.
    - Mở chi tiết 2 lịch trình, mở rộng lượt chạy xem thời lượng/đầu ra/lỗi, sửa và mở hộp xác nhận xoá.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright không được cài đặt")

    import asyncio
    import threading
    from aiohttp import web

    port_holder = {}
    stop_ev = threading.Event()

    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _serve():
            mem = await Memory.open(cfg.db_path)

            await mem.create_task("t_ok", "s1", "Kiểm tra định tuyến mạng nội bộ", ["Đã bắt đầu", "Đo độ trễ", "Kiểm chứng: Đạt yêu cầu"])
            for i in range(3):
                await mem.update_step("t_ok", i, "done", "Hoàn tất")
            await mem.finish_task("t_ok", "done", result="Mạng nội bộ ổn định, độ trễ 4ms.")

            await mem.create_task("t_part", "s1", "Quét 6 nguồn dữ liệu đối tác", [f"Nguồn #{i+1}" for i in range(6)])
            for i in range(5):
                await mem.update_step("t_part", i, "done", "Đã lấy dữ liệu")
            await mem.update_step("t_part", 5, "failed", "Nguồn #6 trả mã 503")
            await mem.finish_task("t_part", "done", result="Đã thu thập được 5/6 nguồn dữ liệu.")

            await mem.create_task("t_err", "s1", "Đẩy bản tin tổng hợp lên kênh thông báo", ["Đã bắt đầu", "Kiểm chứng: Đạt yêu cầu"])
            await mem.update_step("t_err", 0, "done", "Đã chuẩn bị nội dung")
            await mem.update_step("t_err", 1, "done", "OK")
            await mem.finish_task("t_err", "failed", result="Đã gửi bản tin thành công!", error="Token kết nối kênh đã hết hạn (401)")

            await mem.create_schedule(
                "sch_morning", "0 8 * * *", "Asia/Ho_Chi_Minh",
                "Kiểm tra định tuyến mạng nội bộ và tổng hợp báo cáo sáng", "s1",
                "2026-10-28T01:00:00+00:00", title="Báo cáo mạng buổi sáng",
            )
            await mem.log_trajectory("s1", "schedule_fired", {"schedule_id": "sch_morning", "cron": "0 8 * * *"})

            await mem.create_schedule(
                "sch_evening", "30 21 * * *", "Asia/Ho_Chi_Minh",
                "Đẩy bản tin tổng hợp lên kênh thông báo buổi tối", "s1",
                "2026-10-27T14:30:00+00:00", title="Bản tin tổng hợp tối",
            )
            await mem.log_trajectory("s1", "schedule_error", {"schedule_id": "sch_evening", "error": "Token kết nối kênh đã hết hạn (401)"})

            srv = _make_server(replace(cfg, telegram_bot_token=BOT_TOKEN, allowed_user_id=OWNER_ID, webapp_port=0), mem)
            runner = web.AppRunner(srv.build_app())
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port_holder["port"] = site._server.sockets[0].getsockname()[1]
            while not stop_ev.is_set():
                await asyncio.sleep(0.05)
            await runner.cleanup()
            await mem.close()

        loop.run_until_complete(_serve())

    th = threading.Thread(target=run_server, daemon=True)
    th.start()
    for _ in range(100):
        if "port" in port_holder:
            break
        time.sleep(0.05)
    assert "port" in port_holder
    base_url = f"http://127.0.0.1:{port_holder['port']}"
    init_data = make_init_data()

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.route(
                "**/telegram-web-app.js*",
                lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
            )
            page.add_init_script(
                f"""
                window.Telegram = {{
                    WebApp: {{
                        initData: {json.dumps(init_data)},
                        initDataUnsafe: {{ user: {{ id: {OWNER_ID} }} }},
                        ready: function() {{}},
                        expand: function() {{}},
                        BackButton: {{ show: function() {{}}, hide: function() {{}}, onClick: function() {{}} }}
                    }}
                }};
                """
            )
            page.goto(f"{base_url}/app", wait_until="networkidle")
            page.wait_for_selector("#task-list .row[data-task]")

            # 1. Kiểm tra định dạng thời gian duy nhất DD/MM/YYYY HH:MM ở danh sách việc
            times = page.locator("#task-list .r-time").all_inner_texts()
            assert len(times) == 3
            for tm in times:
                assert "/" in tm and ":" in tm, f"Thời gian phải theo định dạng thống nhất DD/MM/YYYY HH:MM: {tm}"

            # 2. Đối chiếu 3 việc giữa danh sách và chi tiết
            for tid, expected_state in [
                ("t_ok", "✓ Đã xong"),
                ("t_part", "· Xong 5/6 bước"),
                ("t_err", "✕ Đã lỗi"),
            ]:
                row = page.locator(f'#task-list .row[data-task="{tid}"]')
                list_state = row.locator(".r-state").inner_text().strip()
                assert list_state == expected_state

                row.click()
                page.wait_for_selector("#screen-task:not(.hidden)")
                page.wait_for_function("() => document.getElementById('task-detail-status').textContent.trim().length > 0")
                detail_state = page.locator("#task-detail-status").inner_text().strip()
                assert detail_state == list_state

                tl_text = page.locator("#task-timeline").inner_text()
                sum_text = page.locator("#task-summary").inner_text()
                if tid == "t_err":
                    assert "✕ Đã lỗi" in tl_text
                    assert "Kiểm chứng: Đạt yêu cầu" not in tl_text
                    assert "Trạng thái: ✕ Đã lỗi" in sum_text
                elif tid == "t_part":
                    assert "Hoàn tất một phần (5/6 bước)" in tl_text
                    assert "✓ Hoàn tất" not in tl_text
                    assert "Hoàn tất 5/6 bước" in sum_text
                else:
                    assert "✓ Hoàn tất" in tl_text

                page.locator("#screen-task .backrow").click()
                page.wait_for_selector("#tab-viec:not(.hidden)")

            # 3. Chuyển sang tab Lịch, kiểm tra diễn giải cron tiếng Việt & mở chi tiết 2 lịch
            page.locator('#segbar button[data-tab="lich"]').click()
            page.wait_for_selector("#tab-lich:not(.hidden)")
            sched_list_text = page.locator("#schedule-list").inner_text()
            assert "Hằng ngày lúc 08:00 (0 8 * * *)" in sched_list_text
            assert "Hằng ngày lúc 21:30 (30 21 * * *)" in sched_list_text

            # Mở lịch 1 (sch_morning)
            page.locator('#schedule-list .row[data-sched-open="sch_morning"]').click()
            page.wait_for_selector("#screen-schedule-detail:not(.hidden)")
            page.wait_for_function("() => document.getElementById('sched-detail-title').textContent.includes('Báo cáo mạng')")
            assert "Hằng ngày lúc 08:00" in page.locator("#sched-detail-cron").inner_text()
            runs_text = page.locator("#sched-detail-runs").inner_text()
            assert "Thời lượng:" in runs_text
            assert "Đầu ra:" in runs_text

            # Quay lại tab Lịch và mở lịch 2 (sch_evening - có lỗi chạy)
            page.locator("#screen-schedule-detail .backrow").click()
            page.wait_for_selector("#tab-lich:not(.hidden)")
            page.locator('#schedule-list .row[data-sched-open="sch_evening"]').click()
            page.wait_for_selector("#screen-schedule-detail:not(.hidden)")
            page.wait_for_function("() => document.getElementById('sched-detail-title').textContent.includes('Bản tin')")
            runs_err_text = page.locator("#sched-detail-runs").inner_text()
            assert "✕ Đã lỗi" in runs_err_text
            assert "Token kết nối kênh đã hết hạn" in runs_err_text

            # Bấm Xoá lịch -> phải hiện hộp xác nhận trước khi xoá
            page.locator("#btn-sched-delete").click()
            assert page.locator("#sched-delete-confirm-box").is_visible()

            browser.close()
    finally:
        stop_ev.set()
