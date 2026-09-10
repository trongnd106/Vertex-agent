---
name: doc-to-docx
description: >
  Use this skill whenever the user wants to convert a .doc file (legacy Word format) to .docx
  (modern Word format). Trigger on any mention of: "chuyển doc sang docx", "convert doc to docx",
  ".doc file", "file .doc", "legacy Word", or when the user uploads a .doc file and wants to
  open, edit, or process it. Also trigger when other skills (like docx) encounter a .doc file
  that must be converted before editing. Do NOT use for files already in .docx, .pdf, or other
  formats.
---

# DOC → DOCX Conversion

Chuyển file `.doc` (định dạng Word cũ) sang `.docx` (định dạng Word hiện đại) bằng LibreOffice.

## Quy trình (3 bước)

### Bước 1 — Xác định file đầu vào

File `.doc` của người dùng thường nằm ở:
- `/mnt/user-data/uploads/<tên-file>.doc`

Kiểm tra file tồn tại trước khi chuyển:
```bash
ls -lh /mnt/user-data/uploads/*.doc 2>/dev/null || echo "Không tìm thấy file .doc"
```

### Bước 2 — Chuyển đổi bằng LibreOffice

Sử dụng `soffice.py` từ skill `docx` để xử lý môi trường sandbox:

```python
import subprocess, sys, shutil
sys.path.insert(0, "/mnt/skills/public/docx/scripts")
from office.soffice import run_soffice

input_doc  = "/mnt/user-data/uploads/input.doc"   # thay bằng path thực
output_dir = "/home/claude/"                        # LibreOffice xuất ra đây

result = run_soffice([
    "--headless",
    "--convert-to", "docx",
    "--outdir", output_dir,
    input_doc
], capture_output=True, text=True)

print(result.stdout)
print(result.stderr)
```

> **Lưu ý:** LibreOffice tự động đặt tên file đầu ra theo tên file gốc, chỉ đổi đuôi thành `.docx`.
> Ví dụ: `report.doc` → `report.docx` trong `output_dir`.

### Bước 3 — Copy sang thư mục output & trình bày cho người dùng

```bash
cp /home/claude/<tên-file>.docx /mnt/user-data/outputs/<tên-file>.docx
```

Sau đó dùng `present_files` để người dùng tải về.

---

## Script đầy đủ (copy-paste ready)

```python
import subprocess, sys, shutil
from pathlib import Path

sys.path.insert(0, "/mnt/skills/public/docx/scripts")
from office.soffice import run_soffice

# ── Cấu hình ──────────────────────────────────────────────
INPUT_DOC  = Path("/mnt/user-data/uploads/input.doc")  # <-- đổi tên file
WORK_DIR   = Path("/home/claude")
OUTPUT_DIR = Path("/mnt/user-data/outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
# ──────────────────────────────────────────────────────────

if not INPUT_DOC.exists():
    print(f"❌ Không tìm thấy file: {INPUT_DOC}")
    sys.exit(1)

print(f"📄 Đang chuyển đổi: {INPUT_DOC.name} ...")
result = run_soffice(
    ["--headless", "--convert-to", "docx", "--outdir", str(WORK_DIR), str(INPUT_DOC)],
    capture_output=True, text=True
)

if result.returncode != 0:
    print("❌ Lỗi LibreOffice:")
    print(result.stderr)
    sys.exit(1)

converted = WORK_DIR / (INPUT_DOC.stem + ".docx")
if not converted.exists():
    print(f"❌ Không tìm thấy file đầu ra: {converted}")
    sys.exit(1)

dest = OUTPUT_DIR / converted.name
shutil.copy2(converted, dest)
print(f"✅ Thành công! File đã lưu tại: {dest}")
```

---

## Xử lý lỗi thường gặp

| Lỗi | Nguyên nhân | Cách khắc phục |
|-----|-------------|----------------|
| `returncode != 0` | LibreOffice bị lỗi | Kiểm tra `result.stderr`; thử lại với `--norestore` |
| File đầu ra không tồn tại | Tên file có ký tự đặc biệt | Đổi tên file trước khi convert |
| `No such file or directory: soffice` | LibreOffice chưa cài | Chạy `apt-get install -y libreoffice` |
| File bị hỏng sau convert | `.doc` có macro phức tạp | Báo người dùng, đề xuất chỉnh sửa thủ công |

---

## Lưu ý chất lượng

- **Font**: LibreOffice cố gắng giữ nguyên font, nhưng font độc quyền (VD: VNI, TCVN3) có thể bị thay thế bằng font tương tự.
- **Định dạng phức tạp**: Bảng, hộp văn bản, WordArt có thể bị lệch nhẹ — nên kiểm tra kỹ sau khi convert.
- **Macro**: Macro VBA trong `.doc` sẽ không được chuyển sang `.docx`.
- **Sau khi convert**: Nếu cần chỉnh sửa thêm, dùng skill `docx` để xử lý file `.docx` vừa tạo.
