"""1.2.0 Khối 4: validate initData Telegram WebApp — chữ ký
HMAC đúng/sai, hết hạn, sai user."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from mulon.webapp_server import validate_init_data

TOKEN = "123456:TEST-TOKEN"
OWNER = 424242


def make_init_data(user_id=OWNER, auth_date=None, token=TOKEN,
                   extra=None):
    data = {
        "query_id": "AAE1test",
        "user": json.dumps({"id": user_id, "first_name": "Chủ"},
                           separators=(",", ":"), ensure_ascii=False),
        "auth_date": str(auth_date if auth_date is not None
                         else int(time.time())),
    }
    if extra:
        data.update(extra)
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(),
                      hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(),
                            hashlib.sha256).hexdigest()
    return urlencode(data)


def test_valid_init_data():
    user = validate_init_data(make_init_data(), TOKEN, OWNER)
    assert user is not None and user["id"] == OWNER


def test_tampered_signature_rejected():
    raw = make_init_data()
    bad = raw[:-4] + "0000"
    assert validate_init_data(bad, TOKEN, OWNER) is None
    # Đổi user sau khi ký -> chữ ký sai.
    forged = make_init_data(user_id=OWNER)
    forged = forged.replace("424242", "999999")
    assert validate_init_data(forged, TOKEN, OWNER) is None


def test_wrong_token_rejected():
    raw = make_init_data(token="999:KHAC")
    assert validate_init_data(raw, TOKEN, OWNER) is None


def test_expired_rejected():
    old = int(time.time()) - 7200  # 2 giờ trước
    raw = make_init_data(auth_date=old)
    assert validate_init_data(raw, TOKEN, OWNER) is None


def test_wrong_user_rejected():
    raw = make_init_data(user_id=111)
    assert validate_init_data(raw, TOKEN, OWNER) is None


def test_missing_and_garbage_rejected():
    assert validate_init_data("", TOKEN, OWNER) is None
    assert validate_init_data("khong-phai-init-data", TOKEN,
                              OWNER) is None
    assert validate_init_data(make_init_data(), "", OWNER) is None
    assert validate_init_data(make_init_data(), TOKEN, 0) is None
