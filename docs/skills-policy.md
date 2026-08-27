# Skills Policy — quy chuẩn nội bộ cho hệ thống Skill

Nguyên tắc tổng thể theo Plan 4.1: mỗi skill là 1 thư mục chứa `SKILL.md` (YAML
front-matter + phần thân dạng hướng dẫn quy trình), được nạp qua
`create_deep_agent(skills=["/skills/"])`. Chỉ `name` + `description` được nạp
mặc định (progressive disclosure); phần thân chỉ đọc khi agent quyết định dùng
skill (qua tool `read_file` trên `SKILL.md`).

## 1. Front-matter tối thiểu

| Field | Bắt buộc | Ràng buộc |
|---|---|---|
| `name` | ✓ | ≤64 ký tự, `a-z`/`0-9`/`-`, không bắt đầu/kết thúc bằng `-`, không `--`, **khớp chính xác tên thư mục chứa nó** |
| `description` | ✓ | ≤1024 ký tự; nêu rõ **khi nào** kích hoạt (what + when), kèm từ khóa giúp agent nhận diện |
| `version` | ✓ | Chuẩn semver đơn giản `"1.0"`; bump khi đổi hành vi kích hoạt/đổi quy trình |
| `license` / `compatibility` / `metadata` | tự chọn | theo agentskills.io spec |

## 2. Phạm vi kích hoạt không chồng lấn

- Mỗi skill `description` phải kết thúc bằng câu phủ định rõ phạm vi của nó
  (vd *"Do not use for X"*).
- Bất kỳ skill mới nào có miêu tả chạm vào miêu tả skill có sẵn ⇒ viết lại để
  tách bạch, hoặc gộp vào skill gần nhất. Ràng buộc này được giữ bằng code review
  ở bước 3.

## 3. Quy trình review skill mới (pull request)

1. Tạo thư mục + `SKILL.md` theo template mục 1-2.
2. Thêm **CI test activation** cho skill đó trong `tests/test_skills.py`
   (kiểu: prompt mẫu X ⇒ skill Y được đọc qua `read_file`, đầu ra tham chiếu nội
   dung body). Kèm test front-matter hợp lệ (dùng regex `name` + độ dài
   `description`).
3. Review `description` để đảm bảo **không chồng lấn phạm vi** với các skill đã có.
4. Bump `version` trong front-matter và tạo tag git `skills/<name>@<version>`
   (vd `skills/data-analysis@1.0`) làm điểm rollback.

## 4. Rollback

- Rollback nội dung: `git revert` commit thay đổi skill, hoặc checkout lại file
  `SKILL.md` từ tag `skills/<name>@<version>`.
- Rollback phiên bản agent: tag git đóng băng bộ skill đồng bộ với deploy; khi
  cần về bản cũ, deploy đúng commit/tag đó.

<!-- Giữ file này ngắn gọn, hành động được. Đừng biến thành tài liệu dài dòng. -->