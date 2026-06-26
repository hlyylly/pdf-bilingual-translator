"""FastAPI 入口：注册/登录、上传翻译、进度查询、下载。"""
import os
import re
import uuid

import fitz  # PyMuPDF
from fastapi import FastAPI, Request, Response, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, auth, worker
from .auth import current_user, COOKIE_NAME, make_token, MAX_AGE
from .languages import LANGUAGES, LANG_BY_CODE, DEFAULT_TARGET, lang_label
from .settings import (
    UPLOAD_DIR, BASE_DIR, FREE_DAILY_PAGES, PAGE_PACKS, MAX_UPLOAD_MB,
    MAX_CONCURRENT_JOBS, server_keys_ready,
)

app = FastAPI(title="PDF 双语翻译器", docs_url=None, redoc_url=None)

STATIC_DIR = os.path.join(BASE_DIR, "static")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


@app.on_event("startup")
def _startup():
    db.init_db()
    db.reset_stuck_jobs()
    if not server_keys_ready():
        _safe_print("[警告] 服务端 DeepSeek/Paddle 密钥未配置，翻译会失败。"
                    "请设置环境变量 DEEPSEEK_API_KEY / PADDLE_TOKEN 或填写 server_config.json")


def _safe_print(msg: str):
    """避免 Windows GBK 控制台对中文/emoji 报 UnicodeEncodeError。"""
    try:
        print(msg)
    except UnicodeEncodeError:
        import sys
        sys.stdout.buffer.write(msg.encode("utf-8", "replace") + b"\n")


def _user_public(user):
    used = db.pages_used_today(user["id"])
    credits = db.get_credits(user["id"])
    return {
        "username": user["username"],
        "free_daily": FREE_DAILY_PAGES,
        "free_used_today": used,
        "free_remaining_today": max(0, FREE_DAILY_PAGES - used),
        "credits": credits,
        "available": max(0, FREE_DAILY_PAGES - used) + credits,
        "max_upload_mb": MAX_UPLOAD_MB,
    }


def _job_public(j):
    return {
        "id": j["id"],
        "filename": j["filename"],
        "pages": j["pages"],
        "target_lang": j["target_lang"],
        "target_label": lang_label(j["target_lang"]),
        "status": j["status"],
        "phase": j["phase"],
        "progress": j["progress"],
        "total": j["total"],
        "message": j["message"],
        "has_output": bool(j["output_path"]),
        "created_at": j["created_at"],
    }


@app.get("/api/languages")
async def languages():
    return {"languages": LANGUAGES, "default": DEFAULT_TARGET}


@app.get("/api/packs")
async def packs():
    return {"free_daily": FREE_DAILY_PAGES, "packs": PAGE_PACKS}


# ---------------- 认证 ----------------
@app.post("/api/register")
async def register(username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(400, "用户名需为 3-20 位字母/数字/下划线")
    if len(password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    uid = db.create_user(username, password)
    if uid is None:
        raise HTTPException(409, "用户名已存在")
    resp = JSONResponse({"ok": True})
    _set_session(resp, uid)
    return resp


@app.post("/api/login")
async def login(username: str = Form(...), password: str = Form(...)):
    user = db.get_user_by_name(username.strip())
    if not user or not db.verify_password(password, user["password_hash"]):
        raise HTTPException(401, "用户名或密码错误")
    resp = JSONResponse({"ok": True})
    _set_session(resp, user["id"])
    return resp


@app.post("/api/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME)
    return resp


def _set_session(resp: Response, uid: int):
    resp.set_cookie(
        COOKIE_NAME, make_token(uid), max_age=MAX_AGE,
        httponly=True, samesite="lax", path="/",
    )


@app.get("/api/me")
async def me(user=Depends(current_user)):
    return _user_public(user)


# ---------------- 上传 / 翻译 ----------------
@app.post("/api/upload")
async def upload(file: UploadFile = File(...), target_lang: str = Form(DEFAULT_TARGET),
                 user=Depends(current_user)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "只接受 PDF 文件")
    if target_lang not in LANG_BY_CODE:
        target_lang = DEFAULT_TARGET

    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"文件超过 {MAX_UPLOAD_MB} MB 上限")

    job_id = uuid.uuid4().hex
    safe_name = re.sub(r"[^\w.\- ]", "_", os.path.basename(file.filename))
    pdf_path = os.path.join(UPLOAD_DIR, f"{job_id}_{safe_name}")
    with open(pdf_path, "wb") as f:
        f.write(data)

    # 统计页数（用于额度）
    try:
        doc = fitz.open(pdf_path)
        pages = doc.page_count
        doc.close()
    except Exception:
        os.remove(pdf_path)
        raise HTTPException(400, "无法读取该 PDF，文件可能损坏")
    if pages == 0:
        os.remove(pdf_path)
        raise HTTPException(400, "PDF 没有页面")

    # 额度校验 + 预扣：先扣每日免费额度，不足再扣页数包余额
    free_used = db.pages_used_today(user["id"])
    free_remaining = max(0, FREE_DAILY_PAGES - free_used)
    credits = db.get_credits(user["id"])
    available = free_remaining + credits
    if pages > available:
        os.remove(pdf_path)
        raise HTTPException(
            429,
            f"额度不足：本文件 {pages} 页，可用 {available} 页"
            f"（今日免费剩 {free_remaining} 页 + 页数包余额 {credits} 页）。"
            f"请购买页数包后再试。",
        )
    use_free = min(pages, free_remaining)
    use_credits = pages - use_free
    if use_free:
        db.add_usage(user["id"], use_free)
    if use_credits:
        db.add_credits(user["id"], -use_credits)
    db.create_job(job_id, user["id"], safe_name, pages, target_lang,
                  used_free=use_free, used_credits=use_credits)
    worker.submit_job(job_id, user["id"], pdf_path)

    return {"job_id": job_id, "pages": pages, **_user_public(user)}


@app.get("/api/jobs")
async def jobs(user=Depends(current_user)):
    return {"jobs": [_job_public(j) for j in db.list_jobs(user["id"])]}


@app.get("/api/jobs/{job_id}")
async def job_detail(job_id: str, user=Depends(current_user)):
    j = db.get_job(job_id, user["id"])
    if not j:
        raise HTTPException(404, "任务不存在")
    return _job_public(j)


@app.get("/api/download/{job_id}")
async def download(job_id: str, user=Depends(current_user)):
    j = db.get_job(job_id, user["id"])
    if not j or j["status"] != "done" or not j["output_path"]:
        raise HTTPException(404, "结果尚未就绪")
    if not os.path.exists(j["output_path"]):
        raise HTTPException(410, "文件已被清理")
    download_name = os.path.splitext(j["filename"])[0] + "-双语对照.pdf"
    return FileResponse(j["output_path"], media_type="application/pdf",
                        filename=download_name)


# ---------------- 页面 + 静态资源 ----------------
@app.get("/")
async def landing():
    return FileResponse(os.path.join(STATIC_DIR, "landing.html"))


@app.get("/app")
async def app_page():
    return FileResponse(os.path.join(STATIC_DIR, "app.html"))


# 静态资源（css/js/图片）
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
