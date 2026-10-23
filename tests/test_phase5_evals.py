"""Phase 5 — eval vàng: nạp case, runner stub chấm đúng tốt/xấu,
nạp case từ correction (cases.jsonl), cổng exit code của CLI."""

import json

from mulon import evals as evals_mod
from mulon.config import PROJECT_ROOT

GOOD_RECALL = {
    "id": "mini-recall",
    "family": "tri_nho",
    "input": "Proxy local của tui cổng mấy?",
    "setup": {"facts": [{"subject": "proxy",
                         "fact": "User dùng proxy local ở cổng 8317"}]},
    "checks": {"contains_all": ["8317"], "fact_recalled": "8317"},
}
GOOD_TOOL = {
    "id": "mini-tool",
    "family": "tool",
    "input": "Đọc file note.txt trong workspace giúp tui",
    "setup": {"files": {"note.txt": "Mã là TOK-99"}},
    "stub": {"tool_call": {"name": "read_file",
                           "arguments": {"path": "note.txt"}}},
    "checks": {"tool_called": ["read_file"], "contains_all": ["TOK-99"]},
}
BAD_CASE = {
    "id": "mini-bad",
    "family": "tri_nho",
    "input": "Cổng proxy là gì?",
    "checks": {"contains_all": ["KHONG-BAO-GIO-XUAT-HIEN"]},
}


def test_golden_file_loads_and_is_valid():
    cases = evals_mod.load_cases(PROJECT_ROOT / "evals")
    assert len(cases) >= 28
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    families = {c["family"] for c in cases}
    assert {"tri_nho", "correction", "tool", "trung_thuc", "giong"} \
        <= families
    for case in cases:
        assert case.get("input") or case.get("turns")
        assert isinstance(case.get("checks"), dict)


async def test_runner_stub_passes_good_fails_bad(cfg):
    report = await evals_mod.run_eval([GOOD_RECALL, GOOD_TOOL, BAD_CASE], cfg)
    by_id = {r["id"]: r for r in report["cases"]}
    assert by_id["mini-recall"]["passed"] is True
    assert by_id["mini-tool"]["passed"] is True
    assert "read_file" in by_id["mini-tool"]["tools_used"]
    assert by_id["mini-bad"]["passed"] is False
    assert by_id["mini-bad"]["failed_checks"]
    assert report["total"] == 3 and report["passed"] == 2
    assert report["families"]["tri_nho"]["total"] == 2
    assert report["mode"] == "stub"


async def test_runner_two_turn_correction_uses_lesson(cfg):
    case = {
        "id": "mini-corr-2turn",
        "family": "correction",
        "turns": ["Sai rồi, gói Pro giá 60K mới đúng",
                  "Vậy nhắc lại coi, gói Pro giá bao nhiêu?"],
        "setup": {"history": [
            {"role": "user", "content": "Gói Pro giá bao nhiêu?"},
            {"role": "assistant", "content": "Gói Pro giá 50K ní."},
        ]},
        "stub": {"category": "du_kien"},
        "checks": {"fact_recalled": "60K"},
    }
    report = await evals_mod.run_eval([case], cfg)
    assert report["cases"][0]["passed"] is True


def test_cases_jsonl_from_correction_is_loaded(tmp_path):
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    (evals_dir / "golden.jsonl").write_text(
        json.dumps(GOOD_RECALL, ensure_ascii=False) + "\n",
        encoding="utf-8")
    generated = {
        "id": "correction-7",
        "category": "du_kien",
        "severity": "critical",
        "original_request": "Gói Pro giá bao nhiêu?",
        "wrong_output": "Gói Pro giá 50K",
        "expected": "Gói Pro giá 60K",
        "source_correction_id": 7,
    }
    (evals_dir / "cases.jsonl").write_text(
        json.dumps(generated, ensure_ascii=False) + "\n", encoding="utf-8")
    cases = evals_mod.load_cases(evals_dir)
    assert [c["id"] for c in cases] == ["mini-recall", "correction-7"]
    corr = cases[1]
    assert corr["family"] == "correction"
    assert corr["input"] == "Gói Pro giá bao nhiêu?"
    assert corr["checks"]["contains_any"] == ["Gói Pro giá 60K"]
    assert corr["checks"]["not_contains"] == ["Gói Pro giá 50K"]


def test_cli_gate_exit_code(cfg, tmp_path, monkeypatch, capsys):
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    rows = [GOOD_RECALL, GOOD_TOOL, BAD_CASE]
    (evals_dir / "golden.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    monkeypatch.setenv("MULON_EVALS_DIR", str(evals_dir))
    out = tmp_path / "report.json"
    # 2/3 đạt = 67% < 85% -> trượt cổng, thoát 1.
    rc = evals_mod.main(["--out", str(out), "--threshold", "0.85"])
    assert rc == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["gate_ok"] is False and report["passed"] == 2
    # Hạ ngưỡng xuống 0.5 -> đạt cổng, thoát 0.
    rc = evals_mod.main(["--out", str(out), "--threshold", "0.5"])
    assert rc == 0
    capsys.readouterr()
