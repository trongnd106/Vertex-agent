# Tool Audit Checklist — HarnessProfile theo role

Quy chuẩn audit **định kỳ** cho cơ chế giới hạn tool theo role của
`HarnessProfile`/`excluded_tools` (Task 2, mechanism verify tại
`docs/phase-0-discovery.md` §12.10 / §13.2 / §16). Checklist này là **bảng
nguồn của sự thật** cho tất cả profile đang được đăng ký trong
`src/agent/roles.py`; `tests/test_observability.py` có một test giữ checklist
này đồng bộ với code (grep key + tên tool bị exclude) — sửa profile mà quên
sửa tài liệu ⇒ CI đỏ.

> Lưu ý phạm vi (đã verify, xem §16): `HarnessProfile(excluded_tools=...)`
> loại tool khỏi **tầng model-facing** (khiến model không thấy/không gọi được
> tool), còn `permissions=[FilesystemPermission(...)]` chỉ chặn các tool
> **filesystem** (`ls`, `read_file`, `write_file`, `edit_file`, `delete`,
> `glob`, `grep`). `execute` KHÔNG bị `FilesystemPermission` chặn — nó chỉ bị
> chặn bởi (a) profile role cho customer-support và (b) ranh giới riêng của
> sandbox (`RestrictedShellSandbox`, Task 2).

## 1. Tool surface hiện tại (đối chiếu discovery §13.5)

Built-in tools mà `create_deep_agent` bind mặc định (bỏ `execute` nếu backend
không thỏa `SandboxBackendProtocol`):

`ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `delete`, `task`
(+ `execute` khi backend là sandbox).

Custom business tools (repo này, cộng thêm qua `tools=[...]`,
`src/agent/tools/__init__.py`): `query_order`, `create_support_ticket`.

## 2. Bảng audit theo role (đối chiếu `src/agent/roles.py`)

| Role key (profile) | Đăng ký trong | Allowed tools | Excluded tools | Risk notes | Review cadence |
|---|---|---|---|---|---|
| `customer-support` | `roles.register_customer_support_role()` | Built-in fs tools (`ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `delete`, `task`) + custom business tools | **`execute`** | Agent fronting end-user **không được chạy shell**. Fs tools vẫn ghi/đọc được khi agent sai prompt — nên thêm `FilesystemPermission` cho vùng nhạy | Hàng tháng + mỗi lần đổi tool surface |
| `operator` | `roles.register_operator_role()` | Mọi built-in (gồm **`execute`**) + custom business tools | **(none)** | Quyền cao nhất; `execute` phải đi qua sandbox rim (`RestrictedShellSandbox`, Task 2) — FilesystemPermission không gate `execute` | Hàng tuần + mỗi lần đổi tool |

## 3. Quy trình audit (mỗi chu kỳ)

1. Chạy `tests/test_tools.py` + `tests/test_permissions.py` + `tests/test_observability.py`
   — kiểm tra exclusion thực sự áp dụng khi build agent (fixture
   `_HARNESS_PROFILES` clear giữa test, không leak state).
2. Rà tất cả `register_harness_profile(...)` trong repo (hiện chỉ ở
   `src/agent/roles.py`) so với bảng mục 2 — **thêm profile mới phải thêm hàng
   ở bảng này**, ngược lại test sync ở mục 4 sẽ fail.
3. Rà built-in tool surface thay đổi theo version deepagents
   (`docs/phase-0-discovery.md` §13.5): đổi tên/thêm tool mới ⇒ cập nhật mục 1
   và cột `Excluded tools`.
4. Đối chiếu cross-layer: tool mà role allow phải có ranh giới tương ứng ở tầng
   thực thi. `FilesystemPermission` chỉ phủ 7 tool fs; `execute` phải được
   sandbox rim che (`src/agent/tools/sandbox.py`).

## 4. Giữ checklist ↔ code đồng bộ (CI)

`tests/test_observability.py::test_audit_checklist_tracks_registered_profiles`:

- Đăng ký toàn bộ role qua `roles.register_all_roles()`.
- Với mỗi key đăng ký (từ `src/agent/roles.py`): key phải xuất hiện trong file
  `docs/tool-audit-checklist.md`; mỗi tool trong `profile.excluded_tools` phải
  xuất hiện trong file; role không exclude gì phải có dòng `(none)`.
- Fix: khi đổi profile trong code, cập nhật hàng tương ứng ở bảng mục 2.