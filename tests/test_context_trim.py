"""Trim kết quả tool: dưới trần giữ nguyên, quá trần thì cắt + offload
ra file artifact kèm tham chiếu, không bao giờ nuốt mất dữ liệu."""

from pathlib import Path
import time
import os

from mulon.context import Dossier, ContextEngine, trim_tool_result, clean_old_tool_results
from tests.conftest import open_memory


def test_small_result_untouched(cfg):
    result = trim_tool_result("ngắn gọn", 8000, cfg.artifact_dir)
    assert result.truncated is False
    assert result.text == "ngắn gọn"
    assert result.artifact_path is None


def test_large_result_offloaded(cfg):
    big = "A" * 5000 + "GIỮA" + "B" * 15000
    result = trim_tool_result(big, 8000, cfg.artifact_dir, tool_name="read_file")
    assert result.truncated is True
    assert len(result.text) <= 8000 + 400  # trần + ghi chú tham chiếu
    assert result.artifact_path is not None
    artifact = Path(result.artifact_path)
    assert artifact.exists()
    assert artifact.read_text(encoding="utf-8") == big
    assert "đã cắt" in result.text


async def test_context_build_respects_budget(cfg):
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    engine = ContextEngine(cfg, dossier, memory, gateway=None)
    await memory.get_or_create_session("s1")
    await memory.append_message("s1", "user", "chào buổi sáng")
    built = await engine.build("s1", "chào buổi sáng")
    assert built.messages[0]["role"] == "system"
    assert "Persona test" in built.messages[0]["content"]
    assert built.total_tokens <= cfg.context_window_tokens
    assert built.recall_hits == []  # chưa có ký ức nào để recall
    await memory.close()


def test_clean_old_tool_results_ttl(cfg):
    """Test cơ chế TTL dọn file artifact tool-results cũ hơn 7 ngày."""
    base = Path(cfg.artifact_dir) / "tool-results"
    base.mkdir(parents=True, exist_ok=True)
    
    old_file = base / "old_result.txt"
    old_file.write_text("cũ hơn 7 ngày", encoding="utf-8")
    # Giả lập mtime cách đây 8 ngày
    eight_days_ago = time.time() - (8 * 86400)
    os.utime(old_file, (eight_days_ago, eight_days_ago))
    
    fresh_file = base / "fresh_result.txt"
    fresh_file.write_text("mới tạo hôm nay", encoding="utf-8")
    
    deleted = clean_old_tool_results(cfg.artifact_dir, max_age_days=7)
    assert deleted == 1
    assert not old_file.exists()
    assert fresh_file.exists()

