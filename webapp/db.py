"""SQLite 数据访问层。表：users / usage / jobs。轻量、零外部依赖。"""
import os
import sqlite3
import threading
import hashlib
import secrets
from datetime import datetime, timezone

from .settings import DB_PATH, REFERRAL_BONUS

_write_lock = threading.Lock()
# 邀请码字母表（去掉易混淆的 0/O/1/I/l）
_REF_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                credits       INTEGER NOT NULL DEFAULT 0,
                referral_code TEXT UNIQUE,
                referred_by   INTEGER,
                referral_rewarded INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage (
                user_id INTEGER NOT NULL,
                day     TEXT NOT NULL,
                pages   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id          TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                filename    TEXT NOT NULL,
                pages       INTEGER NOT NULL DEFAULT 0,
                used_free   INTEGER NOT NULL DEFAULT 0,
                used_credits INTEGER NOT NULL DEFAULT 0,
                target_lang TEXT NOT NULL DEFAULT 'zh-Hans',
                status      TEXT NOT NULL,
                phase       TEXT NOT NULL DEFAULT '',
                progress    INTEGER NOT NULL DEFAULT 0,
                total       INTEGER NOT NULL DEFAULT 0,
                message     TEXT NOT NULL DEFAULT '',
                output_path TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS orders (
                out_trade_no TEXT PRIMARY KEY,
                user_id      INTEGER NOT NULL,
                pages        INTEGER NOT NULL,
                amount_fen   INTEGER NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                wx_trade_no  TEXT,
                created_at   TEXT NOT NULL,
                paid_at      TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at DESC);
            """
        )
        # 兼容旧库：补列
        jcols = {r["name"] for r in c.execute("PRAGMA table_info(jobs)").fetchall()}
        if "target_lang" not in jcols:
            c.execute("ALTER TABLE jobs ADD COLUMN target_lang TEXT NOT NULL DEFAULT 'zh-Hans'")
        if "used_free" not in jcols:
            c.execute("ALTER TABLE jobs ADD COLUMN used_free INTEGER NOT NULL DEFAULT 0")
        if "used_credits" not in jcols:
            c.execute("ALTER TABLE jobs ADD COLUMN used_credits INTEGER NOT NULL DEFAULT 0")
        ucols = {r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        if "credits" not in ucols:
            c.execute("ALTER TABLE users ADD COLUMN credits INTEGER NOT NULL DEFAULT 0")
        if "referral_code" not in ucols:
            c.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
        if "referred_by" not in ucols:
            c.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
        if "referral_rewarded" not in ucols:
            c.execute("ALTER TABLE users ADD COLUMN referral_rewarded INTEGER NOT NULL DEFAULT 0")
        # 给历史用户补邀请码
        for r in c.execute("SELECT id FROM users WHERE referral_code IS NULL").fetchall():
            c.execute("UPDATE users SET referral_code=? WHERE id=?",
                      (_gen_unique_ref_code(c), r["id"]))


# ---------- 密码哈希（stdlib pbkdf2，无需编译依赖） ----------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return f"pbkdf2_sha256$200000${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, want = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return secrets.compare_digest(dk.hex(), want)
    except Exception:
        return False


def _now():
    return datetime.now(timezone.utc).isoformat()


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------- 用户 ----------
def _gen_unique_ref_code(c, length=6):
    """在给定连接上生成不冲突的邀请码。"""
    while True:
        code = "".join(secrets.choice(_REF_ALPHABET) for _ in range(length))
        if not c.execute("SELECT 1 FROM users WHERE referral_code=?", (code,)).fetchone():
            return code


def create_user(username: str, password: str, referred_by=None):
    with _write_lock, _conn() as c:
        try:
            code = _gen_unique_ref_code(c)
            cur = c.execute(
                "INSERT INTO users(username, password_hash, referral_code, referred_by, created_at) "
                "VALUES (?,?,?,?,?)",
                (username, hash_password(password), code, referred_by, _now()),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def get_user_by_referral_code(code: str):
    if not code:
        return None
    with _conn() as c:
        return c.execute("SELECT * FROM users WHERE referral_code=?", (code,)).fetchone()


def referral_stats(user_id: int):
    """返回 (邀请注册人数, 已奖励人数)。"""
    with _conn() as c:
        invited = c.execute("SELECT COUNT(*) n FROM users WHERE referred_by=?",
                            (user_id,)).fetchone()["n"]
        rewarded = c.execute(
            "SELECT COUNT(*) n FROM users WHERE referred_by=? AND referral_rewarded=1",
            (user_id,)).fetchone()["n"]
        return invited, rewarded


def get_user_by_name(username: str):
    with _conn() as c:
        return c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def get_user(user_id: int):
    with _conn() as c:
        return c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


# ---------- 额度 ----------
def pages_used_today(user_id: int) -> int:
    with _conn() as c:
        row = c.execute(
            "SELECT pages FROM usage WHERE user_id=? AND day=?", (user_id, today())
        ).fetchone()
        return row["pages"] if row else 0


def add_usage(user_id: int, pages: int):
    """增减今日已用免费页数（pages 可为负数用于回滚）。"""
    with _write_lock, _conn() as c:
        c.execute(
            """INSERT INTO usage(user_id, day, pages) VALUES(?,?,?)
               ON CONFLICT(user_id, day) DO UPDATE SET pages = MAX(0, pages + ?)""",
            (user_id, today(), max(0, pages), pages),
        )


def get_credits(user_id: int) -> int:
    with _conn() as c:
        row = c.execute("SELECT credits FROM users WHERE id=?", (user_id,)).fetchone()
        return row["credits"] if row else 0


def add_credits(user_id: int, pages: int) -> int:
    """增减页数包余额（充值为正、消耗/退款为负），返回更新后的余额。不会扣成负数。"""
    with _write_lock, _conn() as c:
        c.execute("UPDATE users SET credits = MAX(0, credits + ?) WHERE id=?",
                  (pages, user_id))
        row = c.execute("SELECT credits FROM users WHERE id=?", (user_id,)).fetchone()
        return row["credits"] if row else 0


# ---------- 任务 ----------
def create_job(job_id, user_id, filename, pages, target_lang="zh-Hans",
               used_free=0, used_credits=0):
    with _write_lock, _conn() as c:
        c.execute(
            """INSERT INTO jobs(id,user_id,filename,pages,used_free,used_credits,
                                target_lang,status,total,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (job_id, user_id, filename, pages, used_free, used_credits,
             target_lang, "queued", pages, _now(), _now()),
        )


def update_job(job_id, **fields):
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in fields)
    with _write_lock, _conn() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def get_job(job_id, user_id=None):
    with _conn() as c:
        if user_id is None:
            return c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return c.execute(
            "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)
        ).fetchone()


