"""命令行入口。
用法:
  python cli.py file1.pdf file2.pdf      # 翻译指定文件
  python cli.py ./papers                  # 翻译目录下所有 PDF
  python cli.py ./papers -o ./out         # 指定输出目录

密钥来源（任一）：
  环境变量 DEEPSEEK_API_KEY / PADDLE_TOKEN
  当前目录 config.json
  用户目录 ~/.pdf-bilingual-translator/config.json
"""
import os
import sys
import argparse

from pdf_translator import Config
from pdf_translator.pipeline import translate_pdfs


def collect_pdfs(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += [os.path.join(p, f) for f in sorted(os.listdir(p))
                    if f.lower().endswith(".pdf") and not f.endswith("-dual.pdf")]
        elif p.lower().endswith(".pdf"):
            out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser(description="PDF 双语对照翻译 (PaddleOCR-VL + DeepSeek)")
    ap.add_argument("inputs", nargs="+", help="PDF 文件或目录")
    ap.add_argument("-o", "--output", default="output", help="输出目录 (默认 ./output)")
    ap.add_argument("--deepseek-key", help="覆盖 DeepSeek API Key")
    ap.add_argument("--paddle-token", help="覆盖 PaddleOCR Token")
    ap.add_argument("--model", help="DeepSeek 模型 (默认 deepseek-chat)")
    args = ap.parse_args()

    config = Config.load()
    if args.deepseek_key:
        config.deepseek_key = args.deepseek_key
    if args.paddle_token:
        config.paddle_token = args.paddle_token
    if args.model:
        config.deepseek_model = args.model

    missing = config.validate()
    if missing:
        print("✗ 缺少必填配置：" + "、".join(missing))
        print("  请设置环境变量 DEEPSEEK_API_KEY / PADDLE_TOKEN，或创建 config.json")
        sys.exit(1)

    pdfs = collect_pdfs(args.inputs)
    if not pdfs:
        print("✗ 未找到 PDF 文件")
        sys.exit(1)

    print("=" * 60)
    print(f"待处理 {len(pdfs)} 个 PDF  →  {os.path.abspath(args.output)}")
    print(f"PDF并发:{config.concurrent_pdf}  翻译并发:{config.concurrent_translate}")
    print("=" * 60)

    produced, elapsed = translate_pdfs(pdfs, config, args.output, log=print)
    print(f"\n✓ 完成 {len(produced)}/{len(pdfs)} 篇，耗时 {elapsed:.0f} 秒")
    print(f"  输出目录: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
