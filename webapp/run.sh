#!/bin/bash
# 服务器启动脚本（宝塔 Python 项目 / 手动均可）。
# 在项目根目录执行：bash webapp/run.sh
set -e
cd "$(dirname "$0")/.."          # 切到项目根目录

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"          # 翻译任务在后台线程跑，单 worker 即可；多 worker 需共享 SQLite（WAL 已开）

# 密钥可写在 webapp/server_config.json，或用环境变量：
# export DEEPSEEK_API_KEY=sk-xxx
# export PADDLE_TOKEN=xxx
# export APP_SECRET_KEY=固定的随机串

exec uvicorn webapp.main:app --host "$HOST" --port "$PORT" --workers "$WORKERS"
