# Model Integration Audit — Analyzing a Codebase for New Model Support

Systematic methodology to determine whether a Python codebase supports a given LLM, and identify every component that needs changes to add it.

## When to Use

- Asked: "can we use model X with this system?"
- Need to port prompts/templates from one model family to another (e.g., Llama 3 → DeepSeek)
- A prompt file exists but it's unclear which model it's for

## Workflow

### Phase 1: Identify the API Protocol

Start by finding how the codebase calls the LLM. Look for:

1. **Which API client library is used** — `openai` (Chat Completions), `requests` (raw HTTP), custom SDK
2. **API type** — look in the call function:
   - `messages=[...]` → **Chat Completions** (OpenAI format)
   - `prompt="..."` (string) → **Completion** (raw text, vLLM, TGI)
   - `model.generate_content(...)` → **Google Vertex AI** (Gemini)
3. **Model name resolution** — search for `map_model` dicts, deployment ID lookups, or URL routing functions (`gen_url`, `get_url`)

**Tell Completion vs Chat Completions at a glance:**

| Signal | Completion | Chat Completions |
|--------|-----------|-----------------|
| Body field | `"prompt": "string"` | `"messages": [...]` |
| Model name in URL | `/completions` or `/generate` | `/chat/completions` |
| Stop tokens in body | `"stop": ["</s>", "\n"]` | Not in body (model default) |
| Response | `{"generated_text": "..."}` | `{"choices": [{"message": {...}}]}` |

### Phase 2: Trace the Call Chain

For each model family in the codebase, trace from entry point to API call:

```
Service router (llm_service.py)
  ↓
Prompt builder (llm_prompt.py) — what format does it return?
  ↓
Generator (llm_generate.py) — which function handles the model?
  ↓
URL resolver (string_utils.gen_url or config) — where does the request go?
  ↓
API endpoint — what protocol? (vLLM, TGI, Azure OpenAI, Vertex AI, raw)
```

**Key questions at each layer:**
- **Prompt builder:** Does it return a string or a list of dicts (messages array)?
- **Generator:** Does the function use `openai.ChatCompletion.create()`, raw `requests.post()`, or SDK call?
- **URL resolver:** Is there a mapping for this model already? If not, where's the URL defined?
- **Endpoint:** vLLM (Completion vs Chat?), TGI, Azure OpenAI, DeepSeek, etc.?

### Phase 3: Identify What's Missing for a New Model

Create a checklist:

| Component | What to check | File(s) to inspect |
|-----------|--------------|-------------------|
| **Model list** | Is the model name in the service's model list? | `llm_service.py` (or equivalent router) |
| **Router** | Is there a branch for this model family? | Generator's main dispatch function |
| **Prompt format** | Does the prompt builder return the right format (string vs messages)? | `llm_prompt.py` |
| **API call** | Is there a function that calls the right endpoint with right body? | `llm_generate.py` |
| **URL mapping** | Is there a URL for this model? | `config.py`, `string_utils.py` |
| **Auth** | Does the endpoint need API key, token, or service account? | Config/env vars |
| **Stop tokens** | Do stop tokens match the model's tokenizer? | Generator function body |
| **Max tokens / temperature** | Are there per-model parameter overrides? | Config or generator body |
| **Prompt template** | Does the existing prompt file use the right special tokens? | Prompt file (.txt, .md) |

### Phase 4: Analyze Prompt Template Compatibility

Given a prompt text file, determine which model family it targets:

1. **Check special tokens:**
   - `<|begin_of_text|>`, `<|start_header_id|>system<|end_header_id|>` → **Llama 3** (Meta)
   - `<|system|>`, `<|user|>`, `<|assistant|>` → **Viettel AI** (custom TGI) or older Llama
   - `<|im_start|>user<|im_end|>` → **ChatML** (GPT, Mistral, some open models)
   - `[INST]`, `[/INST]` → **Llama 2** or **Mistral** instruct
   - `User:`, `Assistant:` → **DeepSeek** (older format) or custom
   - `### Human:`, `### Assistant:` → **Claude** or custom fine-tune

2. **Check stop tokens in API calls** — the `stop` array in the generator function tells you what tokens the server expects:
   - `["</s>", "<|eot_id|>"]` → Llama 3 (vLLM Completion)
   - `["</s>"]` → TGI (Text Generation Inference)
   - No explicit stop → Chat Completions (model default)

3. **Check API endpoint URL:**
   - `/v1/completions` → vLLM Completion endpoint
   - `/v1/chat/completions` → Chat Completions (OpenAI-compatible or vLLM chat)
   - `/generate` → TGI endpoint

### Phase 5: Assess Porting Difficulty

| API protocol | Prompt format | Porting to DeepSeek (Chat Completions) difficulty |
|-------------|--------------|--------------------------------------------------|
| vLLM Completion | String (raw text + tokens) | **Hard** — need to restructure to messages array |
| TGI | String (raw text + tokens) | **Medium** — restructure + remove special tokens |
| Chat Completions | Messages array | **Easy** — just change model name + stop tokens |
| Azure OpenAI | Messages array | **Easy** — change base URL + auth |
| Vertex AI (Gemini) | Single string | **Medium** — rewrite to messages array |

## Example: Tracing a Real Codebase

Given a repo with:
- `llm_service.py` with `VAI_MODEL = ["viettel-llm-7B", "70B"]`
- `llm_generate.py` with `generate_vai_70b()` sending `{"prompt": ..., "model": "Meta-Llama-3-70B-Instruct"}`
- `prompt.txt` containing `<|begin_of_text|><|start_header_id|>system<|end_header_id|>...`

**Analysis:**
- This is vLLM Completion API (field `"prompt"`, not `"messages"`)
- Model is Meta-Llama-3-70B-Instruct (Llama 3 template)
- To add DeepSeek-V4-Flash (Chat Completions):
  1. Add `"DeepSeek-V4-Flash"` to a new `DEEPSEEK_MODEL` list in service
  2. Add router branch in generator
  3. Add URL + API key to config
  4. Create new prompt format (messages array with system/user roles)
  5. Don't use Llama 3 special tokens — use OpenAI messages format

## Pitfalls

1. **Assuming one API protocol for all models.** Check each model's generator function individually — different models may use different endpoints (Completion vs Chat), even in the same codebase.
2. **Using a Llama 3 template prompt for a non-Llama model.** Special tokens like `<|begin_of_text|>` and `<|eot_id|>` are only recognized by Llama 3's tokenizer; other models treat them as regular text.
3. **Mixing Completion and Chat Completions.** A prompt built as a string won't work with Chat Completions API, and a messages array won't work with Completion API. Check the API field name (`prompt` vs `messages`) in the request body.
4. **Forgetting to check the service router.** A new model name may fall into a catch-all `else` branch and hit the wrong API (e.g., if the codebase only checks for `VAI_MODEL` and `GOOGLE_MODEL`, everything else goes to GPT/Azure — which may not be intended).
5. **Stop tokens are model-specific.** Copying stop tokens from one model to another can cause truncation or runaway generation. Check the model's tokenizer documentation.
6. **Auth is per-endpoint.** Different model backends use different auth: API key in header, Azure AD token, service account JSON, or no auth.
