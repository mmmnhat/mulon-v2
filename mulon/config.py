"""Cấu hình qua biến môi trường.

Nguyên tắc (thiết kế mục 9): mọi đường dẫn và giá trị cá nhân đi qua
env/config — KHÔNG hardcode ID, tên thật hay đường dẫn máy cá nhân vào
code. File này chỉ chứa placeholder trung tính.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _resolve(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    return p if p.is_absolute() else (PROJECT_ROOT / p)


@dataclass(frozen=True)
class Config:
    # --- Model / proxy (thiết kế mục 2.2: chỉ qua proxy local) ---
    proxy_base_url: str = "http://127.0.0.1:8317/v1"
    proxy_api_key: str = "local-proxy"
    model_brain: str = "gemini-3.8-flash"
    model_cheap: str = "gemini-3.8-flash"
    model_escalated: str = "gemini-3.8-flash"

    # --- Telegram ---
    telegram_bot_token: str = ""
    allowed_user_id: int = 0
    group_mention_only: bool = True
    debounce_seconds: float = 2.5

    # --- Đường dẫn ---
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "mulon.db")
    dossier_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "dossier")
    workspace_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "workspace")
    artifact_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "artifacts")
    policy_path: Path = field(default_factory=lambda: PROJECT_ROOT / "config" / "policy.json")

    # --- Ngân sách ngữ cảnh (thiết kế mục 3.2) ---
    context_window_tokens: int = 200_000
    history_token_budget: int = 30_000
    recall_token_budget: int = 6_000
    tool_result_max_chars: int = 8_000
    history_max_messages: int = 60

    # --- Ngân sách tác vụ (thiết kế mục 3.1) ---
    max_llm_calls_per_task: int = 30
    max_task_seconds: int = 600
    verify_max_retries: int = 2
    llm_timeout_s: int = 60

    # --- An toàn tool ---
    allow_outside_workspace: bool = False

    # --- Phase 2: ký ức sống (mục 4.2, 4.3, 4.4) ---
    # Embedder: fastembed (bge-m3 local, lazy-load) | stub (test) | off.
    # Vắng/không nạp được -> recall degrade BM25-only, không sập.
    embedder_backend: str = "fastembed"
    embedder_model: str = "BAAI/bge-m3"
    embedder_stub_dim: int = 128
    embed_timeout_s: float = 5.0
    recall_vector_weight: float = 0.7
    recall_bm25_weight: float = 0.3
    lessons_token_budget: int = 2_000
    # Review fork sau mỗi lượt (pattern Hermes): bật mặc định, nuốt lỗi.
    review_fork_enabled: bool = True
    review_fork_token_budget: int = 4_000
    # Consolidation nền: MẶC ĐỊNH TẮT (bài học vụ tự bật job) — chỉ
    # chạy khi user bật đích danh bằng CONSOLIDATION_ENABLED=1.
    consolidation_enabled: bool = False
    consolidation_interval_s: int = 900
    consolidation_batch: int = 50
    evals_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "evals")

    # --- Phase 3: tay chân (mục 6, 7) ---
    default_timezone: str = "Asia/Ho_Chi_Minh"
    # MCP client: file cấu hình server stdio (config/mcp_servers.json).
    mcp_config_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "config" / "mcp_servers.json"
    )
    mcp_connect_timeout_s: float = 20.0
    mcp_call_timeout_s: float = 60.0
    # Scheduler: MẶC ĐỊNH TẮT — chỉ chạy khi SCHEDULER_ENABLED=1
    # (bài học vụ user xóa toàn bộ job tự động 2026-10-22).
    scheduler_enabled: bool = False
    scheduler_tick_s: int = 30
    # Subagents: trần riêng + tối đa chạy đồng thời.
    subagent_max_concurrent: int = 4
    subagent_max_llm_calls: int = 15
    subagent_token_budget: int = 60_000
    subagent_max_seconds: int = 300
    subagent_digest_max_chars: int = 2_000
    # Browser worker (Playwright, optional — vắng thì tool báo
    # unavailable sạch).
    browser_timeout_s: float = 30.0
    browser_max_chars: int = 12_000

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> "Config":
        """Nạp .env (nếu có) rồi đọc env. Không ghi secret ra bất cứ đâu."""
        try:
            from dotenv import load_dotenv

            load_dotenv(dotenv_path=env_file)  # mặc định: .env ở thư mục chạy
        except Exception:
            pass
        return cls(
            proxy_base_url=_env("PROXY_BASE_URL", "http://127.0.0.1:8317/v1"),
            proxy_api_key=_env("PROXY_API_KEY", "local-proxy"),
            model_brain=_env("MODEL_BRAIN", "gemini-3.8-flash"),
            model_cheap=_env("MODEL_CHEAP", "gemini-3.8-flash"),
            model_escalated=_env("MODEL_ESCALATED", "gemini-3.8-flash"),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN", ""),
            allowed_user_id=_env_int("ALLOWED_USER_ID", 0),
            group_mention_only=_env_bool("GROUP_MENTION_ONLY", True),
            debounce_seconds=float(_env("DEBOUNCE_SECONDS", "2.5")),
            db_path=_resolve(_env("MULON_DB_PATH", "data/mulon.db")),
            dossier_dir=_resolve(_env("MULON_DOSSIER_DIR", "dossier")),
            workspace_dir=_resolve(_env("MULON_WORKSPACE_DIR", "workspace")),
            artifact_dir=_resolve(_env("MULON_ARTIFACT_DIR", "data/artifacts")),
            policy_path=_resolve(_env("POLICY_PATH", "config/policy.json")),
            context_window_tokens=_env_int("CONTEXT_WINDOW_TOKENS", 200_000),
            history_token_budget=_env_int("HISTORY_TOKEN_BUDGET", 30_000),
            recall_token_budget=_env_int("RECALL_TOKEN_BUDGET", 6_000),
            tool_result_max_chars=_env_int("TOOL_RESULT_MAX_CHARS", 8_000),
            history_max_messages=_env_int("HISTORY_MAX_MESSAGES", 60),
            max_llm_calls_per_task=_env_int("MAX_LLM_CALLS_PER_TASK", 30),
            max_task_seconds=_env_int("MAX_TASK_SECONDS", 600),
            verify_max_retries=_env_int("VERIFY_MAX_RETRIES", 2),
            llm_timeout_s=_env_int("LLM_TIMEOUT_S", 60),
            allow_outside_workspace=_env_bool("ALLOW_OUTSIDE_WORKSPACE", False),
            embedder_backend=_env("EMBEDDER_BACKEND", "fastembed"),
            embedder_model=_env("EMBEDDER_MODEL", "BAAI/bge-m3"),
            embedder_stub_dim=_env_int("EMBEDDER_STUB_DIM", 128),
            embed_timeout_s=_env_float("EMBED_TIMEOUT_S", 5.0),
            recall_vector_weight=_env_float("RECALL_VECTOR_WEIGHT", 0.7),
            recall_bm25_weight=_env_float("RECALL_BM25_WEIGHT", 0.3),
            lessons_token_budget=_env_int("LESSONS_TOKEN_BUDGET", 2_000),
            review_fork_enabled=_env_bool("REVIEW_FORK_ENABLED", True),
            review_fork_token_budget=_env_int("REVIEW_FORK_TOKEN_BUDGET", 4_000),
            consolidation_enabled=_env_bool("CONSOLIDATION_ENABLED", False),
            consolidation_interval_s=_env_int("CONSOLIDATION_INTERVAL_S", 900),
            consolidation_batch=_env_int("CONSOLIDATION_BATCH", 50),
            evals_dir=_resolve(_env("MULON_EVALS_DIR", "evals")),
            default_timezone=_env("DEFAULT_TIMEZONE", "Asia/Ho_Chi_Minh"),
            mcp_config_path=_resolve(
                _env("MCP_CONFIG_PATH", "config/mcp_servers.json")
            ),
            mcp_connect_timeout_s=_env_float("MCP_CONNECT_TIMEOUT_S", 20.0),
            mcp_call_timeout_s=_env_float("MCP_CALL_TIMEOUT_S", 60.0),
            scheduler_enabled=_env_bool("SCHEDULER_ENABLED", False),
            scheduler_tick_s=_env_int("SCHEDULER_TICK_S", 30),
            subagent_max_concurrent=_env_int("SUBAGENT_MAX_CONCURRENT", 4),
            subagent_max_llm_calls=_env_int("SUBAGENT_MAX_LLM_CALLS", 15),
            subagent_token_budget=_env_int("SUBAGENT_TOKEN_BUDGET", 60_000),
            subagent_max_seconds=_env_int("SUBAGENT_MAX_SECONDS", 300),
            subagent_digest_max_chars=_env_int(
                "SUBAGENT_DIGEST_MAX_CHARS", 2_000),
            browser_timeout_s=_env_float("BROWSER_TIMEOUT_S", 30.0),
            browser_max_chars=_env_int("BROWSER_MAX_CHARS", 12_000),
        )

    def masked_summary(self) -> dict:
        """Tóm tắt cấu hình an toàn để in/log — secret luôn bị che."""
        return {
            "proxy_base_url": self.proxy_base_url,
            "proxy_api_key": "***" if self.proxy_api_key else "(empty)",
            "model_brain": self.model_brain,
            "model_cheap": self.model_cheap,
            "model_escalated": self.model_escalated,
            "telegram_bot_token": "***" if self.telegram_bot_token else "(missing)",
            "allowed_user_id": self.allowed_user_id if self.allowed_user_id else "(unset)",
            "group_mention_only": self.group_mention_only,
            "debounce_seconds": self.debounce_seconds,
            "db_path": str(self.db_path),
            "dossier_dir": str(self.dossier_dir),
            "workspace_dir": str(self.workspace_dir),
            "context_window_tokens": self.context_window_tokens,
            "tool_result_max_chars": self.tool_result_max_chars,
            "embedder_backend": self.embedder_backend,
            "embedder_model": self.embedder_model,
            "consolidation_enabled": self.consolidation_enabled,
            "review_fork_enabled": self.review_fork_enabled,
            "default_timezone": self.default_timezone,
            "mcp_config_path": str(self.mcp_config_path),
            "scheduler_enabled": self.scheduler_enabled,
            "subagent_max_concurrent": self.subagent_max_concurrent,
        }
