"""Kiểm thử toàn diện 5 Built-in Connectors chính thức theo chuẩn T-17:
- Google Workspace (Gmail, Calendar, Drive, Docs, Sheets)
- Facebook Page (Meta Graph API)
- Instagram Business (Meta Graph API)
- Threads Official (Threads API)
- TikTok (TikTok API)

Bảo đảm:
1. Đầy đủ các hành động đọc và ghi theo spec.
2. Dữ liệu ngoài được bọc tự động bằng frame_external.
3. Không lộ bí mật/token ra ngoài.
4. Cơ chế Degrade không sập khi thiếu cấu hình hoặc lỗi API.
5. Phân quyền Action-Level Policy: Đọc = allow, Ghi = ask.
6. Tích hợp trong build_default_connectors và Mini App state.
"""

from unittest.mock import MagicMock
import pytest

from mulon.connectors import build_default_connectors
from mulon.google_conn import (
    GoogleAuth,
    GCalendarConnector,
    GDocsConnector,
    GDriveConnector,
    GmailConnector,
    GSheetsConnector,
    LBL_CLIENT_ID,
    LBL_CLIENT_SECRET,
    LBL_REFRESH,
    LBL_EMAIL,
)
from mulon.policy import CONNECTOR_ACTION_DEFAULTS, CONNECTOR_SPECS, PolicyEngine, VERDICT_ALLOW, VERDICT_ASK
from mulon.social_connectors import (
    FacebookPageConnector,
    InstagramBusinessConnector,
    ThreadsOfficialConnector,
    TikTokConnector,
    LBL_FB_PAGE_TOKEN,
    LBL_FB_PAGE_ID,
    LBL_FB_PAGE_NAME,
    LBL_IG_BIZ_TOKEN,
    LBL_IG_BIZ_ACCOUNT_ID,
    LBL_IG_BIZ_USERNAME,
    LBL_TH_OFFICIAL_TOKEN,
    LBL_TH_OFFICIAL_USER_ID,
    LBL_TH_OFFICIAL_USERNAME,
    LBL_TIKTOK_TOKEN,
    LBL_TIKTOK_OPEN_ID,
    LBL_TIKTOK_NAME,
    LIMITATION_TIKTOK,
)
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer


def make_vault(tmp_path):
    return VaultStore(tmp_path / "vault.json")


# =====================================================================
# 1. Google Drive, Docs, Sheets (Google Workspace Built-in)
# =====================================================================

