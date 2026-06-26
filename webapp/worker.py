"""后台任务执行：单个 PDF → OCR → 翻译 → 渲染对照 PDF。进度写入数据库。

用一个有界线程池限制全局并发（保护共享 API 额度）。失败时回滚已预扣的页数额度。
"""
import os
import traceback
from concurrent.futures import ThreadPoolExecutor

from pdf_translator.ocr import ocr_pdf_async
from pdf_translator.translate import translate_all_pages
from pdf_translator.render import render_dual_pdf

from . import db
from .settings import OUTPUT_DIR, MAX_CONCURRENT_JOBS, build_translator_config

_pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS, thread_name_prefix="job")


def submit_job(job_id: str, user_id: int, pdf_path: str):
    _pool.submit(_run, job_id, user_id, pdf_path)


def _run(job_id: str, user_id: int, pdf_path: str):
    config = build_translator_config()
    job = db.get_job(job_id)
    reserved_pages = job["pages"] if job else 0
    tail = []  # 最近日志行

    def log(line: str):
        line = str(line).strip()
        if not line:
            return
        tail.append(line)
        del tail[:-6]  # 只留最近 6 行
        db.update_job(job_id, message="\n".join(tail))

    try:
        db.update_job(job_id, status="running", phase="ocr", message="解析 PDF 中…")
        en_pages, page_images = ocr_pdf_async(pdf_path, config, tag="", log=log)
        if not en_pages:
            raise RuntimeError("OCR 未返回结果")

        total = len(en_pages)
        db.update_job(job_id, phase="translate", total=total, progress=0,
                      message=f"OCR 完成 {total} 页，翻译中…")
        zh_pages = translate_all_pages(en_pages, config, log=log)
        db.update_job(job_id, progress=total, phase="render", message="渲染对照 PDF…")

        base = os.path.splitext(os.path.basename(pdf_path))[0]
        out_path = os.path.join(OUTPUT_DIR, f"{job_id}_{base}-dual.pdf")
        render_dual_pdf(pdf_path, en_pages, zh_pages, page_images, out_path, log=log)

        db.update_job(job_id, status="done", phase="done", progress=total,
                      output_path=out_path, message="完成")
    except Exception as e:
        # 失败：回滚预扣额度
        if reserved_pages:
            db.add_usage(user_id, -reserved_pages)
        db.update_job(job_id, status="failed", phase="failed",
                      message=f"失败：{str(e)[:200]}")
        traceback.print_exc()
    finally:
        # 清理上传的原始文件，节省磁盘
        try:
            os.remove(pdf_path)
        except OSError:
            pass
