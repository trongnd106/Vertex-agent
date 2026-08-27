"""Summ/compaction configuration for the deep agent.

`create_deep_agent` adds a `SummarizationMiddleware` to the base stack by
default (see `deepagents/graph.py`), but its thresholds are auto-selected from
the model's profile — typically `("fraction", 0.85)` / `("messages", 6)`, which
is far too high for the cheap/generic models we target. This helper builds a
configured summarization middleware with modest, predictable thresholds that
can be tuned per call.

## Override semantics (VERIFIED, deepagents 0.7.9)

Passing a configured `SummarizationMiddleware` through `create_deep_agent(
middleware=[...])` **replaces** the default summarization middleware — it does
NOT stack a second summary graph on top of the default one.

Mechanism: `deepagents/graph.py::_apply_custom_middleware` (line ~201) merges
user middleware into the base stack **by `.name`**. When `m.name` matches a
name still present in `base`, the entry is replaced *in place*, preserving stack
order (lines 220-228); otherwise a brand-new entry is appended after the core
stack. Both the langchain base `SummarizationMiddleware` and the deepagents
wrapper report `.name == "SummarizationMiddleware"` (default `AgentMiddleware.name`
is the class name), with the default middleware created by
`create_summarization_middleware` also named `"SummarizationMiddleware"`
(`deepagents/middleware/summarization.py::_DeepAgentsSummarizationMiddleware.name`).

Verified empirically: with a custom middleware at `("messages", 4)` while the
(default) fraction trigger for the same model is also crossed, the resulting
state contains exactly **one** summary message. If the two were stacked, the
default would have fired its own summary too, producing two.

The langchain base `SummarizationMiddleware` is used here (rather than the
deepagents wrapper, which additionally requires a `backend` for history
offload) because it matches the plan's compacting behavior exactly: on crossing
the trigger it rewrites `state["messages"]` with a summary `HumanMessage`
(`lc_source="summarization"`) and trims older messages to the `keep` window.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import SummarizationMiddleware
from langchain.agents.middleware.summarization import TokenCounter
from langchain.chat_models import BaseChatModel
from langchain_core.messages.utils import count_tokens_approximately

# Modest defaults tuned for a generic/cheap model: compact once a conversation
# gets long (token wise) and keep only a small trailing window of messages.
DEFAULT_TRIGGER: tuple[str, int] = ("tokens", 20000)
DEFAULT_KEEP: tuple[str, int] = ("messages", 6)

# Public alias names as seen by the model-facing tests/docs.
__all__ = ["DEFAULT_KEEP", "DEFAULT_TRIGGER", "build_summarization_middleware"]


def build_summarization_middleware(
    model: BaseChatModel,
    *,
    trigger: Any | None = None,
    keep: tuple[str, int] | None = None,
    token_counter: TokenCounter | None = None,
    summary_prompt: str | None = None,
    trim_tokens_to_summarize: int | None = None,
) -> SummarizationMiddleware:
    """Build a configured `SummarizationMiddleware` that overrides the default.

    Returns a langchain `SummarizationMiddleware` whose `.name` is
    `"SummarizationMiddleware"`, so passing it via `create_deep_agent(
    middleware=[this])` **replaces** the default summarization middleware (see
    module docstring for the verified replace-not-stack semantics).

    Args:
        model: Chat model used for conversation summarization.
        trigger: Trigger threshold; `("tokens", n)` | `("messages", n)` |
            `("fraction", f)` | a `TriggerClause` dict, or `None` to use
            `DEFAULT_TRIGGER` (`("tokens", 20000)`).
        keep: Post-summarization retention, `("messages", n)` | `("tokens", n)`
            | `("fraction", f)`; `None` keeps `DEFAULT_KEEP`
            (`("messages", 6)`).
        token_counter: Token-counting callable; `None` uses
            `count_tokens_approximately`.
        summary_prompt: Prompt template for summary generation; `None` uses the
            LangChain default.
        trim_tokens_to_summarize: Max tokens fed to the summary model; `None`
            uses the LangChain default (4000).

    Returns:
        A configured `SummarizationMiddleware` instance suitable for
        `create_deep_agent(middleware=[...])`.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "trigger": trigger if trigger is not None else DEFAULT_TRIGGER,
        "keep": keep if keep is not None else DEFAULT_KEEP,
        "token_counter": token_counter if token_counter is not None else count_tokens_approximately,
    }
    if summary_prompt is not None:
        kwargs["summary_prompt"] = summary_prompt
    if trim_tokens_to_summarize is not None:
        kwargs["trim_tokens_to_summarize"] = trim_tokens_to_summarize
    return SummarizationMiddleware(**kwargs)
