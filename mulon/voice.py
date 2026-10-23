"""Voice hai chiều — LỚP TƯƠNG TÁC giọng nói với user (mục 8.1).

Đây là "giọng của agent" khi nói chuyện với user, tách bạch hẳn
với công cụ media ở mục 8.2 (SenseVoice/Piper chỉ là tool pipeline,
không bao giờ là giọng giao tiếp):

- NGHE: faster-whisper (optional, lazy-load, chạy ngoài event loop
  qua thread) chép lời -> transcript thô đi qua 1 lượt MODEL RẺ
  "hiểu ngữ": sửa lỗi nhận diện theo ngữ cảnh, khôi phục dấu câu /
  tên riêng, trích ý định. Kết quả: {text_tho, text_da_hieu,
  y_dinh}. Vắng faster-whisper -> lỗi sạch có cấu trúc, không sập.
- NÓI: TTS qua PROXY theo chuẩn OpenAI speech
  (POST {PROXY_BASE_URL}/audio/speech, model/voice qua env — vẫn
  chỉ qua proxy local, không API chính thức). Proxy không hỗ trợ
  speech -> degrade sạch {ok: False}.

Không ghi secret vào log/kết quả ở module này.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("mulon.voice")

SttFn = Callable[..., tuple[str, list[dict]]]

_UNDERSTAND_SYSTEM = (
    "Bạn nhận bản chép lời THÔ từ nhận diện giọng nói (có thể sai "
    "chữ, thiếu dấu, lẫn tiếng Anh). Hãy: 1) sửa lỗi nhận diện theo "
    "ngữ cảnh tiếng Việt tự nhiên, khôi phục dấu câu và tên riêng; "
    "2) trích ý định chính của người nói. Chỉ trả JSON: "
    "{\"text_da_hieu\": \"bản đã sửa\", \"y_dinh\": \"ý định ngắn\"}. "
    "Không thêm chữ nào ngoài JSON."
)

_FORMAT_EXT = {"opus": "ogg", "mp3": "mp3", "wav": "wav",
               "aac": "aac", "flac": "flac", "pcm": "pcm"}


# ---------------------------------------------------------------------------
# STT: faster-whisper (optional, lazy)
# ---------------------------------------------------------------------------

_model_cache: dict[str, object] = {}
_model_lock = threading.Lock()


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _load_whisper_model(cfg):
    """Nạp model 1 lần, cache theo tên. CHỈ gọi từ thread nền."""
    name = cfg.voice_whisper_model
    with _model_lock:
        model = _model_cache.get(name)
        if model is None:
            from faster_whisper import WhisperModel

            model = WhisperModel(name)
            _model_cache[name] = model
        return model


def _transcribe_blocking(cfg, audio_path) -> tuple[str, list[dict]]:
    """Chép lời đồng bộ (blocking) — luôn chạy qua asyncio.to_thread."""
    model = _load_whisper_model(cfg)
    segments, _info = model.transcribe(str(audio_path), language="vi")
    segs = [
        {"start": round(float(s.start), 2),
         "end": round(float(s.end), 2),
         "text": (s.text or "").strip()}
        for s in segments
    ]
    text = " ".join(s["text"] for s in segs if s["text"]).strip()
    return text, segs


def _unavailable(reason: str) -> dict:
    return {"ok": False, "unavailable": True,
            "error": f"stt_unavailable: {reason}"}


async def transcribe_audio(
    cfg,
    audio_path,
    gateway=None,
    *,
    stt_fn: Optional[SttFn] = None,
    understand: Optional[bool] = None,
) -> dict:
    """File audio -> {ok, text_tho, text_da_hieu, y_dinh, segments}.

    stt_fn tiêm được cho test; mặc định là faster-whisper thật.
    Bước hiểu ngữ dùng gateway (model rẻ) khi có; lỗi ở bước đó
    thì text_da_hieu = bản thô, không coi là thất bại.
    """
    if stt_fn is None:
        if not whisper_available():
            return _unavailable(
                "chưa cài faster-whisper (pip install faster-whisper)")
        stt_fn = _transcribe_blocking
    try:
        raw, segments = await asyncio.wait_for(
            asyncio.to_thread(stt_fn, cfg, audio_path),
            timeout=cfg.media_timeout_s,
        )
    except asyncio.TimeoutError:
        return {"ok": False,
                "error": f"stt_timeout: quá {cfg.media_timeout_s}s"}
    except Exception as exc:
        return {"ok": False,
                "error": f"stt_failed: {type(exc).__name__}: {exc}"}

    result = {"ok": True, "text_tho": raw, "text_da_hieu": raw,
              "y_dinh": "", "segments": segments}
    want_understand = cfg.voice_understand if understand is None \
        else understand
    if gateway is not None and want_understand and raw:
        try:
            comp = await gateway.complete(
                [{"role": "system", "content": _UNDERSTAND_SYSTEM},
                 {"role": "user", "content": raw}],
                model=cfg.model_cheap, temperature=0.1,
                purpose="voice_understand",
            )
            parsed = _parse_understanding(comp.text)
            if parsed:
                result["text_da_hieu"] = parsed.get("text_da_hieu") or raw
                result["y_dinh"] = parsed.get("y_dinh") or ""
        except Exception as exc:
            logger.warning("hiểu ngữ voice lỗi (giữ bản thô): %s", exc)
    return result


def _parse_understanding(text: str) -> Optional[dict]:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# TTS: qua proxy, chuẩn OpenAI speech
# ---------------------------------------------------------------------------

async def synthesize_speech(
    cfg,
    text: str,
    out_path=None,
    *,
    transport=None,
) -> dict:
    """Text -> file audio qua proxy. Trả {ok, path, format, bytes}.

    transport tiêm được cho test (httpx.MockTransport). Proxy trả
    lỗi / không hỗ trợ speech -> {ok: False, error} sạch.
    """
    import httpx

    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "tts_empty_text"}
    fmt = (cfg.voice_tts_format or "opus").lower()
    url = cfg.proxy_base_url.rstrip("/") + "/audio/speech"
    payload = {"model": cfg.voice_tts_model, "voice": cfg.voice_tts_voice,
               "input": text, "response_format": fmt}
    headers = {"Authorization": f"Bearer {cfg.proxy_api_key}"}
    try:
        # trust_env=False: proxy LOCAL do cấu hình chỉ định — biến
        # HTTP_PROXY/NO_PROXY của môi trường không được chuyển hướng.
        async with httpx.AsyncClient(
            timeout=max(30.0, cfg.llm_timeout_s), transport=transport,
            trust_env=False,
        ) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except Exception as exc:
        return {"ok": False,
                "error": f"tts_unavailable: {type(exc).__name__}: {exc}"}
    if resp.status_code != 200:
        detail = (resp.text or "")[:200].replace("\n", " ")
        return {"ok": False,
                "error": f"tts_failed: HTTP {resp.status_code}: {detail}"}
    if out_path is None:
        out_dir = Path(cfg.workspace_dir) / "voice"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        out_path = out_dir / f"tts-{stamp}.{_FORMAT_EXT.get(fmt, 'mp3')}"
    else:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(resp.content)
    return {"ok": True, "path": str(out_path), "format": fmt,
            "bytes": len(resp.content)}


# ---------------------------------------------------------------------------
# Service bọc cho bề mặt Telegram
# ---------------------------------------------------------------------------

class VoiceService:
    """Mặt tiền voice cho telegram_bot: transcribe_file + speak_to_file."""

    def __init__(self, cfg, gateway=None):
        self.cfg = cfg
        self.gateway = gateway

    def stt_available(self) -> bool:
        return whisper_available()

    async def transcribe_file(self, audio_path) -> dict:
        return await transcribe_audio(self.cfg, audio_path, self.gateway)

    async def speak_to_file(self, text: str, out_path=None) -> dict:
        return await synthesize_speech(self.cfg, text, out_path)
