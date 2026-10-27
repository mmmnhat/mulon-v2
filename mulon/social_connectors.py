"""Built-in Social Media Connectors chính thức (T-17).

Bao gồm 4 nền tảng mạng xã hội:
- Facebook Page (`facebook_page`): Meta Graph API cho Fanpage.
- Instagram Business (`instagram_business`): Meta Graph API cho tài khoản Creator / Business.
- Threads Official (`threads_official`): Meta Threads Publishing & Insights API chính thức.
- TikTok (`tiktok`): TikTok Content Display & Posting API chính thức.

Chuẩn chung theo T-17 & AGENTS.md:
- Built-in (cài MuLon là có, không phải marketplace cài thêm).
- Bí mật / Token CHỈ lưu trong Vault bản cài, không hardcode bất kỳ credential hay ID cá nhân nào.
- Mọi nội dung nhận từ bên ngoài (bài viết, bình luận, caption, bio...) đều bọc qua `frame_external`.
- Lỗi kết nối hoặc thiếu cấu hình chuyển sang chế độ suy giảm (degrade) với thông báo tiếng Việt rõ ràng, bot không sập.
- Thao tác ghi yêu cầu transport thật, cấm stub giả mạo `ok: True`.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlencode

from .context import frame_external

logger = logging.getLogger("mulon.social_connectors")

# Transport tiêm được cho unit test: (method, url, params, json_body, headers) -> (status, dict)
Transport = Callable[..., Awaitable[tuple[int, dict]]]

async def _default_aiohttp_transport(
    method: str,
    url: str,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
    headers: Optional[dict] = None,
) -> tuple[int, dict]:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.request(
            method, url, params=params, json=json_body, headers=headers or {}
        ) as resp:
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {}
            return resp.status, data if isinstance(data, dict) else {}


def _vault_get(store, label: str) -> Optional[str]:
    """Đọc 1 giá trị Vault theo label."""
    if store is None:
        return None
    for item in store.labels():
        if item.get("label") == label:
            return store.resolve(item["ref"])
    return None


def _vault_put(store, label: str, value: str) -> None:
    """Ghi đè giá trị Vault theo label."""
    if store is None or not value:
        return
    for item in store.labels():
        if item.get("label") == label:
            store.delete(item["ref"])
    store.put(label, value.strip())


def _vault_delete(store, label: str) -> None:
    """Xóa giá trị Vault theo label."""
    if store is None:
        return
    for item in store.labels():
        if item.get("label") == label:
            store.delete(item["ref"])


# =====================================================================
# 1. Facebook Page Connector (Meta Graph API)
# =====================================================================

LBL_FB_PAGE_TOKEN = "facebook_page:access_token"
LBL_FB_PAGE_ID = "facebook_page:page_id"
LBL_FB_PAGE_NAME = "facebook_page:page_name"

META_GRAPH_BASE = "https://graph.facebook.com/v21.0"


class FacebookPageConnector:
    """Connector chính thức cho Facebook Page qua Meta Business Graph API (T-17)."""
    name = "facebook_page"

    def __init__(self, cfg=None, vault_store=None, transport: Optional[Transport] = None):
        self.cfg = cfg
        self.vault = vault_store
        self.transport = transport or _default_aiohttp_transport

    def access_token(self) -> str:
        return _vault_get(self.vault, LBL_FB_PAGE_TOKEN) or ""

    def page_id(self) -> str:
        return _vault_get(self.vault, LBL_FB_PAGE_ID) or ""

    def page_name(self) -> str:
        return _vault_get(self.vault, LBL_FB_PAGE_NAME) or ""

    def configured(self) -> bool:
        return bool(self.access_token() and self.page_id())

    async def health_check(self) -> dict:
        token = self.access_token()
        pid = self.page_id()
        pname = self.page_name()
        if not (token and pid):
            return {
                "ok": False,
                "name": self.name,
                "configured": False,
                "connected": False,
                "page_id": pid,
                "page_name": pname,
                "detail": "Chưa có Page Access Token hoặc Page ID trong Vault (nhãn facebook_page:access_token, facebook_page:page_id).",
            }
        return {
            "ok": True,
            "name": self.name,
            "configured": True,
            "connected": True,
            "page_id": pid,
            "page_name": pname or pid,
            "detail": f"Đã kết nối Fanpage {pname or pid}",
        }

    async def call(self, action: str, args: dict) -> dict:
        if action == "configure":
            return await self._configure(args)
        if action == "disconnect":
            return await self._disconnect(args)

        token = self.access_token()
        pid = self.page_id()
        if not (token and pid):
            return {
                "ok": False,
                "error": "Facebook Page chưa được cấu hình (thiếu facebook_page:access_token hoặc facebook_page:page_id trong Vault).",
            }

        if action in ("get_page_info", "get_info"):
            return await self._get_page_info()
        if action in ("read_page_feed", "read_feed"):
            return await self._read_page_feed(args)
        if action in ("read_page_posts", "list_posts"):
            return await self._read_page_posts(args)
        if action in ("read_post_comments", "read_comments"):
            return await self._read_post_comments(args)
        if action in ("get_page_insights", "get_insights"):
            return await self._get_page_insights(args)
        if action == "publish_post":
            return await self._publish_post(args)
        if action == "create_draft_post":
            return await self._create_draft_post(args)
        if action == "reply_comment":
            return await self._reply_comment(args)
        if action == "delete_post":
            return await self._delete_post(args)

        return {"ok": False, "error": f"facebook_page không hỗ trợ action: {action}"}

    async def _configure(self, args: dict) -> dict:
        token = str(args.get("access_token") or args.get("token") or "").strip()
        pid = str(args.get("page_id") or "").strip()
        pname = str(args.get("page_name") or args.get("name") or "").strip()
        if token:
            _vault_put(self.vault, LBL_FB_PAGE_TOKEN, token)
        if pid:
            _vault_put(self.vault, LBL_FB_PAGE_ID, pid)
        if pname:
            _vault_put(self.vault, LBL_FB_PAGE_NAME, pname)
        return {"ok": True, "configured": self.configured(), "page_id": self.page_id()}

    async def _disconnect(self, args: dict) -> dict:
        _vault_delete(self.vault, LBL_FB_PAGE_TOKEN)
        _vault_delete(self.vault, LBL_FB_PAGE_ID)
        _vault_delete(self.vault, LBL_FB_PAGE_NAME)
        return {"ok": True, "connected": False}

    async def _get_page_info(self) -> dict:
        pid = self.page_id()
        status, data = await self.transport(
            "GET",
            f"{META_GRAPH_BASE}/{pid}",
            params={"fields": "id,name,category,about,fan_count,link", "access_token": self.access_token()},
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        name = str(data.get("name") or "")
        about = str(data.get("about") or "")
        return {
            "ok": True,
            "page_id": data.get("id", pid),
            "name": name,
            "category": data.get("category", ""),
            "about": frame_external(about) if about else "",
            "raw_about": about,
            "fan_count": data.get("fan_count", 0),
            "link": data.get("link", ""),
        }

    async def _read_page_feed(self, args: dict) -> dict:
        pid = self.page_id()
        limit = max(1, min(int(args.get("limit") or 10), 50))
        status, data = await self.transport(
            "GET",
            f"{META_GRAPH_BASE}/{pid}/feed",
            params={
                "fields": "id,message,created_time,shares,comments.summary(true),reactions.summary(true)",
                "limit": limit,
                "access_token": self.access_token(),
            },
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        items = []
        for post in data.get("data") or []:
            msg = str(post.get("message") or "")
            items.append({
                "id": post.get("id", ""),
                "message": frame_external(msg) if msg else "",
                "raw_message": msg,
                "created_time": post.get("created_time", ""),
                "shares": (post.get("shares") or {}).get("count", 0),
                "comments_count": (post.get("comments") or {}).get("summary", {}).get("total_count", 0),
                "reactions_count": (post.get("reactions") or {}).get("summary", {}).get("total_count", 0),
            })
        return {"ok": True, "count": len(items), "posts": items}

    async def _read_page_posts(self, args: dict) -> dict:
        pid = self.page_id()
        limit = max(1, min(int(args.get("limit") or 10), 50))
        status, data = await self.transport(
            "GET",
            f"{META_GRAPH_BASE}/{pid}/posts",
            params={
                "fields": "id,message,created_time,status_type",
                "limit": limit,
                "access_token": self.access_token(),
            },
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        items = []
        for post in data.get("data") or []:
            msg = str(post.get("message") or "")
            items.append({
                "id": post.get("id", ""),
                "message": frame_external(msg) if msg else "",
                "raw_message": msg,
                "created_time": post.get("created_time", ""),
                "status_type": post.get("status_type", ""),
            })
        return {"ok": True, "count": len(items), "posts": items}

    async def _read_post_comments(self, args: dict) -> dict:
        post_id = str(args.get("post_id") or "").strip()
        if not post_id:
            return {"ok": False, "error": "thiếu post_id"}
        limit = max(1, min(int(args.get("limit") or 20), 50))
        status, data = await self.transport(
            "GET",
            f"{META_GRAPH_BASE}/{post_id}/comments",
            params={
                "fields": "id,from,message,created_time",
                "limit": limit,
                "access_token": self.access_token(),
            },
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        comments = []
        for c in data.get("data") or []:
            msg = str(c.get("message") or "")
            comments.append({
                "id": c.get("id", ""),
                "from": (c.get("from") or {}).get("name", "Người dùng"),
                "message": frame_external(msg) if msg else "",
                "raw_message": msg,
                "created_time": c.get("created_time", ""),
            })
        return {"ok": True, "post_id": post_id, "count": len(comments), "comments": comments}

    async def _get_page_insights(self, args: dict) -> dict:
        pid = self.page_id()
        metric = str(args.get("metric") or "page_impressions,page_engaged_users")
        status, data = await self.transport(
            "GET",
            f"{META_GRAPH_BASE}/{pid}/insights",
            params={"metric": metric, "period": "day", "access_token": self.access_token()},
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "insights": data.get("data", [])}

    async def _publish_post(self, args: dict) -> dict:
        message = str(args.get("message") or "").strip()
        if not message:
            return {"ok": False, "error": "thiếu nội dung bài đăng (message)"}
        pid = self.page_id()
        body: dict[str, Any] = {"message": message, "access_token": self.access_token()}
        if args.get("link"):
            body["link"] = str(args["link"])
        status, data = await self.transport(
            "POST",
            f"{META_GRAPH_BASE}/{pid}/feed",
            json_body=body,
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "post_id": data.get("id", ""), "published": True}

    async def _create_draft_post(self, args: dict) -> dict:
        message = str(args.get("message") or "").strip()
        if not message:
            return {"ok": False, "error": "thiếu nội dung bài nháp (message)"}
        pid = self.page_id()
        body: dict[str, Any] = {
            "message": message,
            "published": False,
            "access_token": self.access_token(),
        }
        status, data = await self.transport(
            "POST",
            f"{META_GRAPH_BASE}/{pid}/feed",
            json_body=body,
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "draft_id": data.get("id", ""), "draft": True}

    async def _reply_comment(self, args: dict) -> dict:
        comment_id = str(args.get("comment_id") or "").strip()
        message = str(args.get("message") or "").strip()
        if not (comment_id and message):
            return {"ok": False, "error": "cần comment_id và message"}
        body = {"message": message, "access_token": self.access_token()}
        status, data = await self.transport(
            "POST",
            f"{META_GRAPH_BASE}/{comment_id}/comments",
            json_body=body,
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "comment_id": data.get("id", ""), "reply_to": comment_id}

    async def _delete_post(self, args: dict) -> dict:
        post_id = str(args.get("post_id") or args.get("id") or "").strip()
        if not post_id:
            return {"ok": False, "error": "thiếu post_id"}
        status, data = await self.transport(
            "DELETE",
            f"{META_GRAPH_BASE}/{post_id}",
            params={"access_token": self.access_token()},
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "deleted": post_id}


# =====================================================================
# 2. Instagram Business / Creator Connector (Meta Graph API)
# =====================================================================

LBL_IG_BIZ_TOKEN = "instagram_business:access_token"
LBL_IG_BIZ_ACCOUNT_ID = "instagram_business:account_id"
LBL_IG_BIZ_USERNAME = "instagram_business:username"


class InstagramBusinessConnector:
    """Connector chính thức cho Instagram Business / Creator qua Meta Graph API (T-17)."""
    name = "instagram_business"

    def __init__(self, cfg=None, vault_store=None, transport: Optional[Transport] = None):
        self.cfg = cfg
        self.vault = vault_store
        self.transport = transport or _default_aiohttp_transport

    def access_token(self) -> str:
        return _vault_get(self.vault, LBL_IG_BIZ_TOKEN) or ""

    def account_id(self) -> str:
        return _vault_get(self.vault, LBL_IG_BIZ_ACCOUNT_ID) or ""

    def username(self) -> str:
        return _vault_get(self.vault, LBL_IG_BIZ_USERNAME) or ""

    def configured(self) -> bool:
        return bool(self.access_token() and self.account_id())

    async def health_check(self) -> dict:
        token = self.access_token()
        aid = self.account_id()
        uname = self.username()
        if not (token and aid):
            return {
                "ok": False,
                "name": self.name,
                "configured": False,
                "connected": False,
                "account_id": aid,
                "username": uname,
                "detail": "Chưa có Instagram Business Access Token hoặc Account ID trong Vault (nhãn instagram_business:access_token, instagram_business:account_id).",
            }
        return {
            "ok": True,
            "name": self.name,
            "configured": True,
            "connected": True,
            "account_id": aid,
            "username": uname or aid,
            "detail": f"Đã kết nối Instagram Business @{uname or aid}",
        }

    async def call(self, action: str, args: dict) -> dict:
        if action == "configure":
            return await self._configure(args)
        if action == "disconnect":
            return await self._disconnect(args)

        token = self.access_token()
        aid = self.account_id()
        if not (token and aid):
            return {
                "ok": False,
                "error": "Instagram Business chưa được cấu hình (thiếu instagram_business:access_token hoặc instagram_business:account_id trong Vault).",
            }

        if action in ("get_profile", "get_me"):
            return await self._get_profile()
        if action in ("list_media", "get_media"):
            return await self._list_media(args)
        if action == "get_media_detail":
            return await self._get_media_detail(args)
        if action == "read_comments":
            return await self._read_comments(args)
        if action == "get_insights":
            return await self._get_insights(args)
        if action == "publish_photo":
            return await self._publish_photo(args)
        if action == "publish_reel":
            return await self._publish_reel(args)
        if action == "reply_comment":
            return await self._reply_comment(args)
        if action == "delete_comment":
            return await self._delete_comment(args)

        return {"ok": False, "error": f"instagram_business không hỗ trợ action: {action}"}

    async def _configure(self, args: dict) -> dict:
        token = str(args.get("access_token") or args.get("token") or "").strip()
        aid = str(args.get("account_id") or "").strip()
        uname = str(args.get("username") or "").strip()
        if token:
            _vault_put(self.vault, LBL_IG_BIZ_TOKEN, token)
        if aid:
            _vault_put(self.vault, LBL_IG_BIZ_ACCOUNT_ID, aid)
        if uname:
            _vault_put(self.vault, LBL_IG_BIZ_USERNAME, uname)
        return {"ok": True, "configured": self.configured(), "account_id": self.account_id()}

    async def _disconnect(self, args: dict) -> dict:
        _vault_delete(self.vault, LBL_IG_BIZ_TOKEN)
        _vault_delete(self.vault, LBL_IG_BIZ_ACCOUNT_ID)
        _vault_delete(self.vault, LBL_IG_BIZ_USERNAME)
        return {"ok": True, "connected": False}

    async def _get_profile(self) -> dict:
        aid = self.account_id()
        status, data = await self.transport(
            "GET",
            f"{META_GRAPH_BASE}/{aid}",
            params={
                "fields": "id,username,name,biography,followers_count,media_count,profile_picture_url",
                "access_token": self.access_token(),
            },
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        bio = str(data.get("biography") or "")
        return {
            "ok": True,
            "account_id": data.get("id", aid),
            "username": data.get("username", ""),
            "name": data.get("name", ""),
            "biography": frame_external(bio) if bio else "",
            "raw_biography": bio,
            "followers_count": data.get("followers_count", 0),
            "media_count": data.get("media_count", 0),
            "profile_picture_url": data.get("profile_picture_url", ""),
        }

    async def _list_media(self, args: dict) -> dict:
        aid = self.account_id()
        limit = max(1, min(int(args.get("limit") or 10), 50))
        status, data = await self.transport(
            "GET",
            f"{META_GRAPH_BASE}/{aid}/media",
            params={
                "fields": "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count",
                "limit": limit,
                "access_token": self.access_token(),
            },
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        media_list = []
        for m in data.get("data") or []:
            cap = str(m.get("caption") or "")
            media_list.append({
                "id": m.get("id", ""),
                "caption": frame_external(cap) if cap else "",
                "raw_caption": cap,
                "media_type": m.get("media_type", ""),
                "media_url": m.get("media_url", ""),
                "permalink": m.get("permalink", ""),
                "timestamp": m.get("timestamp", ""),
                "like_count": m.get("like_count", 0),
                "comments_count": m.get("comments_count", 0),
            })
        return {"ok": True, "count": len(media_list), "media": media_list}

    async def _get_media_detail(self, args: dict) -> dict:
        media_id = str(args.get("media_id") or "").strip()
        if not media_id:
            return {"ok": False, "error": "thiếu media_id"}
        status, data = await self.transport(
            "GET",
            f"{META_GRAPH_BASE}/{media_id}",
            params={
                "fields": "id,caption,media_type,permalink,timestamp,like_count,comments_count",
                "access_token": self.access_token(),
            },
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        cap = str(data.get("caption") or "")
        return {
            "ok": True,
            "id": data.get("id", media_id),
            "caption": frame_external(cap) if cap else "",
            "raw_caption": cap,
            "media_type": data.get("media_type", ""),
            "permalink": data.get("permalink", ""),
            "timestamp": data.get("timestamp", ""),
            "like_count": data.get("like_count", 0),
            "comments_count": data.get("comments_count", 0),
        }

    async def _read_comments(self, args: dict) -> dict:
        media_id = str(args.get("media_id") or "").strip()
        if not media_id:
            return {"ok": False, "error": "thiếu media_id"}
        limit = max(1, min(int(args.get("limit") or 20), 50))
        status, data = await self.transport(
            "GET",
            f"{META_GRAPH_BASE}/{media_id}/comments",
            params={
                "fields": "id,text,timestamp,username,like_count",
                "limit": limit,
                "access_token": self.access_token(),
            },
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        comments = []
        for c in data.get("data") or []:
            text = str(c.get("text") or "")
            comments.append({
                "id": c.get("id", ""),
                "username": c.get("username", "user"),
                "text": frame_external(text) if text else "",
                "raw_text": text,
                "timestamp": c.get("timestamp", ""),
                "like_count": c.get("like_count", 0),
            })
        return {"ok": True, "media_id": media_id, "count": len(comments), "comments": comments}

    async def _get_insights(self, args: dict) -> dict:
        aid = self.account_id()
        metric = str(args.get("metric") or "impressions,reach")
        status, data = await self.transport(
            "GET",
            f"{META_GRAPH_BASE}/{aid}/insights",
            params={"metric": metric, "period": "day", "access_token": self.access_token()},
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "insights": data.get("data", [])}

    async def _publish_photo(self, args: dict) -> dict:
        image_url = str(args.get("image_url") or "").strip()
        if not image_url:
            return {"ok": False, "error": "thiếu image_url công khai"}
        caption = str(args.get("caption") or "").strip()
        aid = self.account_id()

        # Bước 1: Tạo container ảnh
        body = {"image_url": image_url, "caption": caption, "access_token": self.access_token()}
        s1, d1 = await self.transport("POST", f"{META_GRAPH_BASE}/{aid}/media", json_body=body)
        if s1 != 200 or not d1.get("id"):
            return {"ok": False, "error": f"Tạo Media Container lỗi ({s1}): {d1.get('error', {}).get('message', 'Unknown error')}"}
        creation_id = d1["id"]

        # Bước 2: Publish container
        s2, d2 = await self.transport(
            "POST",
            f"{META_GRAPH_BASE}/{aid}/media_publish",
            params={"creation_id": creation_id, "access_token": self.access_token()},
        )
        if s2 != 200:
            return {"ok": False, "error": f"Publish Media lỗi ({s2}): {d2.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "media_id": d2.get("id", creation_id), "published": True}

    async def _publish_reel(self, args: dict) -> dict:
        video_url = str(args.get("video_url") or "").strip()
        if not video_url:
            return {"ok": False, "error": "thiếu video_url công khai"}
        caption = str(args.get("caption") or "").strip()
        aid = self.account_id()

        # Bước 1: Tạo container Reel
        body = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": self.access_token(),
        }
        s1, d1 = await self.transport("POST", f"{META_GRAPH_BASE}/{aid}/media", json_body=body)
        if s1 != 200 or not d1.get("id"):
            return {"ok": False, "error": f"Tạo Reel Container lỗi ({s1}): {d1.get('error', {}).get('message', 'Unknown error')}"}
        creation_id = d1["id"]

        # Bước 2: Publish container
        s2, d2 = await self.transport(
            "POST",
            f"{META_GRAPH_BASE}/{aid}/media_publish",
            params={"creation_id": creation_id, "access_token": self.access_token()},
        )
        if s2 != 200:
            return {"ok": False, "error": f"Publish Reel lỗi ({s2}): {d2.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "media_id": d2.get("id", creation_id), "published": True}

    async def _reply_comment(self, args: dict) -> dict:
        comment_id = str(args.get("comment_id") or "").strip()
        message = str(args.get("message") or "").strip()
        if not (comment_id and message):
            return {"ok": False, "error": "cần comment_id và message"}
        body = {"message": message, "access_token": self.access_token()}
        status, data = await self.transport(
            "POST",
            f"{META_GRAPH_BASE}/{comment_id}/replies",
            json_body=body,
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "comment_id": data.get("id", ""), "reply_to": comment_id}

    async def _delete_comment(self, args: dict) -> dict:
        comment_id = str(args.get("comment_id") or "").strip()
        if not comment_id:
            return {"ok": False, "error": "thiếu comment_id"}
        status, data = await self.transport(
            "DELETE",
            f"{META_GRAPH_BASE}/{comment_id}",
            params={"access_token": self.access_token()},
        )
        if status != 200:
            return {"ok": False, "error": f"Meta Graph API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "deleted": comment_id}


# =====================================================================
# 3. Threads Official Connector (Meta Threads Publishing API)
# =====================================================================

LBL_TH_OFFICIAL_TOKEN = "threads_official:access_token"
LBL_TH_OFFICIAL_USER_ID = "threads_official:user_id"
LBL_TH_OFFICIAL_USERNAME = "threads_official:username"

THREADS_GRAPH_BASE = "https://graph.threads.net/v1.0"


class ThreadsOfficialConnector:
    """Connector chính thức cho Threads qua Threads Publishing & Insights API (T-17)."""
    name = "threads_official"

    def __init__(self, cfg=None, vault_store=None, transport: Optional[Transport] = None):
        self.cfg = cfg
        self.vault = vault_store
        self.transport = transport or _default_aiohttp_transport

    def access_token(self) -> str:
        return _vault_get(self.vault, LBL_TH_OFFICIAL_TOKEN) or ""

    def user_id(self) -> str:
        return _vault_get(self.vault, LBL_TH_OFFICIAL_USER_ID) or ""

    def username(self) -> str:
        return _vault_get(self.vault, LBL_TH_OFFICIAL_USERNAME) or ""

    def configured(self) -> bool:
        return bool(self.access_token() and self.user_id())

    async def health_check(self) -> dict:
        token = self.access_token()
        uid = self.user_id()
        uname = self.username()
        if not (token and uid):
            return {
                "ok": False,
                "name": self.name,
                "configured": False,
                "connected": False,
                "user_id": uid,
                "username": uname,
                "detail": "Chưa có Threads Access Token hoặc User ID trong Vault (nhãn threads_official:access_token, threads_official:user_id).",
            }
        return {
            "ok": True,
            "name": self.name,
            "configured": True,
            "connected": True,
            "user_id": uid,
            "username": uname or uid,
            "detail": f"Đã kết nối Threads Official @{uname or uid}",
        }

    async def call(self, action: str, args: dict) -> dict:
        if action == "configure":
            return await self._configure(args)
        if action == "disconnect":
            return await self._disconnect(args)

        token = self.access_token()
        uid = self.user_id()
        if not (token and uid):
            return {
                "ok": False,
                "error": "Threads Official chưa được cấu hình (thiếu threads_official:access_token hoặc threads_official:user_id trong Vault).",
            }

        if action in ("get_profile", "get_me"):
            return await self._get_profile()
        if action in ("list_threads", "get_threads"):
            return await self._list_threads(args)
        if action == "get_thread_detail":
            return await self._get_thread_detail(args)
        if action == "read_replies":
            return await self._read_replies(args)
        if action == "get_thread_insights":
            return await self._get_thread_insights(args)
        if action == "publish_thread":
            return await self._publish_thread(args)
        if action == "reply_thread":
            return await self._reply_thread(args)
        if action == "delete_thread":
            return await self._delete_thread(args)

        return {"ok": False, "error": f"threads_official không hỗ trợ action: {action}"}

    async def _configure(self, args: dict) -> dict:
        token = str(args.get("access_token") or args.get("token") or "").strip()
        uid = str(args.get("user_id") or "").strip()
        uname = str(args.get("username") or "").strip()
        if token:
            _vault_put(self.vault, LBL_TH_OFFICIAL_TOKEN, token)
        if uid:
            _vault_put(self.vault, LBL_TH_OFFICIAL_USER_ID, uid)
        if uname:
            _vault_put(self.vault, LBL_TH_OFFICIAL_USERNAME, uname)
        return {"ok": True, "configured": self.configured(), "user_id": self.user_id()}

    async def _disconnect(self, args: dict) -> dict:
        _vault_delete(self.vault, LBL_TH_OFFICIAL_TOKEN)
        _vault_delete(self.vault, LBL_TH_OFFICIAL_USER_ID)
        _vault_delete(self.vault, LBL_TH_OFFICIAL_USERNAME)
        return {"ok": True, "connected": False}

    async def _get_profile(self) -> dict:
        status, data = await self.transport(
            "GET",
            f"{THREADS_GRAPH_BASE}/me",
            params={
                "fields": "id,username,threads_profile_picture_url,threads_biography",
                "access_token": self.access_token(),
            },
        )
        if status != 200:
            return {"ok": False, "error": f"Threads API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        bio = str(data.get("threads_biography") or "")
        return {
            "ok": True,
            "user_id": data.get("id", self.user_id()),
            "username": data.get("username", ""),
            "threads_biography": frame_external(bio) if bio else "",
            "raw_biography": bio,
            "profile_picture_url": data.get("threads_profile_picture_url", ""),
        }

    async def _list_threads(self, args: dict) -> dict:
        limit = max(1, min(int(args.get("limit") or 10), 50))
        status, data = await self.transport(
            "GET",
            f"{THREADS_GRAPH_BASE}/me/threads",
            params={
                "fields": "id,media_product_type,text,timestamp,permalink",
                "limit": limit,
                "access_token": self.access_token(),
            },
        )
        if status != 200:
            return {"ok": False, "error": f"Threads API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        threads_list = []
        for t in data.get("data") or []:
            text = str(t.get("text") or "")
            threads_list.append({
                "id": t.get("id", ""),
                "text": frame_external(text) if text else "",
                "raw_text": text,
                "media_product_type": t.get("media_product_type", "THREADS"),
                "timestamp": t.get("timestamp", ""),
                "permalink": t.get("permalink", ""),
            })
        return {"ok": True, "count": len(threads_list), "threads": threads_list}

    async def _get_thread_detail(self, args: dict) -> dict:
        thread_id = str(args.get("thread_id") or args.get("id") or "").strip()
        if not thread_id:
            return {"ok": False, "error": "thiếu thread_id"}
        status, data = await self.transport(
            "GET",
            f"{THREADS_GRAPH_BASE}/{thread_id}",
            params={
                "fields": "id,text,timestamp,permalink,has_replies",
                "access_token": self.access_token(),
            },
        )
        if status != 200:
            return {"ok": False, "error": f"Threads API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        text = str(data.get("text") or "")
        return {
            "ok": True,
            "id": data.get("id", thread_id),
            "text": frame_external(text) if text else "",
            "raw_text": text,
            "timestamp": data.get("timestamp", ""),
            "permalink": data.get("permalink", ""),
            "has_replies": data.get("has_replies", False),
        }

    async def _read_replies(self, args: dict) -> dict:
        thread_id = str(args.get("thread_id") or args.get("id") or "").strip()
        if not thread_id:
            return {"ok": False, "error": "thiếu thread_id"}
        status, data = await self.transport(
            "GET",
            f"{THREADS_GRAPH_BASE}/{thread_id}/conversation",
            params={
                "fields": "id,text,timestamp,username",
                "access_token": self.access_token(),
            },
        )
        if status != 200:
            return {"ok": False, "error": f"Threads API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        replies = []
        for r in data.get("data") or []:
            text = str(r.get("text") or "")
            replies.append({
                "id": r.get("id", ""),
                "username": r.get("username", "user"),
                "text": frame_external(text) if text else "",
                "raw_text": text,
                "timestamp": r.get("timestamp", ""),
            })
        return {"ok": True, "thread_id": thread_id, "count": len(replies), "replies": replies}

    async def _get_thread_insights(self, args: dict) -> dict:
        thread_id = str(args.get("thread_id") or args.get("id") or "").strip()
        if not thread_id:
            return {"ok": False, "error": "thiếu thread_id"}
        metric = str(args.get("metric") or "views,likes,replies,reposts,quotes")
        status, data = await self.transport(
            "GET",
            f"{THREADS_GRAPH_BASE}/{thread_id}/insights",
            params={"metric": metric, "access_token": self.access_token()},
        )
        if status != 200:
            return {"ok": False, "error": f"Threads API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "thread_id": thread_id, "insights": data.get("data", [])}

    async def _publish_thread(self, args: dict) -> dict:
        text = str(args.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "thiếu nội dung bài đăng (text)"}
        media_type = "TEXT"
        body: dict[str, Any] = {
            "media_type": media_type,
            "text": text,
            "access_token": self.access_token(),
        }
        if args.get("image_url"):
            body["media_type"] = "IMAGE"
            body["image_url"] = str(args["image_url"])

        # Bước 1: Tạo item container
        s1, d1 = await self.transport("POST", f"{THREADS_GRAPH_BASE}/me/threads", json_body=body)
        if s1 != 200 or not d1.get("id"):
            return {"ok": False, "error": f"Tạo Threads Container lỗi ({s1}): {d1.get('error', {}).get('message', 'Unknown error')}"}
        creation_id = d1["id"]

        # Bước 2: Publish container
        s2, d2 = await self.transport(
            "POST",
            f"{THREADS_GRAPH_BASE}/me/threads_publish",
            params={"creation_id": creation_id, "access_token": self.access_token()},
        )
        if s2 != 200:
            return {"ok": False, "error": f"Publish Threads lỗi ({s2}): {d2.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "thread_id": d2.get("id", creation_id), "published": True}

    async def _reply_thread(self, args: dict) -> dict:
        thread_id = str(args.get("thread_id") or "").strip()
        text = str(args.get("text") or "").strip()
        if not (thread_id and text):
            return {"ok": False, "error": "cần thread_id và text"}
        body = {
            "media_type": "TEXT",
            "text": text,
            "reply_to_id": thread_id,
            "access_token": self.access_token(),
        }
        s1, d1 = await self.transport("POST", f"{THREADS_GRAPH_BASE}/me/threads", json_body=body)
        if s1 != 200 or not d1.get("id"):
            return {"ok": False, "error": f"Tạo Reply Container lỗi ({s1}): {d1.get('error', {}).get('message', 'Unknown error')}"}
        creation_id = d1["id"]

        s2, d2 = await self.transport(
            "POST",
            f"{THREADS_GRAPH_BASE}/me/threads_publish",
            params={"creation_id": creation_id, "access_token": self.access_token()},
        )
        if s2 != 200:
            return {"ok": False, "error": f"Publish Reply lỗi ({s2}): {d2.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "reply_id": d2.get("id", creation_id), "reply_to": thread_id}

    async def _delete_thread(self, args: dict) -> dict:
        thread_id = str(args.get("thread_id") or args.get("id") or "").strip()
        if not thread_id:
            return {"ok": False, "error": "thiếu thread_id"}
        status, data = await self.transport(
            "DELETE",
            f"{THREADS_GRAPH_BASE}/{thread_id}",
            params={"access_token": self.access_token()},
        )
        if status != 200:
            return {"ok": False, "error": f"Threads API lỗi ({status}): {data.get('error', {}).get('message', 'Unknown error')}"}
        return {"ok": True, "deleted": thread_id}


# =====================================================================
# 4. TikTok Connector (TikTok Content Display & Posting API)
# =====================================================================

LBL_TIKTOK_TOKEN = "tiktok:access_token"
LBL_TIKTOK_OPEN_ID = "tiktok:open_id"
LBL_TIKTOK_CLIENT_KEY = "tiktok:client_key"
LBL_TIKTOK_NAME = "tiktok:display_name"

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"

LIMITATION_TIKTOK = (
    "TikTok Direct Post API yêu cầu nhà phát triển phải có phạm vi video.publish "
    "đã được duyệt chính thức bởi TikTok. Với các tài khoản thông thường, video tải lên "
    "sẽ được tạo dưới dạng bản nháp và gửi thông báo xác nhận tới ứng dụng di động TikTok của nhà sáng tạo."
)


class TikTokConnector:
    """Connector chính thức cho TikTok qua TikTok Display & Posting API (T-17)."""
    name = "tiktok"

    def __init__(self, cfg=None, vault_store=None, transport: Optional[Transport] = None):
        self.cfg = cfg
        self.vault = vault_store
        self.transport = transport or _default_aiohttp_transport

    def access_token(self) -> str:
        return _vault_get(self.vault, LBL_TIKTOK_TOKEN) or ""

    def open_id(self) -> str:
        return _vault_get(self.vault, LBL_TIKTOK_OPEN_ID) or ""

    def client_key(self) -> str:
        return _vault_get(self.vault, LBL_TIKTOK_CLIENT_KEY) or ""

    def display_name(self) -> str:
        return _vault_get(self.vault, LBL_TIKTOK_NAME) or ""

    def configured(self) -> bool:
        return bool(self.access_token() and self.open_id())

    async def health_check(self) -> dict:
        token = self.access_token()
        oid = self.open_id()
        dname = self.display_name()
        if not (token and oid):
            return {
                "ok": False,
                "name": self.name,
                "configured": False,
                "connected": False,
                "open_id": oid,
                "display_name": dname,
                "limitations": LIMITATION_TIKTOK,
                "detail": "Chưa có TikTok Access Token hoặc Open ID trong Vault (nhãn tiktok:access_token, tiktok:open_id).",
            }
        return {
            "ok": True,
            "name": self.name,
            "configured": True,
            "connected": True,
            "open_id": oid,
            "display_name": dname or oid,
            "limitations": LIMITATION_TIKTOK,
            "detail": f"Đã kết nối TikTok @{dname or oid}",
        }

    async def call(self, action: str, args: dict) -> dict:
        if action == "configure":
            return await self._configure(args)
        if action == "disconnect":
            return await self._disconnect(args)

        token = self.access_token()
        oid = self.open_id()
        if not (token and oid):
            return {
                "ok": False,
                "error": "TikTok chưa được cấu hình (thiếu tiktok:access_token hoặc tiktok:open_id trong Vault).",
            }

        if action in ("get_creator_info", "get_user_info", "get_profile"):
            return await self._get_creator_info()
        if action in ("list_videos", "get_videos"):
            return await self._list_videos(args)
        if action == "get_video_stats":
            return await self._get_video_stats(args)
        if action == "share_video_draft":
            return await self._share_video_draft(args)
        if action == "post_video":
            return await self._post_video(args)

        return {"ok": False, "error": f"tiktok không hỗ trợ action: {action}"}

    async def _configure(self, args: dict) -> dict:
        token = str(args.get("access_token") or args.get("token") or "").strip()
        oid = str(args.get("open_id") or "").strip()
        ck = str(args.get("client_key") or "").strip()
        dname = str(args.get("display_name") or args.get("name") or "").strip()
        if token:
            _vault_put(self.vault, LBL_TIKTOK_TOKEN, token)
        if oid:
            _vault_put(self.vault, LBL_TIKTOK_OPEN_ID, oid)
        if ck:
            _vault_put(self.vault, LBL_TIKTOK_CLIENT_KEY, ck)
        if dname:
            _vault_put(self.vault, LBL_TIKTOK_NAME, dname)
        return {"ok": True, "configured": self.configured(), "open_id": self.open_id()}

    async def _disconnect(self, args: dict) -> dict:
        _vault_delete(self.vault, LBL_TIKTOK_TOKEN)
        _vault_delete(self.vault, LBL_TIKTOK_OPEN_ID)
        _vault_delete(self.vault, LBL_TIKTOK_CLIENT_KEY)
        _vault_delete(self.vault, LBL_TIKTOK_NAME)
        return {"ok": True, "connected": False}

    async def _get_creator_info(self) -> dict:
        fields = "open_id,union_id,avatar_url,display_name,bio_description,profile_deep_link,is_verified,follower_count,following_count,likes_count"
        status, data = await self.transport(
            "GET",
            f"{TIKTOK_API_BASE}/user/info/",
            params={"fields": fields},
            headers={"Authorization": f"Bearer {self.access_token()}"},
        )
        if status != 200 or not data.get("data", {}).get("user"):
            err_msg = data.get("error", {}).get("message", "Lỗi lấy thông tin người dùng TikTok")
            return {"ok": False, "error": f"TikTok API lỗi ({status}): {err_msg}"}
        user = data["data"]["user"]
        bio = str(user.get("bio_description") or "")
        return {
            "ok": True,
            "open_id": user.get("open_id", self.open_id()),
            "display_name": user.get("display_name", ""),
            "avatar_url": user.get("avatar_url", ""),
            "bio_description": frame_external(bio) if bio else "",
            "raw_bio": bio,
            "profile_deep_link": user.get("profile_deep_link", ""),
            "is_verified": user.get("is_verified", False),
            "follower_count": user.get("follower_count", 0),
            "following_count": user.get("following_count", 0),
            "likes_count": user.get("likes_count", 0),
        }

    async def _list_videos(self, args: dict) -> dict:
        max_count = max(1, min(int(args.get("max_count") or 10), 20))
        fields = "id,title,video_description,duration,cover_image_url,embed_link,like_count,comment_count,share_count,view_count"
        body = {"max_count": max_count}
        cursor = args.get("cursor")
        if cursor is not None:
            body["cursor"] = cursor

        status, data = await self.transport(
            "POST",
            f"{TIKTOK_API_BASE}/video/list/",
            params={"fields": fields},
            json_body=body,
            headers={"Authorization": f"Bearer {self.access_token()}"},
        )
        if status != 200 or "data" not in data:
            err_msg = data.get("error", {}).get("message", "Lỗi lấy danh sách video TikTok")
            return {"ok": False, "error": f"TikTok API lỗi ({status}): {err_msg}"}
        videos = []
        for v in (data.get("data") or {}).get("videos") or []:
            title = str(v.get("title") or "")
            desc = str(v.get("video_description") or "")
            videos.append({
                "id": v.get("id", ""),
                "title": frame_external(title) if title else "",
                "raw_title": title,
                "video_description": frame_external(desc) if desc else "",
                "raw_description": desc,
                "duration": v.get("duration", 0),
                "cover_image_url": v.get("cover_image_url", ""),
                "embed_link": v.get("embed_link", ""),
                "like_count": v.get("like_count", 0),
                "comment_count": v.get("comment_count", 0),
                "share_count": v.get("share_count", 0),
                "view_count": v.get("view_count", 0),
            })
        has_more = (data.get("data") or {}).get("has_more", False)
        next_cursor = (data.get("data") or {}).get("cursor", 0)
        return {
            "ok": True,
            "count": len(videos),
            "videos": videos,
            "has_more": has_more,
            "cursor": next_cursor,
        }

    async def _get_video_stats(self, args: dict) -> dict:
        video_id = str(args.get("video_id") or args.get("id") or "").strip()
        if not video_id:
            return {"ok": False, "error": "thiếu video_id"}
        # Lấy danh sách video để tra cứu thống kê
        res = await self._list_videos({"max_count": 20})
        if not res.get("ok"):
            return res
        for v in res.get("videos") or []:
            if str(v.get("id")) == video_id:
                return {
                    "ok": True,
                    "video_id": video_id,
                    "title": v.get("title", ""),
                    "like_count": v.get("like_count", 0),
                    "comment_count": v.get("comment_count", 0),
                    "share_count": v.get("share_count", 0),
                    "view_count": v.get("view_count", 0),
                }
        return {"ok": False, "error": f"Không tìm thấy video {video_id} trong danh sách gần đây"}

    async def _share_video_draft(self, args: dict) -> dict:
        video_url = str(args.get("video_url") or "").strip()
        title = str(args.get("title") or "").strip()
        if not video_url:
            return {"ok": False, "error": "thiếu video_url công khai để chia sẻ vào TikTok Draft"}

        body = {
            "post_info": {
                "title": title,
                "privacy_level": args.get("privacy_level", "SELF_ONLY"),
                "disable_duet": bool(args.get("disable_duet", False)),
                "disable_comment": bool(args.get("disable_comment", False)),
                "disable_stitch": bool(args.get("disable_stitch", False)),
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            },
        }
        status, data = await self.transport(
            "POST",
            f"{TIKTOK_API_BASE}/post/publish/video/init/",
            json_body=body,
            headers={"Authorization": f"Bearer {self.access_token()}"},
        )
        if status != 200 or not (data.get("data") or {}).get("publish_id"):
            err_msg = data.get("error", {}).get("message", "Lỗi tạo TikTok Draft")
            return {"ok": False, "error": f"TikTok API lỗi ({status}): {err_msg}"}
        publish_id = data["data"]["publish_id"]
        return {
            "ok": True,
            "publish_id": publish_id,
            "status": "draft_created",
            "message": "Đã tạo bản nháp video trên TikTok; vui lòng mở ứng dụng TikTok để kiểm tra và xác nhận đăng tải.",
            "limitations": LIMITATION_TIKTOK,
        }

    async def _post_video(self, args: dict) -> dict:
        video_url = str(args.get("video_url") or "").strip()
        title = str(args.get("title") or "").strip()
        if not video_url:
            return {"ok": False, "error": "thiếu video_url công khai để đăng trực tiếp lên TikTok"}

        privacy = str(args.get("privacy_level") or "PUBLIC_TO_EVERYONE")
        body = {
            "post_info": {
                "title": title,
                "privacy_level": privacy,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            },
        }
        status, data = await self.transport(
            "POST",
            f"{TIKTOK_API_BASE}/post/publish/video/init/",
            json_body=body,
            headers={"Authorization": f"Bearer {self.access_token()}"},
        )
        if status != 200 or not (data.get("data") or {}).get("publish_id"):
            err_msg = data.get("error", {}).get("message", "Lỗi đăng video trực tiếp lên TikTok")
            return {"ok": False, "error": f"TikTok API lỗi ({status}): {err_msg}"}
        publish_id = data["data"]["publish_id"]
        return {
            "ok": True,
            "publish_id": publish_id,
            "status": "processing",
            "message": "Đã khởi tạo đăng video lên TikTok thành công.",
            "limitations": LIMITATION_TIKTOK,
        }
