"""服务端配置：API 密钥、目录、额度、并发。密钥来自环境变量或 server_config.json（均不进仓库）。"""
import os
import json
import secrets

from pdf_translator import Config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
OUTPUT_DIR = os.path.join(DATA_DIR, "outputs")
DB_PATH = os.path.join(DATA_DIR, "app.db")
SERVER_CONFIG = os.path.join(BASE_DIR, "server_config.json")

for d in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR):
    os.makedirs(d, exist_ok=True)


def _load_server_config():
    data = {}
    if os.path.exists(SERVER_CONFIG):
        try:
            with open(SERVER_CONFIG, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    # 环境变量优先
    env_map = {
        "deepseek_key": "DEEPSEEK_API_KEY",
        "paddle_token": "PADDLE_TOKEN",
        "deepseek_model": "DEEPSEEK_MODEL",
        "secret_key": "APP_SECRET_KEY",
        "free_daily_pages": "FREE_DAILY_PAGES",
        "max_concurrent_jobs": "MAX_CONCURRENT_JOBS",
        "max_upload_mb": "MAX_UPLOAD_MB",
    }
    for key, env in env_map.items():
        if os.getenv(env):
            data[key] = os.getenv(env)
    return data


_cfg = _load_server_config()

# ---- 业务参数 ----
# 免费版每日额度（每天 0 点 UTC 重置）；付费为一次性页数包，进账户余额、永久有效
FREE_DAILY_PAGES = int(_cfg.get("free_daily_pages", 50))
MAX_CONCURRENT_JOBS = int(_cfg.get("max_concurrent_jobs", 2))
MAX_UPLOAD_MB = int(_cfg.get("max_upload_mb", 50))

# 页数包（落地页展示 + 充值校验）。price 单位：元
PAGE_PACKS = _cfg.get("page_packs") or [
    {"pages": 300, "price": 9.9},
    {"pages": 1000, "price": 19.9},
]

# 会话签名密钥：未配置则生成一次性密钥（重启会使现有登录失效，生产请固定它）
SECRET_KEY = _cfg.get("secret_key") or secrets.token_hex(32)


def build_translator_config():
    """构造 pdf_translator.Config，注入服务端共享密钥。"""
    c = Config()
    c.deepseek_key = _cfg.get("deepseek_key", "")
    c.paddle_token = _cfg.get("paddle_token", "")
    if _cfg.get("deepseek_model"):
        c.deepseek_model = _cfg["deepseek_model"]
    return c


def server_keys_ready():
    c = build_translator_config()
    return not c.validate()
