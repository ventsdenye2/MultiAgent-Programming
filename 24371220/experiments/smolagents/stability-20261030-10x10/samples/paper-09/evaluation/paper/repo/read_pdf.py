"""按 PDF 页序号提取文字，以 JSON 输出，不写入任何文件。"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


def extract_pages(pdf, start, end):
    if start < 1 or end < start:
        raise ValueError("页码从 1 开始，结束页不能小于开始页")
    pdf = pdf.resolve()
    if not pdf.is_file():
        raise ValueError(f"找不到 PDF：{pdf}")
    if not shutil.which("pdftotext"):
        raise ValueError("缺少 pdftotext；Ubuntu/WSL 请安装：sudo apt-get install -y poppler-utils")
    result = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", "-f", str(start), "-l", str(end), str(pdf), "-"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    if result.returncode:
        raise ValueError("PDF 提取失败：" + result.stderr.strip())
    # pdftotext 用换页符分隔页面，末尾通常还有一个换页符。
    pages = result.stdout.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    if len(pages) != end - start + 1:
        raise ValueError(f"请求第 {start}～{end} 页，只取得 {len(pages)} 页；请检查页码是否超出 PDF")
    return {"pdf": str(pdf), "pages": [
        {"page": start + index, "text": text} for index, text in enumerate(pages)
    ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-page", type=int, required=True, help="开始页，从 1 开始，包含该页")
    parser.add_argument("--end-page", type=int, help="结束页，包含该页；省略时只读开始页")
    parser.add_argument("--pdf", type=Path, default=Path(__file__).with_name("paper.pdf"),
                        help="PDF 文件路径；默认读取脚本同目录的 paper.pdf")
    args = parser.parse_args()
    end = args.start_page if args.end_page is None else args.end_page
    print(json.dumps(extract_pages(args.pdf, args.start_page, end), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"读取 PDF 失败：{exc}", file=sys.stderr)
        raise SystemExit(2)
