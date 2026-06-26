# 网页版部署指南（服务器 39.105.206.76）

FastAPI 后端 + 原生前端，复用核心 `pdf_translator` 包。用户注册账号 → 上传 PDF → 后台 OCR+翻译+渲染 → 下载双语对照 PDF。**密钥由服务端统一提供，每账号每天 300 页额度。**

## 一、上传代码到服务器

```bash
# 本机推送（已配置 HTTPS + token）
git add -A && git commit -m "feat: 网页版" && git push

# 服务器拉取（假设放在 /www/wwwroot/pdf-translator）
cd /www/wwwroot && git clone <你的仓库> pdf-translator
```

## 二、创建虚拟环境 + 装依赖（宝塔 / 手动）

> 不要用系统 apt/dnf 装包，用虚拟环境。PaddleOCR 解析是调远程 API，本地不需要装 paddle。

```bash
cd /www/wwwroot/pdf-translator
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements-web.txt
```

## 三、配置密钥与参数

两种方式任选其一（环境变量优先级最高）：

**方式 A：写配置文件**（不进仓库）
```bash
cp webapp/server_config.example.json webapp/server_config.json
# 编辑填入真实 deepseek_key / paddle_token
# secret_key 用下面命令生成并固定，否则每次重启登录态失效：
python -c "import secrets;print(secrets.token_hex(32))"
```

**方式 B：环境变量**（写进启动脚本或宝塔的环境变量栏）
```bash
export DEEPSEEK_API_KEY=sk-xxxx
export PADDLE_TOKEN=xxxx
export APP_SECRET_KEY=固定的随机串
export DAILY_PAGE_QUOTA=300        # 可选，默认 300
export MAX_CONCURRENT_JOBS=2       # 可选，全局同时翻译的任务数，保护 API 额度
export MAX_UPLOAD_MB=50            # 可选
```

## 四、启动

```bash
# 直接启动（前台测试）
bash webapp/run.sh
# 或指定端口
PORT=8000 bash webapp/run.sh
```

访问 `http://39.105.206.76:8000` 即可。

### 宝塔「Python 项目管理器」推荐配置
- 项目路径：`/www/wwwroot/pdf-translator`
- 启动方式 / 启动文件：`webapp.main:app`（框架选 uvicorn/asgi），或运行命令：
  `uvicorn webapp.main:app --host 0.0.0.0 --port 8000`
- 端口：`8000`
- 在「环境变量」里填入上面的密钥变量
- 保存后用「守护进程/Supervisor」保活

## 五、Nginx 反代 + 域名（可选，推荐）

在宝塔给站点加反向代理到 `http://127.0.0.1:8000`，并放开上传大小：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 600s;          # 翻译耗时较长，加大超时
    client_max_body_size 60m;         # 要大于 MAX_UPLOAD_MB
}
```

配好后申请 Let's Encrypt 证书走 HTTPS。

## 六、运维须知

- **数据目录** `webapp/data/`（已 gitignore）：
  - `app.db` —— SQLite（用户、额度、任务），WAL 模式
  - `uploads/` —— 上传的原始 PDF，任务结束后自动删除
  - `outputs/` —— 生成的双语 PDF，提供下载（不会自动清理，需定期清）
- **清理旧结果**（例如保留 7 天）：可加一条定时任务
  `find /www/wwwroot/pdf-translator/webapp/data/outputs -type f -mtime +7 -delete`
- **额度按 UTC 自然日重置**，每账号每天 `DAILY_PAGE_QUOTA` 页，按 PDF 页数计，提交时预扣、失败自动退还。
- **进程重启**：内存中的后台任务会丢失，启动时会把残留的 queued/running 任务标记为失败，用户重新上传即可。
- **多 worker**：默认单 worker（翻译跑在后台线程足够）。若要多 worker，SQLite 已开 WAL 可共享，但每个 worker 有独立线程池，`MAX_CONCURRENT_JOBS` 会按 worker 数翻倍，注意 API 额度。
