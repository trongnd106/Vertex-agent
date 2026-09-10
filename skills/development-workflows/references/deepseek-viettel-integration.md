# DeepSeek-V4-Flash Integration with Viettel AI Server

Specific quirks discovered when integrating DeepSeek-V4-Flash into the `chat-llm-vds` codebase (FastAPI service with multi-model routing).

## Server Info

- **URL:** `http://staging-ai-service.viettelai.vn`
- **Chat endpoint:** `/chat/completions` (no `/v1` prefix!)
- **Model name:** `DeepSeek-V4-Flash`
- **Auth:** API key in `Authorization: Bearer <key>` header
- **API type:** OpenAI Chat Completions (messages array)

## Critical Quirks

### Path: NO `/v1` prefix

The server expects `/chat/completions`, not `/v1/chat/completions`. OpenAI SDK v2 automatically appends `/v1`:

```python
# OpenAI SDK v2 → builds http://host/v1/chat/completions automatically
client = OpenAI(base_url="http://host")  

# For this server, base_url without /v1 is CORRECT — SDK adds it
client = OpenAI(base_url="http://staging-ai-service.viettelai.vn")
# → client calls host/v1/chat/completions ← server also accepts this
```

Both `/chat/completions` and `/v1/chat/completions` work on this server — it accepts both paths.

### Auth Errors: Key appears invalid from unknown IPs

The server uses LiteLLM proxy with `LiteLLM_VerificationTokenTable`. Even with the correct API key, requests from unfamiliar IPs may get 401:

```
Authentication Error, Invalid proxy server token passed. 
Unable to find token in cache or `LiteLLM_VerificationTokenTable`
```

Test the API key from the target deployment environment, not from arbitrary IPs.

## Integration Pattern (chat-llm-vds)

### 5 files to change:

| File | Change |
|------|--------|
| `config.py` | Add `DEEPSEEK_V4_FLASH_MODEL`, `_URL`, `_API_KEY` |
| `llm_service.py` | Add `DEEPSEEK_MODEL = ["DeepSeek-V4-Flash"]` |
| `llm_generate.py` | Add router branches in `question()`, `answer()`, `spelling()`, plus `generate_deepseek()` |
| `llm_prompt.py` | Add `_build_deepseek_answer_prompt()` returning messages array, add to `get_max_token()` |
| `string_utils.py` | Add `gen_url("DeepSeek-V4-Flash")` mapping |

### generate_deepseek() — key points:

```python
def generate_deepseek(prompt: Any, temperature: float, model_name: str):
    import openai as deepseek_openai
    client = deepseek_openai.OpenAI(
        base_url=Config.DEEPSEEK_V4_FLASH_URL,  # no /v1
        api_key=Config.DEEPSEEK_V4_FLASH_API_KEY,
    )
    # prompt can be str (rewire/spelling) or list (answer messages array)
    if isinstance(prompt, list):
        messages = prompt
    else:
        messages = [
            {"role": "system", "content": "Bạn là trợ lý AI hữu ích."},
            {"role": "user", "content": prompt},
        ]
    response = client.chat.completions.create(
        model=Config.DEEPSEEK_V4_FLASH_MODEL,
        messages=messages,
        temperature=temperature if temperature else 0.01,
        max_tokens=4000,
    )
    return response.choices[0].message.content or ""
```

## Prompt Format Conversion

| Original (Llama 3 via vLLM Completion) | New (DeepSeek via Chat Completions) |
|----------------------------------------|-------------------------------------|
| 1 raw string with special tokens | Messages array with `role: system` + `role: user` |
| `<\|begin_of_text\|>` removed | Not needed |
| `<\|start_header_id\|>system<\|end_header_id\|>` | `{"role": "system", "content": "..."}` |
| `<\|start_header_id\|>user<\|end_header_id\|>` | `{"role": "user", "content": "..."}` |
| `<\|eot_id\|>` removed | Not needed |
| Stop tokens in API body | Not needed (model default handles it) |

## Tool Calling (if needed)

DeepSeek-V4-Flash supports OpenAI function calling format. If adding tool support, use the standard OpenAI tools/messages pattern — no special adaptation needed.

## Regional Considerations

- Vietnamese language prompts work best with Vietnamese system message
- API key may be specific to Viettel internal network
- Server may have different model versions behind the same endpoint name — check if version pinning is needed
