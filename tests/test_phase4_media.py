"""Phase 4 — media pipeline tools (mục 8.2): ffmpeg/ffprobe thật
trên máy test. Video test được sinh bằng chính ffmpeg (lavfi),
rồi probe/trim/frames/extract_audio/burn_subs chạy thật trên nó."""

import subprocess
from pathlib import Path

import pytest

import mulon.media_tools as mt
from mulon.tools import ToolRegistry


def _make_clip(cfg) -> Path:
    """Sinh clip 2 giây 320x240 có audio bằng ffmpeg lavfi."""
    clip = Path(cfg.workspace_dir) / "clip.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=320x240:r=30:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:d=2",
        "-shortest", "-codec:v", "mpeg4", "-pix_fmt", "yuv420p",
        "-codec:a", "aac", str(clip),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert clip.is_file()
    return clip


@pytest.fixture
def clip(cfg):
    if not mt.ffmpeg_available(cfg) or not mt.ffprobe_available(cfg):
        pytest.skip("máy test thiếu ffmpeg/ffprobe")
    return _make_clip(cfg)


def _registry(cfg):
    reg = ToolRegistry()
    mt.register_media_tools(reg, cfg)
    return reg


async def test_media_probe_real(cfg, clip):
    reg = _registry(cfg)
    out = await reg.execute("media_probe", {"path": "clip.mp4"})
    assert out["ok"] is True
    assert 1.8 <= out["duration_s"] <= 2.2
    assert out["width"] == 320 and out["height"] == 240
    assert out["video_codec"] == "mpeg4"
    assert out["audio_codec"] == "aac"


async def test_media_trim_and_frames_and_audio(cfg, clip):
    reg = _registry(cfg)
    trimmed = await reg.execute(
        "media_trim", {"path": "clip.mp4", "start_s": 0, "duration_s": 1})
    assert trimmed["ok"] is True
    info = await mt.probe(cfg, trimmed["path"])
    assert info["ok"] is True
    assert 0.7 <= info["duration_s"] <= 1.4

    frames = await reg.execute(
        "media_frames", {"path": "clip.mp4", "count": 2})
    assert frames["ok"] is True
    assert frames["count"] == 2
    for path in frames["frames"]:
        assert Path(path).is_file() and Path(path).stat().st_size > 0

    audio = await reg.execute("media_extract_audio", {"path": "clip.mp4"})
    assert audio["ok"] is True
    assert Path(audio["path"]).is_file()
    ainfo = await mt.probe(cfg, audio["path"])
    assert ainfo["audio_codec"] == "mp3"
    assert ainfo["video_codec"] is None


async def test_media_burn_subs_real(cfg, clip):
    srt = Path(cfg.workspace_dir) / "phu-de.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,500\nXin chào Mulon\n\n",
        encoding="utf-8")
    reg = _registry(cfg)
    out = await reg.execute(
        "media_burn_subs", {"path": "clip.mp4", "subs_path": "phu-de.srt"})
    assert out["ok"] is True, out
    assert Path(out["path"]).is_file()
    info = await mt.probe(cfg, out["path"])
    assert info["ok"] is True and info["duration_s"] > 1.5


async def test_media_missing_file_is_structured_error(cfg, clip):
    reg = _registry(cfg)
    out = await reg.execute("media_probe", {"path": "khong-co.mp4"})
    assert out["ok"] is False
    assert "error" in out


async def test_media_unavailable_degrades(cfg, clip, monkeypatch):
    monkeypatch.setattr(mt, "ffmpeg_available", lambda c: False)
    monkeypatch.setattr(mt, "ffprobe_available", lambda c: False)
    reg = _registry(cfg)
    for name, args in [
        ("media_probe", {"path": "clip.mp4"}),
        ("media_trim", {"path": "clip.mp4"}),
        ("media_frames", {"path": "clip.mp4"}),
        ("media_extract_audio", {"path": "clip.mp4"}),
        ("media_burn_subs", {"path": "clip.mp4", "subs_path": "x.srt"}),
    ]:
        out = await reg.execute(name, args)
        assert out["ok"] is False, name
        assert out["unavailable"] is True, name


async def test_media_transcribe_uses_whisper_layer(cfg, clip, monkeypatch):
    """media_transcribe đi qua lớp whisper của voice (không hiểu ngữ)."""
    seen = {}

    async def fake_transcribe(cfg_, path, gateway=None, understand=None):
        seen["understand"] = understand
        return {"ok": True, "text_tho": "lời trong clip",
                "text_da_hieu": "lời trong clip", "y_dinh": "",
                "segments": [{"start": 0.0, "end": 2.0,
                              "text": "lời trong clip"}]}

    monkeypatch.setattr(mt.voice_mod, "transcribe_audio", fake_transcribe)
    reg = _registry(cfg)
    out = await reg.execute("media_transcribe", {"path": "clip.mp4"})
    assert out["ok"] is True
    assert out["text_tho"] == "lời trong clip"
    assert seen["understand"] is False  # pipeline cần bản thô + timecode


async def test_generate_image_tool_no_key_returns_structured_error(cfg, monkeypatch):
    """Khi không có key trong vault hay env, generate_image trả lỗi hướng dẫn."""
    monkeypatch.delenv("AGNES_AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reg = _registry(cfg)
    out = await reg.execute("generate_image", {"prompt": "bức tranh hoàng hôn"})
    assert out["ok"] is False
    assert "Chưa có API key" in out["error"]