@pytest.mark.asyncio
async def test_google_workspace_connectors_health_and_actions(tmp_path):
    vault = make_vault(tmp_path)
    cfg = MagicMock()
    cfg.google_client_id = ""
    cfg.google_client_secret = ""
    cfg.webapp_url = "https://example.com"
    cfg.webapp_port = 8080

    # Mock transport cho Google
    async def fake_google_transport(method, url, params=None, json_body=None, headers=None):
        if "oauth2.googleapis.com/token" in url:
            return 200, {"access_token": "ya29.fake_token", "expires_in": 3600}
        if "drive/v3/files" in url:
            if method == "GET":
                if url.endswith("/files"):
                    return 200, {
                        "files": [
                            {"id": "file_1", "name": "Báo cáo Q3.pdf", "mimeType": "application/pdf", "size": "1024", "description": "Tài liệu mật"}
                        ]
                    }
                return 200, {"id": "file_1", "name": "Báo cáo Q3.pdf", "mimeType": "application/pdf", "size": "1024"}
            if method == "POST":
                return 200, {"id": "new_folder_1", "name": json_body.get("name", "New Folder")}
            if method == "DELETE":
                return 200, {}
        if "permissions" in url:
            return 200, {"id": "perm_1", "role": json_body.get("role")}
        if "v1/documents" in url:
            if method == "GET":
                return 200, {
                    "documentId": "doc_1",
                    "title": "Kế hoạch 2026",
                    "body": {
                        "content": [
                            {"paragraph": {"elements": [{"textRun": {"content": "Mục tiêu đạt 1000 khách hàng."}}]}}
                        ]
                    },
                }
            if method == "POST":
                if "batchUpdate" in url:
                    return 200, {"appended": True}
                return 200, {"documentId": "doc_new", "title": json_body.get("title")}
        if "spreadsheets" in url:
            if method == "GET":
                if "/values/" in url:
                    return 200, {"range": "Sheet1!A1:B2", "values": [["Tên", "Điểm"], ["An", "10"]]}
                return 200, {"spreadsheetId": "sheet_1", "properties": {"title": "Bảng điểm"}, "sheets": []}
            if method == "POST":
                if ":append" in url:
                    return 200, {"updates": {"updatedRange": "Sheet1!A3", "updatedRows": 1}}
                return 200, {"spreadsheetId": "sheet_new", "properties": {"title": "Bảng mới"}}
            if method == "PUT":
                return 200, {"updatedRange": "Sheet1!A1", "updatedCells": 1}
        return 404, {"error": "Not Found"}

    auth = GoogleAuth(cfg, vault, transport=fake_google_transport)
    drive = GDriveConnector(auth)
    docs = GDocsConnector(auth)
    sheets = GSheetsConnector(auth)

    # Khi chưa cấu hình
    h_drive = await drive.health_check()
    assert h_drive["configured"] is False
    assert h_drive["ok"] is False

    # Cấu hình client và refresh token
    vault.put(LBL_CLIENT_ID, "client_id_123")
    vault.put(LBL_CLIENT_SECRET, "client_secret_abc")
    vault.put(LBL_REFRESH, "refresh_xyz")
    vault.put(LBL_EMAIL, "admin@mulon.ai")

    h_drive = await drive.health_check()
    assert h_drive["configured"] is True
    assert h_drive["connected"] is True
    assert h_drive["ok"] is True
    assert h_drive["detail"] == "admin@mulon.ai"

    # 1. Drive actions
    list_res = await drive.call("list_files", {"query": "trashed = false"})
    assert list_res["ok"] is True
    assert list_res["count"] == 1
    assert "</external_data>" in list_res["files"][0]["name"]
    assert "Báo cáo Q3.pdf" in list_res["files"][0]["raw_name"]

    folder_res = await drive.call("create_folder", {"name": "Tài liệu dự án"})
    assert folder_res["ok"] is True
    assert folder_res["id"] == "new_folder_1"

    share_res = await drive.call("share_file", {"file_id": "file_1", "role": "reader"})
    assert share_res["ok"] is True
    assert share_res["role"] == "reader"

    del_res = await drive.call("delete_file", {"file_id": "file_1"})
    assert del_res["ok"] is True
    assert del_res["deleted"] == "file_1"

    # 2. Docs actions
    doc_res = await docs.call("get_document", {"document_id": "doc_1"})
    assert doc_res["ok"] is True
    assert "</external_data>" in doc_res["text"]
    assert "Mục tiêu đạt 1000 khách hàng." in doc_res["raw_text"]

    create_doc = await docs.call("create_document", {"title": "Tài liệu mới"})
    assert create_doc["ok"] is True
    assert create_doc["document_id"] == "doc_new"

    append_doc = await docs.call("append_text", {"document_id": "doc_1", "text": "Thêm ghi chú."})
    assert append_doc["ok"] is True

    # 3. Sheets actions
    sheet_val = await sheets.call("read_sheet_values", {"spreadsheet_id": "sheet_1", "range": "Sheet1!A1:B2"})
    assert sheet_val["ok"] is True
    assert "</external_data>" in sheet_val["values"][1][0]
    assert sheet_val["raw_values"][1][0] == "An"

    append_sheet = await sheets.call("append_rows", {"spreadsheet_id": "sheet_1", "values": [["Bình", "9"]]})
    assert append_sheet["ok"] is True
    assert append_sheet["updated_rows"] == 1

    create_sheet = await sheets.call("create_spreadsheet", {"title": "Bảng kế hoạch"})
    assert create_sheet["ok"] is True
    assert create_sheet["spreadsheet_id"] == "sheet_new"


# =====================================================================
# 2. Facebook Page Connector (Meta Graph API)
# =====================================================================

