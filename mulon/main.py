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
from .approvals import ApprovalBroker, register_approval_tools
from .browser_worker import register_browser_tools
from .config import Config
from .connectors import build_default_connectors, register_connector_tools
from .consolidation import ConsolidationWorker
from .context import ContextEngine, Dossier, clean_old_tool_results
from .embeddings import build_embedder
from .feed import FeedEngine
from .feed_auto import FeedAutoRunner
from .gateway import ModelGateway
from .ideas import IdeaEngine
from .library import LibraryService
from .marketplace import MarketplaceService, make_reexec_restarter
from .mcp_client import MCPManager
from .media_tools import ffmpeg_available, ffprobe_available, \
    register_media_tools
from .memory import Memory
from .planning import SchedulerService, register_planning_tools
from .policy import PolicyEngine
from .proactivity import ProactivityEngine
from .skills import SkillCatalog, register_skill_tools
from .subagents import PROFILES, SubagentRunner, register_subagent_tool
from .surfaces import SURFACE_KEYS, TopicManager
from .tools import build_default_registry
from .tracing import build_tracer, traced_gateway
from .vault import VaultFormServer, VaultStore, register_vault_tools
from .voice import VoiceService
from .webapp_server import ActivityTracker, WebAppServer
from .websearch import register_search_tool

logger = logging.getLogger("mulon.main")


