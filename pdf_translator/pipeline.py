"""批量流水线编排。
阶段A：并发 OCR + 翻译（网络IO，线程安全）；阶段B：串行渲染（PyMuPDF）。
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .ocr import ocr_pdf_async
from .translate import translate_all_pages
from .render import render_dual_pdf


def _ocr_and_translate(pdf_path, idx, total, config, log):
    name = os.path.basename(pdf_path)
    tag = f"[{idx}/{total}] "
    log(f"{tag}OCR 提交: {name[:60]}")
    en_pages, page_images = ocr_pdf_async(pdf_path, config, tag=tag, log=log)
    if not en_pages:
        log(f"{tag}[跳过] OCR 无结果")
        return pdf_path, {}, {}, {}
    log(f"{tag}翻译 {len(en_pages)} 页...")
    zh_pages = translate_all_pages(en_pages, config, log=log)
    log(f"{tag}翻译完成: {name[:60]}")
    return pdf_path, en_pages, zh_pages, page_images


def _write_md(path, pages, head):
    n = len(pages)
    with open(path, "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(f"\n\n<!-- {head} {i + 1} -->\n\n{pages.get(i, '')}\n")


def process_batch(pdf_paths, config, output_dir, log=print, progress=None,
                  save_md=True, cancel=None):
    """批量处理 PDF 列表。
    log(str)          : 文本日志回调
    progress(done,tot): 进度回调（已完成 PDF 数 / 总数）
    cancel()->bool    : 返回 True 则尽快停止
    返回已成功生成的 dual.pdf 路径列表。
    """
    os.makedirs(output_dir, exist_ok=True)
    total = len(pdf_paths)
    done = 0
    if progress:
        progress(0, total)

    # 阶段A：并发 OCR + 翻译
    results = {}
    with ThreadPoolExecutor(max_workers=config.concurrent_pdf) as ex:
        futures = {
            ex.submit(_ocr_and_translate, p, i, total, config, log): p
            for i, p in enumerate(pdf_paths, 1)
        }
        for fut in as_completed(futures):
            if cancel and cancel():
                break
            pdf_path, en, zh, imgs = fut.result()
            results[pdf_path] = (en, zh, imgs)

    # 阶段B：串行渲染
    log("\n=== 渲染对照PDF（串行）===")
    produced = []
    for pdf_path in pdf_paths:
        if cancel and cancel():
            break
        en_pages, zh_pages, page_images = results.get(pdf_path, ({}, {}, {}))
        if not en_pages:
            done += 1
            if progress:
                progress(done, total)
            continue
        basename = os.path.splitext(os.path.basename(pdf_path))[0]
        dual_path = os.path.join(output_dir, f"{basename}-dual.pdf")
        if save_md:
            _write_md(os.path.join(output_dir, f"{basename}-en.md"), en_pages, "Page")
            _write_md(os.path.join(output_dir, f"{basename}-zh.md"), zh_pages, "第")
        try:
            render_dual_pdf(pdf_path, en_pages, zh_pages, page_images, dual_path, log=log)
            produced.append(dual_path)
            log(f"  [完成] {os.path.basename(dual_path)}")
        except Exception as e:
            log(f"  [渲染失败] {basename[:50]}: {e}")
        done += 1
        if progress:
            progress(done, total)
    return produced


def translate_pdfs(pdf_paths, config, output_dir, log=print, progress=None, cancel=None):
    """对外主入口：校验配置 → 批量处理。返回 (produced_list, elapsed_sec)。"""
    missing = config.validate()
    if missing:
        raise ValueError("缺少必填配置：" + "、".join(missing))
    pdf_paths = [os.path.abspath(p) for p in pdf_paths if p.lower().endswith(".pdf")]
    if not pdf_paths:
        raise ValueError("没有可处理的 PDF 文件")
    start = time.time()
    produced = process_batch(pdf_paths, config, output_dir, log=log,
                             progress=progress, cancel=cancel)
    return produced, time.time() - start
