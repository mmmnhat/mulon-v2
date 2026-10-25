"""Media pipeline tools (thiết kế mục 8.2) — Phase 4.

ĐÂY LÀ CÔNG CỤ LÀM VIỆC cho pipeline video (tải nguồn -> chép lời
-> dựng), KHÔNG phải lớp tương tác giọng nói với user (lớp đó ở
`mulon/voice.py`). Theo chốt của user: SenseVoice (ASR timecode)
và Piper (TTS offline) thuộc nhóm công cụ này; bản này dùng chung
lớp faster-whisper của voice cho `media_transcribe` và giữ đúng
ranh giới vai trò — tool media không bao giờ là giọng giao tiếp.

Bọc ffmpeg/ffprobe thành tool của registry:
- media_probe: thời lượng, độ phân giải, codec.
- media_extract_audio: tách track audio ra .mp3.
- media_trim: cắt [start, start+duration].
- media_burn_subs: đốt phụ đề .ass/.srt (libass) vào video.
- media_frames: trích N frame đều nhau ra ảnh PNG để agent "xem".
- media_transcribe: chép lời file media (whisper, có timecode).

Thiếu ffmpeg/ffprobe -> tool trả unavailable SẠCH, không sập.
Mọi đường dẫn neo trong workspace như các file tool khác.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from . import voice as voice_mod
from .tools import ToolSpec, _resolve_in_workspace

logger = logging.getLogger("mulon.media")


def ffmpeg_available(cfg) -> bool:
    return shutil.which(cfg.media_ffmpeg) is not None


def ffprobe_available(cfg) -> bool:
    return shutil.which(cfg.media_ffprobe) is not None


def _unavailable(what: str) -> dict:
    return {"ok": False, "unavailable": True,
            "error": f"media_unavailable: thiếu {what} trên máy"}


async def _run(args: list[str], timeout: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(),
                                          timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return (proc.returncode or 0,
            out.decode("utf-8", "replace"),
            err.decode("utf-8", "replace"))


def _default_out(cfg, src: Path, suffix: str, ext: str) -> Path:
    out_dir = Path(cfg.workspace_dir) / "media"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{src.stem}-{suffix}.{ext}"


async def probe(cfg, path) -> dict:
    if not ffprobe_available(cfg):
        return _unavailable("ffprobe")
    src = _resolve_in_workspace(cfg, str(path))
    if not src.is_file():
        return {"ok": False, "error": f"không thấy file: {path}"}
    try:
        rc, out, err = await _run(
            [cfg.media_ffprobe, "-v", "error", "-show_format",
             "-show_streams", "-of", "json", str(src)],
            timeout=60,
        )
    except asyncio.TimeoutError:
        return {"ok": False, "error": "ffprobe timeout"}
    if rc != 0:
        return {"ok": False, "error": f"ffprobe lỗi: {err[-300:]}"}
    try:
        data = json.loads(out)
    except Exception:
        return {"ok": False, "error": "ffprobe trả JSON không đọc được"}
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    fmt = data.get("format") or {}
    duration = fmt.get("duration") or v.get("duration") or 0
    return {
        "ok": True,
        "path": str(src),
        "duration_s": round(float(duration), 3),
        "width": v.get("width"),
        "height": v.get("height"),
        "video_codec": v.get("codec_name"),
        "audio_codec": a.get("codec_name"),
        "format": fmt.get("format_name"),
        "size_bytes": int(fmt.get("size") or 0),
    }


async def extract_audio(cfg, path, out=None) -> dict:
    if not ffmpeg_available(cfg):
        return _unavailable("ffmpeg")
    src = _resolve_in_workspace(cfg, str(path))
    if not src.is_file():
        return {"ok": False, "error": f"không thấy file: {path}"}
    dst = (_resolve_in_workspace(cfg, str(out)) if out
           else _default_out(cfg, src, "audio", "mp3"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        rc, _o, err = await _run(
            [cfg.media_ffmpeg, "-y", "-i", str(src), "-vn",
             "-codec:a", "libmp3lame", "-q:a", "4", str(dst)],
            timeout=cfg.media_timeout_s,
        )
    except asyncio.TimeoutError:
        return {"ok": False, "error": "ffmpeg timeout (extract_audio)"}
    if rc != 0 or not dst.is_file():
        return {"ok": False, "error": f"ffmpeg lỗi: {err[-300:]}"}
    return {"ok": True, "path": str(dst), "source": str(src)}


async def trim(cfg, path, start_s: float = 0.0,
               duration_s: Optional[float] = None, out=None) -> dict:
    if not ffmpeg_available(cfg):
        return _unavailable("ffmpeg")
    src = _resolve_in_workspace(cfg, str(path))
    if not src.is_file():
        return {"ok": False, "error": f"không thấy file: {path}"}
    dst = (_resolve_in_workspace(cfg, str(out)) if out
           else _default_out(cfg, src, "trim", src.suffix.lstrip(".") or "mp4"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    args = [cfg.media_ffmpeg, "-y", "-ss", str(float(start_s)),
            "-i", str(src)]
    if duration_s:
        args += ["-t", str(float(duration_s))]
    args += ["-c", "copy", str(dst)]
    try:
        rc, _o, err = await _run(args, timeout=cfg.media_timeout_s)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "ffmpeg timeout (trim)"}
    if rc != 0 or not dst.is_file():
        return {"ok": False, "error": f"ffmpeg lỗi: {err[-300:]}"}
    return {"ok": True, "path": str(dst), "source": str(src),
            "start_s": float(start_s), "duration_s": duration_s}


def _escape_filter_path(path: Path) -> str:
    """Escape đường dẫn cho filter subtitles của ffmpeg."""
    text = str(path).replace("\\", "/")
    return text.replace(":", "\\:").replace("'", "\\'")


async def burn_subs(cfg, path, subs_path, out=None) -> dict:
    if not ffmpeg_available(cfg):
        return _unavailable("ffmpeg")
    src = _resolve_in_workspace(cfg, str(path))
    subs = _resolve_in_workspace(cfg, str(subs_path))
    if not src.is_file():
        return {"ok": False, "error": f"không thấy file: {path}"}
    if not subs.is_file():
        return {"ok": False, "error": f"không thấy phụ đề: {subs_path}"}
    dst = (_resolve_in_workspace(cfg, str(out)) if out
           else _default_out(cfg, src, "subbed", "mp4"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = f"subtitles={_escape_filter_path(subs)}"
    try:
        rc, _o, err = await _run(
            [cfg.media_ffmpeg, "-y", "-i", str(src), "-vf", vf,
             "-codec:a", "copy", str(dst)],
            timeout=cfg.media_timeout_s,
        )
    except asyncio.TimeoutError:
        return {"ok": False, "error": "ffmpeg timeout (burn_subs)"}
    if rc != 0 or not dst.is_file():
        return {"ok": False, "error": f"ffmpeg lỗi: {err[-300:]}"}
    return {"ok": True, "path": str(dst), "source": str(src),
            "subs": str(subs)}


async def frames(cfg, path, count: int = 3, out_dir=None) -> dict:
    """Trích `count` frame chia đều theo thời lượng -> PNG."""
    if not ffmpeg_available(cfg):
        return _unavailable("ffmpeg")
    src = _resolve_in_workspace(cfg, str(path))
    if not src.is_file():
        return {"ok": False, "error": f"không thấy file: {path}"}
    info = await probe(cfg, path)
    if not info.get("ok"):
        return info
    duration = float(info.get("duration_s") or 0)
    if duration <= 0:
        return {"ok": False, "error": "không đọc được thời lượng media"}
    count = max(1, min(int(count), 12))
    dst_dir = (_resolve_in_workspace(cfg, str(out_dir)) if out_dir
               else Path(cfg.workspace_dir) / "media" /
               f"{src.stem}-frames")
    dst_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for i in range(count):
        at = duration * (i + 0.5) / count
        dst = dst_dir / f"frame-{i + 1:02d}.png"
        try:
            rc, _o, err = await _run(
                [cfg.media_ffmpeg, "-y", "-ss", f"{at:.2f}",
                 "-i", str(src), "-frames:v", "1", str(dst)],
                timeout=60,
            )
        except asyncio.TimeoutError:
            return {"ok": False, "error": "ffmpeg timeout (frames)"}
        if rc != 0 or not dst.is_file():
            return {"ok": False, "error": f"ffmpeg lỗi: {err[-300:]}"}
        paths.append(str(dst))
    return {"ok": True, "frames": paths, "count": len(paths),
            "source": str(src)}


async def transcribe(cfg, path, gateway=None) -> dict:
    """Chép lời file media cho pipeline (kèm timecode từng đoạn).

    Dùng chung lớp faster-whisper với voice tương tác nhưng vai
    trò khác hẳn: đây là CÔNG CỤ dựng video (mục 8.2), kết quả đi
    vào pipeline dịch/lồng tiếng — không phải kênh nói chuyện với
    user. Không qua bước "hiểu ngữ" (pipeline cần bản thô +
    timecode nguyên vẹn).
    """
    src = _resolve_in_workspace(cfg, str(path))
    if not src.is_file():
        return {"ok": False, "error": f"không thấy file: {path}"}
    return await voice_mod.transcribe_audio(
        cfg, src, gateway=None, understand=False)


async def generate_image(cfg, prompt: str, model: str = "agnes-image-2.1-flash",
                         size: str = "1024x1024", image_path: str = "",
                         vault_store=None) -> dict:
    """Sinh hoặc chỉnh sửa ảnh AI (Text-to-Image & Image-to-Image) qua API Agnes AI (OpenAI-compatible)."""
    import asyncio
    import base64
    import os
    import time
    import httpx

    # Tìm API key trong Vault
    api_key = ""
    if vault_store is not None:
        try:
            labels = vault_store.labels()
            for item in labels:
                lbl = str(item.get("label", "")).lower()
                if "agnes" in lbl:
                    api_key = vault_store.resolve(item.get("ref", ""))
                    if api_key:
                        break
            if not api_key:
                for item in labels:
                    lbl = str(item.get("label", "")).lower()
                    if "api" in lbl or "key" in lbl:
                        api_key = vault_store.resolve(item.get("ref", ""))
                        if api_key:
                            break
        except Exception as exc:
            logger.warning("Đọc vault cho generate_image lỗi: %s", exc)

    if not api_key:
        api_key = os.environ.get("AGNES_AI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")

    if not api_key:
        return {
            "ok": False,
            "error": "Chưa có API key để sinh ảnh. Hãy gọi tool request_vault_secret(label='agnes_ai:api_key') để yêu cầu chủ nhân lưu key vào Kho an toàn (Vault).",
        }

    extra_body = None
    if image_path and str(image_path).strip():
        clean_img = str(image_path).strip()
        if clean_img.startswith("http://") or clean_img.startswith("https://"):
            extra_body = {"image": [clean_img], "response_format": "url"}
        else:
            try:
                src_path = _resolve_in_workspace(cfg, clean_img)
                if src_path.is_file():
                    ext = src_path.suffix.lower().lstrip(".") or "jpeg"
                    if ext == "jpg":
                        ext = "jpeg"
                    try:
                        from PIL import Image
                        from io import BytesIO
                        with Image.open(src_path) as im:
                            if im.mode not in ("RGB", "L"):
                                im = im.convert("RGB")
                            if max(im.size) > 1024:
                                im.thumbnail((1024, 1024))
                            buf = BytesIO()
                            im.save(buf, format="JPEG", quality=85)
                            b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
                            data_uri = f"data:image/jpeg;base64,{b64_str}"
                    except Exception:
                        raw_bytes = src_path.read_bytes()
                        b64_str = base64.b64encode(raw_bytes).decode("utf-8")
                        data_uri = f"data:image/{ext};base64,{b64_str}"
                    extra_body = {"image": [data_uri], "response_format": "url"}
                else:
                    logger.warning("Không tìm thấy file ảnh i2i: %s", clean_img)
            except Exception as exc:
                logger.warning("Xử lý ảnh i2i thất bại: %s", exc)

    endpoint = "https://apihub.agnes-ai.com/v1/images/generations"
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
    }
    if extra_body:
        payload["extra_body"] = extra_body

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "MulonBot/1.0",
    }

    timeout_s = 120.0 if extra_body else 60.0
    data = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    break
                elif resp.status_code == 503 and attempt < 2:
                    # Server bận/queue full -> đợi 2.5s rồi thử lại
                    await asyncio.sleep(2.5)
                    continue
                else:
                    return {"ok": False, "error": f"Lỗi từ nhà cung cấp ({resp.status_code}): {resp.text[:300]}"}
        except httpx.TimeoutException:
            if attempt < 2:
                await asyncio.sleep(2.0)
                continue
            return {"ok": False, "error": f"Quá thời gian chờ phản hồi ({int(timeout_s)}s) từ dịch vụ tạo ảnh."}
        except Exception as exc:
            return {"ok": False, "error": f"Lỗi kết nối khi gọi API sinh ảnh: {exc}"}

    if not data:
        return {"ok": False, "error": "Không nhận được phản hồi từ dịch vụ tạo ảnh"}

    items = data.get("data", [])
    if not items:
        return {"ok": False, "error": "API không trả về ảnh nào"}

    img_url = items[0].get("url") or ""
    b64 = items[0].get("b64_json") or ""

    workdir = Path(cfg.workspace_dir).resolve() / "images"
    workdir.mkdir(parents=True, exist_ok=True)
    filename = f"gen_{int(time.time())}.png"
    local_path = workdir / filename

    saved = False
    if b64:
        try:
            local_path.write_bytes(base64.b64decode(b64))
            saved = True
        except Exception:
            pass

    if not saved and img_url:
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                img_resp = await client.get(img_url)
                if img_resp.status_code == 200:
                    local_path.write_bytes(img_resp.content)
                    saved = True
        except Exception:
            pass

    return {
        "ok": True,
        "prompt": prompt,
        "image_path": image_path,
        "url": img_url,
        "local_path": str(local_path) if saved else "",
        "message": f"Đã sinh ảnh thành công: {local_path if saved else img_url}",
    }


def register_media_tools(registry, cfg, gateway=None, vault_store=None):
    """Đăng ký các tool media vào registry chung."""

    async def media_probe(path: str):
        return await probe(cfg, path)

    async def media_extract_audio(path: str, out: str = ""):
        return await extract_audio(cfg, path, out or None)

    async def media_trim(path: str, start_s: float = 0.0,
                         duration_s: float = 0.0, out: str = ""):
        return await trim(cfg, path, start_s,
                          duration_s or None, out or None)

    async def media_burn_subs(path: str, subs_path: str, out: str = ""):
        return await burn_subs(cfg, path, subs_path, out or None)

    async def media_frames(path: str, count: int = 3):
        return await frames(cfg, path, count)

    async def media_transcribe(path: str):
        return await transcribe(cfg, path, gateway)

    async def generate_image_tool(prompt: str, model: str = "agnes-image-2.1-flash",
                                  size: str = "1024x1024", image_path: str = ""):
        return await generate_image(cfg, prompt, model=model, size=size, image_path=image_path, vault_store=vault_store)

    specs = [
        ("generate_image",
         "Sinh hoặc chỉnh sửa ảnh AI (Text-to-Image & Image-to-Image). Hỗ trợ truyền 'image_path' (đường dẫn ảnh trong workspace hoặc URL) để biến đổi, giữ nét nhân vật hoặc chuyển phong cách từ ảnh có sẵn qua Agnes AI. Tự động lấy API key từ Vault.",
         {"type": "object",
          "properties": {"prompt": {"type": "string", "description": "Mô tả chi tiết nội dung ảnh muốn tạo hoặc các thay đổi so với ảnh gốc"},
                         "model": {"type": "string", "default": "agnes-image-2.1-flash", "description": "Tên model tạo ảnh (agnes-image-2.1-flash, agnes-image-2.0-flash...)"},
                         "size": {"type": "string", "default": "1024x1024", "description": "Kích thước ảnh"},
                         "image_path": {"type": "string", "default": "", "description": "Đường dẫn file ảnh cục bộ (trong workspace/uploads) hoặc URL ảnh mẫu để thực hiện Image-to-Image (i2i)"}},
          "required": ["prompt"]}, 150, generate_image_tool),
        ("media_probe",
         "Đọc thông tin media bằng ffprobe: thời lượng, độ phân "
         "giải, codec video/audio, dung lượng.",
         {"type": "object",
          "properties": {"path": {"type": "string"}},
          "required": ["path"]}, 60, media_probe),
        ("media_extract_audio",
         "Tách track audio của file media ra .mp3 (cho pipeline "
         "chép lời/dịch).",
         {"type": "object",
          "properties": {"path": {"type": "string"},
                         "out": {"type": "string", "default": ""}},
          "required": ["path"]}, 320, media_extract_audio),
        ("media_trim",
         "Cắt media từ start_s, dài duration_s giây (0 = tới hết).",
         {"type": "object",
          "properties": {"path": {"type": "string"},
                         "start_s": {"type": "number", "default": 0},
                         "duration_s": {"type": "number", "default": 0},
                         "out": {"type": "string", "default": ""}},
          "required": ["path"]}, 320, media_trim),
        ("media_burn_subs",
         "Đốt phụ đề .ass/.srt vào video (hardsub bằng libass).",
         {"type": "object",
          "properties": {"path": {"type": "string"},
                         "subs_path": {"type": "string"},
                         "out": {"type": "string", "default": ""}},
          "required": ["path", "subs_path"]}, 600, media_burn_subs),
        ("media_frames",
         "Trích N frame chia đều theo thời lượng ra ảnh PNG để "
         "xem nội dung video.",
         {"type": "object",
          "properties": {"path": {"type": "string"},
                         "count": {"type": "integer", "default": 3}},
          "required": ["path"]}, 120, media_frames),
        ("media_transcribe",
         "Chép lời file media bằng whisper, kèm timecode từng "
         "đoạn — công cụ pipeline video (dịch/lồng tiếng), không "
         "phải giọng tương tác với user.",
         {"type": "object",
          "properties": {"path": {"type": "string"}},
          "required": ["path"]}, 320, media_transcribe),
    ]
    for name, desc, params, timeout, handler in specs:
        registry.register(ToolSpec(
            name=name, description=desc, parameters=params,
            group="media", timeout_s=timeout, handler=handler))
    return [s[0] for s in specs]