async def build_system(cfg: Config):
    """Dựng toàn bộ hệ thống trừ bề mặt Telegram.

    Trả (agent, memory, dossier, registry, worker, services) —
    services chứa các thành phần Phase 3: mcp, connectors,
    scheduler, subagent runner.
    """
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    cfg.artifact_dir.mkdir(parents=True, exist_ok=True)
    clean_old_tool_results(cfg.artifact_dir, max_age_days=7)
    memory = await Memory.open(cfg.db_path)
    await memory.reconcile_orphan_tasks()
    # Phase 2: gắn embedder cho hybrid recall. Không dựng được thì
    # set_embedder degrade sạch — hệ thống vẫn chạy BM25-only.
    embedder = build_embedder(cfg)
    if embedder is not None:
        memory.embed_timeout_s = cfg.embed_timeout_s
        memory.recall_vector_weight = cfg.recall_vector_weight
        memory.recall_bm25_weight = cfg.recall_bm25_weight
        await memory.set_embedder(embedder)
    dossier = Dossier.load(cfg.dossier_dir)
    # Phase 5: Langfuse tracing tuỳ chọn — thiếu env/gói thì
    # traced_gateway trả lại gateway nguyên bản, hành vi không đổi.
    gateway = traced_gateway(ModelGateway(cfg, memory=memory), cfg)
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    vault_store = VaultStore(cfg.vault_path,
                             getattr(cfg, "vault_encryption_key", ""))
    registry = build_default_registry(cfg, memory, dossier=dossier, vault_store=vault_store)
    policy = PolicyEngine(cfg.policy_path, memory=memory)

    # --- Phase 3: tay chân ---
    # Scheduler + goals tools (chỉ dữ liệu/tool; vòng lặp chạy riêng
    # và mặc định TẮT).
    register_planning_tools(registry, cfg, memory)
    # Browser worker (Playwright optional — vắng thì tool báo
    # unavailable, không sập).
    browser_worker = register_browser_tools(registry, cfg)
    # Tool tìm kiếm web (1.4): cùng năng lực search mà collector
    # Feed dùng — agent được TÌM trang, việc đọc vẫn qua
    # web_fetch/web_read như cũ.
    register_search_tool(registry)
    # Connector framework: adapter 'system' + (1.5.0) Gmail /
    # Google Calendar dùng chung 1 GoogleAuth; VaultStore dựng
    # sớm ở đây để auth đọc credential (marketplace + phase 6
    # dùng lại đúng instance này).
    register_vault_tools(registry, cfg)
    google_auth = None
    if getattr(cfg, "google_legacy_connectors", False):
        from .google_conn import build_google_auth

        google_auth = build_google_auth(cfg, vault_store)
    connectors = build_default_connectors(cfg, google_auth=google_auth, vault_store=vault_store)
    register_connector_tools(registry, connectors)
    # MCP client: nối server đã bật trong config, đăng ký tool của
    # chúng vào registry chung. Server lỗi/vắng -> degrade sạch.
    mcp_manager = MCPManager(cfg, cfg.mcp_config_path)
    if vault_store is not None:
        mcp_manager.set_secret_resolver(vault_store.resolve)
    await mcp_manager.start()
    # 1.2.0: broker duyệt việc (policy nấc "ask") — dùng chung cho
    # agent (mở yêu cầu), bề mặt Telegram (trình + gỡ thẻ) và Mini
    # App (/api/approve).
    broker = ApprovalBroker(policy=policy,
                            timeout_s=cfg.approval_timeout_s)
    register_approval_tools(registry, broker)
    # 1.3.0: MCP Marketplace — boot gate chạy giữa start() và
    # register_into(): server managed chỉ được đăng ký tool khi
    # config fingerprint + tool fingerprint khớp bản đã duyệt;
    # kèm đối chiếu restart pending + tự rollback khi áp dụng
    # thất bại. Restarter/notifier chỉ gắn ở _run (dry-run không
    # tự khởi động lại, không gửi tin).
    marketplace = None
    excluded: set = set()
    if cfg.marketplace_enabled:
        marketplace = MarketplaceService(
            cfg, policy=policy, broker=broker,
            vault_store=vault_store, mcp_manager=mcp_manager)
        excluded = await marketplace.boot_gate()
        if excluded:
            logger.info("marketplace boot gate giữ tool của: %s",
                        sorted(excluded))
    mcp_tools = mcp_manager.register_into(registry, exclude=excluded)
    if mcp_tools:
        logger.info("MCP đã đăng ký %d tool: %s",
                    len(mcp_tools), mcp_tools)
    activity = ActivityTracker()
    agent = Agent(cfg, gateway, memory, ctx, registry, policy,
                  broker=broker)
    # Subagents: agent loop đầy đủ, toolset thu hẹp theo profile.
    runner = SubagentRunner(
        cfg, gateway, memory, ctx, policy,
        registry_factory=lambda: registry,
        activity=activity,
    )
    register_subagent_tool(registry, runner)

    async def _agent_provider():
        return agent

    scheduler = SchedulerService(cfg, memory, _agent_provider)
    worker = ConsolidationWorker(cfg, memory, gateway)

    # --- Phase 4: chủ động + tiếng nói + media + skills ---
    # Media pipeline tools (ffmpeg trên máy — vắng thì unavailable; sinh ảnh qua Agnes AI).
    register_media_tools(registry, cfg, gateway, vault_store=vault_store)
    # Skills SKILL.md: nạp sau khi registry đã đủ tool để xét
    # eligibility theo requires; mục lục vào tool skill_list /
    # skill_read, kết quả vet ghi trajectory.
    catalog = SkillCatalog.load(cfg.skills_dir,
                                tool_names=set(registry.names()))
    register_skill_tools(registry, catalog)
    from .evolution import register_evolution_tools
    register_evolution_tools(registry, cfg, memory)
    await catalog.log_vet_results(memory)
    if catalog.entries:
        logger.info("skills: mục lục %s (tổng %d file)",
                    catalog.visible_names(), len(catalog.entries))
    # Voice tương tác (STT whisper optional + TTS qua proxy).
    voice = VoiceService(cfg, gateway)
    # Proactivity engine: chỉ DỮ LIỆU + engine ở đây; vòng lặp nền
    # ở _run và mặc định TẮT như scheduler/consolidation.
    proactivity = ProactivityEngine(cfg, memory, gateway)

    # --- Phase 6: bề mặt group (mục 16) ---
    # Toàn bộ là dịch vụ theo yêu cầu (lệnh chat gọi mới chạy) —
    # không vòng lặp nền mới nào được bật ở đây. Vault form server
    # chỉ start() trong _run, không start ở dry-run. vault_store
    # đã dựng ở khối 1.3 phía trên (dùng chung một instance).
    # 1.4.0 (spec Feed chủ động + quyết định owner 0.2b): engine
    # được nối collector NGOÀI (tự tìm kiếm web + nguồn ghim +
    # connector feed_snapshot) và FeedAutoRunner đăng ký job hệ
    # thống nội bộ 'feed_auto' vào scheduler — Feed LUÔN tự động,
    # không công tắc. Vòng tick scheduler trong _run chạy khi có
    # handler nội bộ dù SCHEDULER_ENABLED vẫn tắt (cô lập tick:
    # lịch thường không bắn — planning.run_due_once).
    topics = TopicManager()
    feed_engine = FeedEngine(
        cfg, memory, gateway, connectors=connectors,
        reader=browser_worker.read, collect_external=True)
    feed_auto = FeedAutoRunner(cfg, memory, feed_engine,
                               topics=topics, connectors=connectors)
    scheduler.register_internal_handler(
        "feed_auto", lambda sched: feed_auto.run_once())
    await feed_auto.ensure_schedule()
    phase6 = {
        "topics": topics,
        "feed": feed_engine,
        "feed_auto": feed_auto,
        "ideas": IdeaEngine(cfg, memory, gateway),
        "library": LibraryService(cfg, memory),
        "vault_server": VaultFormServer(cfg, vault_store),
        "vault_store": vault_store,
        "connectors": connectors,
    }
    from .library import register_library_tools
    register_library_tools(registry, phase6["library"])
    # 1.2.0: Mini App server — chỉ DỰNG ở đây; start() trong _run
    # (như vault server, dry-run không bind cổng). ActivityTracker
    # dùng chung với bề mặt Telegram và SubagentRunner.
    webapp = WebAppServer(
        cfg, memory=memory, policy=policy, broker=broker,
        connectors=connectors, mcp_manager=mcp_manager,
        vault_store=vault_store, registry=registry, dossier=dossier,
        skills=catalog, activity=activity, marketplace=marketplace,
        feed_auto=feed_auto, google_auth=google_auth,
        library=phase6["library"], ideas=phase6["ideas"])
    services = {
        "mcp": mcp_manager,
        "connectors": connectors,
        "scheduler": scheduler,
        "subagent_runner": runner,
        "browser_worker": browser_worker,
        "voice": voice,
        "proactivity": proactivity,
        "skills": catalog,
        "policy": policy,
        "phase6": phase6,
        "broker": broker,
        "webapp": webapp,
        "activity": activity,
        "marketplace": marketplace,
        "feed_auto": feed_auto,
        "cliproxy": getattr(webapp, "cliproxy", None),
    }
    return agent, memory, dossier, registry, worker, services


