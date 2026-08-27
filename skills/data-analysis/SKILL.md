---
name: data-analysis
description: >-
  Use when the user asks to analyze a data file (CSV/TSV/table), compute
  statistics, summarize metrics, detect outliers, or generate a data report or
  chart. Do not use for customer support replies or code review.
version: "1.0"
---

# Data Analysis Skill

## When to Use

- User đưa ra file dữ liệu (CSV/TSV/JSON bảng) và hỏi thống kê, tóm tắt, hoặc phát hiện bất thường.
- User muốn báo cáo số liệu, biểu đồ, hoặc so sánh các nhóm trong dữ liệu.
- KHÔNG dùng cho trả lời hỗ trợ khách hàng hoặc review mã nguồn.

## Quy trình thực hiện

1. **Đọc dữ liệu:** Dùng tool file-system để đọc file dữ liệu và scripts/analyze.py trong thư mục skill này.
2. **Hiểu cấu trúc:** Xác định các cột, kiểu dữ liệu, và mục tiêu phân tích của user.
3. **Tính toán:** Nếu có tool chạy mã (execute) khả dụng, chạy `scripts/analyze.py` với đường dẫn tuyệt đối tới file dữ liệu; nếu không có, tự tính thủ công các chỉ số chính (tổng, trung bình, min/max, count).
4. **Tóm tắt:** Trình bày kết quả gọn theo đúng câu hỏi, nêu 2-3 quan sát quan trọng nhất và bất kỳ điểm bất thường nào.
5. **Báo cáo tùy chọn:** Nếu user cần báo cáo, kèm bảng số liệu nhỏ và ghi rõ nguồn dữ liệu đã dùng.

## Nguyên tắc

- Luôn nêu rõ phạm vi dữ liệu (số dòng/số cột đã phân tích) để tránh suy diễn quá mức.
- Chỉ đưa ra kết luận nhân quả nếu dữ liệu hỗ trợ; nếu không, dùng ngôn ngữ tương quan.