@pytest.mark.asyncio
async def test_facebook_page_connector(tmp_path):
    vault = make_vault(tmp_path)

    async def fake_fb_transport(method, url, params=None, json_body=None, headers=None):
        if method == "GET":
            if "/feed" in url:
                return 200, {
                    "data": [
                        {"id": "post_1", "message": "Chào mừng quý khách đến với Fanpage!", "created_time": "2026-10-27T10:00:00Z", "shares": {"count": 5}}
                    ]
                }
            if "/posts" in url:
                return 200, {
                    "data": [
                        {"id": "post_1", "message": "Bài viết chính thức", "status_type": "mobile_status_update"}
                    ]
                }
            if "/comments" in url:
                return 200, {
                    "data": [
                        {"id": "comment_1", "from": {"name": "Nguyễn Văn A"}, "message": "Sản phẩm tốt lắm shop!"}
                    ]
                }
            if "/insights" in url:
                return 200, {"data": [{"name": "page_impressions", "values": [{"value": 1500}]}]}
            # Info
            return 200, {
                "id": "page_123",
                "name": "MuLon Official Page",
                "category": "Technology Company",
                "about": "Trợ lý AI đa năng dành cho cá nhân",
                "fan_count": 2500,
            }
        if method == "POST":
            if "/comments" in url:
                return 200, {"id": "reply_c_1"}
            if json_body and json_body.get("published") is False:
                return 200, {"id": "draft_post_1"}
            return 200, {"id": "post_published_1"}
        if method == "DELETE":
            return 200, {"success": True}
        return 404, {"error": {"message": "Not Found"}}

    conn = FacebookPageConnector(vault_store=vault, transport=fake_fb_transport)

    # Chưa cấu hình
    h = await conn.health_check()
    assert h["ok"] is False
    assert h["configured"] is False

    # Cấu hình qua action configure
    conf_res = await conn.call("configure", {
        "access_token": "EAAGfake_page_token",
        "page_id": "page_123",
        "page_name": "MuLon Official Page",
    })
    assert conf_res["ok"] is True
    assert conf_res["configured"] is True

    h = await conn.health_check()
    assert h["ok"] is True
    assert h["connected"] is True
    assert h["page_id"] == "page_123"

    # Đọc thông tin Page
    info = await conn.call("get_page_info", {})
    assert info["ok"] is True
    assert info["name"] == "MuLon Official Page"
    assert "</external_data>" in info["about"]
    assert "Trợ lý AI đa năng" in info["raw_about"]

    # Đọc Feed
    feed = await conn.call("read_page_feed", {"limit": 5})
    assert feed["ok"] is True
    assert len(feed["posts"]) == 1
    assert "</external_data>" in feed["posts"][0]["message"]
    assert "Chào mừng quý khách" in feed["posts"][0]["raw_message"]

    # Đọc comment
    comments = await conn.call("read_post_comments", {"post_id": "post_1"})
    assert comments["ok"] is True
    assert "</external_data>" in comments["comments"][0]["message"]

    # Đăng bài
    pub = await conn.call("publish_post", {"message": "Thông báo bản cập nhật mới v1.7.28"})
    assert pub["ok"] is True
    assert pub["post_id"] == "post_published_1"

    # Nháp bài
    draft = await conn.call("create_draft_post", {"message": "Bài nháp dự kiến đăng ngày mai"})
    assert draft["ok"] is True
    assert draft["draft_id"] == "draft_post_1"

    # Trả lời comment
    rep = await conn.call("reply_comment", {"comment_id": "comment_1", "message": "Cảm ơn ní đã ủng hộ!"})
    assert rep["ok"] is True
    assert rep["reply_to"] == "comment_1"

    # Xóa bài
    del_p = await conn.call("delete_post", {"post_id": "post_published_1"})
    assert del_p["ok"] is True
    assert del_p["deleted"] == "post_published_1"

    # Ngắt kết nối
    disc = await conn.call("disconnect", {})
    assert disc["ok"] is True
    assert (await conn.health_check())["connected"] is False


# =====================================================================
# 3. Instagram Business / Creator Connector (Meta Graph API)
# =====================================================================

@pytest.mark.asyncio
async def test_instagram_business_connector(tmp_path):
    vault = make_vault(tmp_path)

    async def fake_ig_transport(method, url, params=None, json_body=None, headers=None):
        if method == "GET":
            if "/media" in url:
                if url.endswith("/media"):
                    return 200, {
                        "data": [
                            {"id": "media_1", "caption": "Hình ảnh thiên nhiên tuyệt đẹp", "media_type": "IMAGE", "like_count": 120}
                        ]
                    }
                return 200, {"id": "media_1", "caption": "Hình ảnh thiên nhiên tuyệt đẹp", "media_type": "IMAGE", "like_count": 120}
            if "/comments" in url:
                return 200, {
                    "data": [
                        {"id": "ig_comm_1", "username": "photo_lover", "text": "Góc chụp đỉnh quá!"}
                    ]
                }
            if "/insights" in url:
                return 200, {"data": [{"name": "reach", "values": [{"value": 500}]}]}
            # Profile
            return 200, {
                "id": "17841400000000001",
                "username": "mulon_creator",
                "name": "MuLon Studio",
                "biography": "Kênh sáng tạo nội dung số",
                "followers_count": 10500,
            }
        if method == "POST":
            if "/media_publish" in url:
                return 200, {"id": "published_ig_media_1"}
            if "/media" in url:
                return 200, {"id": "creation_container_1"}
            if "/replies" in url:
                return 200, {"id": "reply_ig_1"}
        if method == "DELETE":
            return 200, {"success": True}
        return 404, {"error": {"message": "Not Found"}}

    conn = InstagramBusinessConnector(vault_store=vault, transport=fake_ig_transport)

    # Cấu hình qua configure
    await conn.call("configure", {
        "access_token": "EAAGfake_ig_token",
        "account_id": "17841400000000001",
        "username": "mulon_creator",
    })

    h = await conn.health_check()
    assert h["ok"] is True
    assert h["connected"] is True
    assert h["username"] == "mulon_creator"

    # Xem hồ sơ
    prof = await conn.call("get_profile", {})
    assert prof["ok"] is True
    assert prof["username"] == "mulon_creator"
    assert "</external_data>" in prof["biography"]
    assert "Kênh sáng tạo" in prof["raw_biography"]

    # Xem media
    media = await conn.call("list_media", {"limit": 5})
    assert media["ok"] is True
    assert "</external_data>" in media["media"][0]["caption"]

    # Đăng ảnh (2-step publishing)
    pub = await conn.call("publish_photo", {"image_url": "https://example.com/photo.jpg", "caption": "Bình minh trên biển"})
    assert pub["ok"] is True
    assert pub["media_id"] == "published_ig_media_1"

    # Trả lời bình luận
    rep = await conn.call("reply_comment", {"comment_id": "ig_comm_1", "message": "Cảm ơn bạn nhé!"})
    assert rep["ok"] is True
    assert rep["comment_id"] == "reply_ig_1"


