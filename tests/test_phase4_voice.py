"""Phase 4 — voice hai chiều (mục 8.1): STT whisper (giả lập) +
hiểu ngữ bằng model rẻ (giả lập), TTS qua proxy bằng httpx
MockTransport — không gọi mạng/model thật. Nối Telegram: tin
thoại -> text vào batcher; /voiceon-/voiceoff theo session."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from aiogram.enums import ChatType

import mulon.voice as voice_mod
from mulon.gateway import Completion
from mulon.telegram_bot import MessageBatcher, TelegramSurface
from mulon.voice import VoiceService, synthesize_speech, transcribe_audio

RAW = "xin chao, mai hop luc 9 gio sang nhe"
UNDERSTOOD = "Xin chào, mai họp lúc 9 giờ sáng nhé"


def fake_stt(text=RAW):
    def _fn(cfg, path):
        return text, [{"start": 0.0, "end": 1.5, "text": text}]
    return _fn


class UnderstandGateway:
    async def complete(self, messages, model=None, tools=None,
                       purpose="", temperature=None):
        assert purpose == "voice_understand"
        return Completion(text=json.dumps(
            {"text_da_hieu": UNDERSTOOD, "y_dinh": "nhắc lịch họp"},
            ensure_ascii=False))


class BoomGateway:
    async def complete(self, messages, model=None, tools=None,
                       purpose="", temperature=None):
        raise RuntimeError("proxy sập")


# ------------------------- STT + hiểu ngữ -------------------------

async def test_transcribe_unavailable_without_whisper(cfg, monkeypatch):
    monkeypatch.setattr(voice_mod, "whisper_available", lambda: False)
    out = await transcribe_audio(cfg, "x.ogg", gateway=None)
    assert out["ok"] is False
    assert out["unavailable"] is True


async def test_transcribe_with_understanding(cfg):
    out = await transcribe_audio(cfg, "x.ogg", UnderstandGateway(),
                                 stt_fn=fake_stt())
    assert out["ok"] is True
    assert out["text_tho"] == RAW
    assert out["text_da_hieu"] == UNDERSTOOD
    assert out["y_dinh"] == "nhắc lịch họp"
    assert out["segments"][0]["end"] == 1.5


async def test_transcribe_understanding_failure_keeps_raw(cfg):
    out = await transcribe_audio(cfg, "x.ogg", BoomGateway(),
                                 stt_fn=fake_stt())
    assert out["ok"] is True  # hiểu ngữ lỗi không làm hỏng STT
    assert out["text_da_hieu"] == RAW
    assert out["y_dinh"] == ""


async def test_transcribe_stt_failure_is_structured(cfg):
    def bad_stt(cfg, path):
        raise RuntimeError("file hỏng")

    out = await transcribe_audio(cfg, "x.ogg", None, stt_fn=bad_stt)
    assert out["ok"] is False
    assert "stt_failed" in out["error"]


async def test_transcribe_without_gateway_skips_understanding(cfg):
    out = await transcribe_audio(cfg, "x.ogg", None, stt_fn=fake_stt())
    assert out["ok"] is True
    assert out["text_da_hieu"] == RAW


# ------------------------- TTS qua proxy -------------------------

async def test_tts_writes_audio_file(cfg, tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, content=b"FAKE-OGG-BYTES")

    out_path = tmp_path / "reply.ogg"
    out = await synthesize_speech(
        cfg, "chào buổi sáng", out_path,
        transport=httpx.MockTransport(handler))
    assert out["ok"] is True
    assert out_path.read_bytes() == b"FAKE-OGG-BYTES"
    assert seen["url"].endswith("/audio/speech")
    assert seen["auth"] == f"Bearer {cfg.proxy_api_key}"
    assert seen["body"]["input"] == "chào buổi sáng"
    assert seen["body"]["model"] == cfg.voice_tts_model
    assert seen["body"]["voice"] == cfg.voice_tts_voice


async def test_tts_proxy_error_degrades(cfg, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="model not supported")

    out = await synthesize_speech(
        cfg, "alo", tmp_path / "x.ogg",
        transport=httpx.MockTransport(handler))
    assert out["ok"] is False
    assert "404" in out["error"]
    assert not (tmp_path / "x.ogg").exists()


async def test_tts_empty_text_and_transport_boom(cfg):
    assert (await synthesize_speech(cfg, "  "))["ok"] is False

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no proxy", request=request)

    out = await synthesize_speech(
        cfg, "alo", transport=httpx.MockTransport(handler))
    assert out["ok"] is False
    assert "tts_unavailable" in out["error"]


# ------------------------- nối Telegram -------------------------

class FakeVoiceService:
    def __init__(self, result=None, speak=None):
        self._result = result or {"ok": True, "text_tho": RAW,
                                  "text_da_hieu": UNDERSTOOD,
                                  "y_dinh": "nhắc lịch họp"}
        self._speak = speak or {"ok": True, "path": "/tmp/x.ogg"}
        self.spoken: list[str] = []

    async def transcribe_file(self, path):
        return self._result

    async def speak_to_file(self, text, out_path=None):
        self.spoken.append(text)
        return self._speak


class FakeBot:
    def __init__(self):
        self.id = 999

    async def get_file(self, file_id):
        return SimpleNamespace(file_path="voice/file_1.oga")

    async def download_file(self, file_path, destination=None):
        with open(destination, "wb") as fh:
            fh.write(b"fake-ogg")


def _voice_message():
    chat = SimpleNamespace(id=42, type=ChatType.PRIVATE)
    msg = SimpleNamespace(
        chat=chat,
        is_topic_message=False,
        message_thread_id=None,
        voice=SimpleNamespace(file_id="f1", file_unique_id="u1"),
        from_user=SimpleNamespace(id=42),
        text=None,
        answers=[],
        voices_sent=[],
    )

    async def answer(text, **kw):
        msg.answers.append(text)

    async def answer_voice(file, **kw):
        msg.voices_sent.append(file)

    msg.answer = answer
    msg.answer_voice = answer_voice
    return msg


def _surface(cfg, voice):
    return TelegramSurface(cfg, agent=None, memory=None, dossier=None,
                           voice=voice)


async def test_voice_message_flows_into_batcher_as_text(cfg):
    cfg2 = replace(cfg, debounce_seconds=0.05)
    surface = _surface(cfg2, FakeVoiceService())
    surface.bot = FakeBot()
    captured = []

    async def capture(key, joined, parts):
        captured.append((key, joined))

    surface.batcher = MessageBatcher(0.05, capture)
    msg = _voice_message()
    await surface._process_voice_message(msg)
    await asyncio.sleep(0.2)
    assert len(captured) == 1
    key, joined = captured[0]
    assert joined == UNDERSTOOD  # bản ĐÃ HIỂU NGỮ vào agent, không phải bản thô
    assert key.endswith("dm:42:topic:0")
    # file tải về nằm trong workspace/voice_in
    assert (cfg2.workspace_dir / "voice_in" / "u1.ogg").exists()


async def test_voice_message_stt_unavailable_answers_cleanly(cfg):
    surface = _surface(cfg, FakeVoiceService(
        result={"ok": False, "unavailable": True,
                "error": "stt_unavailable: chưa cài"}))
    surface.bot = FakeBot()
    msg = _voice_message()
    await surface._process_voice_message(msg)
    assert msg.answers and "faster-whisper" in msg.answers[0]


async def test_voice_reply_toggle_and_send(cfg, tmp_path):
    voice = FakeVoiceService()
    surface = _surface(cfg, voice)
    key = "agent:main:telegram:dm:42:topic:0"
    anchor = _voice_message()
    # chưa bật -> không gửi voice
    await surface._maybe_send_voice(key, anchor, "xin chào")
    assert voice.spoken == [] and anchor.voices_sent == []
    # bật -> gửi, và HTML bị gọt trước khi đọc
    surface.set_voice_reply(key, True)
    assert surface.voice_reply_enabled(key) is True
    await surface._maybe_send_voice(key, anchor, "<b>xin chào</b> bạn")
    assert voice.spoken == ["xin chào bạn"]
    assert len(anchor.voices_sent) == 1
    # tắt -> im
    surface.set_voice_reply(key, False)
    await surface._maybe_send_voice(key, anchor, "lại chào")
    assert len(anchor.voices_sent) == 1


async def test_voice_service_wraps_module_functions(cfg, monkeypatch):
    monkeypatch.setattr(voice_mod, "whisper_available", lambda: False)
    svc = VoiceService(cfg, gateway=None)
    assert svc.stt_available() is False
    monkeypatch.setattr(voice_mod, "whisper_available", lambda: True)
    assert svc.stt_available() is True
