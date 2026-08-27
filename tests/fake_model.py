"""Shared deterministic fake chat models for tests (Ruling M1: no network, no keys).

Extracted from `tests/test_hello_world.py` (Phase 0 smoke test) and extended with
a scripted tool-call capability so later tasks can exercise the deep-agent tool
loop without a real LLM. Stock `GenericFakeChatModel` cannot no-op `bind_tools`;
these overrides return `self` so the harness binds whatever tools it wants.
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool


def _tool_name(tool: BaseTool | type | dict[str, Any] | Any) -> str | None:
    """Extract a tool name from whatever shape the harness passes to bind_tools."""
    if isinstance(tool, dict):
        name = tool.get("name")
        return name if isinstance(name, str) else None
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


class ScriptedChatModel(BaseChatModel):
    """Minimal chat model: replays a script of AIMessages, else a fixed reply.

    `script` is a FIFO list of `BaseMessage`s returned one per `_generate` call
    (e.g. an `AIMessage` carrying `tool_calls`, then the final answer). When the
    script is exhausted, every further call returns an `AIMessage` with `reply`.

    After each call, `last_messages` holds the full message list the harness
    passed in (inspect it to capture the system prompt, tool results, etc.).
    `bound_tools` accumulates the names of tools bound via `bind_tools`.
    """

    def __init__(self, script: Sequence[BaseMessage] | None = None, reply: str = "Final reply."):
        super().__init__()
        self._script = list(script or [])
        self._reply = reply
        # Pydantic: `BaseChatModel` validates assignment, so mutable bookkeeping
        # lives on underscore-prefixed (ignored) attrs behind public properties.
        self._last_messages: list[BaseMessage] = []
        self._bound_tools: list[str] = []

    @property
    def last_messages(self) -> list[BaseMessage]:
        """Full message list passed to the most recent `_generate` call."""
        return self._last_messages

    @property
    def bound_tools(self) -> list[str]:
        """Tool names bound via `bind_tools` (accumulated across calls)."""
        return self._bound_tools

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Sequence[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._last_messages = list(messages)
        return ChatResult(generations=[ChatGeneration(message=self._next_message())])

    def _next_message(self) -> BaseMessage:
        """Hook for subclasses; base replays the script, then falls back to `reply`."""
        if self._script:
            return self._script.pop(0)
        return AIMessage(content=self._reply)

    def bind_tools(
        self,
        tools: Sequence[BaseTool | type | dict[str, Any] | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable:
        self._bound_tools.extend(name for name in (_tool_name(t) for t in tools) if name)
        return self

    def bind_tools_by_provider(
        self,
        provider: str,
        *,
        tools: Sequence[BaseTool | type | dict[str, Any] | Any],
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable:
        return self


__all__ = ["ScriptedChatModel"]