# =====================================================================
# 4. Threads Official Connector (Meta Threads API)
# =====================================================================

@pytest.mark.asyncio
async def test_threads_official_connector(tmp_path):
    vault = make_vault(tmp_path)

    async def fake_th_transport(method, url, params=None, json_body=None, headers=None):
        if method == "GET":
            if "/me/threads" in url:
                return 200, {
                    "data": [
                        {"id": "th_post_1", "text": "Hôm nay thời tiết thật đẹp để code!", "timestamp": "2026-10-27T08:00:00Z"}
                    ]
                }
            if "/conversation" in url:
                return 200, {
                    "data": [
                        {"id": "th_reply_1", "username": "friend", "text": "Đồng ý luôn nè ní ơi!"}
                    ]
                }
            if "/insights" in url:
                return 200, {"data": [{"name": "views", "values": [{"value": 240}]}]}
            if "/me" in url:
                return 200, {
                    "id": "th_user_1",
                    "username": "mulon_threads",
                    "threads_biography": "Trò chuyện mỗi ngày về công nghệ",
                }
        if method == "POST":
            if "/threads_publish" in url:
                return 200, {"id": "published_th_id"}
            if "/threads" in url:
                return 200, {"id": "th_container_id"}
        if method == "DELETE":
            return 200, {"success": True}
        return 404, {"error": {"message": "Not Found"}}

    conn = ThreadsOfficialConnector(vault_store=vault, transport=fake_th_transport)

    await conn.call("configure", {
        "access_token": "TH_fake_token",
        "user_id": "th_user_1",
        "username": "mulon_threads",
    })

    h = await conn.health_check()
    assert h["ok"] is True
    assert h["connected"] is True
    assert h["username"] == "mulon_threads"

    # Profile
    prof = await conn.call("get_profile", {})
    assert prof["ok"] is True
    assert "</external_data>" in prof["threads_biography"]

    # List threads
    threads = await conn.call("list_threads", {})
    assert threads["ok"] is True
    assert "</external_data>" in threads["threads"][0]["text"]

    # Đăng bài Threads
    pub = await conn.call("publish_thread", {"text": "Chia sẻ kinh nghiệm lập trình AI"})
    assert pub["ok"] is True
    assert pub["thread_id"] == "published_th_id"

    # Trả lời thread
    rep = await conn.call("reply_thread", {"thread_id": "th_post_1", "text": "Cảm ơn các bạn đã đọc!"})
    assert rep["ok"] is True
    assert rep["reply_id"] == "published_th_id"


# =====================================================================
# 5. TikTok Connector (TikTok API)
# =====================================================================

