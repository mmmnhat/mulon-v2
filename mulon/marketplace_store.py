"""Sổ bền của MCP Marketplace (1.3.0, spec marketplace mục 6 + 10).

Một file JSON ghi nguyên tử (tmp + replace, cùng mẫu VaultStore /
PolicyEngine) tại ``data/marketplace.json``. Chứa:

- ``installed``: registry các server Mulon quản lý (installed
  records theo đúng trường mục 5.4 — KHÔNG chứa secret value;
  chỉ vault ref).
- ``operations``: journal/state của install/update/uninstall/
  health-check (mục 5.8) — bản ghi operation bền để crash giữa
  chừng vẫn đối chiếu được, không mất dấu.
- ``drafts``: bản nháp import thủ công chưa cài.
- ``tombstones``: dấu vết server đã gỡ (mục 5.5) để hiển thị lại
  được trạng thái sau khi record chính bị xoá.
- ``idempotency``: request id của thao tác đổi trạng thái (mục
  11.4) -> operation id, chống double-submit.
- ``restart``: ý định áp dụng đang chờ sau self-restart (cài/gỡ/
  cập nhật) + hàng đợi thông báo cho owner sau khi bot lên lại.
- ``catalog_update``: lần kiểm tra/cập nhật catalog tự động gần
  nhất (job nền hẹp của owner: boot + hàng tuần, chỉ dữ kiện).

Không module nào khác của marketplace được ghi file này trực
tiếp ngoài qua các method ở đây.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

_EMPTY = {
    "installed": {},
    "operations": {},
    "drafts": {},
    "tombstones": [],
    "idempotency": {},
    "restart": {"pending": None, "notifications": []},
    "catalog_update": {"last_check_at": 0.0, "last_result": "",
                       "last_error": ""},
    "apply_generation": 0,
}


class MarketplaceStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = self._load()

    # ---------- nền tảng ----------
    def _load(self) -> dict:
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("store root is not an object")
        except FileNotFoundError:
            return json.loads(json.dumps(_EMPTY))
        except Exception:
            # File hỏng: không ghi đè mù — giữ nguyên file, chạy
            # với sổ rỗng trong bộ nhớ và để boot reconciliation
            # báo trạng thái thay vì mất dữ kiện âm thầm.
            return json.loads(json.dumps(_EMPTY))
        merged = json.loads(json.dumps(_EMPTY))
        merged.update(data)
        return merged

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8")
            tmp.replace(self.path)

    @property
    def data(self) -> dict:
        return self._data

    # ---------- installed registry ----------
    def get_installed(self, local_name: str) -> Optional[dict]:
        return self._data["installed"].get(local_name)

    def all_installed(self) -> dict:
        return dict(self._data["installed"])

    def put_installed(self, record: dict) -> None:
        with self._lock:
            self._data["installed"][record["local_name"]] = record
            self.save()

    def remove_installed(self, local_name: str) -> Optional[dict]:
        with self._lock:
            record = self._data["installed"].pop(local_name, None)
            if record is not None:
                self.save()
            return record

    # ---------- operations ----------
    def get_operation(self, operation_id: str) -> Optional[dict]:
        return self._data["operations"].get(operation_id)

    def all_operations(self) -> dict:
        return dict(self._data["operations"])

    def put_operation(self, operation: dict) -> None:
        with self._lock:
            self._data["operations"][operation["id"]] = operation
            self.save()

    def prune_operations(self, keep: int = 50) -> None:
        """Giữ tối đa ``keep`` operation gần nhất (journal vẫn còn
        đủ để đối chiếu; tránh file phình vô hạn)."""
        with self._lock:
            ops = self._data["operations"]
            if len(ops) <= keep:
                return
            ordered = sorted(
                ops.values(),
                key=lambda o: o.get("created_at", 0))
            for old in ordered[:len(ops) - keep]:
                ops.pop(old["id"], None)
            self.save()

    # ---------- drafts (import thủ công) ----------
    def get_draft(self, draft_id: str) -> Optional[dict]:
        return self._data["drafts"].get(draft_id)

    def put_draft(self, draft: dict) -> None:
        with self._lock:
            self._data["drafts"][draft["id"]] = draft
            self.save()

    def remove_draft(self, draft_id: str) -> None:
        with self._lock:
            if self._data["drafts"].pop(draft_id, None) is not None:
                self.save()

    def prune_drafts(self, max_age_s: float = 24 * 3600) -> None:
        now = time.time()
        with self._lock:
            drafts = self._data["drafts"]
            stale = [k for k, v in drafts.items()
                     if now - v.get("created_at", 0) > max_age_s]
            for key in stale:
                drafts.pop(key, None)
            if stale:
                self.save()

    # ---------- tombstones ----------
    def add_tombstone(self, tombstone: dict) -> None:
        with self._lock:
            self._data["tombstones"].append(tombstone)
            self._data["tombstones"] = self._data["tombstones"][-50:]
            self.save()

    def tombstones(self) -> list[dict]:
        return list(self._data["tombstones"])

    # ---------- idempotency ----------
    def idempotent_get(self, key: str) -> Optional[str]:
        return self._data["idempotency"].get(key)

    def idempotent_put(self, key: str, operation_id: str) -> None:
        with self._lock:
            self._data["idempotency"][key] = operation_id
            # Giới hạn kích thước: giữ 200 key gần nhất.
            items = list(self._data["idempotency"].items())
            if len(items) > 200:
                self._data["idempotency"] = dict(items[-200:])
            self.save()

    # ---------- restart intent + notifications ----------
    def restart_pending(self) -> Optional[dict]:
        return self._data["restart"].get("pending")

    def set_restart_pending(self, pending: Optional[dict]) -> None:
        with self._lock:
            self._data["restart"]["pending"] = pending
            self.save()

    def push_notification(self, text: str, kind: str = "info") -> None:
        with self._lock:
            self._data["restart"]["notifications"].append(
                {"text": text, "kind": kind, "at": time.time()})
            self.save()

    def pop_notifications(self) -> list[dict]:
        with self._lock:
            notes = list(self._data["restart"]["notifications"])
            self._data["restart"]["notifications"] = []
            if notes:
                self.save()
            return notes

    # ---------- apply generation ----------
    def next_apply_generation(self) -> int:
        with self._lock:
            self._data["apply_generation"] = int(
                self._data.get("apply_generation", 0)) + 1
            self.save()
            return self._data["apply_generation"]

    # ---------- catalog auto-update ----------
    def catalog_update_state(self) -> dict:
        return dict(self._data["catalog_update"])

    def set_catalog_update_state(self, **fields) -> None:
        with self._lock:
            self._data["catalog_update"].update(fields)
            self.save()
