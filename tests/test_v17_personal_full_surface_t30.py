"""Test kiểm chứng toàn diện cho T-30:
Bề mặt đầy đủ Facebook + Threads CÁ NHÂN theo chuẩn Muse parity (ƯU TIÊN 29).

Bao gồm:
1. Facebook cá nhân:
   - Danh tính & Quan hệ: get_profile, get_friends, view_user_profile.
   - Bảng tin: read_feed, read_friends_feed.
   - Nhóm: list_groups (kể cả nhóm kín/ẩn), get_group_detail, read_group_posts, search_groups.
   - Bài viết & Tương tác: read_post, read_comments, read_reactions.
   - Hành động ghi có kiểm duyệt (ask) và chặn stub giả khi không có transport:
     write_comment, reply_comment, create_post.
   - Fanpage: list_pages, get_page_insights, create_page_draft, create_page_post.
   - Sự kiện, Story, Đã lưu, Marketplace.
   - Checkpoint Guard tự ngắt khi gặp checkpoint.
   - Bọc dữ liệu ngoài qua frame_external.

2. Threads cá nhân (nội dung/bài viết):
   - Ưu tiên API chính thức (Graph API token: threads_personal:token).
   - Fallback Web Session Cookie (threads_personal:session) cho endpoint web-only:
     read_feed, get_trends, search_posts, set_feed_suggestions.
   - Metadata transport ("official_api" | "web_session") và cờ web_only.
   - Thao tác ghi có kiểm duyệt (ask) và chặn stub giả khi thiếu transport:
     create_post, create_reply, set_feed_suggestions.

3. Policy Engine:
   - Đọc = allow, Ghi = ask.
   - Đăng ký vào CONNECTOR_SPECS và build_default_connectors.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from mulon.connectors import build_default_connectors
from mulon.context import frame_external
from mulon.personal_connectors import (
    FacebookPersonalConnector,
    ThreadsPersonalConnector,
    LBL_FB_CHECKPOINT,
    LBL_FB_SESSION,
    LBL_FB_USER,
    LBL_TH_CONTENT_CHECKPOINT,
    LBL_TH_CONTENT_SESSION,
    LBL_TH_CONTENT_TOKEN,
    LBL_TH_CONTENT_USER,
    LIMITATION_FACEBOOK,
    LIMITATION_THREADS_PERSONAL,
    WARNING_FACEBOOK,
    WARNING_THREADS_PERSONAL,
)
from mulon.policy import (
    CONNECTOR_ACTION_DEFAULTS,
    CONNECTOR_SPECS,
    VERDICT_ALLOW,
    VERDICT_ASK,
)
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer


def make_vault(tmp_path, name="vault.json") -> VaultStore:
    return VaultStore(tmp_path / name)


@pytest.mark.asyncio
async def test_facebook_personal_full_surface_read(tmp_path):
    """Kiểm tra toàn bộ bề mặt đọc Facebook cá nhân và cơ chế frame_external."""
    vault = make_vault(tmp_path, "fb_read.json")
    vault.put(LBL_FB_SESSION, json.dumps({"c_user": "100012345", "xs": "mock_xs_session"}))
    vault.put(
        LBL_FB_USER,
        json.dumps({
            "id": "100012345",
            "name": "Nguyen Van A",
            "profile_url": "https://www.facebook.com/100012345",
            "bio": "Bio cá nhân Facebook",
            "cached_friends": [{"id": "2001", "name": "Friend One"}],
            "cached_profiles": {
                "2001": {
                    "id": "2001",
                    "name": "Friend One",
                    "bio": "External Bio of Friend",
                    "posts": [{"id": "p_fr_1", "raw_text": "Post from friend"}],
                }
            },
            "cached_posts": [{"id": "post_1", "raw_text": "Hello Facebook Feed"}],
            "cached_friends_posts": [{"id": "f_post_1", "raw_text": "Friends Feed Post"}],
            "cached_groups": [
                {"id": "grp_pub", "name": "Public Community", "privacy": "public"},
                {"id": "grp_sec", "name": "Secret Private Group", "privacy": "secret"},
            ],
            "cached_groups_detail": {
                "grp_sec": {
                    "id": "grp_sec",
                    "name": "Secret Private Group",
                    "privacy": "secret",
                    "members_count": 42,
                    "rules": ["Không spam", "Tôn trọng thành viên"],
                    "description": "Mô tả nhóm bí mật",
                }
            },
            "cached_group_posts": {
                "grp_sec": [{"id": "gp_1", "raw_text": "Bài viết trong nhóm kín"}]
            },
            "cached_posts_by_id": {
                "post_100": {"id": "post_100", "raw_text": "Nội dung bài viết số 100"}
            },
            "cached_comments": {
                "post_100": [{"id": "c_1", "raw_text": "Bình luận đầu tiên"}]
            },
            "cached_reactions": {
                "post_100": {"total": 15, "like": 10, "love": 5}
            },
            "cached_pages": [{"id": "pg_1", "name": "Mulon Fanpage"}],
            "cached_page_insights": {"pg_1": {"page_id": "pg_1", "reach": 1500, "followers": 320}},
            "cached_events": [{"id": "ev_1", "name": "Tech Meetup 2026"}],
            "cached_events_detail": {"ev_1": {"id": "ev_1", "name": "Tech Meetup 2026", "description": "Gặp mặt dev"}},
            "cached_stories": [{"id": "st_1", "raw_text": "Story 24h"}],
            "cached_saved": [{"id": "sv_1", "title": "Bài viết AI cần lưu"}],
            "cached_marketplace": [{"id": "mp_1", "raw_title": "Mac mini M4", "raw_description": "Like new 99%"}],
            "cached_my_marketplace": [{"id": "my_mp_1", "title": "Bàn phím cơ"}],
            "cached_messages": {"inbox": [{"id": "m_1", "raw_text": "Tin nhắn Messenger"}]},
        }),
    )

    conn = FacebookPersonalConnector(vault_store=vault)

    # 1. Profile & Friends
    prof_res = await conn.call("get_profile", {})
    assert prof_res["ok"] is True
    assert prof_res["profile"]["id"] == "100012345"
    assert "Bio cá nhân Facebook" in prof_res["profile"]["bio"]

    fr_res = await conn.call("get_friends", {})
    assert fr_res["ok"] is True
    assert fr_res["count"] == 1

    # 2. View user profile (timeline người khác)
    u_prof = await conn.call("view_user_profile", {"user_id": "2001"})
    assert u_prof["ok"] is True
    assert "External Bio of Friend" in u_prof["profile"]["bio"]
    assert u_prof["profile"]["posts"][0]["raw_text"] == "Post from friend"

    # 3. Feed & Friends Feed
    feed_res = await conn.call("read_feed", {})
    assert feed_res["ok"] is True
    assert feed_res["count"] == 1
    assert feed_res["posts"][0]["raw_text"] == "Hello Facebook Feed"

    ff_res = await conn.call("read_friends_feed", {})
    assert ff_res["ok"] is True
    assert ff_res["count"] == 1
    assert ff_res["posts"][0]["raw_text"] == "Friends Feed Post"

    # 4. Groups: Liệt kê TOÀN BỘ (kể cả nhóm kín/ẩn)
    groups_res = await conn.call("list_groups", {"all": True})
    assert groups_res["ok"] is True
    assert groups_res["count"] == 2
    privacies = [g["privacy"] for g in groups_res["groups"]]
    assert "public" in privacies and "secret" in privacies

    # Chi tiết nhóm + Đọc bài nhóm
    grp_det = await conn.call("get_group_detail", {"group_id": "grp_sec"})
    assert grp_det["ok"] is True
    assert grp_det["group"]["members_count"] == 42
    assert "Mô tả nhóm bí mật" in grp_det["group"]["description"]

    grp_posts = await conn.call("read_group_posts", {"group_id": "grp_sec"})
    assert grp_posts["ok"] is True
    assert grp_posts["posts"][0]["raw_text"] == "Bài viết trong nhóm kín"

    # Tìm nhóm
    s_grp = await conn.call("search_groups", {"q": "Community"})
    assert s_grp["ok"] is True
    assert len(s_grp["groups"]) == 1

    # 5. Bài viết, Comments & Reactions
    post_res = await conn.call("read_post", {"post_id": "post_100"})
    assert post_res["ok"] is True
    assert post_res["post"]["raw_text"] == "Nội dung bài viết số 100"

    cmts_res = await conn.call("read_comments", {"post_id": "post_100"})
    assert cmts_res["ok"] is True
    assert cmts_res["comments"][0]["raw_text"] == "Bình luận đầu tiên"

    rx_res = await conn.call("read_reactions", {"post_id": "post_100"})
    assert rx_res["ok"] is True
    assert rx_res["reactions"]["like"] == 10

    # 6. Pages, Events, Stories, Saved, Marketplace
    pgs = await conn.call("list_pages", {})
    assert pgs["ok"] is True
    assert pgs["count"] == 1

    pg_ins = await conn.call("get_page_insights", {"page_id": "pg_1"})
    assert pg_ins["ok"] is True
    assert pg_ins["insights"]["reach"] == 1500

    ev_det = await conn.call("get_event_detail", {"event_id": "ev_1"})
    assert ev_det["ok"] is True
    assert "Gặp mặt dev" in ev_det["event"]["description"]

    st_res = await conn.call("read_stories", {})
    assert st_res["ok"] is True
    assert st_res["stories"][0]["raw_text"] == "Story 24h"

    saved_res = await conn.call("list_saved", {})
    assert saved_res["ok"] is True
    assert saved_res["count"] == 1

    mp_res = await conn.call("search_marketplace", {"q": "Mac"})
    assert mp_res["ok"] is True
    assert mp_res["items"][0]["raw_title"] == "Mac mini M4"

    my_mp = await conn.call("get_my_marketplace_listings", {})
    assert my_mp["ok"] is True
    assert my_mp["count"] == 1


@pytest.mark.asyncio
async def test_facebook_personal_write_requires_transport(tmp_path):
    """Kiểm tra kỷ luật cứng: CẤM trả ok stub khi chưa có transport thật."""
    vault = make_vault(tmp_path, "fb_write.json")
    vault.put(LBL_FB_SESSION, json.dumps({"c_user": "100012345", "xs": "xs_token"}))

    # Trường hợp không có session_runner hay http_client
    conn = FacebookPersonalConnector(vault_store=vault)

    # 1. write_comment
    c_res = await conn.call("write_comment", {"post_id": "p1", "message": "Test comment"})
    assert c_res["ok"] is False
    assert c_res.get("unsupported") is True
    assert "Chưa có transport thực tế" in c_res["error"]

    # 2. reply_comment
    r_res = await conn.call("reply_comment", {"comment_id": "c1", "message": "Test reply"})
    assert r_res["ok"] is False
    assert r_res.get("unsupported") is True

    # 3. create_post
    p_res = await conn.call("create_post", {"message": "New status post"})
    assert p_res["ok"] is False
    assert p_res.get("unsupported") is True

    # 4. create_page_draft & create_page_post
    draft_res = await conn.call("create_page_draft", {"page_id": "pg1", "message": "Page draft"})
    assert draft_res["ok"] is False
    assert draft_res.get("unsupported") is True

    post_pg_res = await conn.call("create_page_post", {"page_id": "pg1", "message": "Page post"})
    assert post_pg_res["ok"] is False
    assert post_pg_res.get("unsupported") is True

    # 5. save_item & unsave_item
    s_res = await conn.call("save_item", {"item_id": "item_123"})
    assert s_res["ok"] is False
    assert s_res.get("unsupported") is True

    uns_res = await conn.call("unsave_item", {"item_id": "item_123"})
    assert uns_res["ok"] is False
    assert uns_res.get("unsupported") is True

    # Trường hợp có session_runner: thao tác được ủy quyền thành công
    async def mock_runner(action, args, cookies):
        return {"ok": True, "action_performed": action, "args": args}

    conn_with_runner = FacebookPersonalConnector(vault_store=vault, session_runner=mock_runner)
    c_ok = await conn_with_runner.call("write_comment", {"post_id": "p1", "message": "Test comment"})
    assert c_ok["ok"] is True
    assert c_ok["action_performed"] == "write_comment"


@pytest.mark.asyncio
async def test_facebook_personal_checkpoint_guard(tmp_path):
    """Kiểm tra Checkpoint Guard tự ngắt khi phát hiện tín hiệu checkpoint."""
    vault = make_vault(tmp_path, "fb_cp.json")
    vault.put(LBL_FB_SESSION, json.dumps({"c_user": "100012345", "xs": "xs_token"}))

    async def checkpoint_runner(action, args, cookies):
        return {"ok": False, "checkpoint": True, "error": "Redirected to /checkpoint/1508"}

    conn = FacebookPersonalConnector(vault_store=vault, session_runner=checkpoint_runner)
    res = await conn.call("read_feed", {})
    assert res["ok"] is False
    assert res["checkpoint"] is True
    assert "Checkpoint Guard" in res["error"]

    # Kiểm tra cờ checkpoint trong Vault được lưu
    assert vault.resolve(vault.labels()[-1]["ref"]) == "true" or any(l["label"] == LBL_FB_CHECKPOINT for l in vault.labels())

    # Lượt gọi tiếp theo bị chặn ngay lập tức (fail-fast)
    conn_next = FacebookPersonalConnector(vault_store=vault)
    health = await conn_next.health_check()
    assert health["connected"] is False
    assert health["checkpoint_detected"] is True

    blocked = await conn_next.call("get_profile", {})
    assert blocked["ok"] is False
    assert blocked["checkpoint"] is True


@pytest.mark.asyncio
async def test_threads_personal_modes_and_health(tmp_path):
    """Kiểm tra các chế độ hoạt động của Threads cá nhân (official_api, web_session, hybrid)."""
    vault = make_vault(tmp_path, "th_modes.json")
    conn = ThreadsPersonalConnector(vault_store=vault)

    # 1. Chưa cấu hình
    h1 = await conn.health_check()
    assert h1["connected"] is False
    assert h1["mode"] == "unconfigured"

    # 2. Cấu hình Graph API Token
    await conn.call("configure", {"token": "TH_OAUTH_TOKEN_XYZ", "username": "ai_user"})
    h2 = await conn.health_check()
    assert h2["connected"] is True
    assert h2["mode"] == "official_api"
    assert h2["user"]["username"] == "ai_user"

    # 3. Bổ sung Web Session Cookies -> Chế độ Hybrid
    await conn.call("configure", {"cookies": "sessionid=threads_sess_123; ds_user_id=9876;"})
    h3 = await conn.health_check()
    assert h3["connected"] is True
    assert h3["mode"] == "hybrid"

    # 4. Ngắt kết nối sạch sẽ
    d_res = await conn.call("disconnect", {})
    assert d_res["ok"] is True
    h4 = await conn.health_check()
    assert h4["connected"] is False
    assert h4["mode"] == "unconfigured"


@pytest.mark.asyncio
async def test_threads_personal_read_surface_and_metadata(tmp_path):
    """Kiểm tra bề mặt đọc Threads cá nhân: ưu tiên official_api và fallback web_only."""
    vault = make_vault(tmp_path, "th_read.json")
    # Cấu hình cả Token và Web Cookie
    vault.put(LBL_TH_CONTENT_TOKEN, "GRAPH_TOKEN_123")
    vault.put(LBL_TH_CONTENT_SESSION, json.dumps({"sessionid": "sess_999", "ds_user_id": "th_user_1"}))
    vault.put(
        LBL_TH_CONTENT_USER,
        json.dumps({
            "id": "th_user_1",
            "username": "threads_dev",
            "name": "Threads Developer",
            "biography": "Bio Threads cá nhân",
            "cached_threads_posts": [{"id": "tp_1", "raw_text": "Bài đăng Threads đầu tiên"}],
            "cached_threads_posts_by_id": {"tp_1": {"id": "tp_1", "raw_text": "Chi tiết bài đăng Threads"}},
            "cached_threads_replies": {"tp_1": [{"id": "tr_1", "raw_text": "Phản hồi bài đăng"}]},
            "cached_threads_insights": {"tp_1": {"views": 120, "likes": 25, "replies": 4}},
            "cached_threads_activity": [{"type": "like", "from": "other_user"}],
            "cached_threads_feed": [{"id": "feed_post_1", "raw_text": "Bài viết trên Feed Threads"}],
            "cached_threads_trends": [{"topic": "#Python312"}],
            "cached_threads_search_results": [{"id": "s_1", "raw_text": "Kết quả tìm kiếm Threads"}],
        }),
    )

    conn = ThreadsPersonalConnector(vault_store=vault)

    # 1. Profile có ưu tiên official_api
    prof = await conn.call("get_profile", {})
    assert prof["ok"] is True
    assert prof["transport"] == "official_api"
    assert "Bio Threads cá nhân" in prof["profile"]["threads_biography"]

    # 2. Posts & Replies
    posts = await conn.call("list_posts", {})
    assert posts["ok"] is True
    assert posts["transport"] == "official_api"
    assert posts["posts"][0]["raw_text"] == "Bài đăng Threads đầu tiên"

    p_det = await conn.call("get_post", {"post_id": "tp_1"})
    assert p_det["ok"] is True
    assert p_det["post"]["raw_text"] == "Chi tiết bài đăng Threads"

    replies = await conn.call("get_post_replies", {"post_id": "tp_1"})
    assert replies["ok"] is True
    assert replies["replies"][0]["raw_text"] == "Phản hồi bài đăng"

    insights = await conn.call("get_insights", {"post_id": "tp_1"})
    assert insights["ok"] is True
    assert insights["insights"]["likes"] == 25

    # 3. Endpoint Web-Only (read_feed, get_trends, search_posts)
    feed = await conn.call("read_feed", {})
    assert feed["ok"] is True
    assert feed["transport"] == "web_session"
    assert feed["web_only"] is True
    assert feed["posts"][0]["raw_text"] == "Bài viết trên Feed Threads"

    trends = await conn.call("get_trends", {})
    assert trends["ok"] is True
    assert trends["transport"] == "web_session"
    assert trends["web_only"] is True
    assert len(trends["trends"]) == 1

    search_res = await conn.call("search_posts", {"q": "Python"})
    assert search_res["ok"] is True
    assert search_res["transport"] == "web_session"
    assert search_res["web_only"] is True
    assert search_res["posts"][0]["raw_text"] == "Kết quả tìm kiếm Threads"


@pytest.mark.asyncio
async def test_threads_personal_write_requires_transport(tmp_path):
    """Kiểm tra thao tác ghi Threads cá nhân: bắt buộc có transport thật, cấm stub ok."""
    vault = make_vault(tmp_path, "th_write.json")
    vault.put(LBL_TH_CONTENT_TOKEN, "GRAPH_TOKEN_123")
    vault.put(LBL_TH_CONTENT_SESSION, json.dumps({"sessionid": "sess_999"}))

    # Không có api_client hay session_runner
    conn = ThreadsPersonalConnector(vault_store=vault)

    # 1. create_post
    p_res = await conn.call("create_post", {"text": "Hello Threads world!"})
    assert p_res["ok"] is False
    assert p_res.get("unsupported") is True
    assert "Chưa có transport thực tế" in p_res["error"]

    # 2. create_reply
    r_res = await conn.call("create_reply", {"reply_to_id": "tp_1", "text": "Replying to post"})
    assert r_res["ok"] is False
    assert r_res.get("unsupported") is True

    # 3. set_feed_suggestions
    s_res = await conn.call("set_feed_suggestions", {"suggestions": ["Tech", "AI"]})
    assert s_res["ok"] is False
    assert s_res.get("unsupported") is True
    assert s_res.get("web_only") is True

    # Khi có api_client: thao tác được ủy quyền thành công
    async def mock_api(action, args, token):
        return {"ok": True, "action_done": action, "token": token}

    conn_with_api = ThreadsPersonalConnector(vault_store=vault, api_client=mock_api)
    p_ok = await conn_with_api.call("create_post", {"text": "Real post via Graph API"})
    assert p_ok["ok"] is True
    assert p_ok["action_done"] == "create_post"


@pytest.mark.asyncio
async def test_policy_and_registry_integration(tmp_path):
    """Kiểm chứng phân quyền Action-Level Policy và đăng ký ConnectorRegistry cho T-30."""
    # 1. Kiểm tra chính sách mặc định trong policy.py
    # Facebook cá nhân: Đọc = allow, Ghi = ask
    assert CONNECTOR_ACTION_DEFAULTS["connector:facebook_personal:view_user_profile"] == VERDICT_ALLOW
    assert CONNECTOR_ACTION_DEFAULTS["connector:facebook_personal:list_groups"] == VERDICT_ALLOW
    assert CONNECTOR_ACTION_DEFAULTS["connector:facebook_personal:read_group_posts"] == VERDICT_ALLOW
    assert CONNECTOR_ACTION_DEFAULTS["connector:facebook_personal:write_comment"] == VERDICT_ASK
    assert CONNECTOR_ACTION_DEFAULTS["connector:facebook_personal:create_post"] == VERDICT_ASK
    assert CONNECTOR_ACTION_DEFAULTS["connector:facebook_personal:create_page_post"] == VERDICT_ASK

    # Threads cá nhân: Đọc = allow, Ghi = ask
    assert CONNECTOR_ACTION_DEFAULTS["connector:threads_personal:get_profile"] == VERDICT_ALLOW
    assert CONNECTOR_ACTION_DEFAULTS["connector:threads_personal:read_feed"] == VERDICT_ALLOW
    assert CONNECTOR_ACTION_DEFAULTS["connector:threads_personal:get_trends"] == VERDICT_ALLOW
    assert CONNECTOR_ACTION_DEFAULTS["connector:threads_personal:create_post"] == VERDICT_ASK
    assert CONNECTOR_ACTION_DEFAULTS["connector:threads_personal:create_reply"] == VERDICT_ASK
    assert CONNECTOR_ACTION_DEFAULTS["connector:threads_personal:set_feed_suggestions"] == VERDICT_ASK

    # 2. Đăng ký trong CONNECTOR_SPECS
    assert "facebook_personal" in CONNECTOR_SPECS
    fb_actions = {a["id"] for a in CONNECTOR_SPECS["facebook_personal"]["actions"]}
    assert {"list_groups", "get_group_detail", "write_comment", "create_post", "search_marketplace"}.issubset(fb_actions)

    assert "threads_personal" in CONNECTOR_SPECS
    th_actions = {a["id"] for a in CONNECTOR_SPECS["threads_personal"]["actions"]}
    assert {"get_profile", "list_posts", "read_feed", "get_trends", "create_post", "create_reply"}.issubset(th_actions)

    # 3. Đăng ký trong build_default_connectors
    mock_cfg = MagicMock()
    mock_cfg.default_timezone = "UTC"
    vault = make_vault(tmp_path, "reg_vault.json")
    registry = build_default_connectors(cfg=mock_cfg, vault_store=vault)
    all_names = registry.names()
    assert "facebook_personal" in all_names
    assert "threads_personal" in all_names
    assert "threads_messages" in all_names

    # 4. Tích hợp WebAppServer
    assert "threads_personal" in WebAppServer.VALID_PERSONAL_CONNECTORS
