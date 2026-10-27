"""Tích hợp muse2api theo Đường A (T-16).

Đường A đã chốt (26/10/2026): muse2api làm upstream của CLIProxyAPI,
MuLon KHÔNG gọi thẳng muse2api, KHÔNG nới validate_proxy_base_url.
MuLon chỉ gọi model qua proxy local 127.0.0.1:8317 như mọi model khác;
phía sau proxy, CLIProxyAPI route prefix ``muse`` sang muse2api.

Module này chỉ chứa logic thuần túy, không gọi HTTP, không giữ secret:
- Tên model MuLon: ``muse/muse-spark``.
- Tên model phía muse2api: ``muse-spark``.
- Cấu hình upstream cho CLIProxyAPI được sinh từ tham số do người cài
  cung cấp (base-url + tham chiếu key), không lấy từ code.
- Key thật không bao giờ được truyền vào hàm sinh cấu hình: chỉ nhận
  tham chiếu dạng placeholder hoặc Vault, key thật nằm ở máy cài.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Tên model dùng trong MuLon (đi qua proxy 8317) và phía muse2api.
MULON_MODEL = "muse/muse-spark"
MUSE2API_MODEL = "muse-spark"

# Định danh upstream trong cấu hình CLIProxyAPI.
UPSTREAM_NAME = "muse2api"
UPSTREAM_PREFIX = "muse"

# Host local duy nhất được chấp nhận cho upstream muse2api chạy trên
# máy cài. Muse2api là service local (Docker trên máy cài), không phải
# API ngoài, nên upstream của nó không được trỏ ra host lạ.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Cổng proxy model của MuLon (khóa cứng theo luật 1.6.3, xem
# mulon/config.py:validate_proxy_base_url). Hàm kiểm tra dưới đây
# chỉ là guard phụ cho Đường A, không thay thế validation chính.
_MULON_PROXY_PORT = 8317


def is_muse_model(model: str | None) -> bool:
    """Trả True nếu model là model Muse qua muse2api (các dạng tên)."""
    if not model:
        return False
    return model.strip() in {MULON_MODEL, MUSE2API_MODEL, f"openai/{MULON_MODEL}"}


def resolve_muse_model(model: str | None) -> str | None:
    """Chuẩn hóa tên model Muse về dạng MuLon dùng, hoặc None."""
    if not is_muse_model(model):
        return None
    return MULON_MODEL


def build_cliproxy_upstream(base_url: str, api_key_reference: str) -> dict:
    """Sinh mục upstream muse2api cho cấu hình CLIProxyAPI.

    Tham số:
    - ``base_url``: base-url của service muse2api trên máy cài, ví dụ
      dạng ``http://127.0.0.1:<cổng>/v1``. Cổng do người cài quyết
      (theo tài liệu muse2api trên máy đó), code không mặc định cổng.
    - ``api_key_reference``: tham chiếu key, chỉ chấp nhận dạng
      placeholder ``${...}`` hoặc ``vault:...``. Key thật bị từ chối
      ngay tại đây để không bao giờ lọt vào file cấu hình commit lên
      repo.

    Trả về dict đúng dạng ``openai-compatibility`` của CLIProxyAPI
    (xem T-16). Dict này do CLIProxyAPI trên máy cài đọc, MuLon
    không đọc file này và không gọi thẳng base_url này.
    """
    raw_url = (base_url or "").strip()
    try:
        parsed = urlparse(raw_url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        host, port = "", None
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("base-url của muse2api phải dùng http/https.")
    if host not in _LOCAL_HOSTS:
        raise ValueError(
            "base-url của muse2api phải là service local trên máy cài, "
            f"không trỏ ra host lạ (nhận được host={host!r})."
        )
    if port is None:
        raise ValueError("base-url của muse2api phải ghi rõ cổng.")
    ref = (api_key_reference or "").strip()
    if not ref:
        raise ValueError("thiếu tham chiếu key cho muse2api.")
    is_placeholder = ref.startswith("${") and ref.endswith("}")
    is_vault_ref = ref.startswith("vault:")
    if not (is_placeholder or is_vault_ref):
        raise ValueError(
            "chỉ nhận tham chiếu key dạng placeholder ${...} hoặc "
            "vault:..., không nhận key thật vào cấu hình."
        )
    return {
        "openai-compatibility": [
            {
                "name": UPSTREAM_NAME,
                "prefix": UPSTREAM_PREFIX,
                "base-url": raw_url.rstrip("/"),
                "keys": [{"api-key": ref}],
                "models": [{"name": MUSE2API_MODEL, "alias": MUSE2API_MODEL}],
            }
        ]
    }


def muse_model_in_proxy_models(models) -> bool:
    """Kiểm tra model Muse có trong danh sách model của proxy 8317.

    Dùng cho bước nghiệm thu sống 1 của T-16: GET /v1/models qua
    proxy 8317 rồi đối chiếu danh sách trả về, không gọi muse2api
    trực tiếp. ``models`` là list chuỗi hoặc list dict có ``id``/``name``.
    """
    for item in models or []:
        if isinstance(item, dict):
            name = str(item.get("id") or item.get("name") or "")
        else:
            name = str(item)
        if name.strip() in {MUSE2API_MODEL, MULON_MODEL}:
            return True
    return False


def assert_mulon_proxy_unchanged(proxy_base_url: str) -> None:
    """Guard Đường A: proxy model của MuLon vẫn phải là 8317 local.

    Validation chính vẫn nằm ở mulon/config.py; hàm này chỉ để
    test và tài liệu T-16 kiểm tra lại cùng một luật mà không cần
    import toàn bộ Config.
    """
    raw = (proxy_base_url or "").strip()
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        host, port = "", None
    if (
        parsed.scheme not in {"http", "https"}
        or host not in _LOCAL_HOSTS
        or port != _MULON_PROXY_PORT
    ):
        raise ValueError(
            "Đường A yêu cầu proxy model của MuLon vẫn là "
            "127.0.0.1:8317 local, không được dời sang muse2api."
        )
