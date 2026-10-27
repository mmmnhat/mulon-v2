"""T-25 (LUỒNG MUSE, ký: Muse): nhãn giờ Feed trong Sắp tới
phải suy từ cron thật, không ghi cứng.

Bối cảnh: mục Feed chủ động trong `/api/upcoming` từng ghi cứng
nhãn "08:00 & 17:00" và fallback cron "0 8,17 * * *" trong khi
cron mặc định thật của feed_auto là "0 8,20 * * *" — nhãn lệch
3 tiếng so với lịch chạy thật. Test này chốt 3 việc:
1. `cron_times_label` suy đúng nhãn giờ cố định từ biểu thức cron.
2. Mục feed_auto trong `_upcoming_state` dùng đúng cron hiệu lực
   mà `FeedAutoRunner.get_state()` trả về.
3. Khi `get_state()` thiếu cron, fallback là `DEFAULT_CRON` của
   `mulon.feed_auto` — một nguồn sự thật duy nhất, không còn
   chuỗi "0 8,17" trôi nổi.
"""
import pytest

from mulon.feed_auto import DEFAULT_CRON, cron_times_label
from mulon.memory import Memory
from tests.test_v17_activity_upcoming import _create_server


def test_cron_times_label_mau_co_dinh():
    assert cron_times_label("0 8,20 * * *") == "08:00 & 20:00"
    assert cron_times_label(DEFAULT_CRON) == "08:00 & 20:00"
    assert cron_times_label("30 6 * * *") == "06:30"
    # Suy theo đúng cron được đưa vào, không áp đặt giờ nào khác
    assert cron_times_label("0 8,17 * * *") == "08:00 & 17:00"
    assert cron_times_label("15 9,12,18 * * *") == "09:15 & 12:15 & 18:15"


def test_cron_times_label_mau_khong_co_dinh_tra_rong():
    assert cron_times_label("*/30 * * * *") == ""
    assert cron_times_label("0 * * * *") == ""
    assert cron_times_label("0 8-20 * * *") == ""
    assert cron_times_label("0 8 * * 1") == ""
    assert cron_times_label("0 8 1 * *") == ""
    assert cron_times_label("0 25 * * *") == ""
    assert cron_times_label("0 8,20 * *") == ""
    assert cron_times_label("") == ""
    assert cron_times_label(None) == ""


class _FakeFeedAuto:
    """Giả FeedAutoRunner — _upcoming_state chỉ cần get_state()."""

    def __init__(self, state):
        self._state = state

    async def get_state(self):
        return self._state


@pytest.mark.asyncio
async def test_upcoming_feed_label_suy_tu_cron_that(tmp_path, cfg):
    mem = await Memory.open(tmp_path / "t25_cron_that.db")
    server = await _create_server(cfg, mem)
    try:
        server.feed_auto = _FakeFeedAuto(
            {"enabled": True, "cron": "30 6,21 * * *",
             "next_run_at": ""})
        upcoming = await server._upcoming_state()
        feed = [u for u in upcoming if u["kind"] == "feed_auto"]
        assert len(feed) == 1
        assert feed[0]["cron"] == "30 6,21 * * *"
        assert "06:30" in feed[0]["time_label"]
        assert "21:30" in feed[0]["time_label"]
        assert "17:00" not in feed[0]["time_label"]
    finally:
        await server.stop()
        await mem.close()


@pytest.mark.asyncio
async def test_upcoming_feed_fallback_la_default_cron(tmp_path, cfg):
    mem = await Memory.open(tmp_path / "t25_fallback.db")
    server = await _create_server(cfg, mem)
    try:
        # get_state() không có khoá "cron" — fallback phải là
        # DEFAULT_CRON của feed_auto, không phải chuỗi ghi cứng cũ
        server.feed_auto = _FakeFeedAuto(
            {"enabled": True, "next_run_at": ""})
        upcoming = await server._upcoming_state()
        feed = [u for u in upcoming if u["kind"] == "feed_auto"]
        assert len(feed) == 1
        assert feed[0]["cron"] == DEFAULT_CRON
        assert "20:00" in feed[0]["time_label"]
        assert "17:00" not in feed[0]["time_label"]
    finally:
        await server.stop()
        await mem.close()