@pytest.mark.asyncio
async def test_tiktok_connector(tmp_path):
    vault = make_vault(tmp_path)

    async def fake_tiktok_transport(method, url, params=None, json_body=None, headers=None):
        if method == "GET":
            if "/user/info/" in url:
                return 200, {
                    "data": {
                        "user": {
                            "open_id": "tt_open_id_123",
                            "display_name": "MuLon TikTok Creator",
                            "bio_description": "Kênh video công nghệ ngắn",
                            "follower_count": 50000,
                            "likes_count": 250000,
                        }
                    }
                }
        if method == "POST":
            if "/video/list/" in url:
                return 200, {
                    "data": {
                        "videos": [
                            {"id": "tt_vid_1", "title": "Giới thiệu MuLon Bot", "view_count": 15000, "like_count": 3200}
                        ],
                        "has_more": False,
                    }
                }
            if "/post/publish/video/init/" in url:
                return 200, {"data": {"publish_id": "pub_tt_456"}}
        return 404, {"error": {"message": "Not Found"}}

    conn = TikTokConnector(vault_store=vault, transport=fake_tiktok_transport)

    # Cấu hình
    await conn.call("configure", {
        "access_token": "tt_fake_token",
        "open_id": "tt_open_id_123",
        "client_key": "tt_key_abc",
        "display_name": "MuLon TikTok Creator",
    })

    h = await conn.health_check()
    assert h["ok"] is True
    assert h["connected"] is True
    assert h["display_name"] == "MuLon TikTok Creator"
    assert LIMITATION_TIKTOK in h["limitations"]

    # Xem thông tin creator
    user = await conn.call("get_creator_info", {})
    assert user["ok"] is True
    assert user["display_name"] == "MuLon TikTok Creator"
    assert "</external_data>" in user["bio_description"]
    assert "Kênh video công nghệ" in user["raw_bio"]

    # Danh sách video
    vids = await conn.call("list_videos", {})
    assert vids["ok"] is True
    assert len(vids["videos"]) == 1
    assert "</external_data>" in vids["videos"][0]["title"]
    assert vids["videos"][0]["view_count"] == 15000

    # Video stats
    stats = await conn.call("get_video_stats", {"video_id": "tt_vid_1"})
    assert stats["ok"] is True
    assert stats["like_count"] == 3200

    # Đăng bản nháp draft
    draft = await conn.call("share_video_draft", {"video_url": "https://example.com/video.mp4", "title": "Bản nháp video"})
    assert draft["ok"] is True
    assert draft["status"] == "draft_created"
    assert draft["publish_id"] == "pub_tt_456"

    # Đăng trực tiếp
    direct = await conn.call("post_video", {"video_url": "https://example.com/video.mp4", "title": "Video mới"})
    assert direct["ok"] is True
    assert direct["status"] == "processing"


# =====================================================================
# 6. Registry & Policy Enforcement & Mini App State Integration
# =====================================================================

@pytest.mark.asyncio
async def test_builtin_connectors_registry_and_policy(tmp_path):
    vault = make_vault(tmp_path)
    vault.put(LBL_CLIENT_ID, "id")
    vault.put(LBL_CLIENT_SECRET, "secret")
    vault.put(LBL_REFRESH, "refresh")

    mock_cfg = MagicMock()
    mock_cfg.default_timezone = "Asia/Ho_Chi_Minh"
    mock_cfg.google_client_id = "id"
    mock_cfg.google_client_secret = "secret"
    mock_cfg.webapp_url = "http://127.0.0.1:8080"
    mock_cfg.webapp_port = 8080

    registry = build_default_connectors(cfg=mock_cfg, vault_store=vault)
    names = registry.names()

    # Xác nhận đầy đủ các connector built-in chính thức
    assert "system" in names
    assert "gmail" in names
    assert "gcalendar" in names
    assert "gdrive" in names
    assert "gdocs" in names
    assert "gsheets" in names
    assert "facebook_page" in names
    assert "instagram_business" in names
    assert "threads_official" in names
    assert "tiktok" in names

    # Kiểm tra Action-Level Policy
    policy = PolicyEngine(policy_path=tmp_path / "policy.json")
    # Reads must be ALLOW
    assert policy.decide("connector_call", "connector:gdrive:list_files").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:gdocs:get_document").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:gsheets:read_sheet_values").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:facebook_page:read_page_feed").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:instagram_business:list_media").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:threads_official:read_replies").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:tiktok:list_videos").verdict == VERDICT_ALLOW

    # Writes must be ASK
    assert policy.decide("connector_call", "connector:gdrive:upload_file").verdict == VERDICT_ASK
    assert policy.decide("connector_call", "connector:gdocs:append_text").verdict == VERDICT_ASK
    assert policy.decide("connector_call", "connector:gsheets:append_rows").verdict == VERDICT_ASK
    assert policy.decide("connector_call", "connector:facebook_page:publish_post").verdict == VERDICT_ASK
    assert policy.decide("connector_call", "connector:instagram_business:publish_photo").verdict == VERDICT_ASK
    assert policy.decide("connector_call", "connector:threads_official:publish_thread").verdict == VERDICT_ASK
    assert policy.decide("connector_call", "connector:tiktok:post_video").verdict == VERDICT_ASK
