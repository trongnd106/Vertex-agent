"""Tool-result limiting middleware (plan 4.3 "Tool result truncation").

Large tool outputs (DB query dumps, crawled pages, verbose file reads) can blow
up the message list and the token budget. This middleware caps each synchronous
tool result to a configurable character limit before it lands in state.

## Hook used (VERIFIED, langchain 1.3.18)

`AgentMiddleware` does NOT expose an `on_tool_end` hook. The tool-execution
interceptor is `wrap_tool_call` (sync) / `awrap_tool_call` (async) in
`langchain/agents/middleware/types.py` (see `AgentMiddleware.wrap_tool_call`,
line ~674). It receives a `ToolCallRequest` and a `handler` callable; calling
`handler(request)` executes the tool and returns a `ToolMessage` (or a
`Command`). The limiter calls the handler, then truncates the returned
`ToolMessage.content` when it exceeds the configured max length.

Only `ToolMessage` results are truncated. Tool calls that return a `Command`
(e.g. the built-in `task` subagent tool, which replies with a `Command` whose
`update["messages"]` carries a fresh `ToolMessage`) are passed through intact —
the subagent already returns a compact summary, and the deepagent
`SubAgentMiddleware` produces the final `ToolMessage`.

This is a synchronous-only interceptor. When the agent is driven through
`ainvoke`/`astream` the harness falls back to `awrap_tool_call`, which this
class does not override, so async runs are intentionally unaffected.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

DEFAULT_MAX_LENGTH = 4000
DEFAULT_TRUNCATION_MARKER = "\n...[output truncated]"

__all__ = [
    "DEFAULT_MAX_LENGTH",
    "DEFAULT_TRUNCATION_MARKER",
    "LimitToolOutputMiddleware",
]


class LimitToolOutputMiddleware(AgentMiddleware):
    """Truncate oversized tool results to a max length before entering state.

    Args:
        max_length: Maximum character length for a single tool result.
            Longer string results are clipped (head kept) and suffixed with
            `truncation_marker`. Defaults to `DEFAULT_MAX_LENGTH` (4000).
        truncation_marker: Marker appended to a truncated result so downstream
            models/tests can detect that content was dropped.
        strategy: `"head"` keeps the beginning of the result (default);
            `"tail"` keeps the end. Reserved for head/tail choice.
    """

    def __init__(
        self,
        max_length: int = DEFAULT_MAX_LENGTH,
        *,
        truncation_marker: str = DEFAULT_TRUNCATION_MARKER,
        strategy: str = "head",
    ) -> None:
        if max_length <= 0:
            raise ValueError("max_length must be a positive integer")
        if strategy not in {"head", "tail"}:
            raise ValueError("strategy must be 'head' or 'tail'")
        self._max_length = max_length
        self._marker = truncation_marker
        self._strategy = strategy

    def _truncate_text(self, text: str) -> str:
        """Trim a string payload to `max_length` (head or tail) + marker."""
        if len(text) <= self._max_length:
            return text
        if self._strategy == "head":
            return text[: self._max_length] + self._marker
        return self._marker + text[-self._max_length :]

    def wrap_tool_call(
        self,
        request: Any,
        handler: Any,
    ) -> Any:
        """Run the tool, then truncate any oversized `ToolMessage` result."""
        result = handler(request)
        if isinstance(result, ToolMessage):
            content = result.content
            if isinstance(content, str):
                truncated = self._truncate_text(content)
                if truncated != content:
                    result = result.model_copy(update={"content": truncated})
        return result
