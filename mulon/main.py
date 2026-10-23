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
from .context import ContextEngine, Dossier
from .gateway import ModelGateway
from .memory import Memory
from .policy import PolicyEngine
from .tools import build_default_registry


async def build_system(cfg: Config):
    """Dựng toàn bộ hệ thống trừ bề mặt Telegram."""
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    cfg.artifact_dir.mkdir(parents=True, exist_ok=True)
    memory = await Memory.open(cfg.db_path)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = ModelGateway(cfg, memory=memory)
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    agent = Agent(cfg, gateway, memory, ctx, registry, policy)
    return agent, memory, dossier, registry


async def _dry_run(cfg: Config) -> int:
    agent, memory, dossier, registry = await build_system(cfg)
    report = {
        "config": cfg.masked_summary(),
        "dossier_files": {
            name: len(text) for name, text in sorted(dossier.files.items())
        },
        "bootstrap_pending": dossier.bootstrap_pending(),
        "tools": registry.names(),
        "sqlite_vec": memory.vector_enabled,
        "db": str(cfg.db_path),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    await memory.close()
    return 0


async def _run(cfg: Config) -> int:
    from .telegram_bot import TelegramSurface

    agent, memory, dossier, registry = await build_system(cfg)
    surface = TelegramSurface(cfg, agent, memory, dossier)
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
