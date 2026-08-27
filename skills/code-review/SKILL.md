---
name: code-review
description: >-
  Use when the user asks to review source code under version control or in the
  filesystem: pull requests, diffs, code quality, correctness, security
  concerns, or refactoring suggestions. Do not use for data analysis or
  customer support tasks.
version: "1.0"
---

# Code Review Skill

## When to Use

- User nhờ review code: PR/diff, chất lượng mã nguồn, tìm bug, hoặc đề xuất refactoring.
- User muốn đánh giá tính đúng đắn, bảo mật, hoặc hiệu năng của một đoạn mã.
- KHÔNG dùng cho phân tích dữ liệu hoặc trả lời khách hàng.

## Quy trình review

1. **Xác định phạm vi:** Đọc danh sách file/thay đổi cần review (git diff nếu có, hoặc các file được chỉ định).
2. **Đọc theo thứ tự ưu tiên:** review phần logic nghiệp vụ trước, rồi xử lý lỗi/ngoại lệ, bảo mật, hiệu năng, cuối cùng là style.
3. **Đánh giá từng hạng mục:**
   - Correctness: nhánh lỗi, điều kiện biên, null/empty handling, race condition.
   - Security: injection, hardcoded secret, sai permission, xử lý input không tin cậy.
   - Maintainability: đặt tên, tách hàm, trùng lặp, test phủ.
4. **Kết luận:** Tổng kết theo mức độ — blocking / nên sửa / gợi ý. Mỗi ý nêu rõ vị trí file:dòng và lý do.

## Nguyên tắc

- Không yêu cầu thay đổi về style thuần túy nếu nó không ảnh hưởng đúng đắn hay bảo trì.
- Đề xuất kèm ví dụ mã cụ thể; ưu tiên tìm lỗi chức năng hơn là góp ý cosmetic.