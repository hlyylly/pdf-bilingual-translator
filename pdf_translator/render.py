"""渲染逐页英中对照 PDF：原英文页 + 中文 Markdown 渲染页 交替。

公式用飞桨返回的 LaTeX 渲染（见 formula_render），图片 base64 内嵌。
PyMuPDF 跨文档并发不安全，故本模块串行调用。
"""
import io
import re
import base64
import fitz
import markdown as md_lib
from PIL import Image

from .formula_render import replace_formulas_with_images

CSS_TEMPLATE = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.45; color: #000; }
h1 { font-size: 18pt; margin: 12pt 0 8pt 0; font-weight: bold; }
h2 { font-size: 15pt; margin: 10pt 0 6pt 0; font-weight: bold; }
h3 { font-size: 13pt; margin: 8pt 0 5pt 0; font-weight: bold; }
h4 { font-size: 11.5pt; margin: 6pt 0 4pt 0; font-weight: bold; }
p  { margin: 3pt 0; text-align: justify; }
ul, ol { margin: 3pt 0; padding-left: 18pt; }
li { margin: 1pt 0; }
code { font-family: monospace; background: #f5f5f5; }
pre { font-family: monospace; background: #f5f5f5; padding: 6pt; }
table { border-collapse: collapse; margin: 6pt 0; }
th, td { border: 1px solid #999; padding: 3pt 6pt; }
img.formula-inline { display: inline-block; vertical-align: -0.2em; max-height: 1.2em; }
div.formula-block { text-align: left; margin: 2pt 0; padding-left: 12pt; }
div.formula-block img { max-height: 2em; }
sup, sub { font-size: 0.75em; line-height: 0; position: relative; }
sup { top: -0.5em; }
sub { bottom: -0.25em; }
i { font-style: italic; }
div.block-img { text-align: center; margin: 6pt 0; }
div.block-img img { max-width: 100%; }
table.formula-align { border: 0; margin: 4pt 0 4pt 24pt; border-collapse: collapse; }
table.formula-align td { border: 0; padding: 1pt 12pt 1pt 0; vertical-align: middle; }
"""

_IMG_TAG_RE = re.compile(r'<img\b[^>]*?/?>', re.IGNORECASE)
_SRC_RE = re.compile(r'src\s*=\s*["\']([^"\']+)["\']', re.I)
_WIDTH_PCT_RE = re.compile(r'width\s*=\s*["\']?([\d.]+)%', re.I)
USABLE_PX = 500   # 渲染框去掉边距后的近似可用宽度(px)


def embed_images_in_md(md_text, images):
    """把 <img src="imgs/xxx.jpg"> 替换为内嵌 base64 图并设定显示尺寸；没下到的删占位。"""
    def repl(m):
        tag = m.group(0)
        ms = _SRC_RE.search(tag)
        data = images.get(ms.group(1)) if ms else None
        if not data:
            return ''
        try:
            iw, ih = Image.open(io.BytesIO(data)).size
        except Exception:
            iw = ih = 0
        mw = _WIDTH_PCT_RE.search(tag)
        if mw:
            disp_w = int(USABLE_PX * float(mw.group(1)) / 100)
        else:
            disp_w = min(iw, USABLE_PX) if iw else int(USABLE_PX * 0.6)
        disp_w = max(60, min(disp_w, USABLE_PX))
        disp_h = int(disp_w * ih / iw) if iw else 0
        b64 = base64.b64encode(data).decode("ascii")
        fmt = "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpeg"
        hattr = f' height="{disp_h}"' if disp_h else ""
        return (f'<div class="block-img"><img src="data:image/{fmt};base64,{b64}" '
                f'width="{disp_w}"{hattr} alt="图"/></div>')

    return _IMG_TAG_RE.sub(repl, md_text)


def _strip_code_indent(md_text):
    """去掉非```围栏行的前导空格，避免缩进行被 markdown 误判为代码块、露出 HTML 标签。"""
    out, fence = [], False
    for ln in md_text.split("\n"):
        s = ln.lstrip()
        if s.startswith("```"):
            fence = not fence
            out.append(s)
        else:
            out.append(ln if fence else s)
    return "\n".join(out)


def md_to_html(md_text, images=None):
    if images is not None:
        md_text = embed_images_in_md(md_text, images)
    md_text = _strip_code_indent(md_text)
    text = replace_formulas_with_images(md_text, inline_fontsize=14, block_fontsize=14)
    return md_lib.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])


def render_zh_page(doc, md_text, page_rect, images=None, log=print):
    new_page = doc.new_page(width=page_rect.width, height=page_rect.height)
    if not md_text or not md_text.strip():
        return new_page
    full_html = f"<body>{md_to_html(md_text, images=images or {})}</body>"
    margin = 40
    where = fitz.Rect(margin, margin, page_rect.width - margin, page_rect.height - margin)
    try:
        new_page.insert_htmlbox(where, full_html, css=CSS_TEMPLATE, scale_low=0.35)
    except Exception as e:
        log(f"    [渲染错误] 第{new_page.number + 1}页: {str(e)[:120]}")
    return new_page


def render_dual_pdf(input_path, en_pages, zh_pages, page_images, dual_path, log=print):
    """生成逐页对照 PDF：原英文页 + 中文渲染页 交替。"""
    doc_orig = fitz.open(input_path)
    doc_dual = fitz.open()
    n = doc_orig.page_count
    for i in range(n):
        doc_dual.insert_pdf(doc_orig, from_page=i, to_page=i)
        render_zh_page(doc_dual, zh_pages.get(i, ""), doc_orig[i].rect,
                       images=(page_images or {}).get(i, {}), log=log)
    doc_dual.save(dual_path, garbage=4, deflate=True, clean=True)
    doc_dual.close()
    doc_orig.close()
