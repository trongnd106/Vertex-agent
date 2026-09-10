# Advanced Features

> **Nguồn tham khảo:** Vertex-agent `src/memory/dreaming/` (enqueue, scan, dream, consolidate); DeepAgents `middleware/rubric.py`; LangMem `reflection.py`; orchestrator deep research agent patterns

## Mục tiêu

Xây dựng advanced features: dreaming system, self-improvement, rubric evaluation, deep research, và multi-modal support.

## Tasks

### Task 10.1: Dreaming System — Enqueue & Scan

**Mô tả:** Implement dreaming enqueue và scan system.

**File tham khảo:**
- Vertex-agent: `src/memory/dreaming/enqueue.py` (EnqueueAfterTurnMiddleware)
- `src/memory/dreaming/scan.py` (scan thread IDs)

**Yêu cầu:**
- EnqueueAfterTurnMiddleware:
  - `after_agent` hook: gọi sau mỗi agent turn
  - Enqueue thread_id + user_id vào queue
  - Không block agent execution (fire-and-forget)
  - Configurable: enable/disable per session
- Scan system:
  - Thread discovery: `scan_thread_ids(saver)` từ checkpoint
  - Backlog computation: so sánh threads có trong checkpoint vs threads đã dream
  - Incremental scan: chỉ scan threads mới/chưa dream
  - Cold scan: scan tất cả (first run)
- Queue types:
  - In-memory queue (dev)
  - Database queue (production)
  - Background thread processing

### Task 10.2: Dreaming — Dream & Consolidation

**Mô tả:** Implement dream engine và consolidation logic.

**File tham khảo:**
- Vertex-agent: `src/memory/dreaming/dream.py` (write_dream_results, dream thread)
- `src/memory/dreaming/consolidate.py` (consolidation logic)

**Yêu cầu:**
- Dream Engine:
  - Read conversation từ checkpoint (qua `load_thread_messages`)
  - Analyze conversation: extract facts, preferences, patterns
  - Generate structured dreams:
    - Facts: `memories/` namespace
    - Lessons: `system.lessons/` namespace
    - Conflicts: `system.conflict_markers/` namespace
  - Write dream results vào Store: `write_dream_results(store, thread_id, dreams)`
- Consolidation:
  - Staleness detection: items không đọc trong N ngày
  - Priority-based aging: chỉ items có `priority` mới được age
  - Conflict resolution: multiple dreams cho cùng topic
  - Deduplication: không ghi duplicate facts
  - Batch processing: process N threads per cycle
- Deterministic testing:
  - Fake model cho dream LLM calls
  - Fake store cho dream results
  - Backdate items via raw SQL cho staleness test

### Task 10.3: Rubric & Self-Evaluation System

**Mô tả:** Implement rubric evaluation system: agent tự đánh giá output của mình.

**File tham khảo:**
- DeepAgents: `middleware/rubric.py` (RubricMiddleware, RubricState, RubricResult, RubricEvaluation, GraderResponse)
- LangMem: `reflection.py` patterns

**Yêu cầu:**
- Rubric definition:
  - Criteria: identity (bản sắc), critical (quan trọng), simple (đơn giản)
  - CriterionEval: criterion + expected behavior + weight
  - CriterionPass/Fail: pass/fail với reasoning
- Grader LLM: sub-agent call để chấm điểm
- GraderResponse: structured output với verdict + feedback
- Revision loop:
  - Nếu fail rubric -> inject feedback làm HumanMessage
  - Agent revision -> re-grade
  - Configurable max revision attempts
- Rubric profiles: reusable rubric configs
- Streaming: grader feedback stream về UI
- Logging: rubric evaluation history

### Task 10.4: Deep Research Agent

**Mô tả:** Xây dựng Deep Research Agent pattern: multi-step research với web search, analysis, và synthesis.

**File tham khảo:**
- orchestrator: AIQ Agent (Deep Researcher), subagent patterns
- DeepAgents: subagent systems

**Yêu cầu:**
- Research workflow:
  1. Phân tích câu hỏi -> xác định research plan
  2. Parallel search: web search + document search + knowledge base
  3. Deep read: đọc và phân tích từng source
  4. Cross-reference: so sánh multiple sources
  5. Synthesis: tổng hợp thành answer structured
- Research memory: lưu research state (what's been searched, found, analyzed)
- Citation: track sources, generate citations
- Iterative refinement: multi-round research (discover -> read -> refine)
- Streaming: stream research progress (searching -> reading -> synthesizing)
- Configurable depth: quick vs deep research

### Task 10.5: Multi-Modal & Extensions

**Mô tả:** Implement multi-modal support và extension points.

**File tham khảo:**
- DeepAgents: `middleware/_video.py` (video frame extraction)
- LangChain: multi-modal support patterns
- orchestrator: extension patterns

**Yêu cầu:**
- Image processing:
  - Đọc và phân tích image từ tool results
  - Image in conversation (user sends image)
  - Base64 image handling
- Video frame extraction:
  - Extract frames từ video files
  - Analyze key frames
  - Frame deduplication
- Code execution:
  - Python sandbox với libraries
  - Code output capture (stdout, stderr, plots)
  - Visualization rendering
- Plugins/Extensions:
  - Plugin system: add new capabilities via plugins
  - Hook system: lifecycle hooks cho extensions
  - Custom middleware registration
  - Custom tool registration
- Knowledge base integration:
  - RAG: retrieval augmented generation
  - Vector store: semantic search
  - Document processing: PDF, HTML, Markdown
- Model fallback & routing:
  - Primary model -> fallback model -> degrade
  - Model routing per task type
  - Cost-based model selection