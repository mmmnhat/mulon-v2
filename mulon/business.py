"""Module Telegram Business Chatbot (T-29).

Quản lý bot rep thay nick cá nhân của chủ sở hữu:
1. Thu nhận và quản lý trạng thái kết nối Telegram Business (business_connection, can_reply).
2. Tách biệt ngữ cảnh tuyệt đối (bài học X-01): chat khách là vũ trụ riêng,
   nội dung khách bọc qua frame_external, không có tool nhạy cảm hay thông tin nội bộ.
3. Mức tự chủ chặt chẽ:
   - TỰ REP: Chào hỏi, thông tin/giá sản phẩm (từ catalog, cấm bịa giá),
     hướng dẫn mua, bảo hành cơ bản — bằng giọng miền Nam thân thiện.
   - SOẠN NHÁP CHỜ DUYỆT: Thương lượng giảm giá, thông tin STK/chuyển khoản
     (TUYỆT ĐỐI KHÔNG TỰ GỬI), khiếu nại, hỗ trợ kỹ thuật, hoặc ca không chắc
     — mở thẻ phê duyệt về DM chủ qua ApprovalBroker; chủ duyệt mới gửi,
     chủ từ chối/im lặng thì bot im lặng.
   - Bỏ qua tin nhắn do chính chủ gửi từ client khác.
   - Rate limit chống spam theo từng chat khách.
"""

from __future__ import annotations

import asyncio
import html as _html
import json
import logging
import re
import time
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .context import frame_external
from .datafiles import load_json_data, load_prompt

logger = logging.getLogger(__name__)


class BusinessActionKind(str, Enum):
    AUTO_REPLY = "auto_reply"
    DRAFT_APPROVAL = "draft_approval"
    IGNORE = "ignore"


