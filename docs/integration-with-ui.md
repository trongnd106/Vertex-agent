# Báo cáo: Tích hợp Vertex Agent Backend với Vertex-agent-UI

## Hiện trạng

### Backend (Vertex-agent)
- **FastAPI** server ở port 8000
- Endpoints: `GET /health`, `POST /invoke`, `POST /stream`, `GET|POST /state/{thread_id}`
- CORS đã bật (Allow `*`)
- Request/Response dùng JSON

### UI (Vertex-agent-UI)
- **React 19 + Vite + TypeScript + Zustand** — thuần frontend
- **Zero API calls** — tất cả response là mock (hardcoded sample replies)
- Không có `.env`, không có API service layer, không có HTTP client

## API Contract: Backend vs UI cần

### Backend cung cấp

| Endpoint | Method | Request Body | Response |
|---|---|---|---|
| `/invoke` | POST | `{ message: string, thread_id: string, user_id: string }` | `{ thread_id, response: string\|list, messages: [...] }` |
| `/stream` | POST | `{ message: string, thread_id: string, user_id: string }` | SSE stream events |
| `/health` | GET | — | `{ status, version, ... }` |

### UI mong đợi (từ TypeScript types)

```typescript
interface ChatMessage {
  id: string
  role: 'user' | 'ai'
  content: string
  timestamp: Date
  reasoningSteps?: ReasoningStep[]
  files?: File[]
}
```

## Gaps — Những thứ cần bổ sung

### 1. UI cần thêm

| Thứ cần | Mức độ | Chi tiết |
|---|---|---|
| **API service layer** | Bắt buộc | File `src/services/api.ts` chứa các hàm gọi backend |
| **Environment config** | Bắt buộc | `.env` với `VITE_API_URL=http://localhost:8000` |
| **Vite proxy** | Bắt buộc | Cấu hình proxy trong `vite.config.ts` để tránh CORS khi dev |
| **Thay mock bằng real call** | Bắt buộc | Sửa `chatStore.ts::sendMessage` — bỏ `setTimeout` mock, gọi API thật |
| **Xử lý thread_id** | Bắt buộc | UI cần track `thread_id` cho mỗi conversation |
| **Loading state** | Nên có | Spinner/skeleton khi chờ response từ backend |
| **Error handling** | Nên có | Hiển thị lỗi khi backend không phản hồi |

### 2. Backend cần thêm (tùy chọn)

| Thứ cần | Mức độ | Chi tiết |
|---|---|---|
| **History endpoint** | Nên có | `GET /conversations` — lấy danh sách conversation của user |
| **Conversation CRUD** | Nên có | `DELETE /conversations/{id}`, `PATCH /conversations/{id}/title` |
| **File upload** | Nếu cần | `POST /upload` — upload file đính kèm, trả về file_id |
| **Reasoning steps** | Tốt nhất có | Backend trả về thêm structured reasoning steps nếu có |

## Cách tích hợp — Implementation Plan

### Bước 1: UI — Tạo API service layer

```typescript
// src/services/api.ts
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export async function sendMessage(
  message: string,
  threadId: string,
  userId: string = 'anonymous'
): Promise<{ response: string; thread_id: string }> {
  const res = await fetch(`${API_BASE}/invoke`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id: threadId, user_id: userId }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
```

### Bước 2: UI — Sửa chatStore.ts

- `sendMessage`: gọi `api.sendMessage()` thay vì `setTimeout`
- Lưu `threadId` vào conversation state
- Map response backend (`{ thread_id, response, messages }`) thành `ChatMessage`

### Bước 3: UI — Cấu hình .env

```
VITE_API_URL=http://localhost:8000
```

### Bước 4: UI — Vite proxy (tùy chọn, để tránh CORS khi dev)

```typescript
// vite.config.ts
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

### Bước 5: Backend — Thêm history endpoint (nếu cần)

```python
@app.get("/conversations")
async def list_conversations(user_id: str = "anonymous"):
    """List user's conversations from checkpointer."""
    # TODO: query checkpointer for thread list
```

## Kết luận

Việc tích hợp là **khả thi ngay lập tức** vì:

- Backend có CORS bật sẵn (Allow `*`)
- Backend có endpoint `/invoke` đầy đủ
- UI có store structure phù hợp để map với API response
- Cả hai đều dùng TypeScript / Python thuần, không phụ thuộc phức tạp

Thời gian ước tính: **2-4 giờ** cho lập trình viên frontend.