async def _dry_run(cfg: Config) -> int:
    (agent, memory, dossier, registry, worker,
     services) = await build_system(cfg)
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
        "phase3": {
            "mcp": services["mcp"].status(),
            "connectors": services["connectors"].names(),
            "scheduler_enabled": cfg.scheduler_enabled,
            "subagent_profiles": sorted(PROFILES),
        },
        "phase4": {
            "proactivity_enabled": cfg.proactivity_enabled,
            "proactivity_active_hours": cfg.proactivity_active_hours,
            "voice": {
                "stt_available": services["voice"].stt_available(),
                "whisper_model": cfg.voice_whisper_model,
                "tts_model": cfg.voice_tts_model,
                "tts_voice": cfg.voice_tts_voice,
                "tts_format": cfg.voice_tts_format,
            },
            "media": {
                "ffmpeg": ffmpeg_available(cfg),
                "ffprobe": ffprobe_available(cfg),
            },
            "skills": services["skills"].catalog(),
            "browser_persistent_profile":
                services["browser_worker"].uses_persistent_profile(),
        },
        "phase5": {
            "eval_pass_threshold": cfg.eval_pass_threshold,
            "langfuse_enabled": build_tracer(cfg).enabled,
            "backup_dir": str(cfg.backup_dir),
        },
        "phase6": {
            "surfaces": SURFACE_KEYS,
            "vault": {
                "port": cfg.vault_port,
                "path": str(cfg.vault_path),
                "entries": len(services["phase6"]["vault_store"]
                               .labels()),
            },
            "library_items": len(
                await memory.list_library_items(status=None)),
            "idea_ttl_days": cfg.idea_ttl_days,
        },
        "v12": {
            "webapp_configured": bool(cfg.webapp_url
                                      and cfg.webapp_app_name),
            "webapp_port": cfg.webapp_port,
            "approval_timeout_s": cfg.approval_timeout_s,
            "commands": 31,
        },
        "v13": {
            "marketplace_enabled": cfg.marketplace_enabled,
            "marketplace": (services["marketplace"].summary()
                            if services.get("marketplace")
                            else None),
            "catalog_auto_update":
                cfg.marketplace_catalog_auto_update,
        },
        "v14": {
            "feed_auto": await services["feed_auto"].get_state(),
            "scheduler_isolated_tick": bool(
                services["scheduler"].has_internal_handlers()),
        },
        "db": str(cfg.db_path),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if "mcp" in services:
        try:
            await services["mcp"].close()
        except BaseException:
            pass
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


