"""Feed chủ động — runner lịch xác định (Mulon 1.4.0).

Theo spec feed-chu-dong-1.4 + quyết định owner 0.2b:
- Feed LUÔN TỰ ĐỘNG: nâng cấp xong, scheduler có ngay dòng
  lịch `feed-auto`; tới nhịp là tự chạy, owner không phải
  bật gì. Không công tắc tổng, không lệnh /feed_auto.
- Lượt chạy là JOB HỆ THỐNG xác định: KHÔNG qua agent loop,
  KHÔNG tool, KHÔNG approval. SchedulerService dispatch qua
  internal handler (planning.py) — tách hẳn khỏi đường
  schedule do agent tạo (cô lập tick, spec mục 4.3).
- Kỷ luật lượt: trần bài/ngày, giờ yên lặng (dời lượt, không
  đăng), trần token model rẻ/ngày, chạy bù tối đa 1 lượt,
  lỗi 3 lượt liên tiếp -> tự tạm dừng + báo owner đúng 1 tin
  vào topic Lịch sử & Hệ thống.
- Thiếu tư liệu / trùng đề tài / bị cổng chặn -> BỎ LƯỢT,
  ghi trajectory `feed_run` với trạng thái rõ ràng; không
  đăng bài rỗng, không bịa, không tính là lỗi hệ thống.

Hàm này không import agent/policy/broker — kiểm bằng test
cấu trúc (test_v14_feed_auto.test_feed_auto_is_structurally_
isolated).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from .cron import next_run_iso, parse_cron
from .planning import internal_payload
from .proactivity import in_active_hours, parse_active_hours

logger = logging.getLogger("mulon.feed_auto")

SCHEDULE_ID = "feed-auto"
SESSION_KEY = "agent:main:system:feed"
INTERNAL_PAYLOAD = internal_payload("feed_auto")
DEFAULT_CRON = "0 8,20 * * *"
DEFAULT_QUIET = "23:00-07:00"
DEFAULT_MAX_POSTS = 3
DEFAULT_TOKEN_BUDGET = 60000
FAIL_LIMIT = 3

Sender = Callable[[int, str, Optional[int]], Awaitable[int]]

_QUIET_RE = re.compile(
    r"^([01]?\d|2[0-3]):[0-5]\d-([01]?\d|2[0-3]):[0-5]\d$")


def valid_quiet_hours(spec: object) -> bool:
    """Kiểm NGHIÊM chuỗi giờ yên lặng 'HH:MM-HH:MM' (parse của
    proactivity tự fallback nên không dùng để validate)."""
    return bool(_QUIET_RE.match(str(spec or "").strip()))


class _BotShim:
    """Đưa sender (chat_id, text, thread_id) -> message_id vào
    đúng duck-type send_message mà FeedEngine.publish_composed
    kỳ vọng."""

    def __init__(self, sender: Sender):
        self._sender = sender

    async def send_message(self, chat_id: int, text: str,
                           message_thread_id: Optional[int] = None):
        mid = await self._sender(chat_id, text, message_thread_id)

        class _Msg:
            pass

        m = _Msg()
        m.message_id = mid
        return m


class FeedAutoRunner:
    """Chạy lượt Feed theo lịch + giữ cài đặt Feed (feed_settings)."""

    def __init__(self, cfg, memory, engine, topics=None,
                 connectors=None):
        self.cfg = cfg
        self.memory = memory
        self.engine = engine
        self.topics = topics
        self.connectors = connectors
        self._sender: Optional[Sender] = None

    # ---------- hạ tầng gửi ----------
    def bind_sender(self, sender: Sender) -> None:
        """TelegramBot gọi sau khi bot sẵn sàng (giống pattern
        bind_notifier của MCP marketplace 1.3)."""
        self._sender = sender

    # ---------- cài đặt hiệu lực (DB thắng env, env chỉ seed) ----------
    async def settings(self) -> dict:
        async def get(key: str, default: str) -> str:
            v = await self.memory.get_feed_setting(key, "")
            return v if v else default

        cron = await get("cron", getattr(
            self.cfg, "feed_auto_cron", DEFAULT_CRON))
        try:
            parse_cron(cron)
        except ValueError:
            cron = DEFAULT_CRON
        quiet = await get("quiet_hours", getattr(
            self.cfg, "feed_quiet_hours", DEFAULT_QUIET))
        if not valid_quiet_hours(quiet):
            quiet = DEFAULT_QUIET

        def _int(raw: str, default: int) -> int:
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                return default

        max_posts = _int(await get("max_posts_per_day", ""), 0) \
            or int(getattr(self.cfg, "feed_max_posts_per_day",
                           DEFAULT_MAX_POSTS))
        budget = _int(await get("daily_token_budget", ""), 0) \
            or int(getattr(self.cfg, "feed_daily_token_budget",
                           DEFAULT_TOKEN_BUDGET))
        denylist_raw = await get("denylist", "[]")
        try:
            denylist = [str(d) for d in json.loads(denylist_raw)]
        except Exception:
            denylist = []
        return {
            "cron": cron,
            "quiet_hours": quiet,
            "max_posts_per_day": max_posts,
            "daily_token_budget": budget,
            "paused_until": await get("paused_until", ""),
            "auto_paused_reason": await get(
                "auto_paused_reason", ""),
            "denylist": denylist,
        }

    async def apply_settings(self, changes: dict) -> dict:
        """Ghi cài đặt mới (Mini App gọi) + dựng lại lịch. Trả
        cài đặt hiệu lực sau khi áp."""
        for key in ("cron", "quiet_hours"):
            if key in changes and changes[key]:
                await self.memory.set_feed_setting(
                    key, str(changes[key]))
        for key in ("max_posts_per_day", "daily_token_budget"):
            if key in changes and changes[key] is not None:
                await self.memory.set_feed_setting(
                    key, str(int(changes[key])))
        if "denylist" in changes:
            await self.memory.set_feed_setting(
                "denylist", json.dumps(
                    [str(d).strip().lower()
                     for d in changes["denylist"] if str(d).strip()]))
        await self.ensure_schedule()
        return await self.settings()

    # ---------- lịch trong bảng schedules ----------
    async def ensure_schedule(self, now: Optional[datetime] = None
                              ) -> dict:
        """Tạo/cập nhật dòng lịch feed-auto từ cài đặt hiệu lực.
        Idempotent — gọi mỗi lần boot: đây là cơ chế 'luôn bật'
        của 0.2b (không có bước kích hoạt nào khác)."""
        now = now or datetime.now(timezone.utc)
        st = await self.settings()
        row = await self.memory.get_schedule(SCHEDULE_ID)
        nxt = next_run_iso(st["cron"], now,
                           self.cfg.default_timezone)
        if row is None:
            await self.memory.create_schedule(
                SCHEDULE_ID, st["cron"], self.cfg.default_timezone,
                INTERNAL_PAYLOAD, "", nxt)
        elif row.get("cron") != st["cron"] \
                or row.get("payload") != INTERNAL_PAYLOAD:
            await self.memory.update_schedule(
                SCHEDULE_ID, st["cron"],
                self.cfg.default_timezone, nxt)
        return await self.memory.get_schedule(SCHEDULE_ID) or {}

    # ---------- đích đăng ----------
    async def _topic_map(self, chat_id: int) -> dict:
        if self.topics is None:
            return {}
        try:
            return await self.topics.get_map(self.memory, chat_id) \
                or {}
        except TypeError:
            return await self.topics.get_map(chat_id) or {}

    def _thread_of(self, mapping: dict, key: str) -> Optional[int]:
        if self.topics is not None and hasattr(
                self.topics, "topic_for"):
            return self.topics.topic_for(mapping, key)
        tid = (mapping or {}).get(key)
        return tid if tid else None

    async def resolve_target(self) -> Optional[tuple[int, Optional[int]]]:
        """(chat_id, thread_id topic Feed) của group làm việc.
        Ưu tiên kv đã lưu khi /setup_topics; fallback: quét map
        topic đã lưu tìm group có topic feed."""
        raw = await self.memory.kv_get("feed:group_chat_id") or ""
        if raw:
            try:
                chat_id = int(raw)
            except ValueError:
                chat_id = 0
            if chat_id:
                m = await self._topic_map(chat_id)
                return chat_id, self._thread_of(m, "feed")
        if self.topics is not None:
            for key in await self.memory.kv_keys("topics:"):
                try:
                    chat_id = int(key.split(":", 1)[1])
                except (IndexError, ValueError):
                    continue
                m = await self._topic_map(chat_id)
                if m and "feed" in m:
                    await self.memory.kv_set(
                        "feed:group_chat_id", str(chat_id))
                    return chat_id, self._thread_of(m, "feed")
        return None

    async def _history_thread(self, chat_id: int) -> Optional[int]:
        m = await self._topic_map(chat_id)
        return self._thread_of(m, "history")

    # ---------- trợ giúp thời gian ----------
    def _tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.cfg.default_timezone)
        except Exception:
            return ZoneInfo("UTC")

    def _day_bounds(self, now: datetime) -> tuple[str, str]:
        tz = self._tz()
        local = now.astimezone(tz)
        start = datetime.combine(local.date(), time.min, tz)
        end = start + timedelta(days=1)
        return (start.astimezone(timezone.utc).isoformat(
                    timespec="seconds"),
                end.astimezone(timezone.utc).isoformat(
                    timespec="seconds"))

    def _in_quiet(self, now: datetime, quiet: str) -> bool:
        """now có nằm trong khung yên lặng không. Chuỗi quiet
        TỰ nó là cửa sổ yên lặng (vd '23:00-07:00', hỗ trợ qua
        đêm) — tái dùng đúng ngữ nghĩa cửa sổ của proactivity.
        Cửa sổ rỗng (start == end) = không yên lặng."""
        start, end = parse_active_hours(quiet)
        if start == end:
            return False
        return in_active_hours(now.astimezone(self._tz()), quiet)

    def _quiet_end(self, now: datetime, quiet: str) -> datetime:
        """Mốc hết yên lặng (UTC) — dùng để dời next_run tới
        đúng cuối cửa sổ yên lặng theo giờ địa phương."""
        _, end = parse_active_hours(quiet)
        tz = self._tz()
        local = now.astimezone(tz)
        cand = datetime.combine(local.date(), end, tz)
        if cand <= local:
            cand += timedelta(days=1)
        return cand.astimezone(timezone.utc)

    # ---------- ghi vết + đếm lỗi ----------
    async def _log_run(self, status: str, **extra) -> None:
        payload = {"status": status}
        payload.update(extra)
        await self.memory.log_trajectory(
            SESSION_KEY, "feed_run", payload)

    async def _consecutive_failures(self) -> int:
        cur = await self.memory.db.execute(
            "SELECT payload FROM trajectory WHERE kind='feed_run' "
            "ORDER BY id DESC LIMIT 50")
        rows = await cur.fetchall()
        n = 0
        for r in rows:
            try:
                payload = json.loads(r["payload"] or "{}")
            except Exception:
                continue
            if payload.get("status") == "failed":
                n += 1
            else:
                break
        return n

    async def _check_auto_pause(self, st: dict) -> None:
        """3 lượt lỗi liên tiếp -> tự tạm dừng + báo owner ĐÚNG
        1 tin (cờ auto_paused_reason là khóa chống báo lại)."""
        if st["auto_paused_reason"]:
            return
        fails = await self._consecutive_failures()
        if fails < FAIL_LIMIT:
            return
        reason = (f"Tự tạm dừng: {fails} lượt Feed lỗi liên "
                  f"tiếp. Kiểm tra rồi bấm Chạy lại trong Mini "
                  f"App (Cài đặt → Feed chủ động).")
        await self.memory.set_feed_setting(
            "auto_paused_reason", reason)
        st["auto_paused_reason"] = reason
        await self._log_run("auto_paused", failures=fails)
        await self._notify_owner(
            "⏸ Feed chủ động đã tự tạm dừng.\n" + reason)

    async def _notify_owner(self, text: str) -> None:
        if self._sender is None:
            return
        target = await self.resolve_target()
        try:
            if target is not None:
                chat_id, _ = target
                thread = await self._history_thread(chat_id)
                await self._sender(chat_id, text, thread)
            elif self.cfg.allowed_user_id:
                await self._sender(self.cfg.allowed_user_id,
                                   text, None)
        except Exception as exc:
            logger.warning("báo owner lỗi: %s", exc)

    async def resume(self) -> dict:
        """Chạy lại sau tự tạm dừng (nút trong Mini App — thay
        cho lệnh /feed_auto resume đã bị 0.2b huỷ)."""
        await self.memory.set_feed_setting("auto_paused_reason", "")
        await self.memory.set_feed_setting("paused_until", "")
        await self._log_run("resumed")
        return await self.settings()

    # ---------- 1 lượt chạy ----------
    async def run_once(self, now: Optional[datetime] = None,
                       force: bool = False,
                       sender: Optional[Sender] = None) -> dict:
        """Một lượt Feed. force=True (nút 'Chạy ngay' trong Mini
        App) bỏ qua cổng giờ yên lặng/trần ngày/trần token và
        ghi origin='manual' cho trung thực về nguồn gốc bài."""
        now = now or datetime.now(timezone.utc)
        sender = sender or self._sender
        st = await self.settings()
        # Cổng tạm dừng (tự tạm dừng vì lỗi / tạm dừng thủ công).
        if st["auto_paused_reason"]:
            await self._log_run("paused",
                                reason=st["auto_paused_reason"])
            return {"ok": False, "status": "paused",
                    "reason": st["auto_paused_reason"]}
        if st["paused_until"]:
            try:
                until = datetime.fromisoformat(st["paused_until"])
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                if now < until:
                    await self._log_run("paused",
                                        until=st["paused_until"])
                    return {"ok": False, "status": "paused",
                            "until": st["paused_until"]}
            except ValueError:
                pass
        # Cổng giờ yên lặng: dời lượt, không bỏ hẳn.
        if not force and self._in_quiet(now, st["quiet_hours"]):
            wake = self._quiet_end(now, st["quiet_hours"])
            await self.memory.set_schedule_next_run(
                SCHEDULE_ID, wake.isoformat(timespec="seconds"))
            await self._log_run("deferred_quiet",
                                wake=wake.isoformat(
                                    timespec="seconds"))
            return {"ok": False, "status": "deferred_quiet",
                    "wake": wake.isoformat(timespec="seconds")}
        day_start, day_end = self._day_bounds(now)
        if not force:
            # Trần token model rẻ/ngày (đo qua trajectory llm_call).
            used = await self.memory.sum_llm_tokens(
                "feed", day_start)
            if st["daily_token_budget"] \
                    and used >= st["daily_token_budget"]:
                await self._log_run("skipped_token_budget",
                                    used=used,
                                    budget=st["daily_token_budget"])
                return {"ok": False,
                        "status": "skipped_token_budget",
                        "used": used}
            # Trần bài tự động/ngày theo giờ địa phương.
            posted = await self.memory.count_feed_posts(
                "auto", day_start, day_end)
            if posted >= st["max_posts_per_day"]:
                await self._log_run("skipped_daily_cap",
                                    posted=posted,
                                    cap=st["max_posts_per_day"])
                return {"ok": False, "status": "skipped_daily_cap",
                        "posted": posted}
        target = await self.resolve_target()
        if target is None or sender is None:
            await self._log_run("no_target")
            return {"ok": False, "status": "no_target"}
        chat_id, thread_id = target
        try:
            await self.engine.update_taste()
            material = await self.engine.collect_material()
            external: list[dict] = []
            stats: dict = {}
            if self.engine.collect_external:
                got = await self.engine.collect_external_material(
                    material)
                external = got["items"]
                stats = got["stats"]
            has_internal = any(material.get(k) for k in
                               ("goals", "tracked", "lessons",
                                "facts"))
            if not has_internal and not external:
                await self._log_run("material_empty", **stats)
                return {"ok": False, "status": "material_empty"}
            recent = await self.memory.list_recent_feed_posts(
                limit=10)
            composed = await self.engine.compose(
                material, external, recent, purpose="feed_auto")
        except Exception as exc:
            await self._log_run("failed", stage="collect/writer",
                                error=str(exc)[:300])
            await self._check_auto_pause(st)
            return {"ok": False, "status": "failed",
                    "error": str(exc)[:300]}
        if not composed.get("ok"):
            reason = composed.get("reason", "")
            if reason == "duplicate_topic":
                await self._log_run("duplicate_topic", **stats)
                return {"ok": False, "status": "duplicate_topic"}
            await self._log_run("failed", stage="validate",
                                reason=reason, **stats)
            await self._check_auto_pause(st)
            return {"ok": False, "status": "failed",
                    "reason": reason}
        try:
            result = await self.engine.publish_composed(
                _BotShim(sender), chat_id, thread_id, composed,
                origin="manual" if force else "auto")
        except Exception as exc:
            await self._log_run("failed", stage="send",
                                error=str(exc)[:300], **stats)
            await self._check_auto_pause(st)
            return {"ok": False, "status": "failed",
                    "error": str(exc)[:300]}
        await self._log_run("posted", post_id=result["post_id"],
                            topic=result.get("topic", ""), **stats)
        return {"ok": True, "status": "posted", **result}

    # ---------- trạng thái cho Mini App / dry-run ----------
    async def get_state(self, now: Optional[datetime] = None) -> dict:
        now = now or datetime.now(timezone.utc)
        st = await self.settings()
        row = await self.memory.get_schedule(SCHEDULE_ID)
        day_start, day_end = self._day_bounds(now)
        sources = []
        for s in self.engine.read_sources():
            cache = await self.memory.get_feed_material_cache(
                s["url"])
            sources.append({**s, "last_status":
                            (cache or {}).get("fetched_at", "")})
        return {
            "cron": st["cron"],
            "next_run_at": (row or {}).get("next_run_at", ""),
            "quiet_hours": st["quiet_hours"],
            "max_posts_per_day": st["max_posts_per_day"],
            "daily_token_budget": st["daily_token_budget"],
            "posts_today": await self.memory.count_feed_posts(
                "auto", day_start, day_end),
            "tokens_today": await self.memory.sum_llm_tokens(
                "feed", day_start),
            "paused_until": st["paused_until"],
            "auto_paused_reason": st["auto_paused_reason"],
            "denylist": st["denylist"],
            "sources": sources,
        }
