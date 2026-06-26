"""DeepSeek 逐页翻译。保留 LaTeX/Markdown/表格，<img> 标签用占位符保护。"""
import re
import time
import threading
import openai
from concurrent.futures import ThreadPoolExecutor, as_completed

def build_system_prompt(target_lang="Simplified Chinese"):
    """根据目标语言生成翻译指令；源语言由模型自动识别，已是目标语言则保持不变。"""
    return (
        "You are a professional academic translator. "
        f"Translate the given Markdown document into {target_lang}, "
        "automatically detecting the source language. "
        f"If a segment is already written in {target_lang}, leave it unchanged. "
        "Keep ALL Markdown syntax intact: headings (#, ##, ###), lists (-, *, 1.), "
        "formulas ($...$ and $$...$$), code blocks (```), HTML tables (<table>...</table>), "
        "bold/italic (**, *), links. "
        "Keep LaTeX formulas, math, variable names, proper nouns and URLs UNCHANGED. "
        "For <table> blocks, translate only the human-readable cell text, keep the HTML tags. "
        f"Output ONLY the translated Markdown in {target_lang}, no explanations."
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
    system_prompt = build_system_prompt(getattr(config, "target_lang", "Simplified Chinese"))
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=config.deepseek_model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
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


def translate_all_pages(en_pages, config, log=print, progress=None):
    """逐页翻译。progress(done, total) 可选回调：每完成一页回报一次。"""
    zh_pages = {}
    total = len(en_pages)
    done = 0
    with ThreadPoolExecutor(max_workers=config.concurrent_translate) as ex:
        futures = [ex.submit(translate_page, md, idx, config, log)
                   for idx, md in en_pages.items()]
        for fut in as_completed(futures):
            idx, zh = fut.result()
            zh_pages[idx] = zh
            done += 1
            if progress:
                progress(done, total)
    return zh_pages
