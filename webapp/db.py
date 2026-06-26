"""SQLite 数据访问层。表：users / usage / jobs。轻量、零外部依赖。"""
import os
import sqlite3
import threading
import hashlib
import secrets
from datetime import datetime, timezone

from .settings import DB_PATH

_write_lock = threading.Lock()


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
            """
        )
        # 兼容旧库：补列
        cols = {r["name"] for r in c.execute("PRAGMA table_info(jobs)").fetchall()}
        if "target_lang" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN target_lang TEXT NOT NULL DEFAULT 'zh-Hans'")


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
def create_user(username: str, password: str):
    with _write_lock, _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO users(username, password_hash, created_at) VALUES (?,?,?)",
                (username, hash_password(password), _now()),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


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
    """增减今日已用页数（pages 可为负数用于回滚）。"""
    with _write_lock, _conn() as c:
        c.execute(
            """INSERT INTO usage(user_id, day, pages) VALUES(?,?,?)
               ON CONFLICT(user_id, day) DO UPDATE SET pages = MAX(0, pages + ?)""",
            (user_id, today(), max(0, pages), pages),
        )


# ---------- 任务 ----------
def create_job(job_id, user_id, filename, pages, target_lang="zh-Hans"):
    with _write_lock, _conn() as c:
        c.execute(
            """INSERT INTO jobs(id,user_id,filename,pages,target_lang,status,total,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (job_id, user_id, filename, pages, target_lang, "queued", pages, _now(), _now()),
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


def reset_stuck_jobs():
    """启动时把残留的 running/queued 任务标记为失败（进程重启后无法恢复内存任务）。"""
    with _write_lock, _conn() as c:
        c.execute(
            "UPDATE jobs SET status='failed', message='服务重启，任务中断' "
            "WHERE status IN ('queued','running')"
        )
