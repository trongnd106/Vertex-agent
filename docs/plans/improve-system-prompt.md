# Plan: Cải thiện System Prompt cho Vertex Agent

## Hiện trạng

Vertex agent hiện tại xây dựng system prompt rất đơn giản:

| Thành phần | Vertex hiện tại | Hermes Agent (tham khảo) |
|---|---|---|
| **File** | `src/agent/graph.py` — 1 function (`build_system_prompt`) | `agent/system_prompt.py` + `agent/prompt_builder.py` — module riêng |
| **Cấu trúc** | Flat string: `base + MEMORY_GUIDANCE` | 3 cache tiers: **Stable** / **Context** / **Volatile** |
| **Identity** | Không có | `SOUL.md` hoặc `DEFAULT_AGENT_IDENTITY` |
| **Skills** | Load file SKILL.md in skills/ nhưng không chủ động đưa vào system prompt | `build_skills_system_prompt()` — index tất cả skills + mô tả |
| **Memory** | `MEMORY_GUIDANCE` hardcode, hướng dẫn ghi file `/memory/notes.md` | `build_memory_guidance()` — động theo trạng thái memory |
| **Dynamic injection** | Không có | Timestamp, model info, env hints, plugin sections, ephemeral |
| **Tool guidance** | Không có | `_tool_guidance_block()` — hướng dẫn riêng cho từng tool |
| **Model-gated** | Không có | `_guidance_parts()` — guidance khác nhau theo model/provider |
| **Cache tiers** | Không có | 3 tiers để tối ưu prompt caching |
| **Plugin system** | Không có | Plugin đóng góp section vào system prompt |

## Mục tiêu

1. **Tách system prompt thành module riêng** — không nhét trong `graph.py`
2. **Thêm agent identity** — định danh rõ Vertex là ai, làm gì
3. **Cache tiers** — tách stable prefix khỏi volatile suffix để tận dụng prompt caching
4. **Skills index** — chủ động liệt kê skills + mô tả trong system prompt
5. **Dynamic injection** — timestamp, model name, environment hints
6. **Tool guidance** — hướng dẫn sử dụng tool rõ ràng
7. **Model-gated guidance** — guidance khác nhau nếu dùng model/provider khác

## Phạm vi

- **Không** thay đổi `deepagents` / `create_deep_agent` — chỉ thay đổi phần prompt trước khi truyền vào
- **Không** thay đổi cách skills được load (vẫn giữ skills/*/SKILL.md)
- **Không** thêm plugin system (quá lớn cho phase này)
- **Ảnh hưởng**: `src/agent/graph.py` (tách `build_system_prompt`), `src/agent/server.py` (dùng module mới), `src/api/server.py` (nếu cần ephemeral prompt)

## Thiết kế

### 1. Module mới: `src/agent/system_prompt.py`

```
src/agent/system_prompt.py
├── DEFAULT_AGENT_IDENTITY         # fallback identity string
├── MEMORY_GUIDANCE                # từ graph.py cũ, giữ nguyên
├── SKILLS_INDEX_GUIDANCE          # hướng dẫn cách dùng skills
├── TOOL_USE_ENFORCEMENT_GUIDANCE  # quy tắc dùng tool
├── TASK_COMPLETION_GUIDANCE       # quy tắc hoàn thành task
│
├── build_system_prompt(           # public API — trả về string hoàn chỉnh
│   agent_identity: str | None,
│   system_message: str | None,
│   config: dict,
│ ) -> str
│
├── build_system_prompt_parts(     # trả về 3 tiers để cache planning
│   agent_identity,
│   system_message,
│   config,
│ ) -> dict[str, str]              # {stable, context, volatile}
│
├── _identity_part()               # SOUL.md tương lai hoặc default
├── _guidance_part()               # tool/model guidance (model-gated)
├── _skills_index_part()           # danh sách skills từ disk
├── _memory_part()                 # memory guidance (dynamic)
├── _timestamp_line()              # ngày giờ, model, provider
├── _environment_hints()           # host OS, cwd, sandbox type
└── _tool_guidance_block()         # guidance cho tools đang active
```

### 2. Cache tiers

```
Stable (byte-stable trong session):
├── Agent identity
├── Help guidance
├── Tool use enforcement guidance
├── Task completion guidance
├── Memory guidance (static part)

Context (thay đổi theo conversation):
├── Caller system_message (nếu có)
├── Project context (để dành cho tương lai)

Volatile (thay đổi mỗi turn):
├── Skills index
├── Memory snapshot
├── Timestamp line (current date + model info)
├── Environment hints
```

### 3. Identity mặc định

```python
DEFAULT_AGENT_IDENTITY = (
    "You are Vertex Agent, an AI assistant built on deepagents (LangGraph). "
    "You help users with a variety of tasks including customer support, "
    "data analysis, and code review. "
    "You have access to a filesystem for reading/writing files and "
    "a long-term memory system via /memory/notes.md."
)
```

### 4. Skills index

```python
def _skills_index_part(skills_dir: str = "/skills/") -> str:
    """Đọc skills/*/SKILL.md, trích xuất name + description, tạo index."""
    # Trả về:
    # ## Available Skills
    # - **customer-support**: Use when responding to customer support requests...
    # - **data-analysis**: Use when the user asks to analyze a data file...
    # - **code-review**: Use when the user asks to review source code...
    # 
    # To load a skill, use skill_view("<skill-name>") tool.
```

## Các bước thực hiện

### Bước 1: Tạo `src/agent/system_prompt.py`

- Tạo module mới với `DEFAULT_AGENT_IDENTITY` và các guidance constants
- Implement `build_system_prompt()` và `build_system_prompt_parts()`
- Implement `_skills_index_part()` — đọc skills/*/SKILL.md
- Implement `_timestamp_line()` — format: `Current time: {datetime}. Model: {model}. Provider: {provider}.`
- Implement `_environment_hints()` — host OS, cwd

### Bước 2: Cập nhật `src/agent/graph.py`

- Giữ `MEMORY_GUIDANCE` hoặc move vào module mới
- `build_system_prompt()` trở thành wrapper gọi `system_prompt.build_system_prompt()`
- Giữ backward compatibility (tham số `base` vẫn hoạt động)

### Bước 3: Cập nhật `src/agent/server.py`

- `_build_graph()` truyền thêm config vào `build_system_prompt`
- Model name, provider name được inject vào system prompt

### Bước 4: Cập nhật `src/api/server.py` (nếu cần)

- Thêm `ephemeral_system_prompt` cho request-specific instructions

### Bước 5: Xoá code cũ (nếu không dùng)

- Sau khi verify mọi thứ hoạt động, xoá constants/functions cũ khỏi `graph.py`

## Những gì KHÔNG thay đổi

- `src/agent/graph.py::build_agent` — signature giữ nguyên
- `create_deep_agent` — không động tới
- Skills loading — vẫn giữ cơ chế skills/*/SKILL.md
- Memory backend — không động tới

## Mở rộng tương lai (out of scope cho phase này)

- `SOUL.md` — load identity từ file ngoài
- Plugin system prompt sections — plugin đóng góp section
- Per-turn ephemeral system prompt — API request-specific instructions
- Prompt caching optimization with LangSmith
- Multi-language identity (i18n)