"""Bộ eval vàng chạy thật (thiết kế mục 10, roadmap Phase 5).

Đóng vòng học của Phase 2: case do correction nghiêm trọng sinh ra
(`evals/cases.jsonl`, learning.append_eval_case) từ Phase 5 được
NẠP VÀ CHẠY cùng bộ vàng đóng gói (`evals/golden.jsonl`).

Hai chế độ gateway:
- **stub** (mặc định, offline): StubGateway là "model tham chiếu"
  tất định — nó chỉ trả lời được từ đúng những gì harness nạp vào
  ngữ cảnh (dossier/lesson/recall) và kết quả tool thật chạy qua
  registry thật. Case xanh ở chế độ này nghĩa là ĐƯỜNG ỐNG đúng:
  fact được recall vào ngữ cảnh, tool được gọi và kết quả chảy
  ngược về, lesson từ correction xuất hiện trong ngữ cảnh.
- **live** (EVAL_LIVE=1 hoặc --live): gateway thật qua proxy —
  đo cả model. Cùng một bộ case, cùng một cách chấm.

Cách chấm hoàn toàn bằng máy, không LLM-judge: mỗi case khai
``checks`` gồm contains_all / contains_any / not_contains /
tool_called / fact_recalled. Cổng chất lượng: pass rate (theo
trọng số) < ngưỡng (env EVAL_PASS_THRESHOLD, mặc định 0.85) ->
CLI thoát mã 1, dùng được làm cổng CI.

Mỗi case chạy trong DB + workspace tạm riêng: không đụng dữ liệu
thật, không để lại rác.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from .gateway import Completion, ToolCall

logger = logging.getLogger("mulon.evals")

CHECK_KEYS = (
    "contains_all", "contains_any", "not_contains",
    "tool_called", "fact_recalled",
)


# ------------------------------------------------------------------
# Nạp + chuẩn hoá case
# ------------------------------------------------------------------
def _normalize_case(raw: dict) -> Optional[dict]:
    """Chuẩn hoá 1 case về schema vàng. None = case không hợp lệ."""
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    case = dict(raw)
    case.setdefault("family", "khac")
    case.setdefault("weight", 1.0)
    case.setdefault("checks", {})
    if not case.get("input") and not case.get("turns"):
        # Schema của learning.append_eval_case (Phase 2): chạy lại
        # yêu cầu gốc, kỳ vọng chứa bản đúng và không lặp lại bản sai.
        if raw.get("original_request"):
            case["input"] = str(raw["original_request"])
            checks = dict(case["checks"])
            expected = str(raw.get("expected") or "").strip()
            wrong = str(raw.get("wrong_output") or "").strip()
            if expected:
                checks.setdefault("contains_any", [expected])
            if wrong:
                checks.setdefault("not_contains", [wrong])
            case["checks"] = checks
            case["family"] = "correction"
            case["source"] = "correction"
        else:
            return None
    return case


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("bỏ dòng JSONL hỏng trong %s", path)
    return rows


def load_cases(evals_dir: str | Path,
               extra_files: Optional[list[str | Path]] = None) -> list[dict]:
    """Nạp golden.jsonl + cases.jsonl (nếu có) + file phụ.

    Trùng id: bản gặp trước thắng (golden là nguồn chuẩn).
    """
    base = Path(evals_dir)
    sources: list[Path] = [base / "golden.jsonl", base / "cases.jsonl"]
    sources += [Path(p) for p in (extra_files or [])]
    cases: list[dict] = []
    seen: set[str] = set()
    for path in sources:
        for raw in _read_jsonl(path):
            case = _normalize_case(raw)
            if case is None:
                logger.warning("bỏ case không hợp lệ trong %s: %s",
                               path, str(raw)[:120])
                continue
            if case["id"] in seen:
                continue
            seen.add(case["id"])
            cases.append(case)
    return cases


# ------------------------------------------------------------------
# Stub gateway — model tham chiếu tất định cho chế độ offline
# ------------------------------------------------------------------
def _tool_snippet(raw: str) -> str:
    """Ép kết quả tool (JSON) thành đoạn text ngắn để stub 'đọc' được."""
    try:
        data = json.loads(raw)
    except Exception:
        data = None
    if isinstance(data, dict):
        if data.get("error"):
            return f"Kết quả: {data['error']}"
        flat = json.dumps(data, ensure_ascii=False, default=str)
        return "Kết quả: " + flat[:600]
    return "Kết quả: " + raw[:400]


class StubGateway:
    """Gateway giả lập cho eval offline.

    Không "biết" gì ngoài ngữ cảnh agent đưa vào: trả lời suy ra từ
    recall/lesson trong messages và output tool thật. Nhờ vậy case
    đo được harness thay vì đo trí tưởng tượng của stub.
    """

    def __init__(self, case: dict):
        self._stub: dict = case.get("stub") or {}
        checks = case.get("checks") or {}
        targets: list[str] = []
        if checks.get("fact_recalled"):
            targets.append(str(checks["fact_recalled"]))
        for item in checks.get("contains_all") or []:
            targets.append(str(item))
        self._targets = [t for t in targets if t]
        self._tool_emitted = False

    # ----- các purpose phụ trợ -----
    def _classify(self, messages: list[dict]) -> dict:
        from .learning import _guess_category, _guess_severity, \
            _looks_explicit

        prompt_text = ""
        for m in reversed(messages):
            if isinstance(m, dict) and isinstance(m.get("content"), str):
                prompt_text = m["content"]
                break
        marker = "TIN NHẮN MỚI CỦA USER:"
        user_text = prompt_text
        if marker in prompt_text:
            user_text = prompt_text.split(marker, 1)[1].strip()
        return {
            "is_correction": bool(
                self._stub.get("classify_is_correction", True)),
            "explicit": bool(
                self._stub.get("explicit", _looks_explicit(user_text))),
            "category": self._stub.get(
                "category", _guess_category(user_text)),
            "severity": self._stub.get(
                "severity", _guess_severity(user_text)),
            "corrected": self._stub.get("corrected", user_text),
        }

    def _compose(self, messages: list[dict]) -> str:
        if self._stub.get("answer"):
            return str(self._stub["answer"])
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "tool" \
                    and m.get("content"):
                return "Đã làm xong ní. " + _tool_snippet(str(m["content"]))
        last_user = ""
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user" \
                    and isinstance(m.get("content"), str):
                last_user = m["content"]
                break
        low = last_user.lower()
        if "cảm ơn" in low:
            return "Không có gì ní."
        if len(last_user) <= 30 and low.strip().startswith(
                ("chào", "chao", "hello", "hi")):
            return "Chào ní, có gì cứ nói."
        joined = "\n".join(
            str(m.get("content") or "")
            for m in messages if isinstance(m, dict)
        )
        for target in self._targets:
            if target in joined:
                return f"Theo ký ức của tui: {target}."
        return "Tui chưa có dữ kiện này nên chưa trả lời chắc được ní."

    # ----- interface gateway -----
    async def complete(self, messages, model=None, tools=None,
                       temperature=0.7, timeout=None, purpose=""):
        if purpose == "plan":
            return Completion(text=json.dumps(
                {"steps": ["Hoàn thành yêu cầu của user"]},
                ensure_ascii=False))
        if purpose == "verify":
            ok = bool(self._stub.get("verify_ok", True))
            return Completion(text=json.dumps(
                {"ok": ok, "diagnosis": "" if ok else "stub ép fail"},
                ensure_ascii=False))
        if purpose == "correction_classify":
            return Completion(text=json.dumps(
                self._classify(messages), ensure_ascii=False))
        if purpose == "review_fork":
            return Completion(text=json.dumps(
                {"digest": "eval stub", "facts": []}, ensure_ascii=False))
        if purpose == "consolidation_extract":
            return Completion(text=json.dumps(
                {"facts": []}, ensure_ascii=False))
        tool_call = self._stub.get("tool_call")
        if tools and tool_call and not self._tool_emitted:
            self._tool_emitted = True
            return Completion(text="", tool_calls=[ToolCall(
                id="eval-call-1",
                name=str(tool_call.get("name", "")),
                arguments=json.dumps(
                    tool_call.get("arguments") or {}, ensure_ascii=False),
            )])
        return Completion(text=self._compose(messages))

    async def stream(self, messages, model=None, temperature=0.7,
                     timeout=None, purpose="", on_delta=None):
        text = self._stub.get("answer") or self._compose(messages)
        if on_delta is not None:
            maybe = on_delta(text)
            if asyncio.iscoroutine(maybe):
                await maybe
        return Completion(text=text)


# ------------------------------------------------------------------
# Chấm 1 case
# ------------------------------------------------------------------
def _has(text: str, needle: str) -> bool:
    return needle.casefold() in text.casefold()


def _check_case(case: dict, answer: str, tools_used: set[str]) -> list[str]:
    """Trả danh sách check trượt (rỗng = đạt)."""
    checks = case.get("checks") or {}
    failed: list[str] = []
    for needle in checks.get("contains_all") or []:
        if not _has(answer, str(needle)):
            failed.append(f"contains_all:{needle}")
    any_list = checks.get("contains_any") or []
    if any_list and not any(_has(answer, str(s)) for s in any_list):
        failed.append("contains_any")
    for needle in checks.get("not_contains") or []:
        if _has(answer, str(needle)):
            failed.append(f"not_contains:{needle}")
    for tool in checks.get("tool_called") or []:
        if tool not in tools_used:
            failed.append(f"tool_called:{tool}")
    recalled = checks.get("fact_recalled")
    if recalled and not _has(answer, str(recalled)):
        failed.append("fact_recalled")
    return failed


async def _seed(memory, session_key: str, setup: dict, workspace: Path):
    await memory.get_or_create_session(session_key)
    for fact in setup.get("facts") or []:
        await memory.add_fact(
            str(fact.get("fact", "")),
            subject=str(fact.get("subject", "")),
            salience=float(fact.get("salience", 0.8)),
            source="eval_seed",
        )
    for name, content in (setup.get("files") or {}).items():
        target = (workspace / str(name)).resolve()
        if workspace not in target.parents and target != workspace:
            raise ValueError(f"setup file ra ngoài workspace: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
    for msg in setup.get("history") or []:
        await memory.append_message(
            session_key, str(msg.get("role", "user")),
            str(msg.get("content", "")),
        )
    for other_key, msgs in (setup.get("other_history") or {}).items():
        await memory.get_or_create_session(str(other_key))
        for msg in msgs or []:
            await memory.append_message(
                str(other_key), str(msg.get("role", "user")),
                str(msg.get("content", "")),
            )


async def _run_one_case(case: dict, base_cfg, dossier, run_root: Path,
                        live: bool) -> dict:
    from .agent import Agent
    from .context import ContextEngine
    from .memory import Memory
    from .policy import PolicyEngine
    from .tools import build_default_registry

    case_dir = run_root / "".join(
        c if c.isalnum() or c in "-_" else "_" for c in case["id"]
    )
    case_dir.mkdir(parents=True, exist_ok=True)
    cfg = dataclasses.replace(
        base_cfg,
        db_path=case_dir / "mulon.db",
        workspace_dir=case_dir / "workspace",
        artifact_dir=case_dir / "artifacts",
        policy_path=case_dir / "policy.json",
    )
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    memory = await Memory.open(cfg.db_path)
    session_key = f"eval:{case['id']}"
    try:
        await _seed(memory, session_key, case.get("setup") or {},
                    cfg.workspace_dir)
        if live:
            from .embeddings import build_embedder
            from .gateway import ModelGateway

            gateway: Any = ModelGateway(cfg, memory=memory)
            embedder = build_embedder(cfg)
            if embedder is not None:
                await memory.set_embedder(embedder)
        else:
            gateway = StubGateway(case)
        ctx = ContextEngine(cfg, dossier, memory, gateway)
        registry = build_default_registry(cfg, memory)
        policy = PolicyEngine(cfg.policy_path, memory=memory)
        agent = Agent(cfg, gateway, memory, ctx, registry, policy)

        cur = await memory.db.execute(
            "SELECT COALESCE(MAX(id), 0) AS m FROM trajectory")
        row = await cur.fetchone()
        before_id = int(row["m"] or 0)

        turns = case.get("turns") or [case.get("input", "")]
        answer = ""
        for text in turns:
            result = await agent.handle(session_key, str(text))
            answer = result.text or ""
        # Cho review fork nền kịp ghi xong trước khi đóng DB.
        await asyncio.sleep(0.15)

        tools_used: set[str] = set()
        cur = await memory.db.execute(
            "SELECT payload FROM trajectory WHERE kind='tool_call'"
            " AND id>?", (before_id,))
        for r in await cur.fetchall():
            try:
                tools_used.add(str(json.loads(r["payload"]).get("tool", "")))
            except Exception:
                pass
        failed = _check_case(case, answer, tools_used)
        return {
            "id": case["id"],
            "family": case.get("family", "khac"),
            "weight": float(case.get("weight") or 1.0),
            "passed": not failed,
            "failed_checks": failed,
            "tools_used": sorted(tools_used),
            "answer_excerpt": answer[:200],
        }
    finally:
        await memory.close()


async def run_eval(cases: list[dict], cfg, live: bool = False) -> dict:
    """Chạy toàn bộ case, trả báo cáo (chưa gồm ngưỡng cổng)."""
    from .context import Dossier

    dossier = Dossier.load(cfg.dossier_dir)
    run_root = Path(tempfile.mkdtemp(prefix="mulon-eval-"))
    results: list[dict] = []
    try:
        for case in cases:
            try:
                results.append(
                    await _run_one_case(case, cfg, dossier, run_root, live))
            except Exception as exc:
                logger.exception("case %s lỗi hạ tầng", case.get("id"))
                results.append({
                    "id": case.get("id", "?"),
                    "family": case.get("family", "khac"),
                    "weight": float(case.get("weight") or 1.0),
                    "passed": False,
                    "failed_checks": [f"error:{exc}"],
                    "tools_used": [],
                    "answer_excerpt": "",
                })
    finally:
        shutil.rmtree(run_root, ignore_errors=True)

    total_weight = sum(r["weight"] for r in results) or 1.0
    passed_weight = sum(r["weight"] for r in results if r["passed"])
    families: dict[str, dict] = {}
    for r in results:
        fam = families.setdefault(
            r["family"], {"total": 0, "passed": 0, "pass_rate": 0.0})
        fam["total"] += 1
        fam["passed"] += 1 if r["passed"] else 0
    for fam in families.values():
        fam["pass_rate"] = round(fam["passed"] / fam["total"], 4) \
            if fam["total"] else 0.0
    return {
        "mode": "live" if live else "stub",
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "pass_rate": round(passed_weight / total_weight, 4),
        "families": families,
        "cases": results,
    }


# ------------------------------------------------------------------
# CLI: python -m mulon.evals [--live] [--threshold 0.85] [--out F]
# ------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="mulon.evals")
    parser.add_argument("--live", action="store_true",
                        help="dùng gateway thật qua proxy (hoặc env "
                             "EVAL_LIVE=1); mặc định stub offline")
    parser.add_argument("--threshold", type=float, default=None,
                        help="ngưỡng pass rate (mặc định env "
                             "EVAL_PASS_THRESHOLD / 0.85)")
    parser.add_argument("--out", default=None,
                        help="đường dẫn báo cáo JSON (mặc định "
                             "<evals_dir>/report.json)")
    parser.add_argument("--cases", action="append", default=[],
                        help="nạp thêm file case JSONL (lặp được)")
    parser.add_argument("--json", action="store_true",
                        help="in báo cáo JSON ra stdout thay vì tóm tắt")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from .config import Config

    cfg = Config.load(env_file=args.env_file)
    live = args.live or os.environ.get("EVAL_LIVE", "") == "1"
    threshold = args.threshold if args.threshold is not None \
        else cfg.eval_pass_threshold
    cases = load_cases(cfg.evals_dir, extra_files=args.cases)
    if not cases:
        print("Không có case nào để chạy (kiểm tra evals/golden.jsonl).",
              file=sys.stderr)
        return 2
    report = asyncio.run(run_eval(cases, cfg, live=live))
    report["threshold"] = threshold
    report["gate_ok"] = report["pass_rate"] >= threshold

    out_path = Path(args.out) if args.out else Path(cfg.evals_dir) / "report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Eval ({report['mode']}): {report['passed']}/{report['total']}"
              f" case đạt — pass rate {report['pass_rate']:.0%}"
              f" (ngưỡng {threshold:.0%}) ->"
              f" {'ĐẠT CỔNG' if report['gate_ok'] else 'TRƯỢT CỔNG'}")
        for fam, stats in sorted(report["families"].items()):
            print(f"  {fam}: {stats['passed']}/{stats['total']}"
                  f" ({stats['pass_rate']:.0%})")
        for r in report["cases"]:
            if not r["passed"]:
                print(f"  TRƯỢT {r['id']}: {', '.join(r['failed_checks'])}")
        print(f"Báo cáo: {out_path}")
    return 0 if report["gate_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
