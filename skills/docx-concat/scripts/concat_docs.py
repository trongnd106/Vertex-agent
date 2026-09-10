#!/usr/bin/env python3
"""
concat_docs.py — Nối nhiều file .docx thành một tài liệu duy nhất.

Yêu cầu:
    pip install python-docx docxcompose --break-system-packages

Cách dùng:
    python3 concat_docs.py output.docx file1.docx file2.docx [file3.docx ...]

Tuỳ chọn:
    --page-break        Thêm ngắt trang giữa các tài liệu (mặc định: bật)
    --no-page-break     Nối liên tục, không ngắt trang
    --keep-styles       Giữ styles từ tài liệu phụ (mặc định: dùng styles của tài liệu đầu)

Cơ chế:
    1. Tài liệu đầu tiên = base (giữ nguyên header/footer/styles/page setup)
    2. Các tài liệu tiếp theo được trích nội dung body và nối vào
    3. Ảnh, bảng, numbering được remap tự động để không xung đột
    4. Mỗi tài liệu nối thêm bắt đầu bằng page break (tuỳ chọn)
"""

import sys
import os
import argparse
import copy
import zipfile
import tempfile
import shutil
import re
from pathlib import Path

try:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    from docxcompose.composer import Composer
except ImportError as e:
    print(f"❌ Thiếu thư viện: {e}")
    print("   Chạy: pip install python-docx docxcompose --break-system-packages")
    sys.exit(1)


def add_page_break(doc):
    """Thêm ngắt trang vào cuối tài liệu."""
    p = OxmlElement('w:p')
    r = OxmlElement('w:r')
    br = OxmlElement('w:br')
    br.set(qn('w:type'), 'page')
    r.append(br)
    p.append(r)
    doc.element.body.append(p)


def concat_documents(output_path: str, input_paths: list, page_break: bool = True):
    """
    Nối các tài liệu lại.
    - input_paths[0] = tài liệu gốc (giữ styles, header, footer)
    - input_paths[1:] = các tài liệu nối thêm
    """
    if not input_paths:
        print("❌ Không có file nào để nối.", file=sys.stderr)
        sys.exit(1)

    if len(input_paths) == 1:
        print("⚠️  Chỉ có 1 file — copy thẳng ra output.", file=sys.stderr)
        shutil.copy(input_paths[0], output_path)
        print(f"✅ Output: {output_path}")
        return

    # Kiểm tra file tồn tại
    for p in input_paths:
        if not os.path.exists(p):
            print(f"❌ Không tìm thấy file: {p}", file=sys.stderr)
            sys.exit(1)

    print(f"📄 Tài liệu gốc: {input_paths[0]}")
    
    # Load tài liệu đầu làm base
    base_doc = Document(input_paths[0])
    composer = Composer(base_doc)

    for i, path in enumerate(input_paths[1:], start=2):
        print(f"📄 Nối tài liệu {i}: {path}")
        
        if page_break:
            add_page_break(base_doc)
        
        doc = Document(path)
        composer.append(doc)

    composer.save(output_path)
    print(f"✅ Đã nối {len(input_paths)} tài liệu → {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Nối nhiều file .docx thành một"
    )
    parser.add_argument("output", help="File đầu ra (.docx)")
    parser.add_argument("inputs", nargs="+", help="Các file đầu vào (theo thứ tự)")
    parser.add_argument("--no-page-break", action="store_true",
                        help="Không thêm ngắt trang giữa các tài liệu")

    args = parser.parse_args()

    page_break = not args.no_page_break

    concat_documents(
        output_path=args.output,
        input_paths=args.inputs,
        page_break=page_break,
    )


if __name__ == "__main__":
    main()
