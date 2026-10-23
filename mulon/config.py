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
        }
