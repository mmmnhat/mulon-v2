"""Boot: init DB -> nạp dossier -> registry -> policy -> agent -> bot.

Chạy:
    python -m mulon.main             # chạy bot (cần TELEGRAM_BOT_TOKEN)
    python -m mulon.main --dry-run   # smoke test: không cần token,
                                     # in cấu hình đã che secret, thoát 0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .agent import Agent
from .config import Config
from .consolidation import ConsolidationWorker
from .context import ContextEngine, Dossier
from .embeddings import build_embedder
from .gateway import ModelGateway
from .memory import Memory
from .policy import PolicyEngine
from .tools import build_default_registry

logger = logging.getLogger("mulon.main")


async def build_system(cfg: Config):
    """Dựng toàn bộ hệ thống trừ bề mặt Telegram."""
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    cfg.artifact_dir.mkdir(parents=True, exist_ok=True)
    memory = await Memory.open(cfg.db_path)
    # Phase 2: gắn embedder cho hybrid recall. Không dựng được thì
    # set_embedder degrade sạch — hệ thống vẫn chạy BM25-only.
    embedder = build_embedder(cfg)
    if embedder is not None:
        memory.embed_timeout_s = cfg.embed_timeout_s
        memory.recall_vector_weight = cfg.recall_vector_weight
        memory.recall_bm25_weight = cfg.recall_bm25_weight
        await memory.set_embedder(embedder)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = ModelGateway(cfg, memory=memory)
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    agent = Agent(cfg, gateway, memory, ctx, registry, policy)
    worker = ConsolidationWorker(cfg, memory, gateway)
    return agent, memory, dossier, registry, worker


async def _dry_run(cfg: Config) -> int:
    agent, memory, dossier, registry, worker = await build_system(cfg)
    report = {
        "config": cfg.masked_summary(),
        "dossier_files": {
            name: len(text) for name, text in sorted(dossier.files.items())
        },
        "bootstrap_pending": dossier.bootstrap_pending(),
        "tools": registry.names(),
        "sqlite_vec": memory.vector_enabled,
        "embedder": getattr(memory.embedder, "name", None),
        "hybrid_recall": bool(memory.vec_ready),
        "consolidation_enabled": cfg.consolidation_enabled,
        "db": str(cfg.db_path),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    await memory.close()
    return 0


async def _consolidation_loop(worker: ConsolidationWorker,
                              interval_s: int) -> None:
    """Vòng lặp nền tuỳ chọn — CHỈ chạy khi CONSOLIDATION_ENABLED=1."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            stats = await worker.run_once()
            if stats.get("messages"):
                logger.info("consolidation nền: %s", stats)
        except Exception as exc:
            logger.warning("consolidation nền lỗi (bỏ qua vòng này): %s",
                           exc)


async def _run(cfg: Config) -> int:
    from .telegram_bot import TelegramSurface

    agent, memory, dossier, registry, worker = await build_system(cfg)
    surface = TelegramSurface(cfg, agent, memory, dossier,
                              consolidator=worker)
    if cfg.consolidation_enabled:
        asyncio.create_task(
            _consolidation_loop(worker, cfg.consolidation_interval_s)
        )
        logger.info("consolidation nền BẬT (mỗi %ss)",
                    cfg.consolidation_interval_s)
    await surface.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mulon")
    parser.add_argument("--dry-run", action="store_true",
                        help="smoke test không cần token Telegram")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = Config.load(env_file=args.env_file)
    if args.dry_run:
        return asyncio.run(_dry_run(cfg))
    if not cfg.telegram_bot_token:
        print("Thiếu TELEGRAM_BOT_TOKEN — xem .env.example. "
              "(Hoặc chạy --dry-run để smoke test.)", file=sys.stderr)
        return 2
    return asyncio.run(_run(cfg))


if __name__ == "__main__":
    raise SystemExit(main())
