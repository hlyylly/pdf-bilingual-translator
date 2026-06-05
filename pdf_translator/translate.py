"""DeepSeek 逐页翻译。保留 LaTeX/Markdown/表格，<img> 标签用占位符保护。"""
import re
import time
import threading
import openai
from concurrent.futures import ThreadPoolExecutor, as_completed

SYSTEM_PROMPT = (
    "You are a professional academic translator. "
    "Translate English Markdown to Simplified Chinese (zh-CN) while keeping ALL Markdown "
    "syntax intact: headings (#, ##, ###), lists (-, *, 1.), formulas ($...$ and $$...$$), "
    "code blocks (```), HTML tables (<table>...</table>), bold/italic (**, *), links. "
    "Keep LaTeX formulas, math, variable names, proper nouns and URLs UNCHANGED. "
    "For <table> blocks, translate only the human-readable cell text, keep the HTML tags. "
    "Output ONLY the translated Markdown, no explanations."
)

_IMG_TAG_RE = re.compile(r'<img\b[^>]*?/?>', re.IGNORECASE)
_local = threading.local()


def _get_client(config):
    if not hasattr(_local, "client"):
        _local.client = openai.OpenAI(api_key=config.deepseek_key,
                                      base_url=config.deepseek_base)
    return _local.client


def _protect_imgs(md_text):
    """把 <img> 标签换成占位符，避免模型改坏 src/属性，顺带省 token。"""
    holders = []

    def repl(m):
        holders.append(m.group(0))
        return f'⟦IMG{len(holders) - 1}⟧'

    return _IMG_TAG_RE.sub(repl, md_text), holders


def _restore_imgs(text, holders):
    for i, tag in enumerate(holders):
        text = text.replace(f'⟦IMG{i}⟧', tag)
    return text


def translate_page(md_text, idx, config, log=print):
    if not md_text or len(md_text.strip()) < 3:
        return idx, md_text
    protected, holders = _protect_imgs(md_text)
    client = _get_client(config)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=config.deepseek_model,
                temperature=0,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": protected},
                ],
            )
            out = resp.choices[0].message.content.strip()
            return idx, _restore_imgs(out, holders)
        except Exception as e:
            if attempt < 2:
                time.sleep(2 + attempt * 2)
            else:
                log(f"    [翻译失败] 第{idx + 1}页: {str(e)[:120]}")
    return idx, md_text


def translate_all_pages(en_pages, config, log=print):
    zh_pages = {}
    with ThreadPoolExecutor(max_workers=config.concurrent_translate) as ex:
        futures = [ex.submit(translate_page, md, idx, config, log)
                   for idx, md in en_pages.items()]
        for fut in as_completed(futures):
            idx, zh = fut.result()
            zh_pages[idx] = zh
    return zh_pages