async def _proactivity_loop(engine: ProactivityEngine,
                            interval_s: int) -> None:
    """Vòng lặp heartbeat — luôn chạy; engine tự bỏ lượt khi
    công tắc hiệu lực đang tắt (xem proactivity.effective_enabled)."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            stats = await engine.run_once()
            if stats.get("notes"):
                logger.info("heartbeat xếp hàng %d đề xuất: %s",
                            stats["notes"], stats)
        except Exception as exc:
            logger.warning("heartbeat nền lỗi (bỏ qua vòng này): %s", exc)


async def _ideas_auto_loop(engine, interval_s: int, surface=None) -> None:
    """Vòng lặp Ideas tự sinh — luôn chạy; khi sinh được thẻ mới,
    tự động gửi thẻ vào topic Ideas kèm nút bấm trực tiếp."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            stats = await engine.generate_auto()
            cards = stats.get("card_objs", [])
            if cards:
                logger.info("ideas tự sinh: %d thẻ mới: %s",
                            len(cards), stats)
                if surface is not None:
                    await surface.publish_ideas(cards)
        except Exception as exc:
            logger.warning("ideas tự sinh nền lỗi (bỏ qua vòng này): "
                           "%s", exc)


async def _run(cfg: Config) -> int:
    from .telegram_bot import TelegramSurface

    (agent, memory, dossier, registry, worker,
     services) = await build_system(cfg)
    surface = TelegramSurface(cfg, agent, memory, dossier,
                              consolidator=worker,
                              voice=services["voice"],
                              policy=services["policy"],
                              surfaces=services["phase6"],
                              broker=services["broker"],
                              activity=services["activity"],
                              marketplace=services.get("marketplace"))
    if "webapp" in services and services["webapp"] is not None:
        services["webapp"].set_vault_notifier(surface.on_vault_secret_captured)
    # 1.3.0: marketplace — gắn restarter thật (bot tự khởi động
    # lại sau cài/gỡ/cập nhật). Notifier + quyết toán boot do bề
    # mặt Telegram gắn khi bot sẵn sàng (trong run()). Job nền
    # hẹp duy nhất: kiểm tra catalog (boot + hàng tuần, chỉ dữ
    # kiện — không bao giờ tự cài).
    marketplace = services.get("marketplace")
    if marketplace is not None:
        marketplace.restarter = make_reexec_restarter()
        if cfg.marketplace_catalog_auto_update:
            asyncio.create_task(marketplace.catalog_loop())
            logger.info("marketplace: tự kiểm tra catalog BẬT "
                        "(boot + hàng tuần, chỉ dữ kiện)")
    # Vault form server: bind 127.0.0.1, link một lần qua /vault.
    if services["phase6"]["vault_server"].start():
        logger.info("vault form server BẬT (chỉ localhost)")
    # Mini App server (1.2.0): bind 127.0.0.1; app chỉ mở được khi
    # host có WEBAPP_URL HTTPS (tunnel) + app name trong BotFather.
    if await services["webapp"].start():
        logger.info("Mini App server BẬT (chỉ localhost, port %d)",
                    services["webapp"].port)
    # T-14: CLIProxyAPI tự khởi chạy nếu được cấu hình (degrade, không sập)
    cliproxy_mgr = services.get("cliproxy")
    if cliproxy_mgr and getattr(cfg, "cliproxy_auto_start", False):
        try:
            start_res = await cliproxy_mgr.start_process()
            if start_res.get("ok"):
                logger.info("CLIProxyAPI: %s", start_res.get("detail"))
            else:
                logger.warning("CLIProxyAPI tự khởi chạy không thành công: %s", start_res.get("error"))
        except Exception as exc:
            logger.warning("CLIProxyAPI tự khởi chạy lỗi (degrade, bot không sập): %s", exc)
    if cfg.consolidation_enabled:
        asyncio.create_task(
            _consolidation_loop(worker, cfg.consolidation_interval_s)
        )
        logger.info("consolidation nền BẬT (mỗi %ss)",
                    cfg.consolidation_interval_s)
    # Vòng tick scheduler: chạy khi scheduler thường BẬT hoặc có
    # job hệ thống nội bộ (Feed chủ động 1.4 — luôn có). Chế độ
    # cô lập: lịch thường chỉ bắn khi SCHEDULER_ENABLED=1, job
    # nội bộ luôn được phục vụ (planning.run_forever tự quyết).
    if cfg.scheduler_enabled or services["scheduler"] \
            .has_internal_handlers():
        asyncio.create_task(services["scheduler"].run_forever())
        if not cfg.scheduler_enabled:
            logger.info("scheduler nền chạy ở chế độ CÔ LẬP: chỉ "
                        "job hệ thống nội bộ (Feed chủ động); lịch "
                        "thường vẫn TẮT (SCHEDULER_ENABLED=0)")
    else:
        logger.info("scheduler nền TẮT (bật bằng SCHEDULER_ENABLED=1)")
    # Vòng heartbeat luôn chạy; lượt quét tự bỏ qua khi công tắc
    # hiệu lực tắt (Mini App ghi kv, mặc định theo
    # PROACTIVITY_ENABLED) — gạt trong app là ăn ngay, khỏi
    # restart, khỏi sửa .env.
    asyncio.create_task(
        _proactivity_loop(services["proactivity"],
                          cfg.proactivity_interval_s)
    )
    logger.info("proactivity: vòng quét chạy mỗi %ss (giờ %s); "
                "trạng thái hiệu lực theo công tắc trong Mini "
                "App, mặc định PROACTIVITY_ENABLED=%s",
                cfg.proactivity_interval_s,
                cfg.proactivity_active_hours,
                cfg.proactivity_enabled)
    # sửa 1.6.2: vòng Ideas tự sinh luôn chạy; lượt sinh tự bỏ qua
    # khi công tắc hiệu lực tắt (gạt kv trong Mini App là ăn ngay,
    # khỏi restart, khỏi sửa .env; mặc định IDEAS_AUTO_ENABLED=0).
    asyncio.create_task(
        _ideas_auto_loop(services["phase6"]["ideas"],
                         cfg.ideas_auto_interval_s,
                         surface=surface)
    )
    logger.info("ideas tự sinh: vòng chạy mỗi %ss; trạng thái hiệu "
                "lực theo công tắc trong Mini App, mặc định "
                "IDEAS_AUTO_ENABLED=%s (khi bật chỉ ghi thẻ chờ "
                "duyệt, không tự nhắn, không tự chạy task)",
                cfg.ideas_auto_interval_s,
                cfg.ideas_auto_enabled)
    await surface.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mulon")
    parser.add_argument("--dry-run", action="store_true",
                        help="smoke test không cần token Telegram")
    parser.add_argument("--setup", action="store_true",
                        help="chạy trình hướng dẫn thiết lập bản cài (setup wizard)")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    if args.setup:
        from .setup_wizard import run_setup
        run_setup()
        return 0
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
