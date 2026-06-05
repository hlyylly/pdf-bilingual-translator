"""PaddleOCR-VL 异步 OCR：提交 PDF → 轮询 → 逐页 Markdown + 下载页内图片。

关键：关闭 restructurePages / mergeTables，保证 OCR 结果与原 PDF 严格 1:1 逐页对应。
"""
import json
import time
import base64
import requests

# 逐页 1:1 对应所需的参数（不要开 restructurePages / mergeTables）
OPTIONAL_PAYLOAD = {
    "markdownIgnoreLabels": [
        "header", "header_image", "footer", "footer_image",
        "number", "footnote", "aside_text",
    ],
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useLayoutDetection": True,
    "useChartRecognition": False,
    "useSealRecognition": True,
    "useOcrForImageBlock": False,
    "mergeTables": False,
    "relevelTitles": True,
    "layoutShapeMode": "auto",
    "promptLabel": "ocr",
    "repetitionPenalty": 1,
    "temperature": 0,
    "topP": 1,
    "minPixels": 147384,
    "maxPixels": 2822400,
    "layoutNms": True,
    "restructurePages": False,
}


def _download_image(url, retries=3):
    """下载图片为 bytes；URL 直链，失败重试。也兼容 base64 字符串。"""
    if not isinstance(url, str):
        return None
    if not url.startswith("http"):
        try:
            return base64.b64decode(url.split(",", 1)[-1])
        except Exception:
            return None
    for i in range(retries):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 200 and r.content:
                return r.content
        except Exception:
            pass
        time.sleep(1 + i)
    return None


def ocr_pdf_async(pdf_path, config, tag="", log=print):
    """提交 PDF 为异步 job，轮询到 done。
    返回 (en_pages, page_images)：
      en_pages    = {page_idx: english_markdown}
      page_images = {page_idx: {"imgs/xxx.jpg": bytes}}
    失败返回 ({}, {})。
    """
    headers = {"Authorization": f"bearer {config.paddle_token}"}
    data = {"model": config.paddle_model, "optionalPayload": json.dumps(OPTIONAL_PAYLOAD)}
    job_url = config.paddle_job_url

    # 提交（带重试）
    job_id = None
    for attempt in range(3):
        try:
            with open(pdf_path, "rb") as f:
                resp = requests.post(job_url, headers=headers,
                                     data=data, files={"file": f}, timeout=120)
            if resp.status_code == 200:
                job_id = resp.json()["data"]["jobId"]
                break
            log(f"  {tag}[提交失败] HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log(f"  {tag}[提交异常] {str(e)[:120]}")
        time.sleep(3 + attempt * 3)
    if not job_id:
        return {}, {}

    log(f"  {tag}job 提交成功 id={job_id}")

    # 轮询
    jsonl_url = ""
    while True:
        try:
            r = requests.get(f"{job_url}/{job_id}", headers=headers, timeout=60)
            d = r.json()["data"]
        except Exception as e:
            log(f"  {tag}[轮询异常] {str(e)[:120]}，继续重试")
            time.sleep(config.poll_interval)
            continue

        state = d["state"]
        if state == "done":
            ep = d.get("extractProgress", {})
            log(f"  {tag}OCR 完成，{ep.get('extractedPages')} 页")
            jsonl_url = d["resultUrl"]["jsonUrl"]
            break
        elif state == "failed":
            log(f"  {tag}[OCR失败] {d.get('errorMsg')}")
            return {}, {}
        elif state == "running":
            ep = d.get("extractProgress", {})
            log(f"  {tag}OCR 运行中 {ep.get('extractedPages')}/{ep.get('totalPages')}")
        time.sleep(config.poll_interval)

    # 下载并解析逐页 markdown + 图片
    try:
        jr = requests.get(jsonl_url, timeout=120)
        jr.raise_for_status()
    except Exception as e:
        log(f"  {tag}[结果下载失败] {str(e)[:120]}")
        return {}, {}

    en_pages, page_images = {}, {}
    page_idx, img_count = 0, 0
    for line in jr.text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            result = json.loads(line)["result"]
        except Exception:
            continue
        for res in result.get("layoutParsingResults", []):
            md = res.get("markdown", {})
            text = md.get("text", "")
            en_pages[page_idx] = text
            # 只下载正文 <img src> 实际引用到的图片
            got = {}
            for path, url in (md.get("images", {}) or {}).items():
                if path in text:
                    b = _download_image(url)
                    if b:
                        got[path] = b
            page_images[page_idx] = got
            img_count += len(got)
            page_idx += 1
    if img_count:
        log(f"  {tag}下载图片 {img_count} 张")
    return en_pages, page_images
