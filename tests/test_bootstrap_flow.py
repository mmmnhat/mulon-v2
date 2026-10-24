"""Bản vá 1.0.1 — luồng BOOTSTRAP đầu-cuối (mục 16.10).

Ba chỗ từng gãy: Dossier.load không nạp BOOTSTRAP.md nên /start
lần đầu gửi tin chào cụt không câu hỏi; snapshot đóng băng không
có reload() nên file đổi trên đĩa không ai thấy; file tools bị
neo trong workspace nên agent không có đường điền IDENTITY.md /
USER.md để hoàn tất nghi lễ. Các test dưới đây khóa cả ba, cộng
đường chat tự nạp lại dossier sau lượt hoàn tất nghi lễ.
"""

from types import SimpleNamespace

from mulon.context import Dossier
from mulon.telegram_bot import TelegramSurface, \
    extract_bootstrap_questions
from mulon.tools import build_default_registry
from tests.conftest import open_memory

BOOT_MD = """# BOOTSTRAP — Nghi lễ khởi tạo (chỉ lần chạy đầu)

Khi USER.md còn dòng BOOTSTRAP_PENDING, đây là lần chạy đầu tiên.

## Cần hỏi
1. Bạn muốn gọi agent là gì? Agent xưng hô với bạn thế nào?
2. Bạn tên gì, muốn được gọi là gì? Múi giờ có đúng Asia/Ho_Chi_Minh?
3. Câu hỏi riêng để nhận diện bản test 12345?

## Sau khi hỏi xong
- Điền IDENTITY.md (tên, xưng hô, emoji chữ ký nếu user chọn).
- Ghi 1 fact khởi tạo vào ký ức.
"""


def _seed_pending_dossier(cfg) -> Dossier:
    (cfg.dossier_dir / "USER.md").write_text(
        "# USER\nBOOTSTRAP_PENDING\n", encoding="utf-8")
    (cfg.dossier_dir / "BOOTSTRAP.md").write_text(
        BOOT_MD, encoding="utf-8")
    return Dossier.load(cfg.dossier_dir)


# --------------------- Dossier: nạp + render + reload ---------------------

def test_dossier_loads_bootstrap_and_render_gates_on_pending(cfg):
    dossier = _seed_pending_dossier(cfg)
    assert "BOOTSTRAP.md" in dossier.files
    assert "Cần hỏi" in dossier.files["BOOTSTRAP.md"]
    assert dossier.bootstrap_pending() is True
    rendered = dossier.render()
    assert "gọi agent là gì" in rendered
    # Agent phải biết ghi file vào đâu để hoàn tất nghi lễ.
    assert str(cfg.dossier_dir) in rendered
    # reload thay nội dung TẠI CHỖ: cùng object dict, ai giữ tham
    # chiếu cũng thấy bản mới.
    files_ref = dossier.files
    (cfg.dossier_dir / "USER.md").write_text(
        "# USER\nĐã khởi tạo.\n", encoding="utf-8")
    dossier.reload()
    assert dossier.files is files_ref
    assert dossier.bootstrap_pending() is False
    rendered = dossier.render()
    assert "gọi agent là gì" not in rendered
    assert "BOOTSTRAP" not in rendered


def test_extract_bootstrap_questions_only_takes_question_section():
    questions = extract_bootstrap_questions(BOOT_MD)
    assert "gọi agent là gì" in questions
    assert "Câu hỏi riêng để nhận diện bản test 12345?" in questions
    # Chỉ thị nội bộ không được lọt ra tin nhắn cho user.
    assert "Sau khi hỏi xong" not in questions
    assert "Điền IDENTITY.md" not in questions
    assert "Nghi lễ khởi tạo" not in questions
    assert extract_bootstrap_questions("") == ""
    assert extract_bootstrap_questions("# BOOTSTRAP\nkhông có mục") == ""


# --------------------- /start ---------------------

def test_start_message_first_run_asks_real_questions(cfg):
    dossier = _seed_pending_dossier(cfg)
    surface = TelegramSurface(cfg, agent=None, memory=None,
                              dossier=dossier)
    text = surface.start_message_text()
    assert "lần chạy đầu tiên" in text
    assert "gọi agent là gì" in text
    assert "Câu hỏi riêng để nhận diện bản test 12345?" in text
    assert "Sau khi hỏi xong" not in text
    assert "Điền IDENTITY.md" not in text


def test_start_message_fallback_when_section_missing(cfg):
    (cfg.dossier_dir / "USER.md").write_text(
        "# USER\nBOOTSTRAP_PENDING\n", encoding="utf-8")
    (cfg.dossier_dir / "BOOTSTRAP.md").write_text(
        "# BOOTSTRAP\n(bản rút gọn, không có mục hỏi)\n",
        encoding="utf-8")
    dossier = Dossier.load(cfg.dossier_dir)
    surface = TelegramSurface(cfg, agent=None, memory=None,
                              dossier=dossier)
    text = surface.start_message_text()
    # Trích không được -> bộ câu hỏi dự phòng trong code, đủ 5 ý.
    assert "gọi agent là gì" in text
    assert "tuyệt đối không được tự làm" in text


def test_start_message_when_not_pending(cfg):
    dossier = Dossier.load(cfg.dossier_dir)  # fixture: không pending
    surface = TelegramSurface(cfg, agent=None, memory=None,
                              dossier=dossier)
    text = surface.start_message_text()
    assert "Mình đang chạy" in text
    assert "Agent test." in text  # IDENTITY.md của fixture


