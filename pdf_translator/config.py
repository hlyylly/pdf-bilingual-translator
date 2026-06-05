"""配置：API key 与运行参数。优先级 env > config.json(当前目录) > 用户目录配置。"""
import os
import json
from dataclasses import dataclass, asdict, fields

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".pdf-bilingual-translator")
USER_CONFIG = os.path.join(CONFIG_DIR, "config.json")


@dataclass
class Config:
    # ---- 必填密钥 ----
    deepseek_key: str = ""
    paddle_token: str = ""
    # ---- DeepSeek ----
    deepseek_base: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    # ---- PaddleOCR-VL ----
    paddle_job_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    paddle_model: str = "PaddleOCR-VL-1.6"
    # ---- 运行参数 ----
    concurrent_pdf: int = 3        # 同时处理的 PDF 数
    concurrent_translate: int = 6  # 单个 PDF 内逐页翻译并发
    poll_interval: int = 5         # OCR 轮询间隔(秒)

    @classmethod
    def load(cls):
        data = {}
        for path in (os.path.join(os.getcwd(), "config.json"), USER_CONFIG):
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        data.update(json.load(f))
                    break
                except Exception:
                    pass
        # 环境变量覆盖
        if os.getenv("DEEPSEEK_API_KEY"):
            data["deepseek_key"] = os.getenv("DEEPSEEK_API_KEY")
        if os.getenv("PADDLE_TOKEN"):
            data["paddle_token"] = os.getenv("PADDLE_TOKEN")
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self):
        """保存到用户目录（不会写进项目仓库）。"""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(USER_CONFIG, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        return USER_CONFIG

    def validate(self):
        """返回缺失的必填项列表（空=OK）。"""
        missing = []
        if not self.deepseek_key.strip():
            missing.append("DeepSeek API Key")
        if not self.paddle_token.strip():
            missing.append("PaddleOCR Token")
        return missing
