"""Nguồn dữ kiện catalog của MCP Marketplace (1.3.0).

Theo spec marketplace mục 4 + quyết định owner 15.3 (phương án
B): Mulon 1.3 KHÔNG phụ thuộc API của mcp-marketplace.io (đã
kiểm chứng: họ chỉ công bố Creator Docs, không có API client
công khai có version). Nguồn sự thật là:

- ``CuratedBundleProvider``: bundle tuyển chọn đóng gói cùng bản
  phát hành (``config/marketplace_curated.json``) + snapshot đã
  tải về từ chính repo GitHub của dự án khi catalog tự cập nhật
  (kiểm tra checksum trước khi dùng — việc tải về và đối chiếu
  sống trong MarketplaceService, provider chỉ đọc snapshot hợp
  lệ đã được ghi vào ``marketplace_catalog.json``).
- ``ManualImportProvider``: owner dán cấu hình; không có catalog.

Provider chỉ cung cấp DỮ KIỆN niêm yết. Cài đặt luôn đi qua
MarketplaceService (chuẩn hoá -> phân tích rủi ro -> probe ->
2 lần duyệt -> commit có rollback).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

CATEGORY_LABELS = {
    "developer-tools": "Công cụ dev",
    "data-analytics": "Dữ liệu & phân tích",
    "productivity": "Năng suất & ghi chú",
    "communication": "Giao tiếp & chat",
    "design": "Thiết kế & đồ họa",
    "cloud-devops": "Cloud & DevOps",
    "finance": "Tài chính & thanh toán",
    "file-storage": "File & lưu trữ",
    "ai-ml": "AI & Machine Learning",
    "content-media": "Nội dung & media",
    "security": "Bảo mật & xác thực",
    "business-tools": "Công cụ doanh nghiệp",
    "search-web": "Tìm kiếm & web",
    "marketing-social": "Marketing & mạng xã hội",
    "education-research": "Giáo dục & nghiên cứu",
    "utilities": "Tiện ích hệ thống",
    "data": "Dữ liệu",
    "other": "Khác",
}

MCP_MARKETPLACE_CATEGORIES_FALLBACK = [
    {
        "slug": "developer-tools",
        "name": "Công cụ dev",
        "description": "Kho code, CI/CD, automation trình duyệt, dev workflow",
        "server_count": 37825,
    },
    {
        "slug": "finance",
        "name": "Tài chính & thanh toán",
        "description": "Cổng thanh toán, hoá đơn, dữ liệu tài chính",
        "server_count": 825,
    },
    {
        "slug": "security",
        "name": "Bảo mật & xác thực",
        "description": "Xác thực, mã hoá, quét lỗ hổng và tuân thủ",
        "server_count": 329,
    },
    {
        "slug": "marketing-social",
        "name": "Marketing & mạng xã hội",
        "description": "Mạng xã hội, email marketing, chiến dịch và analytics",
        "server_count": 322,
    },
    {
        "slug": "data-analytics",
        "name": "Dữ liệu & phân tích",
        "description": "Cơ sở dữ liệu, query engines, pipeline dữ liệu",
        "server_count": 293,
    },
    {
        "slug": "cloud-devops",
        "name": "Cloud & DevOps",
        "description": "Hạ tầng cloud, container, triển khai và vận hành",
        "server_count": 205,
    },
    {
        "slug": "search-web",
        "name": "Tìm kiếm & web",
        "description": "Tìm kiếm web, thu thập dữ liệu, scraping và khám phá",
        "server_count": 193,
    },
    {
        "slug": "ai-ml",
        "name": "AI & Machine Learning",
        "description": "Mô hình suy luận AI, tìm kiếm ngữ nghĩa, công cụ ML",
        "server_count": 188,
    },
    {
        "slug": "content-media",
        "name": "Nội dung & media",
        "description": "Video, audio, tạo ảnh và trích xuất nội dung",
        "server_count": 180,
    },
    {
        "slug": "education-research",
        "name": "Giáo dục & nghiên cứu",
        "description": "Tìm kiếm học thuật, công cụ học tập, quản lý trích dẫn",
        "server_count": 130,
    },
    {
        "slug": "communication",
        "name": "Giao tiếp & chat",
        "description": "Nền tảng chat, tin nhắn, giao tiếp đội ngũ",
        "server_count": 127,
    },
    {
        "slug": "business-tools",
        "name": "Công cụ doanh nghiệp",
        "description": "CRM, quản trị dự án, hoá đơn và tự động hoá doanh nghiệp",
        "server_count": 119,
    },
    {
        "slug": "productivity",
        "name": "Năng suất & ghi chú",
        "description": "Quản lý công việc, ghi chú và kho tri thức cá nhân",
        "server_count": 117,
    },
    {
        "slug": "design",
        "name": "Thiết kế & đồ họa",
        "description": "Công cụ thiết kế UI/UX, mô hình 3D, sáng tạo hình ảnh",
        "server_count": 67,
    },
    {
        "slug": "file-storage",
        "name": "File & lưu trữ",
        "description": "Hệ thống file, lưu trữ đám mây, quản lý tài liệu",
        "server_count": 37,
    },
    {
        "slug": "other",
        "name": "Khác",
        "description": "Các server tiện ích và tích hợp chuyên biệt khác",
        "server_count": 7,
    },
]

CURATED_PROVIDER_ID = "mulon-curated"
MANUAL_PROVIDER_ID = "manual"


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bundle_content_hash(bundle: dict) -> str:
    """Checksum nội dung bundle: hash trên phần dữ kiện cốt lõi
    (phiên bản + listings) ở dạng canonical — file tải về phải
    khớp hash này mới được thay snapshot (quyết định owner)."""
    core = {"bundle_version": bundle.get("bundle_version"),
            "listings": bundle.get("listings")}
    return sha256_hex(canonical_json(core))


def validate_bundle(bundle) -> Optional[str]:
    """Trả thông điệp lỗi nếu bundle không hợp lệ, None nếu ổn.
    Kiểm tra cấu trúc tối thiểu + checksum (khi file có khai)."""
    if not isinstance(bundle, dict):
        return "bundle không phải JSON object"
    if bundle.get("provider_id") != CURATED_PROVIDER_ID:
        return "provider_id của bundle không khớp nguồn tuyển chọn"
    listings = bundle.get("listings")
    if not isinstance(listings, list):
        return "bundle thiếu danh sách listings"
    slugs = set()
    for item in listings:
        if not isinstance(item, dict) or not item.get("slug"):
            return "listing thiếu slug"
        if item["slug"] in slugs:
            return f"slug bị trùng trong bundle: {item['slug']}"
        slugs.add(item["slug"])
        install = item.get("install")
        if not isinstance(install, dict) or not install.get("command"):
            return f"listing {item['slug']} thiếu cấu hình install"
    declared = bundle.get("content_sha256")
    if declared and declared != bundle_content_hash(bundle):
        return "checksum nội dung bundle không khớp"
    return None


class CuratedBundleProvider:
    """Đọc bundle đóng gói + snapshot đã tải (nếu mới hơn)."""

    provider_id = CURATED_PROVIDER_ID
    display_name = "Mulon tuyển chọn"

    def __init__(self, bundled_path: str | Path,
                 downloaded_path: str | Path):
        self.bundled_path = Path(bundled_path)
        self.downloaded_path = Path(downloaded_path)

    def _read(self, path: Path) -> Optional[dict]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if validate_bundle(data) is not None:
            return None
        return data

    def bundled(self) -> Optional[dict]:
        return self._read(self.bundled_path)

    def downloaded(self) -> Optional[dict]:
        return self._read(self.downloaded_path)

    def effective(self) -> tuple[Optional[dict], dict]:
        """(bundle hiệu lực, meta). Snapshot tải về chỉ thắng khi
        bundle_version mới hơn bản đóng gói."""
        bundled = self.bundled()
        downloaded = self.downloaded()
        meta = {"provider_id": self.provider_id,
                "source": "bundled",
                "fetched_at": None,
                "bundle_version": None,
                "status": "unavailable"}
        chosen = bundled
        if downloaded is not None:
            dv = str(downloaded.get("bundle_version") or "")
            bv = str((bundled or {}).get("bundle_version") or "")
            if bundled is None or dv > bv:
                chosen = downloaded
                meta["source"] = "downloaded"
                meta["fetched_at"] = downloaded.get("_fetched_at")
        if chosen is not None:
            meta["status"] = "fresh"
            meta["bundle_version"] = chosen.get("bundle_version")
            meta["reviewed_at"] = chosen.get("reviewed_at")
        return chosen, meta

    # ---------- truy vấn ----------
    def listings(self) -> list[dict]:
        bundle, _meta = self.effective()
        if bundle is None:
            return []
        return [dict(item) for item in bundle.get("listings") or []]

    def get_listing(self, slug: str) -> Optional[dict]:
        for item in self.listings():
            if item.get("slug") == slug:
                return item
        return None

    def categories(self) -> list[dict]:
        counts: dict[str, int] = {}
        for item in self.listings():
            for cat in item.get("categories") or []:
                counts[cat] = counts.get(cat, 0) + 1
        return [{"id": cat,
                 "label": CATEGORY_LABELS.get(cat, cat),
                 "count": count}
                for cat, count in sorted(counts.items())]


class ManualImportProvider:
    """Nguồn 'manual': owner dán cấu hình. Không có catalog —
    MarketplaceService chuẩn hoá payload thành draft listing."""

    provider_id = MANUAL_PROVIDER_ID
    display_name = "Nhập thủ công"