def test_start_message_reloads_before_checking(cfg):
    # USER.md đổi trên đĩa SAU khi load (snapshot đã đóng băng):
    # /start phải thấy trạng thái mới nhờ reload trước khi xét.
    dossier = Dossier.load(cfg.dossier_dir)
    assert dossier.bootstrap_pending() is False
    (cfg.dossier_dir / "USER.md").write_text(
        "# USER\nBOOTSTRAP_PENDING\n", encoding="utf-8")
    (cfg.dossier_dir / "BOOTSTRAP.md").write_text(
        BOOT_MD, encoding="utf-8")
    surface = TelegramSurface(cfg, agent=None, memory=None,
                              dossier=dossier)
    text = surface.start_message_text()
    assert "gọi agent là gì" in text


# --------------------- file tools: jail workspace + dossier ---------------------

async def test_file_tools_can_write_dossier_but_not_outside(cfg):
    memory = await open_memory(cfg)
    reg = build_default_registry(cfg, memory)
    identity = cfg.dossier_dir / "IDENTITY.md"
    result = await reg.execute(
        "write_file",
        {"path": str(identity), "content": "# IDENTITY\nTên: Mulon\n"})
    assert result["ok"] is True
    assert "Mulon" in identity.read_text(encoding="utf-8")
    result = await reg.execute("read_file", {"path": str(identity)})
    assert result["ok"] and "Mulon" in result["content"]
    result = await reg.execute(
        "edit_file",
        {"path": str(identity), "old_text": "Mulon",
         "new_text": "Mulon X"})
    assert result["ok"] is True
    # Đường tương đối thoát workspace rơi đúng vào dossier: được.
    result = await reg.execute(
        "write_file", {"path": "../dossier/NOTE.md", "content": "ghi"})
    assert result["ok"] is True
    assert (cfg.dossier_dir / "NOTE.md").exists()
    result = await reg.execute(
        "list_dir", {"path": str(cfg.dossier_dir)})
    assert result["ok"] and any(
        e["name"] == "IDENTITY.md" for e in result["entries"])
    # Ngoài cả hai vùng: vẫn chặn như cũ.
    result = await reg.execute(
        "write_file", {"path": "/etc/passwd", "content": "x"})
    assert result["ok"] is False
    result = await reg.execute("read_file", {"path": "../secret.txt"})
    assert result["ok"] is False
    result = await reg.execute(
        "write_file", {"path": str(cfg.db_path), "content": "x"})
    assert result["ok"] is False
    # run_command giữ nguyên: cwd ở dossier vẫn bị chặn.
    result = await reg.execute(
        "run_command",
        {"command": "pwd", "cwd": str(cfg.dossier_dir)})
    assert result["ok"] is False
    await memory.close()


# --------------------- luồng hoàn tất nghi lễ ---------------------

async def test_bootstrap_completion_flow_via_file_tool(cfg):
    dossier = _seed_pending_dossier(cfg)
    assert dossier.bootstrap_pending() is True
    assert "gọi agent là gì" in dossier.render()
    memory = await open_memory(cfg)
    reg = build_default_registry(cfg, memory)
    # Agent hoàn tất nghi lễ đúng như BOOTSTRAP.md chỉ dẫn: gỡ
    # dòng BOOTSTRAP_PENDING khỏi USER.md bằng file tool.
    result = await reg.execute(
        "edit_file",
        {"path": str(cfg.dossier_dir / "USER.md"),
         "old_text": "BOOTSTRAP_PENDING\n", "new_text": ""})
    assert result["ok"] is True
    dossier.reload()
    assert dossier.bootstrap_pending() is False
    assert "gọi agent là gì" not in dossier.render()
    await memory.close()


class _FakeAnchor:
    """Neo tin nhắn giả cho _on_batch: react + answer -> placeholder."""

    def __init__(self):
        self.answers = []

    async def react(self, reactions):
        pass

    async def answer(self, text, **kw):
        self.answers.append(text)
        placeholder = SimpleNamespace(text=None)

        async def edit_text(t, **kw2):
            placeholder.text = t

        placeholder.edit_text = edit_text
        return placeholder


class _BootstrapFinishingAgent:
    """Agent giả: trong lượt xử lý, gỡ BOOTSTRAP_PENDING trên đĩa —
    đúng việc agent thật làm bằng file tools khi user trả lời."""

    def __init__(self, dossier_dir):
        self.dossier_dir = dossier_dir

    async def handle(self, key, text, on_delta=None, on_event=None):
        user_md = self.dossier_dir / "USER.md"
        user_md.write_text(
            user_md.read_text(encoding="utf-8").replace(
                "BOOTSTRAP_PENDING\n", ""),
            encoding="utf-8")
        return SimpleNamespace(text="Đã dựng hồ sơ xong.")


async def test_chat_turn_reloads_dossier_when_bootstrap_finishes(cfg):
    dossier = _seed_pending_dossier(cfg)
    assert dossier.bootstrap_pending() is True
    surface = TelegramSurface(
        cfg, agent=_BootstrapFinishingAgent(cfg.dossier_dir),
        memory=None, dossier=dossier)
    key = "agent:main:telegram:dm:42:topic:0"
    anchor = _FakeAnchor()
    surface._sessions_meta[key] = anchor
    await surface._on_batch(
        key, "tên tui là Nhật, gọi agent là Mulon", ["một tin"])
    # Không ai gọi reload tay — đường chat tự nạp lại cuối lượt,
    # và bot vẫn trả lời bình thường.
    assert dossier.bootstrap_pending() is False
    assert anchor.answers