def list_jobs(user_id, limit=50):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()


# ---------- 订单（微信支付） ----------
def create_order(out_trade_no, user_id, pages, amount_fen):
    with _write_lock, _conn() as c:
        c.execute(
            """INSERT INTO orders(out_trade_no,user_id,pages,amount_fen,status,created_at)
               VALUES(?,?,?,?,'pending',?)""",
            (out_trade_no, user_id, pages, amount_fen, _now()),
        )


def get_order(out_trade_no, user_id=None):
    with _conn() as c:
        if user_id is None:
            return c.execute("SELECT * FROM orders WHERE out_trade_no=?",
                             (out_trade_no,)).fetchone()
        return c.execute("SELECT * FROM orders WHERE out_trade_no=? AND user_id=?",
                         (out_trade_no, user_id)).fetchone()


def mark_order_paid(out_trade_no, wx_trade_no=None):
    """幂等：仅当订单仍为 pending 时置为 paid 并发放页数，返回是否本次发放。

    回调与轮询可能同时到达，用 UPDATE...WHERE status='pending' 的影响行数保证只发一次。
    """
    with _write_lock, _conn() as c:
        cur = c.execute(
            "UPDATE orders SET status='paid', wx_trade_no=?, paid_at=? "
            "WHERE out_trade_no=? AND status='pending'",
            (wx_trade_no, _now(), out_trade_no),
        )
        if cur.rowcount != 1:
            return False  # 已处理过或不存在
        row = c.execute("SELECT user_id, pages FROM orders WHERE out_trade_no=?",
                        (out_trade_no,)).fetchone()
        uid = row["user_id"]
        c.execute("UPDATE users SET credits = credits + ? WHERE id=?", (row["pages"], uid))
        # 邀请有礼：被推荐人首次完成充值 → 奖励推荐人，每位好友仅一次
        u = c.execute("SELECT referred_by, referral_rewarded FROM users WHERE id=?",
                      (uid,)).fetchone()
        if u and u["referred_by"] and not u["referral_rewarded"]:
            c.execute("UPDATE users SET credits = credits + ? WHERE id=?",
                      (REFERRAL_BONUS, u["referred_by"]))
            c.execute("UPDATE users SET referral_rewarded=1 WHERE id=?", (uid,))
        return True


def mark_order_failed(out_trade_no):
    with _write_lock, _conn() as c:
        c.execute("UPDATE orders SET status='failed' WHERE out_trade_no=? AND status='pending'",
                  (out_trade_no,))


def list_orders(user_id, limit=20):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()


def reset_stuck_jobs():
    """启动时把残留的 running/queued 任务标记为失败（进程重启后无法恢复内存任务）。"""
    with _write_lock, _conn() as c:
        c.execute(
            "UPDATE jobs SET status='failed', message='服务重启，任务中断' "
            "WHERE status IN ('queued','running')"
        )
