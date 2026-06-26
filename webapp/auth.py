"""会话：用 HMAC 签名的 cookie 携带 user_id，无需服务端会话表。"""
import hmac
import json
import time
import base64
import hashlib

from fastapi import Request, HTTPException

from .settings import SECRET_KEY, ADMIN_USERS
from . import db

COOKIE_NAME = "session"
MAX_AGE = 14 * 24 * 3600  # 14 天


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user_id: int) -> str:
    payload = _b64e(json.dumps({"uid": user_id, "ts": int(time.time())}).encode())
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{_b64e(sig)}"


def _verify_token(token: str):
    try:
        payload, sig = token.split(".")
        want = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64d(sig), want):
            return None
        data = json.loads(_b64d(payload))
        if int(time.time()) - data["ts"] > MAX_AGE:
            return None
        return data["uid"]
    except Exception:
        return None


def current_user(request: Request):
    """依赖：返回登录用户行；未登录抛 401。"""
    token = request.cookies.get(COOKIE_NAME)
    uid = _verify_token(token) if token else None
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    user = db.get_user(uid)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def current_admin(request: Request):
    """依赖：仅 ADMIN_USERS 内的账号可访问，否则 403。"""
    user = current_user(request)
    if user["username"] not in ADMIN_USERS:
        raise HTTPException(status_code=403, detail="无权限")
    return user
