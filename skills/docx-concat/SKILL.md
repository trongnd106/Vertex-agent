---
name: docx-concat
description: >
  Nối (ghép) nhiều file .docx thành một tài liệu duy nhất.
  Dùng skill này khi người dùng muốn: ghép tài liệu Word, nối file docx,
  merge nhiều file Word lại, kết hợp báo cáo với phụ lục, gộp nhiều chương
  thành một file, hoặc nói "nối", "ghép", "gộp", "kết hợp" các file .docx.
  Input: 2+ file .docx. Output: 1 file .docx đã ghép theo thứ tự.
---

# DOCX Concat Skill

Ghép nhiều file `.docx` thành một tài liệu duy nhất, giữ nguyên định dạng,
ảnh, bảng, header/footer của từng tài liệu.

## Yêu cầu thư viện

```bash
pip install python-docx docxcompose --break-system-packages
```

## Workflow

### Bước 1 — Xác định thứ tự nối

Hỏi người dùng (hoặc suy từ context) thứ tự các file:
- **File đầu tiên = tài liệu gốc**: giữ nguyên styles, header, footer, page setup
- **Các file tiếp theo**: nội dung body được nối vào, mỗi file bắt đầu bằng page break

### Bước 2 — Chạy script

```bash
python3 /home/claude/docx-concat/scripts/concat_docs.py \
  /mnt/user-data/outputs/ket_qua.docx \
  /mnt/user-data/uploads/file1.docx \
  /mnt/user-data/uploads/file2.docx \
  /mnt/user-data/uploads/file3.docx
```

**Không muốn ngắt trang giữa các file:**
```bash
python3 /home/claude/docx-concat/scripts/concat_docs.py \
  /mnt/user-data/outputs/ket_qua.docx \
  file1.docx file2.docx \
  --no-page-break
```

### Bước 3 — Present kết quả

```python
present_files(["/mnt/user-data/outputs/ket_qua.docx"])
```

---

## Tham số

| Tham số | Mô tả |
|---------|-------|
| `output` | File đầu ra (bắt buộc, đặt trước inputs) |
| `inputs` | 2+ file đầu vào theo thứ tự |
| `--no-page-break` | Nối liên tục, không thêm ngắt trang |

---

## Cơ chế hoạt động

- Tài liệu 1 làm **base** — giữ nguyên styles, header, footer, margins
- Các tài liệu sau được trích **body content** và append vào base
- `docxcompose` tự động remap: relationship IDs, ảnh, numbering IDs để tránh xung đột
- Một `<w:br w:type="page"/>` được chèn vào trước mỗi tài liệu mới (trừ khi dùng `--no-page-break`)

---

## Lưu ý

- **Styles xung đột**: nếu cả 2 file có Heading1 khác màu, styles của file đầu tiên sẽ thắng
- **Header/Footer**: chỉ giữ header/footer của file đầu tiên
- **File bảo vệ / encrypted**: cần mở khóa trước khi nối
- **Nhiều hơn 2 file**: truyền tất cả cùng lúc, không cần chạy nhiều lần
