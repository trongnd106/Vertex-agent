# Agent Tasks - Tất cả Task Chi Tiết

> **Mục đích:** Tạo một agent mạnh mẽ dựa trên source code LangGraph + DeepAgents + kiến trúc từ orchestrator.
>
> **Phạm vi:** Xây dựng agent backend hoàn chỉnh với graph orchestration, middleware stack, tool system, memory management, streaming, và production deployment.
>
> **Ngày tạo:** 2026-09-09

## Cấu trúc thư mục

```
docs/tasks/
├── README.md                          # File này - overview tất cả tasks
├── 01-agent-graph-core/               # Core Graph Architecture
├── 02-middleware-stack/               # Middleware Pipeline
├── 03-tool-system/                    # Tool Management System
├── 04-memory-persistence/             # Memory & Persistence
├── 05-subagent-communication/         # Subagent & Communication
├── 06-streaming-pipeline/             # Streaming & Observability
├── 07-routing-control-flow/           # Routing & Control Flow
├── 08-backend-infrastructure/         # Backend & Storage
├── 09-deployment-operations/          # Deployment & Operations
└── 10-advanced-features/              # Advanced Features
```

## Danh sách tất cả Tasks

| STT | Task                                                              | File       | Mục tiêu                                                   |
| --- | ----------------------------------------------------------------- | ---------- | ---------------------------------------------------------- |
| 1   | [Agent Graph Core](./01-agent-graph-core/README.md)               | 9 subtasks | Xây dựng core graph engine dựa trên LangGraph Pregel       |
| 2   | [Middleware Stack](./02-middleware-stack/README.md)               | 7 subtasks | Xây dựng middleware pipeline theo pattern của orchestrator |
| 3   | [Tool System](./03-tool-system/README.md)                         | 6 subtasks | Tool management, MCP integration, sandbox                  |
| 4   | [Memory & Persistence](./04-memory-persistence/README.md)         | 6 subtasks | Checkpointing, long-term memory, dreaming                  |
| 5   | [Subagent & Communication](./05-subagent-communication/README.md) | 5 subtasks | Subagent patterns, async communication, MCP                |
| 6   | [Streaming & Observability](./06-streaming-pipeline/README.md)    | 5 subtasks | Streaming pipeline, tracing, monitoring                    |
| 7   | [Routing & Control Flow](./07-routing-control-flow/README.md)     | 5 subtasks | Conditional routing, loops, human-in-the-loop              |
| 8   | [Backend & Storage](./08-backend-infrastructure/README.md)        | 5 subtasks | Backend protocols, composite backend                       |
| 9   | [Deployment & Operations](./09-deployment-operations/README.md)   | 5 subtasks | Docker, CI/CD, production setup                            |
| 10  | [Advanced Features](./10-advanced-features/README.md)             | 5 subtasks | Dreaming, self-improvement, rubric                         |

**Tổng số subtasks:** ~58 tasks chi tiết
