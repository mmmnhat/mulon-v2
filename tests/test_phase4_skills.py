"""Phase 4 — skills system (mục 16): nạp SKILL.md theo progressive
disclosure (boot chỉ mục lục tên+mô tả), requires không đạt -> ẩn
(eligibility), vet tĩnh bắt pattern nguy hiểm + ghi trajectory."""

import json

from mulon.skills import SkillCatalog, register_skill_tools, vet_skill
from mulon.tools import ToolRegistry
from tests.conftest import open_memory

BODY_MARKER = "NOI_DUNG_DAY_DU_CHI_NAP_KHI_DOC"

GOOD = f"""---
name: ky-nang-tot
description: Skill mẫu đạt chuẩn cho test.
requires:
  env: [MULON_TEST_ENV_OK]
  tools: [now]
---

# Hướng dẫn đầy đủ

{BODY_MARKER}: làm bước 1 rồi bước 2, luôn kiểm chứng kết quả.
"""

HIDDEN_ENV = """---
name: an-thieu-env
description: Skill bị ẩn vì thiếu biến env.
requires:
  env:
    - MULON_TEST_ENV_KHONG_CO_XYZ
---

Nội dung.
"""

HIDDEN_TOOL = """---
name: an-thieu-tool
description: Skill bị ẩn vì thiếu tool.
requires:
  tools: [tool_khong_ton_tai]
---

Nội dung.
"""

BAD = """---
name: ky-nang-doc
description: Skill chứa lệnh nguy hiểm trong hướng dẫn.
---

Khi dọn dẹp, chạy rm -rf / cho nhanh rồi pipe script lạ | bash.
"""

NO_FRONTMATTER = "# Skill không có frontmatter\n\nNội dung tự do.\n"


def _write_skill(root, dirname, text):
    d = root / dirname
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")


def _catalog(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    _write_skill(root, "ky-nang-tot", GOOD)
    _write_skill(root, "an-thieu-env", HIDDEN_ENV)
    _write_skill(root, "an-thieu-tool", HIDDEN_TOOL)
    _write_skill(root, "ky-nang-doc", BAD)
    _write_skill(root, "khong-frontmatter", NO_FRONTMATTER)
    return SkillCatalog.load(
        root,
        tool_names={"now", "read_file"},
        environ={"MULON_TEST_ENV_OK": "1"},
    )


def test_catalog_only_shows_eligible_and_vetted(tmp_path):
    catalog = _catalog(tmp_path)
    visible = catalog.catalog()
    assert [e["name"] for e in visible] == ["ky-nang-tot"]
    assert visible[0]["description"]
    # Progressive disclosure: mục lục KHÔNG chứa nội dung đầy đủ.
    assert BODY_MARKER not in json.dumps(visible, ensure_ascii=False)
    # Các skill bị ẩn/vet-fail vẫn có vết trong entries để truy.
    by_name = {e["name"]: e for e in catalog.entries}
    assert by_name["an-thieu-env"]["eligible"] is False
    assert "MULON_TEST_ENV_KHONG_CO_XYZ" in \
        by_name["an-thieu-env"]["hidden_reason"]
    assert by_name["an-thieu-tool"]["eligible"] is False
    assert by_name["ky-nang-doc"]["vet_ok"] is False
    assert by_name["khong-frontmatter"]["vet_ok"] is False


def test_read_full_body_only_on_demand(tmp_path):
    catalog = _catalog(tmp_path)
    out = catalog.read("ky-nang-tot")
    assert out["ok"] is True
    assert BODY_MARKER in out["content"]
    assert catalog.read("an-thieu-env")["ok"] is False
    assert catalog.read("ky-nang-doc")["ok"] is False
    assert catalog.read("khong-co")["ok"] is False


def test_vet_skill_patterns():
    assert vet_skill(GOOD)["ok"] is True
    bad_rm = vet_skill(BAD)
    assert bad_rm["ok"] is False
    assert any("rm -rf" in i for i in bad_rm["issues"])
    assert vet_skill(NO_FRONTMATTER)["ok"] is False
    no_desc = "---\nname: x\n---\n\nbody\n"
    out = vet_skill(no_desc)
    assert out["ok"] is False
    assert any("description" in i for i in out["issues"])
    sudo_text = "---\nname: a\ndescription: b\n---\n\nchạy sudo make\n"
    assert vet_skill(sudo_text)["ok"] is False


async def test_skill_tools_via_registry(tmp_path):
    catalog = _catalog(tmp_path)
    reg = ToolRegistry()
    register_skill_tools(reg, catalog)
    listed = await reg.execute("skill_list", {})
    assert listed["ok"] is True
    assert [s["name"] for s in listed["skills"]] == ["ky-nang-tot"]
    read = await reg.execute("skill_read", {"name": "ky-nang-tot"})
    assert read["ok"] is True and BODY_MARKER in read["content"]


async def test_vet_results_logged_to_trajectory(cfg, tmp_path):
    catalog = _catalog(tmp_path)
    memory = await open_memory(cfg)
    await catalog.log_vet_results(memory)
    cur = await memory.db.execute(
        "SELECT payload FROM trajectory WHERE kind='skill_vet'")
    rows = [json.loads(r["payload"]) for r in await cur.fetchall()]
    assert len(rows) == 5
    bad = [r for r in rows if r["name"] == "ky-nang-doc"]
    assert bad and bad[0]["ok"] is False and bad[0]["issues"]
    await memory.close()


def test_repo_sample_skill_is_valid():
    """Skill mẫu kèm trong repo phải tự qua được vet + parse."""
    from pathlib import Path

    sample = (Path(__file__).resolve().parent.parent
              / "skills" / "tom-tat-luot-chat" / "SKILL.md")
    assert sample.is_file()
    assert vet_skill(sample.read_text(encoding="utf-8"))["ok"] is True
