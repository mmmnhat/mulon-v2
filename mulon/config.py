"""Cấu hình qua biến môi trường.

Nguyên tắc (thiết kế mục 9): mọi đường dẫn và giá trị cá nhân đi qua
env/config — KHÔNG hardcode ID, tên thật hay đường dẫn máy cá nhân vào
code. File này chỉ chứa placeholder trung tính.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("mulon.config")

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


# Sửa 1.6.3: khóa PROXY_BASE_URL về localhost.
#
# MuLon chỉ được gọi model qua proxy local duy nhất của owner
# (127.0.0.1:8317). Nếu PROXY_BASE_URL bị sửa thành host lạ
# (lỗi .env, copy config máy khác, hoặc injection qua env), API key
# model + toàn bộ prompt sẽ gửi thẳng tới host đó. Vì vậy:
# - Mặc định: chỉ chấp nhận host 127.0.0.1 / localhost / ::1
#   và đúng cổng 8317 (scheme http/https, path nào cũng được,
#   mặc định là /v1). Sai -> ValueError, fail-fast, bot không
#   khởi động gateway.
# - Ngoại lệ tường minh duy nhất: đặt MULON_ALLOW_REMOTE_PROXY=1
#   (dùng _env_bool, chấp nhận 1/true/yes/on). Khi đó chỉ log
#   cảnh báo rõ host:port, vẫn khởi động — chỉ dùng khi owner
#   cố ý dời proxy sang máy khác trong mạng nhà và hiểu rủi ro
#   (key + prompt đi tới host đó). Env này KHÔNG phải là cờ
#   "bật tính năng", mà là cờ "tôi chấp nhận rủi ro".
# - Hàm này được gọi ở Config.load() và ModelGateway.__init__
#   (gateway.py, import lười để khỏi vòng import), nên cả đường
#   nạp config lẫn đường dựng gateway trực tiếp đều bị khóa.
# - Voice TTS (voice.py) cũng dùng cfg.proxy_base_url, nên khi
#   config đã qua load() thì TTS cũng bị khóa theo; dựng Config
#   thủ công mà không qua load() thì gateway vẫn chặn ở __init__.

_LOCAL_PROXY_HOSTS = {"127.0.0.1", "localhost", "::1"}
_LOCAL_PROXY_PORT = 8317


def validate_proxy_base_url(url: str) -> None:
    """Fail-fast nếu PROXY_BASE_URL không phải proxy local.

    Raise ValueError khi host/cổng/scheme không đạt, trừ khi
    MULON_ALLOW_REMOTE_PROXY=1 (khi đó chỉ log cảnh báo).
    """
    raw = (url or "").strip()
    scheme = ""
    try:
        parsed = urlparse(raw)
        scheme = parsed.scheme
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        host, port = "", None
    if _env_bool("MULON_ALLOW_REMOTE_PROXY", False):
        logger.warning(
            "MULON_ALLOW_REMOTE_PROXY=1: cho phép proxy model ngoài "
            "localhost (%s:%s) — API key và prompt sẽ gửi tới host "
            "này, chỉ dùng khi owner cố ý dời proxy.", host, port)
        return
    if (scheme not in {"http", "https"}
            or host not in _LOCAL_PROXY_HOSTS
            or port != _LOCAL_PROXY_PORT):
        raise ValueError(
            "PROXY_BASE_URL bị từ chối (fail-fast, sửa 1.6.3): proxy "
            "model của MuLon phải là 127.0.0.1:8317 hoặc "
            "localhost:8317, nhận được "
            f"host={host!r} port={port!r}. Nếu cố ý dùng proxy ngoài, "
            "đặt MULON_ALLOW_REMOTE_PROXY=1 (chỉ khi hiểu rủi ro: "
            "API key model sẽ gửi tới host đó).")


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
    max_llm_calls_per_task: int = 0  # 0 = không giới hạn trần ngân sách lời gọi model
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
    embed_timeout_s: float = 30.0
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
    # Feed chủ động (1.4, spec + quyết định owner 0.2b): LUÔN TỰ
    # ĐỘNG — các giá trị dưới đây chỉ là MẶC ĐỊNH KHỞI TẠO (seed);
    # cài đặt hiệu lực sống trong DB (bảng feed_settings), đổi
    # qua Mini App/chat. KHÔNG có công tắc tắt Feed ở đây: job
    # feed-auto là job hệ thống nội bộ, tách khỏi scheduler
    # thường ở trên (cô lập tick — planning.py).
    feed_auto_cron: str = "0 8,20 * * *"
    feed_quiet_hours: str = "23:00-07:00"
    feed_max_posts_per_day: int = 3
    feed_daily_token_budget: int = 60_000
    # Trần fetch nguồn ghim + tìm kiếm trong 1 lượt collector.
    feed_fetch_max_sources: int = 8
    # Trần leo thang sang browser render khi trang fetch thường
    # quá mỏng (mỗi lượt).
    feed_web_read_max: int = 2
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
    # Thư mục profile cố định để giữ đăng nhập giữa các lần chạy.
    # None (mặc định) = profile tạm như cũ. BROWSER_PROFILE_DIR rỗng
    # cũng hiểu là None.
    browser_profile_dir: Path | None = None

    # --- Phase 4: chủ động + tiếng nói + media (mục 7, 8) ---
    # Proactivity: MẶC ĐỊNH TẮT — chỉ chạy khi PROACTIVITY_ENABLED=1
    # (bài học vụ user xóa toàn bộ job tự động 2026-10-22).
    proactivity_enabled: bool = False
    proactivity_interval_s: int = 1800
    # Khung giờ được phép quét chủ động (giờ địa phương theo
    # default_timezone). Ngoài khung -> bỏ qua, không làm phiền.
    proactivity_active_hours: str = "07:00-23:00"
    # Voice tương tác (mục 8.1): nghe = faster-whisper (optional,
    # lazy) + model rẻ hiểu ngữ; nói = TTS qua proxy (chuẩn OpenAI
    # speech POST /audio/speech vào PROXY_BASE_URL).
    voice_whisper_model: str = "large-v3"
    voice_tts_model: str = "gpt-4o-mini-tts"
    voice_tts_voice: str = "nova"
    # opus -> .ogg (voice note Telegram); mp3 -> .mp3.
    voice_tts_format: str = "opus"
    voice_understand: bool = True
    # Media pipeline (mục 8.2): ffmpeg/ffprobe trên máy.
    media_ffmpeg: str = "ffmpeg"
    media_ffprobe: str = "ffprobe"
    media_timeout_s: float = 300.0
    # Skills (SKILL.md, progressive disclosure): thư mục chứa các
    # thư mục con, mỗi thư mục 1 SKILL.md.
    skills_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "skills")

    # --- Phase 5: cứng hóa (mục 10, 11) ---
    # Cổng eval vàng: pass rate tổng dưới ngưỡng này -> runner thoát 1.
    eval_pass_threshold: float = 0.85
    # Langfuse tracing TUỲ CHỌN: chỉ bật khi đủ cả 3 env. Thiếu một
    # trong ba (hoặc thiếu gói langfuse) -> tracing no-op hoàn toàn,
    # hành vi bot không đổi. Secret chỉ sống trong env, không log.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""
    # Thư mục chứa các gói backup .zip (mulon/backup.py).
    backup_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "backups")

    # --- Phase 6: bề mặt group (mục 16) ---
    # Secure Vault: form web một lần do agent tự host, bind
    # 127.0.0.1. VAULT_PORT=0 = không mở server (lệnh /vault báo rõ).
    vault_port: int = 8765
    vault_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "data" / "vault.json")
    # Token link form: dùng 1 lần, hết hạn sau ngần này giây (~10 phút).
    vault_token_ttl_s: int = 600
    # Sửa 1.6.2: key Fernet cho mã hoá Vault at-rest (TUỲ CHỌN).
    # Tạo bằng: python3 -c "from cryptography.fernet import Fernet;
    # print(Fernet.generate_key().decode())". Để trống = lưu
    # plaintext JSON 0600 như cũ. Đặt key nhưng thiếu gói
    # cryptography hoặc key sai định dạng = vẫn plaintext + cảnh
    # báo log, KHÔNG tự nhận là đã mã hoá. MẤT KEY = MẤT toàn bộ
    # entry đã mã hoá: backup key riêng, tách khỏi file vault.
    # Key này không nằm trong bản dump cấu hình (chỉ có cờ bool).
    vault_encryption_key: str = ""
    # Thẻ ý tưởng tự hết hạn sau ngần này ngày (thiết kế: ~2 tuần).
    idea_ttl_days: int = 14
    # sửa 1.6.2 — Ideas tự sinh OPT-IN, mặc định TẮT (bật bằng
    # IDEAS_AUTO_ENABLED=1 hoặc gạt kv trong Mini App; khi bật,
    # thẻ sinh ra vẫn chỉ chờ user duyệt/"làm luôn", không tự
    # nhắn tin, không tự chạy task). Chu kỳ mặc định 1 ngày.
    ideas_auto_enabled: bool = False
    ideas_auto_interval_s: int = 86400
    # File trong thùng rác Library khôi phục được trong ngần này ngày.
    library_trash_days: int = 30

    # --- 1.2.0: Mini App (bảng điều khiển) + thẻ duyệt ---
    # WEBAPP_URL: URL HTTPS công khai của Mini App (vd qua tunnel
    # cloudflared/tailscale funnel trỏ về 127.0.0.1:WEBAPP_PORT).
    # WEBAPP_APP_NAME: short name của Mini App đăng ký trong
    # BotFather (/myapps) — dùng dựng Direct Link
    # https://t.me/<bot>/<app>?startapp=... Thiếu 1 trong 2 ->
    # nút mở app degrade về inline callback, bot vẫn chạy đủ.
    webapp_url: str = ""
    webapp_app_name: str = ""
    webapp_port: int = 8320
    # --- 1.5.0: Google connectors (Gmail + Calendar) ---
    # Client ID/Secret của OAuth client do owner tạo ở Google
    # Cloud. Có thể để trống ở đây và nhập vào Vault với label
    # google:client_id / google:client_secret (env thắng).
    # Refresh token KHÔNG qua env — chỉ ở Vault.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_legacy_connectors: bool = False
    # Thẻ duyệt (policy nấc "ask") hết hạn sau ngần này giây.
    approval_timeout_s: float = 60.0

    # --- 1.3.0: MCP Marketplace (spec marketplace mục 10.7 +
    # quyết định owner 15.3) ---
    # Chỉ server miễn phí + local stdio; không remote, không paid.
    marketplace_enabled: bool = True
    # Bundle tuyển chọn đóng gói cùng bản phát hành (nguồn cài đặt
    # chính) + snapshot catalog đã tự tải về (chỉ dữ kiện niêm yết).
    marketplace_curated_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "config"
        / "marketplace_curated.json")
    marketplace_catalog_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "data"
        / "marketplace_catalog.json")
    # Sổ marketplace: installed registry + operation journal +
    # trạng thái restart/catalog (JSON nguyên tử, không chứa
    # secret value — bí mật chỉ ở Vault).
    marketplace_store_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "data"
        / "marketplace.json")
    # Catalog tự cập nhật (owner duyệt riêng 2026-10-24): file
    # tuyển chọn duy trì tại repo GitHub của dự án; kiểm tra lúc
    # khởi động + hàng tuần, kiểm checksum trước khi thay, CHỈ
    # cập nhật dữ kiện — không bao giờ tự cài server.
    marketplace_catalog_url: str = (
        "https://raw.githubusercontent.com/mmmnhat/mulon-v2/main"
        "/config/marketplace_curated.json")
    marketplace_catalog_auto_update: bool = True
    marketplace_catalog_check_interval_s: int = 7 * 24 * 3600
    marketplace_catalog_timeout_s: float = 15.0
    # TTL của plan + mỗi stage duyệt operation (giây).
    marketplace_operation_ttl_s: int = 900
    # Ngưỡng điểm bảo mật để được cài nhanh từ listing có điểm.
    marketplace_security_min_score: float = 7.0
    # Trần kích thước payload import/catalog (byte).
    marketplace_max_input_bytes: int = 65536

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> "Config":
        """Nạp .env (nếu có) rồi đọc env. Không ghi secret ra bất cứ đâu."""
        try:
            from dotenv import load_dotenv

            load_dotenv(dotenv_path=env_file)  # mặc định: .env ở thư mục chạy
        except Exception:
            pass
        cfg = cls(
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
            max_llm_calls_per_task=_env_int("MAX_LLM_CALLS_PER_TASK", 0),  # 0 = không giới hạn
            max_task_seconds=_env_int("MAX_TASK_SECONDS", 600),
            verify_max_retries=_env_int("VERIFY_MAX_RETRIES", 2),
            llm_timeout_s=_env_int("LLM_TIMEOUT_S", 60),
            allow_outside_workspace=_env_bool("ALLOW_OUTSIDE_WORKSPACE", False),
            embedder_backend=_env("EMBEDDER_BACKEND", "fastembed"),
            embedder_model=_env("EMBEDDER_MODEL", "BAAI/bge-m3"),
            embedder_stub_dim=_env_int("EMBEDDER_STUB_DIM", 128),
            embed_timeout_s=_env_float("EMBED_TIMEOUT_S", 30.0),
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
            feed_auto_cron=_env("FEED_AUTO_CRON", "0 8,20 * * *"),
            feed_quiet_hours=_env("FEED_QUIET_HOURS", "23:00-07:00"),
            feed_max_posts_per_day=_env_int(
                "FEED_MAX_POSTS_PER_DAY", 3),
            feed_daily_token_budget=_env_int(
                "FEED_DAILY_TOKEN_BUDGET", 60_000),
            feed_fetch_max_sources=_env_int(
                "FEED_FETCH_MAX_SOURCES", 8),
            feed_web_read_max=_env_int("FEED_WEB_READ_MAX", 2),
            subagent_max_concurrent=_env_int("SUBAGENT_MAX_CONCURRENT", 4),
            subagent_max_llm_calls=_env_int("SUBAGENT_MAX_LLM_CALLS", 15),
            subagent_token_budget=_env_int("SUBAGENT_TOKEN_BUDGET", 60_000),
            subagent_max_seconds=_env_int("SUBAGENT_MAX_SECONDS", 300),
            subagent_digest_max_chars=_env_int(
                "SUBAGENT_DIGEST_MAX_CHARS", 2_000),
            browser_timeout_s=_env_float("BROWSER_TIMEOUT_S", 30.0),
            browser_max_chars=_env_int("BROWSER_MAX_CHARS", 12_000),
            browser_profile_dir=(
                _resolve(_env("BROWSER_PROFILE_DIR", ""))
                if _env("BROWSER_PROFILE_DIR", "") else None
            ),
            proactivity_enabled=_env_bool("PROACTIVITY_ENABLED", False),
            proactivity_interval_s=_env_int("PROACTIVITY_INTERVAL_S", 1800),
            proactivity_active_hours=_env(
                "PROACTIVITY_ACTIVE_HOURS", "07:00-23:00"),
            voice_whisper_model=_env("VOICE_WHISPER_MODEL", "large-v3"),
            voice_tts_model=_env("VOICE_TTS_MODEL", "gpt-4o-mini-tts"),
            voice_tts_voice=_env("VOICE_TTS_VOICE", "nova"),
            voice_tts_format=_env("VOICE_TTS_FORMAT", "opus"),
            voice_understand=_env_bool("VOICE_UNDERSTAND", True),
            media_ffmpeg=_env("MEDIA_FFMPEG", "ffmpeg"),
            media_ffprobe=_env("MEDIA_FFPROBE", "ffprobe"),
            media_timeout_s=_env_float("MEDIA_TIMEOUT_S", 300.0),
            skills_dir=_resolve(_env("SKILLS_DIR", "skills")),
            eval_pass_threshold=_env_float("EVAL_PASS_THRESHOLD", 0.85),
            langfuse_public_key=_env("LANGFUSE_PUBLIC_KEY", ""),
            langfuse_secret_key=_env("LANGFUSE_SECRET_KEY", ""),
            langfuse_host=_env("LANGFUSE_HOST", ""),
            backup_dir=_resolve(_env("BACKUP_DIR", "backups")),
            vault_port=_env_int("VAULT_PORT", 8765),
            vault_path=_resolve(_env("VAULT_PATH", "data/vault.json")),
            vault_token_ttl_s=_env_int("VAULT_TOKEN_TTL_S", 600),
            vault_encryption_key=_env("VAULT_ENCRYPTION_KEY", ""),
            idea_ttl_days=_env_int("IDEA_TTL_DAYS", 14),
            ideas_auto_enabled=_env_bool("IDEAS_AUTO_ENABLED", False),
            ideas_auto_interval_s=_env_int("IDEAS_AUTO_INTERVAL_S",
                                          86400),
            library_trash_days=_env_int("LIBRARY_TRASH_DAYS", 30),
            webapp_url=_env("WEBAPP_URL", ""),
            webapp_app_name=_env("WEBAPP_APP_NAME", ""),
            webapp_port=_env_int("WEBAPP_PORT", 8320),
            google_client_id=_env("GOOGLE_CLIENT_ID", ""),
            google_client_secret=_env("GOOGLE_CLIENT_SECRET", ""),
            google_legacy_connectors=_env_bool("GOOGLE_LEGACY_CONNECTORS", False),
            approval_timeout_s=_env_float("APPROVAL_TIMEOUT_S", 60.0),
            marketplace_enabled=_env_bool("MARKETPLACE_ENABLED", True),
            marketplace_curated_path=_resolve(_env(
                "MARKETPLACE_CURATED_PATH",
                "config/marketplace_curated.json")),
            marketplace_catalog_path=_resolve(_env(
                "MARKETPLACE_CATALOG_PATH",
                "data/marketplace_catalog.json")),
            marketplace_store_path=_resolve(_env(
                "MARKETPLACE_STORE_PATH", "data/marketplace.json")),
            marketplace_catalog_url=_env(
                "MARKETPLACE_CATALOG_URL",
                "https://raw.githubusercontent.com/mmmnhat/mulon-v2"
                "/main/config/marketplace_curated.json"),
            marketplace_catalog_auto_update=_env_bool(
                "MARKETPLACE_CATALOG_AUTO_UPDATE", True),
            marketplace_catalog_check_interval_s=_env_int(
                "MARKETPLACE_CATALOG_CHECK_INTERVAL_S", 7 * 24 * 3600),
            marketplace_catalog_timeout_s=_env_float(
                "MARKETPLACE_CATALOG_TIMEOUT_S", 15.0),
            marketplace_operation_ttl_s=_env_int(
                "MARKETPLACE_OPERATION_TTL_S", 900),
            marketplace_security_min_score=_env_float(
                "MARKETPLACE_SECURITY_MIN_SCORE", 7.0),
            marketplace_max_input_bytes=_env_int(
                "MARKETPLACE_MAX_INPUT_BYTES", 65536),
        )
        # Sửa 1.6.3: khóa proxy về localhost, fail-fast tại load().
        validate_proxy_base_url(cfg.proxy_base_url)
        return cfg

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
            "feed_auto_cron": self.feed_auto_cron,
            "feed_quiet_hours": self.feed_quiet_hours,
            "feed_max_posts_per_day": self.feed_max_posts_per_day,
            "feed_daily_token_budget": self.feed_daily_token_budget,
            "subagent_max_concurrent": self.subagent_max_concurrent,
            "browser_profile_dir": (
                str(self.browser_profile_dir)
                if self.browser_profile_dir else None
            ),
            "proactivity_enabled": self.proactivity_enabled,
            "proactivity_active_hours": self.proactivity_active_hours,
            "voice_tts_model": self.voice_tts_model,
            "voice_tts_voice": self.voice_tts_voice,
            "skills_dir": str(self.skills_dir),
            "eval_pass_threshold": self.eval_pass_threshold,
            "langfuse_enabled": bool(
                self.langfuse_public_key and self.langfuse_secret_key
                and self.langfuse_host
            ),
            "langfuse_host": self.langfuse_host or "(unset)",
            "backup_dir": str(self.backup_dir),
            "vault_port": self.vault_port,
            "vault_path": str(self.vault_path),
            # Sửa 1.6.2: chỉ cờ bool — giá trị key KHÔNG BAO GIỜ
            # xuất hiện trong dump cấu hình.
            "vault_encryption_configured": bool(self.vault_encryption_key),
            "idea_ttl_days": self.idea_ttl_days,
            "ideas_auto_enabled": self.ideas_auto_enabled,
            "ideas_auto_interval_s": self.ideas_auto_interval_s,
            "library_trash_days": self.library_trash_days,
            "webapp_configured": bool(self.webapp_url
                                      and self.webapp_app_name),
            "webapp_port": self.webapp_port,
            "approval_timeout_s": self.approval_timeout_s,
            "marketplace_enabled": self.marketplace_enabled,
            "marketplace_catalog_auto_update":
                self.marketplace_catalog_auto_update,
            "marketplace_security_min_score":
                self.marketplace_security_min_score,
        }