def normalize_vietnamese_text(text: str) -> str:
    """Chuẩn hoá chuỗi tiếng Việt để so khớp từ khoá."""
    s = (text or "").lower().strip()
    s = re.sub(r"[àáạảãâầấậẩẫăằắặẳẵ]", "a", s)
    s = re.sub(r"[èéẹẻẽêềếệểễ]", "e", s)
    s = re.sub(r"[ìíịỉĩ]", "i", s)
    s = re.sub(r"[òóọỏõôồốộổỗơờớợởỡ]", "o", s)
    s = re.sub(r"[ùúụủũưừứựửữ]", "u", s)
    s = re.sub(r"[ỳýỵỷỹ]", "y", s)
    s = re.sub(r"[đ]", "d", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


class TelegramBusinessClassifier:
    """Bộ phân loại ý định khách hàng Telegram Business.
    
    Phân loại rõ ràng 2 nhánh:
    (a) TỰ REP: câu hỏi đơn giản khớp catalog/FAQ.
    (b) SOẠN NHÁP CHỜ DUYỆT: STK ngân hàng, giảm giá, khiếu nại, hoặc không chắc.
    """

    # Từ khoá STK / Chuyển khoản (TUYỆT ĐỐI KHÔNG TỰ GỬI)
    BANK_KEYWORDS = [
        "stk", "so tai khoan", "so tk", "chuyen khoan", "chuyen tien",
        "thanh toan", "banking", "bank", "qr", "ck", "atm",
        "tai khoan ngan hang", "thong tin chuyen khoan",
    ]

    # Từ khoá thương lượng / giảm giá
    DISCOUNT_KEYWORDS = [
        "giam gia", "bot", "bot khong", "bot ko", "chiet khau",
        "sale", "fix", "voucher", "giam them", "gia tot hon", "keo gia",
    ]

    # Từ khoá khiếu nại / sự cố
    COMPLAINT_KEYWORDS = [
        "khieu nai", "hong", "bi loi", "loi roi", "tra hang",
        "hoan tien", "lua dao", "khong nhan duoc", "that vong", "lam an",
        "hang dom", "kem chat luong", "doi tien",
    ]

    # Từ khoá yêu cầu gặp chủ / người thật
    HUMAN_KEYWORDS = [
        "gap chu", "gap nguoi", "gap tu van", "nhan vien", "hotline",
        "goi dien", "so dien thoai", "sdt", "alo", "noi chuyen truc tiep",
    ]

    # Từ khoá chào hỏi
    GREETING_KEYWORDS = [
        "chao", "chao shop", "hi", "hello", "shop oi", "ad oi", "ban oi",
        "alo shop", "cho minh hoi", "cho em hoi", "co ai o day khong",
    ]

    def __init__(self, catalog: dict):
        self.catalog = catalog or {}
        self.products = self.catalog.get("products", [])
        self.faq = self.catalog.get("faq", [])
        self.bank_info = self.catalog.get("bank_info", {})

    def classify(self, text: str) -> tuple[BusinessActionKind, str, Optional[dict]]:
        """Phân loại tin nhắn của khách.
        
        Trả về: (action_kind, reason, match_data)
        """
        raw = text.strip()
        norm = normalize_vietnamese_text(raw)

        if not norm:
            return BusinessActionKind.IGNORE, "Tin nhắn rỗng", None

        # 1. Chặn câu hỏi moi thông tin hệ thống / prompt injection / tấn công
        suspicious = [
            "system prompt", "dossier", "allowed_user_id", "bash", "vault",
            "token", "api key", "cat ", "rm -rf", "ls ", "cat /",
        ]
        if any(kw in raw.lower() for kw in suspicious):
            # Từ chối an toàn bằng cách tự rep câu từ chối chuẩn
            return BusinessActionKind.AUTO_REPLY, "security_refusal", None

        # 2. STK / Ngân hàng -> SOẠN NHÁP CHỜ DUYỆT
        if any(re.search(r"\b" + re.escape(kw) + r"\b", norm) for kw in self.BANK_KEYWORDS):
            return (
                BusinessActionKind.DRAFT_APPROVAL,
                "Khách hỏi thông tin STK/chuyển khoản ngân hàng",
                {"type": "bank_transfer", "bank_info": self.bank_info},
            )

        # 3. Thương lượng / giảm giá -> SOẠN NHÁP CHỜ DUYỆT
        if any(re.search(r"\b" + re.escape(kw) + r"\b", norm) for kw in self.DISCOUNT_KEYWORDS):
            return (
                BusinessActionKind.DRAFT_APPROVAL,
                "Khách thương lượng hoặc xin giảm giá ngoài bảng niêm yết",
                {"type": "discount_negotiation"},
            )

        # 4. Khiếu nại / sự cố -> SOẠN NHÁP CHỜ DUYỆT
        if any(re.search(r"\b" + re.escape(kw) + r"\b", norm) for kw in self.COMPLAINT_KEYWORDS):
            return (
                BusinessActionKind.DRAFT_APPROVAL,
                "Khách phản ánh sự cố hoặc khiếu nại sản phẩm/dịch vụ",
                {"type": "complaint"},
            )

        # 5. Yêu cầu gặp người thật / chủ -> SOẠN NHÁP CHỜ DUYỆT
        if any(re.search(r"\b" + re.escape(kw) + r"\b", norm) for kw in self.HUMAN_KEYWORDS):
            return (
                BusinessActionKind.DRAFT_APPROVAL,
                "Khách yêu cầu gặp chủ shop hoặc tư vấn viên trực tiếp",
                {"type": "human_handoff"},
            )

        # 6. Tìm kiếm sản phẩm trong catalog
        matched_prod = self._match_product(norm)
        if matched_prod:
            return (
                BusinessActionKind.AUTO_REPLY,
                f"Tự trả lời thông tin sản phẩm: {matched_prod['name']}",
                {"type": "product_inquiry", "product": matched_prod},
            )

        # 7. FAQ (giao hàng, bảo hành)
        matched_faq = self._match_faq(norm)
        if matched_faq:
            return (
                BusinessActionKind.AUTO_REPLY,
                f"Tự trả lời theo FAQ: {matched_faq.get('topic', 'faq')}",
                {"type": "faq", "faq": matched_faq},
            )

        # 8. Chào hỏi
        if any(re.search(r"\b" + re.escape(kw) + r"\b", norm) for kw in self.GREETING_KEYWORDS):
            return (
                BusinessActionKind.AUTO_REPLY,
                "Tự trả lời lời chào khách hàng",
                {"type": "greeting"},
            )

        # 9. Mọi trường hợp không chắc chắn -> SOẠN NHÁP CHỜ DUYỆT
        return (
            BusinessActionKind.DRAFT_APPROVAL,
            "Nội dung cần chủ shop xác nhận trước khi trả lời",
            {"type": "uncertain_inquiry"},
        )

    def _match_product(self, norm_text: str) -> Optional[dict]:
        """Đối chiếu sản phẩm theo tên và danh sách từ khoá."""
        for p in self.products:
            name_norm = normalize_vietnamese_text(p.get("name", ""))
            if name_norm in norm_text or norm_text in name_norm:
                return p
            for kw in p.get("keywords", []):
                kw_norm = normalize_vietnamese_text(kw)
                if re.search(r"\b" + re.escape(kw_norm) + r"\b", norm_text):
                    return p
        return None

    def _match_faq(self, norm_text: str) -> Optional[dict]:
        """Đối chiếu FAQ theo từ khoá."""
        for item in self.faq:
            for kw in item.get("keywords", []):
                kw_norm = normalize_vietnamese_text(kw)
                if re.search(r"\b" + re.escape(kw_norm) + r"\b", norm_text):
                    return item
        return None


class TelegramBusinessService:
    """Dịch vụ chính quản lý Telegram Business Chatbot.
    
    Tích hợp với dispatcher của aiogram và ApprovalBroker của hệ thống.
    """

    def __init__(self, cfg, memory=None, broker=None, bot=None):
        self.cfg = cfg
        self.memory = memory
        self.broker = broker
        self.bot = bot

        # Nạp catalog từ config/shop_catalog.json (Rule 0)
        self.catalog = self._load_catalog()
        self.classifier = TelegramBusinessClassifier(self.catalog)

        # Bộ nhớ tạm rate-limit: {chat_id: [timestamp]}
        self._rate_limits: dict[int, list[float]] = {}
        # Đếm thống kê
        self._stats = {
            "auto_replies": 0,
            "drafts_created": 0,
            "drafts_approved": 0,
            "drafts_denied": 0,
        }

    def _load_catalog(self) -> dict:
        """Nạp dữ liệu catalog sản phẩm & cấu hình bán hàng."""
        catalog_path = getattr(self.cfg, "telegram_business_catalog_path", None)
        filename = "shop_catalog.json"
        if catalog_path and isinstance(catalog_path, (str, Path)):
            p = Path(catalog_path)
            if p.is_file():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as exc:
                    logger.warning("Không nạp được file catalog từ path %s: %s", catalog_path, exc)
        return load_json_data(filename, {
            "shop_name": "Tiệm Nhà Mulon",
            "tone": "miền Nam, ngắn gọn, thân thiện, lễ phép",
            "greeting_default": "Dạ em chào anh/chị nha! Em có thể hỗ trợ gì cho mình ạ?",
            "products": [],
            "faq": [],
            "bank_info": {},
        })

    # ---------- Quản lý kết nối ----------

    async def handle_business_connection(self, conn: Any) -> dict:
        """Xử lý cập nhật kết nối Telegram Business (Update.business_connection)."""
        conn_id = str(getattr(conn, "id", ""))
        user = getattr(conn, "user", None)
        user_id = getattr(user, "id", 0) if user else 0
        user_chat_id = getattr(conn, "user_chat_id", 0)
        can_reply = bool(getattr(conn, "can_reply", False))
        is_enabled = bool(getattr(conn, "is_enabled", False))
        dt = getattr(conn, "date", None)
        date_ts = dt.timestamp() if hasattr(dt, "timestamp") else time.time()

        record = {
            "connection_id": conn_id,
            "user_id": user_id,
            "user_chat_id": user_chat_id,
            "can_reply": can_reply,
            "is_enabled": is_enabled,
            "updated_at": date_ts,
        }

        if self.memory is not None:
            try:
                await self.memory.kv_set(f"business:connection:{conn_id}", json.dumps(record))
                if is_enabled:
                    await self.memory.kv_set("business:active_connection", conn_id)
                else:
                    # Ngắt kết nối: xóa active connection
                    active = await self.memory.kv_get("business:active_connection")
                    if active == conn_id:
                        await self.memory.kv_del("business:active_connection")
            except Exception as exc:
                logger.warning("Lưu trạng thái Telegram Business connection lỗi: %s", exc)

        logger.info(
            "Telegram Business connection %s: is_enabled=%s, can_reply=%s",
            conn_id, is_enabled, can_reply,
        )

        # Thông báo cho chủ nếu bị ngắt kết nối
        if not is_enabled and self.bot is not None and self.cfg.allowed_user_id:
            try:
                await self.bot.send_message(
                    self.cfg.allowed_user_id,
                    f"<b>Telegram Business đã bị ngắt kết nối!</b>\n"
                    f"Connection ID: <code>{_html.escape(conn_id)}</code>\n"
                    f"Bot đã tự động dừng trả lời tin nhắn của khách.",
                    parse_mode="HTML",
                )
            except Exception as exc:
                logger.warning("Gửi thông báo ngắt kết nối Telegram Business thất bại: %s", exc)

        return record

    async def is_active_and_can_reply(self, conn_id: Optional[str] = None) -> bool:
        """Kiểm tra xem bot có đang kết nối và có quyền reply không."""
        if not getattr(self.cfg, "telegram_business_enabled", False):
            return False

        if not conn_id and self.memory is not None:
            try:
                conn_id = await self.memory.kv_get("business:active_connection")
            except Exception:
                conn_id = None

        if not conn_id:
            return False

        if self.memory is not None:
            try:
                raw = await self.memory.kv_get(f"business:connection:{conn_id}")
                if raw:
                    info = json.loads(raw)
                    return bool(info.get("is_enabled") and info.get("can_reply"))
            except Exception:
                pass
        return True

    # ---------- Rate Limit ----------

    def check_rate_limit(self, chat_id: int) -> bool:
        """Kiểm tra rate limit chống spam theo từng chat.
        
        Trả về True nếu được phép, False nếu bị quá hạn.
        """
        limit = int(getattr(self.cfg, "telegram_business_rate_limit_per_min", 10))
        now = time.time()
        window = 60.0

        timestamps = self._rate_limits.setdefault(chat_id, [])
        # Xóa các mốc cũ quá 60s
        timestamps = [ts for ts in timestamps if now - ts < window]
        if len(timestamps) >= limit:
            self._rate_limits[chat_id] = timestamps
            return False

        timestamps.append(now)
        self._rate_limits[chat_id] = timestamps
        return True

    # ---------- Sinh câu trả lời & Nháp ----------

    def build_auto_reply(self, reason: str, match_data: Optional[dict], customer_name: str) -> str:
        """Tạo câu trả lời tự động chuẩn giọng miền Nam thân thiện."""
        c_name = customer_name or "mình"

        if reason == "security_refusal":
            return (
                "Dạ em chỉ hỗ trợ tư vấn các sản phẩm và đơn hàng của shop thôi nha anh/chị. "
                "Nếu mình cần hỗ trợ gì về sản phẩm cứ nhắn em nhé ạ!"
            )

        if not match_data:
            return self.catalog.get(
                "greeting_default",
                f"Dạ em chào {c_name} nha! Em có thể hỗ trợ gì cho mình về sản phẩm hoặc đơn hàng ạ?",
            )

        m_type = match_data.get("type")
        if m_type == "greeting":
            return self.catalog.get(
                "greeting_default",
                f"Dạ em chào {c_name} nha! Em có thể hỗ trợ gì cho mình về sản phẩm hoặc đơn hàng ạ?",
            )

        if m_type == "product_inquiry":
            prod = match_data.get("product", {})
            name = prod.get("name", "sản phẩm")
            price = prod.get("formatted_price", "")
            desc = prod.get("description", "")
            warranty = prod.get("warranty", "")
            stock = "dạ còn sẵn hàng" if prod.get("in_stock", True) else "dạ tạm hết hàng"

            lines = [
                f"Dạ {name} bên em hiện có giá niêm yết là <b>{price}</b> nha anh/chị ({stock}) ạ.",
            ]
            if desc:
                lines.append(f"• Thông số: {desc}")
            if warranty:
                lines.append(f"• Bảo hành: {warranty}")
            lines.append("Anh/chị xem qua có cần em tư vấn thêm gì không ạ?")
            return "\n".join(lines)

        if m_type == "faq":
            faq = match_data.get("faq", {})
            return faq.get("answer", "Dạ bên em sẵn sàng hỗ trợ anh/chị ạ.")

        return "Dạ em chào anh/chị, em có thể hỗ trợ gì cho mình ạ?"

    def build_draft_reply(self, reason: str, match_data: Optional[dict], raw_text: str, customer_name: str) -> str:
        """Tạo câu trả lời nháp trình chủ duyệt."""
        c_name = customer_name or "anh/chị"
        m_type = (match_data or {}).get("type", "")

        if m_type == "bank_transfer":
            b_info = self.catalog.get("bank_info", {})
            bank_name = b_info.get("bank_name", "Ngân hàng")
            stk = b_info.get("account_number", "")
            holder = b_info.get("account_holder", "")
            return (
                f"Dạ để thanh toán đơn hàng, {c_name} có thể chuyển khoản giúp shop qua thông tin này nha ạ:\n"
                f"• Ngân hàng: {bank_name}\n"
                f"• Số tài khoản: {stk}\n"
                f"• Chủ tài khoản: {holder}\n"
                f"Nội dung chuyển khoản: [Tên KH] + [Sản phẩm]\n\n"
                f"Sau khi chuyển xong, {c_name} chụp màn hình gửi em để em kiểm tra và ship hàng ngay nhé ạ!"
            )

        if m_type == "discount_negotiation":
            return (
                f"Dạ về mức giá ưu đãi thêm cho sản phẩm, shop em luôn để giá niêm yết tốt nhất rồi ạ. "
                f"Tuy nhiên nếu mình chốt đơn ngay hôm nay, shop xin phép hỗ trợ tặng thêm quà tặng "
                f"hoặc freeship cho {c_name} nha ạ!"
            )

        if m_type == "complaint":
            return (
                f"Dạ em thật sự xin lỗi {c_name} vì sự cố không mong muốn này ạ! "
                f"Anh/chị chụp giúp em hình ảnh hoặc video tình trạng sản phẩm để shop kiểm tra "
                f"và hỗ trợ đổi mới ngay cho mình nhé ạ."
            )

        if m_type == "human_handoff":
            return (
                f"Dạ em đã báo cho anh chủ shop rồi ạ. "
                f"Anh ấy sẽ kiểm tra và nhắn lại cho {c_name} trong ít phút nữa nha, anh/chị đợi xíu nhé ạ!"
            )

        return (
            f"Dạ em chào {c_name}, em xin phép ghi nhận thông tin này và sẽ kiểm tra phản hồi lại cho mình ngay nha ạ!"
        )

    # ---------- Xử lý tin nhắn khách hàng ----------

    async def process_business_message(self, message: Any) -> dict:
        """Xử lý tin nhắn khách từ Update.business_message.
        
        Trả về kết quả xử lý.
        """
        # 1. Bỏ qua nếu tính năng bị tắt
        if not getattr(self.cfg, "telegram_business_enabled", False):
            return {"action": BusinessActionKind.IGNORE, "reason": "business_disabled"}

        conn_id = getattr(message, "business_connection_id", None)
        if not conn_id:
            return {"action": BusinessActionKind.IGNORE, "reason": "no_business_connection_id"}

        # 2. Bỏ qua tin nhắn do CHÍNH CHỦ gửi từ client khác
        from_user = getattr(message, "from_user", None)
        sender_id = getattr(from_user, "id", 0) if from_user else 0
        owner_id = self.cfg.allowed_user_id
        if sender_id and owner_id and sender_id == owner_id:
            logger.debug("Bỏ qua tin business_message do chính chủ gửi (id=%s)", sender_id)
            return {"action": BusinessActionKind.IGNORE, "reason": "owner_outgoing_message"}

        # 3. Kiểm tra trạng thái kết nối
        active_conn = await self.is_active_and_can_reply(conn_id)
        if not active_conn:
            logger.info("Bỏ qua business_message vì connection %s không hoạt động hoặc không có can_reply", conn_id)
            return {"action": BusinessActionKind.IGNORE, "reason": "connection_cannot_reply"}

        # 4. Kiểm tra rate-limit chống spam
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", 0) if chat else sender_id
        if not self.check_rate_limit(chat_id):
            logger.warning("Chat %s bị rate-limit business chatbot", chat_id)
            return {"action": BusinessActionKind.IGNORE, "reason": "rate_limited"}

        # 5. Lấy nội dung tin nhắn và bọc frame_external (bảo vệ chống prompt injection)
        raw_text = getattr(message, "text", "") or getattr(message, "caption", "") or ""
        framed_text = frame_external(raw_text)

        customer_name = ""
        if from_user:
            fname = getattr(from_user, "first_name", "") or ""
            lname = getattr(from_user, "last_name", "") or ""
            customer_name = f"{fname} {lname}".strip() or getattr(from_user, "username", "") or ""

        # 6. Phân loại ý định khách
        action_kind, reason, match_data = self.classifier.classify(raw_text)

        # 7. Nhánh TỰ REP
        if action_kind == BusinessActionKind.AUTO_REPLY:
            reply_text = self.build_auto_reply(reason, match_data, customer_name)
            if self.bot is not None:
                try:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=reply_text,
                        parse_mode="HTML",
                        business_connection_id=conn_id,
                    )
                    self._stats["auto_replies"] += 1
                    logger.info("Telegram Business auto-replied to chat %s (conn=%s)", chat_id, conn_id)
                    await self._log_interaction(
                        conn_id=conn_id,
                        chat_id=chat_id,
                        sender_id=sender_id,
                        sender_name=customer_name,
                        message_text=raw_text,
                        reply_text=reply_text,
                        action_kind="auto_reply",
                        status="sent",
                    )
                except Exception as exc:
                    logger.warning("Gửi auto-reply Telegram Business thất bại: %s", exc)
                    return {"action": BusinessActionKind.IGNORE, "error": str(exc)}
            return {"action": BusinessActionKind.AUTO_REPLY, "reply": reply_text, "reason": reason}

        # 8. Nhánh SOẠN NHÁP CHỜ DUYỆT
        if action_kind == BusinessActionKind.DRAFT_APPROVAL:
            draft_text = self.build_draft_reply(reason, match_data, raw_text, customer_name)
            approval_id = await self._open_draft_approval(
                conn_id=conn_id,
                customer_chat_id=chat_id,
                customer_name=customer_name,
                customer_text=raw_text,
                draft_text=draft_text,
                reason=reason,
            )
            self._stats["drafts_created"] += 1
            await self._log_interaction(
                conn_id=conn_id,
                chat_id=chat_id,
                sender_id=sender_id,
                sender_name=customer_name,
                message_text=raw_text,
                reply_text=draft_text,
                action_kind="draft_approval",
                status="pending",
            )
            return {
                "action": BusinessActionKind.DRAFT_APPROVAL,
                "approval_id": approval_id,
                "draft": draft_text,
                "reason": reason,
            }

        return {"action": BusinessActionKind.IGNORE, "reason": reason}

    # ---------- Phê duyệt nháp ----------

    async def _open_draft_approval(
        self,
        conn_id: str,
        customer_chat_id: int,
        customer_name: str,
        customer_text: str,
        draft_text: str,
        reason: str,
    ) -> str:
        """Mở yêu cầu phê duyệt nháp trả lời khách hàng."""
        import uuid
        approval_id = f"biz_{uuid.uuid4().hex[:10]}"

        payload = {
            "approval_id": approval_id,
            "tool": "telegram_business_reply",
            "group": "business",
            "summary": f"Tin nhắn nháp Telegram Business trả lời khách {_html.escape(customer_name or str(customer_chat_id))}",
            "target": f"customer:{customer_chat_id}",
            "reason": reason,
            "business_connection_id": conn_id,
            "customer_chat_id": customer_chat_id,
            "customer_name": customer_name,
            "customer_text": customer_text,
            "draft_text": draft_text,
            "kind": "business_draft",
        }

        if self.broker is not None:
            self.broker.open(approval_id, payload, ttl_s=3600.0)

        # Gửi thẻ duyệt đến DM chủ
        owner_id = self.cfg.allowed_user_id
        if self.bot is not None and owner_id:
            try:
                card_text = (
                    f"<b>[Telegram Business] Cần duyệt tin nhắn trả lời khách hàng</b>\n\n"
                    f"• <b>Khách hàng:</b> {_html.escape(customer_name or 'Khách')} (<code>{customer_chat_id}</code>)\n"
                    f"• <b>Khách hỏi:</b> <i>{_html.escape(customer_text)}</i>\n"
                    f"• <b>Lý do cần duyệt:</b> {reason}\n\n"
                    f"• <b>Bản thảo trả lời:</b>\n"
                    f"<blockquote>{_html.escape(draft_text)}</blockquote>\n\n"
                    f"<i>Bấm Cho phép để bot gửi thay nick của bạn, hoặc Từ chối để im lặng.</i>"
                )
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="Gửi tin này", callback_data=f"appr:{approval_id}:yes"),
                            InlineKeyboardButton(text="Từ chối", callback_data=f"appr:{approval_id}:no"),
                        ]
                    ]
                )
                msg = await self.bot.send_message(
                    chat_id=owner_id,
                    text=card_text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
                if self.broker is not None:
                    self.broker.attach(approval_id, {"chat_id": owner_id, "message_id": msg.message_id})
            except Exception as exc:
                logger.warning("Gửi thẻ duyệt Telegram Business thất bại: %s", exc)

        # Chạy task lắng nghe quyết định
        asyncio.create_task(self._settle_draft_approval(approval_id, payload))
        return approval_id

    async def _settle_draft_approval(self, approval_id: str, payload: dict) -> None:
        """Lắng nghe quyết định phê duyệt và gửi tin nếu được duyệt."""
        if self.broker is None:
            return

        record = await self.broker.wait(approval_id)
        approved = bool(record.get("approved", False))
        outcome = record.get("outcome", "")

        conn_id = payload.get("business_connection_id")
        customer_chat_id = payload.get("customer_chat_id")
        draft_text = payload.get("draft_text", "")
        customer_name = payload.get("customer_name", "")

        owner_id = self.cfg.allowed_user_id

        if approved:
            self._stats["drafts_approved"] += 1
            if self.bot is not None and conn_id and customer_chat_id:
                try:
                    await self.bot.send_message(
                        chat_id=customer_chat_id,
                        text=draft_text,
                        parse_mode="HTML",
                        business_connection_id=conn_id,
                    )
                    logger.info("Đã gửi tin nhắn Telegram Business sau khi chủ duyệt (chat=%s)", customer_chat_id)
                    if owner_id:
                        await self.bot.send_message(
                            owner_id,
                            f"<b>Đã gửi tin nhắn cho khách {_html.escape(customer_name or str(customer_chat_id))} thành công!</b>",
                            parse_mode="HTML",
                        )
                except Exception as exc:
                    logger.warning("Lỗi gửi tin nhắn Telegram Business sau khi duyệt: %s", exc)
                    if owner_id:
                        await self.bot.send_message(
                            owner_id,
                            f"<b>Gửi tin cho khách thất bại:</b> {_html.escape(str(exc))}",
                            parse_mode="HTML",
                        )
        else:
            self._stats["drafts_denied"] += 1
            logger.info("Chủ đã từ chối hoặc thẻ nháp Telegram Business %s hết hạn (outcome=%s)", approval_id, outcome)

    # ---------- Ghi log & Thống kê ----------

    async def _log_interaction(
        self,
        conn_id: str,
        chat_id: int,
        sender_id: int,
        sender_name: str,
        message_text: str,
        reply_text: str,
        action_kind: str,
        status: str,
    ) -> None:
        """Ghi nhận lịch sử tương tác vào KV/DB."""
        if self.memory is None:
            return
        try:
            entry = {
                "id": f"{int(time.time() * 1000)}",
                "conn_id": conn_id,
                "chat_id": chat_id,
                "sender_id": sender_id,
                "sender_name": sender_name,
                "message_text": message_text[:200],
                "reply_text": reply_text[:200],
                "action_kind": action_kind,
                "status": status,
                "created_at": time.time(),
            }
            # Lưu 20 tương tác gần nhất
            raw_logs = await self.memory.kv_get("business:recent_logs")
            logs = json.loads(raw_logs) if raw_logs else []
            logs.insert(0, entry)
            logs = logs[:20]
            await self.memory.kv_set("business:recent_logs", json.dumps(logs))
        except Exception as exc:
            logger.debug("Lỗi lưu business log: %s", exc)

    async def get_status_report(self) -> dict:
        """Trả về báo cáo trạng thái Telegram Business phục vụ lệnh /business và API."""
        is_enabled_cfg = bool(getattr(self.cfg, "telegram_business_enabled", False))
        active_conn_id = None
        conn_info = None

        if self.memory is not None:
            try:
                active_conn_id = await self.memory.kv_get("business:active_connection")
                if active_conn_id:
                    raw = await self.memory.kv_get(f"business:connection:{active_conn_id}")
                    if raw:
                        conn_info = json.loads(raw)
            except Exception:
                pass

        recent_logs = []
        if self.memory is not None:
            try:
                raw_logs = await self.memory.kv_get("business:recent_logs")
                if raw_logs:
                    recent_logs = json.loads(raw_logs)
            except Exception:
                pass

        return {
            "config_enabled": is_enabled_cfg,
            "active_connection_id": active_conn_id,
            "connection_info": conn_info,
            "stats": dict(self._stats),
            "recent_logs": recent_logs,
            "products_count": len(self.catalog.get("products", [])),
            "faq_count": len(self.catalog.get("faq", [])),
        }
