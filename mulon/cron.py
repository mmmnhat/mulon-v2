"""Cron 5 trường tối thiểu, tự viết (thiết kế mục 7).

Hỗ trợ: `*`, `a`, `a-b`, `*/n`, `a-b/n`, danh sách `a,b,c` cho từng
trường minute/hour/dom/month/dow. dow: 0 và 7 đều là Chủ nhật
(chuẩn cron). Ngữ nghĩa dom+dow khi CẢ HAI cùng bị giới hạn: khớp
một trong hai (chuẩn Vixie cron). Tính theo múi giờ tường minh bằng
zoneinfo — không phụ thuộc giờ máy.

Chỉ là hàm thuần: không I/O, không state — test trực tiếp được.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class CronSpec:
    minutes: frozenset
    hours: frozenset
    doms: frozenset
    months: frozenset
    dows: frozenset  # 0=Chủ nhật .. 6=Thứ bảy
    dom_restricted: bool
    dow_restricted: bool


def _parse_field(field: str, lo: int, hi: int, name: str) -> frozenset:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"cron: trường {name} rỗng")
        base, step = part, 1
        if "/" in part:
            base, step_text = part.split("/", 1)
            try:
                step = int(step_text)
            except ValueError:
                raise ValueError(f"cron: step không hợp lệ ở {name}: {part}")
            if step < 1:
                raise ValueError(f"cron: step phải >= 1 ở {name}")
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            a_text, b_text = base.split("-", 1)
            try:
                start, end = int(a_text), int(b_text)
            except ValueError:
                raise ValueError(f"cron: khoảng không hợp lệ ở {name}: {part}")
        else:
            try:
                start = end = int(base)
            except ValueError:
                raise ValueError(f"cron: giá trị không hợp lệ ở {name}: {part}")
        if start < lo or end > hi or start > end:
            raise ValueError(
                f"cron: giá trị ngoài [{lo},{hi}] ở {name}: {part}"
            )
        values.update(range(start, end + 1, step))
    return frozenset(values)


def parse_cron(expr: str) -> CronSpec:
    fields = (expr or "").split()
    if len(fields) != 5:
        raise ValueError(
            f"cron cần đúng 5 trường (phút giờ ngày tháng thứ): {expr!r}"
        )
    minute, hour, dom, month, dow = fields
    dows_raw = _parse_field(dow, 0, 7, "dow")
    dows = frozenset(0 if d == 7 else d for d in dows_raw)
    return CronSpec(
        minutes=_parse_field(minute, 0, 59, "minute"),
        hours=_parse_field(hour, 0, 23, "hour"),
        doms=_parse_field(dom, 1, 31, "dom"),
        months=_parse_field(month, 1, 12, "month"),
        dows=dows,
        dom_restricted=dom != "*",
        dow_restricted=dow != "*",
    )


def _cron_dow(d) -> int:
    """date -> số thứ kiểu cron (0=Chủ nhật). Python weekday: Thứ 2=0."""
    return (d.weekday() + 1) % 7


def next_run(expr: str, after: datetime, tz_name: str) -> datetime:
    """Lần chạy kế tiếp SAU `after`, trả datetime aware theo tz_name."""
    if after.tzinfo is None:
        raise ValueError("after phải là datetime có múi giờ")
    tz = ZoneInfo(tz_name)
    spec = parse_cron(expr)
    local_after = after.astimezone(tz)
    earliest = local_after.replace(second=0, microsecond=0) + timedelta(
        minutes=1
    )
    start_day = earliest.date()
    hours = sorted(spec.hours)
    minutes = sorted(spec.minutes)
    for offset in range(0, 371):
        day = start_day + timedelta(days=offset)
        if day.month not in spec.months:
            continue
        dom_match = day.day in spec.doms
        dow_match = _cron_dow(day) in spec.dows
        if spec.dom_restricted and spec.dow_restricted:
            day_ok = dom_match or dow_match
        elif spec.dom_restricted:
            day_ok = dom_match
        elif spec.dow_restricted:
            day_ok = dow_match
        else:
            day_ok = True
        if not day_ok:
            continue
        for h in hours:
            for m in minutes:
                cand = datetime(day.year, day.month, day.day, h, m,
                                tzinfo=tz)
                if cand >= earliest:
                    return cand
    raise ValueError(
        f"cron {expr!r} không có lần chạy nào trong 370 ngày tới"
    )


def next_run_iso(expr: str, after: datetime, tz_name: str) -> str:
    """next_run nhưng trả ISO UTC — định dạng lưu trong DB."""
    from datetime import timezone

    return next_run(expr, after, tz_name).astimezone(timezone.utc).isoformat(
        timespec="seconds"
    )
