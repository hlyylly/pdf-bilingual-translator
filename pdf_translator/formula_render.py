"""LaTeX公式渲染为PNG (base64 嵌入HTML)"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64
import re
import hashlib
from PIL import Image

_CACHE = {}


def _clean_single_line(latex):
    """单行公式预处理。
    注意：mathtext 在数学模式下会忽略普通空格，所以列分隔/间距必须用
    mathtext 支持的间距命令（\\quad \\qquad \\, \\;），不能降级成普通空格，
    否则相邻列会黏在一起（如 Y_1/p 与 \\mu/p>1）。
    """
    # 只有 array/tabular 才有列格式参数 {ll}，删掉它；
    # 其它环境(aligned/cases…)后面紧跟的 {..} 是真正的内容（如首个单元格 {D(p,\mu)}），不能删
    latex = re.sub(r'\\begin\{(?:array|tabular)\}\s*\{[^}]*\}', '', latex)
    latex = re.sub(r'\\begin\{[a-zA-Z*]+\}', '', latex)
    latex = re.sub(r'\\end\{[a-zA-Z*]+\}', '', latex)
    # 列分隔符 & → 用 \quad 形成可见间距（保留 aligned/array 的列间隔）
    latex = latex.replace('&', r' \quad ')
    latex = latex.replace('\\!', '')
    # \quad \qquad \, \; 全部保留（mathtext 原生支持），不再降级为普通空格
    latex = re.sub(r'\\text\{([^}]*)\}', r'\\mathrm{\1}', latex)
    return latex.strip()


def _trim_alpha(img):
    """裁掉PNG四周的透明边缘"""
    if img.mode != 'RGBA':
        return img
    bbox = img.getbbox()
    if bbox:
        return img.crop(bbox)
    return img


def _render_one_line(latex_line, fontsize, dpi):
    """渲染单行公式为 PIL Image"""
    if not latex_line:
        return None
    try:
        fig, ax = plt.subplots(figsize=(8, 0.5))
        ax.axis('off')
        ax.text(0.5, 0.5, f'${latex_line}$', ha='center', va='center',
                fontsize=fontsize, transform=ax.transAxes)
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight',
                    pad_inches=0.0, transparent=True, dpi=dpi)
        plt.close(fig)
        buf.seek(0)
        img = Image.open(buf).convert('RGBA')
        img = _trim_alpha(img)
        return img
    except Exception:
        try:
            plt.close('all')
        except Exception:
            pass
        return None


def _render_text_fallback(text, fontsize, dpi):
    """渲染普通文本（公式渲染失败时）"""
    try:
        fig, ax = plt.subplots(figsize=(8, 0.5))
        ax.axis('off')
        ax.text(0.5, 0.5, text, ha='center', va='center',
                fontsize=fontsize-2, transform=ax.transAxes,
                family='monospace')
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight',
                    pad_inches=0.0, transparent=True, dpi=dpi)
        plt.close(fig)
        buf.seek(0)
        img = Image.open(buf).convert('RGBA')
        return _trim_alpha(img)
    except Exception:
        try:
            plt.close('all')
        except Exception:
            pass
        return None


def _stack_images_vertically(images, gap=4):
    """垂直拼接多张图片，居中对齐"""
    images = [im for im in images if im is not None]
    if not images:
        return None
    max_w = max(im.width for im in images)
    total_h = sum(im.height for im in images) + gap * (len(images) - 1)
    canvas = Image.new('RGBA', (max_w, total_h), (255, 255, 255, 0))
    y = 0
    for im in images:
        x = (max_w - im.width) // 2
        canvas.paste(im, (x, y), im)
        y += im.height + gap
    return canvas


def render_latex_to_base64_png(latex, fontsize=14, dpi=160):
    """LaTeX 公式 → base64 PNG（多行通过PIL垂直拼接）
    保持字号像素一致：所有公式按相同 fontsize+dpi 渲染
    """
    if not latex or not latex.strip():
        return None

    key = hashlib.md5(f"{latex}|{fontsize}|{dpi}".encode()).hexdigest()
    if key in _CACHE:
        return _CACHE[key]

    lines = re.split(r'\\\\', latex)
    rendered = []
    for line in lines:
        cleaned = _clean_single_line(line)
        if not cleaned:
            continue
        img = _render_one_line(cleaned, fontsize, dpi)
        if img is None:
            img = _render_text_fallback(cleaned, fontsize, dpi)
        if img is not None:
            rendered.append(img)

    if not rendered:
        return None

    if len(rendered) == 1:
        final = rendered[0]
    else:
        final = _stack_images_vertically(rendered, gap=4)
        if final is None:
            return None

    buf = io.BytesIO()
    final.save(buf, format='PNG')
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode('ascii')
    _CACHE[key] = b64
    return b64


def _sized_img(b64, scale=0.48, css_class="formula-block-img"):
    """根据 PNG 实际像素给 <img> 设置显式 width/height。
    公式 PNG 用 dpi=160/fontsize=14 渲染（≈32px/行），insert_htmlbox 不认 CSS
    max-height/em，只能写死像素。正文 10.5pt≈14px，故：
      block scale=0.48 → ≈15px/行（≈正文1.1倍）
      inline scale=0.44 → ≈14px（≈正文等高）
    这样公式尺寸恒为正文的固定倍数——insert_htmlbox 整页自适应缩放时公式与正文
    同比缩放，比例不变，做到"随本页正文动态、跨页统一"。
    """
    try:
        im = Image.open(io.BytesIO(base64.b64decode(b64)))
        w, h = im.size
        dw, dh = max(1, round(w * scale)), max(1, round(h * scale))
        return (f'<img class="{css_class}" width="{dw}" height="{dh}" '
                f'src="data:image/png;base64,{b64}" alt="formula"/>')
    except Exception:
        return f'<img src="data:image/png;base64,{b64}" alt="formula"/>'


def preprocess_markdown_latex_commands(md_text):
    """预处理 markdown 文本里的非数学环境的 LaTeX 命令"""
    md_text = re.sub(r'\$\s*\\underline\{\\text\{([^}]*)\}\}\s*\$',
                     r'<u>\1</u>', md_text)
    md_text = re.sub(r'\\underline\{\\text\{([^}]*)\}\}', r'<u>\1</u>', md_text)
    md_text = re.sub(r'\\underline\{([^}]*)\}', r'<u>\1</u>', md_text)
    return md_text


# 简单LaTeX的HTML替代映射
_SIMPLE_PATTERNS = [
    # 纯上标 ^{N} 或 ^N
    (re.compile(r'^\^\{([^{}]+)\}$'), r'<sup>\1</sup>'),
    (re.compile(r'^\^([a-zA-Z0-9])$'), r'<sup>\1</sup>'),
    # 纯下标 _{N} 或 _N
    (re.compile(r'^_\{([^{}]+)\}$'), r'<sub>\1</sub>'),
    (re.compile(r'^_([a-zA-Z0-9])$'), r'<sub>\1</sub>'),
    # 单字母变量
    (re.compile(r'^([a-zA-Z])$'), r'<i>\1</i>'),
    # 单数字
    (re.compile(r'^([0-9]+(?:\.[0-9]+)?)$'), r'\1'),
    # 字母带下标: X_{N} 或 X_N
    (re.compile(r'^([a-zA-Z])_\{([^{}]+)\}$'), r'<i>\1</i><sub>\2</sub>'),
    (re.compile(r'^([a-zA-Z])_([a-zA-Z0-9])$'), r'<i>\1</i><sub>\2</sub>'),
    # 字母带上标
    (re.compile(r'^([a-zA-Z])\^\{([^{}]+)\}$'), r'<i>\1</i><sup>\2</sup>'),
    (re.compile(r'^([a-zA-Z])\^([a-zA-Z0-9])$'), r'<i>\1</i><sup>\2</sup>'),
    # 字母上下标都有: X_{a}^{b}
    (re.compile(r'^([a-zA-Z])_\{([^{}]+)\}\^\{([^{}]+)\}$'),
     r'<i>\1</i><sub>\2</sub><sup>\3</sup>'),
    (re.compile(r'^([a-zA-Z])\^\{([^{}]+)\}_\{([^{}]+)\}$'),
     r'<i>\1</i><sub>\3</sub><sup>\2</sup>'),
    # 简单比较: X < Y, X > Y, X = Y, X <= Y
    (re.compile(r'^([a-zA-Z0-9_^{}\\]+)\s*(<|>|=|\\leq|\\geq|\\le|\\ge|\\neq)\s*([a-zA-Z0-9_^{}\\]+)$'),
     None),  # 留给后续单独处理
]

_REL_MAP = {'\\geqslant': '≥', '\\leqslant': '≤',
            '\\leq': '≤', '\\geq': '≥', '\\le': '≤', '\\ge': '≥',
            '\\neq': '≠', '\\cdot': '·', '\\times': '×',
            '\\alpha': 'α', '\\beta': 'β', '\\gamma': 'γ', '\\mu': 'μ',
            '\\sigma': 'σ', '\\theta': 'θ', '\\lambda': 'λ', '\\pi': 'π',
            '\\epsilon': 'ε', '\\delta': 'δ', '\\rho': 'ρ', '\\phi': 'φ',
            '\\sum': '∑', '\\prod': '∏', '\\infty': '∞', '\\partial': '∂',
            '\\in': '∈', '\\notin': '∉', '\\subset': '⊂',
            '\\rightarrow': '→', '\\leftarrow': '←',
            '\\quad': '  ', '\\,': ' ', '\\;': ' ', '\\!': ''}


_UNICODE_FRAC = {
    ('1', '2'): '½', ('1', '3'): '⅓', ('2', '3'): '⅔',
    ('1', '4'): '¼', ('3', '4'): '¾', ('1', '5'): '⅕',
    ('2', '5'): '⅖', ('3', '5'): '⅗', ('4', '5'): '⅘',
    ('1', '6'): '⅙', ('5', '6'): '⅚', ('1', '8'): '⅛',
    ('3', '8'): '⅜', ('5', '8'): '⅝', ('7', '8'): '⅞',
}
_FRAC_RE = re.compile(r'(\d*)\s*\\[dt]?frac\s*\{(\d+)\}\s*\{(\d+)\}')


def _convert_simple_to_html(latex):
    """尝试把简单的 LaTeX 公式转为 HTML（不走图片渲染）"""
    s = latex.strip()
    if not s:
        return None

    # 纯整数分数 → Unicode 分数字符（½ ¾ ⅓…）或 a/b 文本。
    # 行内图片渲染在窄表格单元格里会换行、分数线发虚；用紧凑字符更好看：18¾、37½
    mfrac = _FRAC_RE.fullmatch(s)
    if mfrac:
        whole, num, den = mfrac.group(1), mfrac.group(2), mfrac.group(3)
        frac = _UNICODE_FRAC.get((num, den)) or f'{num}/{den}'
        return f'{whole}{frac}' if whole else frac

    for pattern, replacement in _SIMPLE_PATTERNS:
        if replacement is None:
            continue
        m = pattern.match(s)
        if m:
            return pattern.sub(replacement, s)

    # 替换希腊字母/关系符号后再判断是否纯文本
    converted = s
    for cmd, sym in _REL_MAP.items():
        converted = converted.replace(cmd, sym)

    # 把 X_{N} → X<sub>N</sub>，X^{N} → X<sup>N</sup>
    converted = re.sub(r'([a-zA-Z0-9αβγμσθλπεδρφ])_\{([^{}]+)\}',
                       r'<i>\1</i><sub>\2</sub>', converted)
    converted = re.sub(r'([a-zA-Z0-9αβγμσθλπεδρφ])\^\{([^{}]+)\}',
                       r'<i>\1</i><sup>\2</sup>', converted)
    converted = re.sub(r'([a-zA-Z0-9αβγμσθλπεδρφ])_([a-zA-Z0-9])',
                       r'<i>\1</i><sub>\2</sub>', converted)
    converted = re.sub(r'([a-zA-Z0-9αβγμσθλπεδρφ])\^([a-zA-Z0-9])',
                       r'<i>\1</i><sup>\2</sup>', converted)

    # 检查转换后是否还有 LaTeX 命令（\xxx 形式）或括号
    if re.search(r'\\[a-zA-Z]+', converted):
        return None
    if '{' in converted or '}' in converted:
        return None

    # 简单短公式可以用 HTML
    if len(s) <= 30 and not any(c in s for c in '\\{}'):
        # 把空格之类的清理一下，给单字母加斜体
        # 在变量字母周围加 <i>
        # 把孤立的英文字母转斜体（避免重复转）
        return converted

    if len(s) <= 30:
        return converted

    return None


def _render_aligned_table(latex):
    """渲染对齐多行公式 (align/aligned/array) 为 HTML 表格，每行每列分开渲染为小图"""
    # 提取环境内的内容
    m = re.search(r'\\begin\{[a-zA-Z*]+\}(?:\{[^}]*\})?(.*?)\\end\{[a-zA-Z*]+\}',
                  latex, flags=re.DOTALL)
    body = m.group(1) if m else latex

    body = body.replace('\\quad', ' ').replace('\\qquad', '  ')
    body = body.replace('\\,', ' ').replace('\\;', ' ').replace('\\!', '')
    body = re.sub(r'\\text\{([^}]*)\}', r'\1', body)
    body = re.sub(r'\\mathrm\{([^}]*)\}', r'\1', body)

    # 按 \\ 分行
    rows = re.split(r'\\\\', body)
    rows = [r.strip() for r in rows if r.strip()]

    # 每行按 & 分列
    rendered_rows = []
    max_cols = 0
    for row in rows:
        cells = [c.strip() for c in row.split('&')]
        rendered_cells = []
        for cell in cells:
            if not cell:
                rendered_cells.append('')
                continue
            # 行内简单LaTeX用HTML，复杂用图片
            html = _convert_simple_to_html(cell)
            if html is not None:
                rendered_cells.append(html)
            else:
                b64 = render_latex_to_base64_png(cell, fontsize=14)
                if b64:
                    rendered_cells.append(
                        f'<img class="formula-inline" src="data:image/png;base64,{b64}" alt="formula"/>')
                else:
                    rendered_cells.append(f'<code>{cell}</code>')
        rendered_rows.append(rendered_cells)
        max_cols = max(max_cols, len(cells))

    # 构建HTML表格
    lines = ['<table class="formula-align">']
    for cells in rendered_rows:
        while len(cells) < max_cols:
            cells.append('')
        lines.append('<tr>')
        for c in cells:
            lines.append(f'<td>{c}</td>')
        lines.append('</tr>')
    lines.append('</table>')
    return '\n\n' + ''.join(lines) + '\n\n'


_CJK_RE = re.compile(r'[一-鿿　-〿＀-￯]')


def _cjk_formula_to_html(latex, block=False):
    """公式里混入中文时走 HTML 文本渲染（matplotlib 数学字体无中文字形会渲成空box）。
    中文按正文显示，上下标/关系符号尽量保留。"""
    s = latex
    s = re.sub(r'\\begin\{[a-zA-Z*]+\}(\{[^}]*\})?', '', s)
    s = re.sub(r'\\end\{[a-zA-Z*]+\}', '', s)
    s = re.sub(r'\\(?:text|mathrm|mathbf|mathit|operatorname|mathsf)\s*\{([^{}]*)\}', r'\1', s)
    s = s.replace('&', ' ')
    s = re.sub(r'\\\\', '<br>', s)
    s = re.sub(r'\^\{([^{}]+)\}', r'<sup>\1</sup>', s)
    s = re.sub(r'_\{([^{}]+)\}', r'<sub>\1</sub>', s)
    s = re.sub(r'\^([A-Za-z0-9])', r'<sup>\1</sup>', s)
    s = re.sub(r'_([A-Za-z0-9])', r'<sub>\1</sub>', s)
    for cmd, sym in _REL_MAP.items():
        s = s.replace(cmd, sym)
    s = re.sub(r'\\[a-zA-Z]+', '', s)   # 丢弃剩余未知 LaTeX 命令
    s = s.replace('{', '').replace('}', '').strip()
    if block:
        return f'\n\n<div class="formula-block">{s}</div>\n\n'
    return s


def replace_formulas_with_images(md_text, inline_fontsize=11, block_fontsize=13):
    """把 markdown 中的 $...$ 和 $$...$$ 替换为 <img> 标签"""
    md_text = preprocess_markdown_latex_commands(md_text)

    # 把 \(...\) 转成 $...$（同义的内联公式标记）
    # 用非贪婪 [^\n]+? 匹配到第一个 \)，允许公式内部含括号（如 D(p, \mu)、\mu(p)）；
    # 旧的 [^)]+? 会在内部第一个 ) 处截断，导致含括号的公式不被识别而露出原始 LaTeX。
    md_text = re.sub(r'\\\(([^\n]+?)\\\)', r'$\1$', md_text)
    # 把 \[...\] 转成 $$...$$
    md_text = re.sub(r'\\\[(.+?)\\\]', r'$$\1$$', md_text, flags=re.DOTALL)

    # OCR错误修复：$$内部 `\ $` 应该是换行符 `\\`
    # 用一次性pattern匹配整个$$...$$块，内部清理掉孤立的$
    def fix_block(m):
        content = m.group(1)
        # 把孤立的 ` $ ` 或 `\ $` 替换为 \\
        content = re.sub(r'\\\s*\$', r'\\\\', content)
        content = re.sub(r'\s\$\s', ' \\\\ ', content)
        return f'$${content}$$'

    # 先用宽松matching捕获所有可能的$$...$$块
    # 找到所有 $$...$$ 对（贪婪到下一个$$）
    md_text = re.sub(r'\$\$(.+?)\$\$', fix_block, md_text, flags=re.DOTALL)

    def block_repl(m):
        latex = m.group(1).strip()
        if not latex:
            return ''
        if _CJK_RE.search(latex):          # 公式含中文 → HTML 文本，避免空box
            return _cjk_formula_to_html(latex, block=True)
        # 不论单行还是多行环境(align/aligned/array/matrix/cases/eqnarray)，
        # 一律用 matplotlib 渲成一张纵向拼接的 PNG。
        # 不再用 HTML 表格：PyMuPDF 的 insert_htmlbox 撑不开多行多列表格。
        b64 = render_latex_to_base64_png(latex, fontsize=block_fontsize)
        if not b64:
            return f'\n\n<code>{latex}</code>\n\n'
        return f'\n\n<div class="formula-block">{_sized_img(b64)}</div>\n\n'

    md_text = re.sub(r'\$\$(.+?)\$\$', block_repl, md_text, flags=re.DOTALL)

    def inline_repl(m):
        latex = m.group(1).strip()
        if not latex or len(latex) < 1:
            return m.group(0)
        if _CJK_RE.search(latex):          # 公式含中文 → HTML 文本
            return _cjk_formula_to_html(latex)
        # 先尝试简单LaTeX→HTML转换
        html_simple = _convert_simple_to_html(latex)
        if html_simple is not None:
            return html_simple
        # 复杂公式才走matplotlib图片渲染（显式尺寸≈正文等高，避免行内公式图过大）
        b64 = render_latex_to_base64_png(latex, fontsize=inline_fontsize)
        if b64:
            return _sized_img(b64, scale=0.44, css_class="formula-inline")
        return f'<code>{latex}</code>'

    md_text = re.sub(r'\$([^\$\n]+?)\$', inline_repl, md_text)
    return md_text


if __name__ == "__main__":
    import sys
    test_md = r"""
# 测试

行内公式：$D(p) = (Y_2 + Y_1)/p$ 和 $^{1}$ 上标。

块级公式：
$$ \begin{aligned}&S(p)=N\\&S(p)=0 \end{aligned} $$

URL: $ \underline{\text{http://example.com}} $
"""
    result = replace_formulas_with_images(test_md)
    with open('test_out.html', 'w', encoding='utf-8') as f:
        f.write(f"<html><body>{result}</body></html>")
    print("结果已保存到 test_out.html")
    # 测试单行渲染
    b64 = render_latex_to_base64_png(r'\begin{aligned}&S(p)=N\\&S(p)=0 \end{aligned}')
    if b64:
        with open('test_aligned.png', 'wb') as f:
            f.write(base64.b64decode(b64))
        print("test_aligned.png 已保存")
