"""Summarization middleware — automatically compact conversation history.

Triggered when token usage exceeds a threshold (fraction of context window,
absolute token count, or message count).  Keeps a window of recent messages
and offloads older history.

Inspired by DeepAgents' ``middleware/summarization.py`` and
orchestrator's summarization patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.middleware.types import (
    AgentMiddleware,
    MiddlewareConfig,
    MiddlewareResult,
    ModelRequest,
    TriggerMode,
)

# ── Token counting helpers ───────────────────────────────────────────────

# Approximate tokens per character in various languages
TOKENS_PER_CHAR = 0.25
TOKENS_PER_WORD = 1.3
MAX_TOKENS_PER_MESSAGE_OVERHEAD = 4  # role + metadata overhead


def count_tokens_approximately(text: str) -> int:
    """Count tokens approximately for a text string.

    Uses a simple heuristic: ~0.25 tokens per character for mixed text,
    or ~1.3 tokens per word. Takes the average of both approaches.

    Args:
        text: Text to count tokens for.

    Returns:
        Approximate token count.
    """
    if not text:
        return 0
    char_based = len(text) * TOKENS_PER_CHAR
    word_based = len(text.split()) * TOKENS_PER_WORD
    return int((char_based + word_based) / 2)


def count_message_tokens(msg: dict[str, Any]) -> int:
    """Count tokens for a single message.

    Args:
        msg: Message dict (must have 'content' key).

    Returns:
        Approximate token count for this message.
    """
    content = msg.get("content", "")
    if isinstance(content, list):
        # Multi-part content (e.g. text + image)
        total = 0
        for part in content:
            if isinstance(part, dict):
                text = part.get("text", "")
                total += count_tokens_approximately(text)
            elif isinstance(part, str):
                total += count_tokens_approximately(part)
        return total + MAX_TOKENS_PER_MESSAGE_OVERHEAD
    return count_tokens_approximately(str(content)) + MAX_TOKENS_PER_MESSAGE_OVERHEAD


def count_total_tokens(messages: list[dict[str, Any]]) -> int:
    """Count total tokens for a list of messages.

    Args:
        messages: List of message dicts.

    Returns:
        Total approximate token count.
    """
    return sum(count_message_tokens(m) for m in messages)


# ── Media handling ───────────────────────────────────────────────────────

# Base64 image pattern: data:image/...;base64,<long string>
_BASE64_PATTERN = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]{100,}")


def _is_base64_content(content: str) -> bool:
    """Check if content contains base64-encoded media.

    Args:
        content: Text content to check.

    Returns:
        True if base64 media is present.
    """
    return bool(_BASE64_PATTERN.search(content))


def _strip_base64(content: str) -> str:
    """Remove base64-encoded media from content, replacing with a placeholder.

    Args:
        content: Text content to clean.

    Returns:
        Content with base64 media replaced by ``[image]``.
    """
    return _BASE64_PATTERN.sub("[image]", content)


# ── Summarization configuration ─────────────────────────────────────────


@dataclass
class SummarizationConfig:
    """Configuration for summarization behavior."""

    trigger_mode: TriggerMode = TriggerMode.FRACTION
    """How to determine when to summarize."""
    threshold: float = 0.75
    """Trigger threshold:
       - FRACTION: fraction of context window (0.0-1.0)
       - ABSOLUTE: absolute token count
       - MESSAGES: number of messages."""
    context_window: int = 128_000
    """Model context window size in tokens (used for FRACTION mode)."""
    keep_messages: int = 10
    """Number of most recent messages to keep untouched."""
    offload_history: bool = True
    """Whether to offload summarized history to backend storage."""
    model: str | None = None
    """Model to use for summarization (None = use same as agent)."""
    anthropic_caching: bool = True
    """Enable Anthropic prompt caching for the summary."""


# ── Summarization middleware ─────────────────────────────────────────────


class SummarizationMiddleware(AgentMiddleware[Any]):
    """Automatically compacts conversation history when token usage is high.

    When the conversation exceeds the configured threshold, the middleware
    summarizes older messages into a condensed summary and keeps only a
    window of recent messages.
    """

    name = "summarization"
    system_prompt = (
        "You have access to conversation history. "
        "When asked, provide a concise summary of the conversation."
    )

    def __init__(
        self,
        config: SummarizationConfig | None = None,
    ) -> None:
        super().__init__()
        self._config = config or SummarizationConfig()
        self._summary: str = ""

    @property
    def summary(self) -> str:
        """Get the current conversation summary."""
        return self._summary

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Check if summarization is needed before agent execution."""
        messages = state.get("messages", [])
        if not messages:
            return None

        # Anthropic caching: prepend cached summary system message
        if self._config.anthropic_caching and self._summary:
            cached_block = {
                "type": "text",
                "text": f"Previous conversation summary:\n{self._summary}",
                "cache_control": {"type": "ephemeral"},
            }
            state.setdefault("_system_blocks", []).append(cached_block)

        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """After agent execution, check if we need to summarize."""
        if not self._should_summarize(state):
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        # Keep the keep_messages window
        keep_window = self._config.keep_messages
        if len(messages) <= keep_window:
            return None

        to_summarize = messages[:-keep_window]
        keep = messages[-keep_window:]

        # Generate a summary of the older messages
        self._summary = self._generate_summary(to_summarize)

        # Offload to history if configured
        if self._config.offload_history:
            self._offload_history(to_summarize, config)

        # Update state
        state["messages"] = keep
        state["_summary"] = self._summary

        return MiddlewareResult(state={"messages": keep, "_summary": self._summary})

    def modify_request(self, request: ModelRequest) -> ModelRequest:
        """Inject summary into the system prompt."""
        if self._summary:
            summary_note = (
                f"\n\n[Previous conversation summary: {self._summary}]"
            )
            if request.system_prompt:
                request.system_prompt += summary_note
            else:
                request.system_prompt = summary_note.lstrip()
        return request

    # ── Internal helpers ──────────────────────────────────────────────

    def _should_summarize(self, state: dict[str, Any]) -> bool:
        """Determine if summarization should be triggered."""
        messages = state.get("messages", [])
        if not messages:
            return False

        match self._config.trigger_mode:
            case TriggerMode.MESSAGES:
                return len(messages) > self._config.threshold
            case TriggerMode.ABSOLUTE:
                total = count_total_tokens(messages)
                return total > self._config.threshold
            case TriggerMode.FRACTION:
                total = count_total_tokens(messages)
                fraction = total / self._config.context_window
                return fraction > self._config.threshold
            case _:
                return False

    def _generate_summary(self, messages: list[dict[str, Any]]) -> str:
        """Generate a text summary of the given messages.

        In a full implementation, this would call a model.  Here we produce
        a compact text representation.

        Args:
            messages: Messages to summarize.

        Returns:
            A text summary.
        """
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            # Strip base64 media before summarization
            if isinstance(content, str):
                content = _strip_base64(content)

            # Truncate long content
            content_str = str(content)
            if len(content_str) > 200:
                content_str = content_str[:200] + "..."

            parts.append(f"{role}: {content_str}")

        return "\n".join(parts)

    def _offload_history(
        self,
        messages: list[dict[str, Any]],
        config: MiddlewareConfig,
    ) -> None:
        """Offload summarized messages to backend storage.

        Args:
            messages: The messages being offloaded.
            config: Runtime configuration.
        """
        # In production, this would write to a file or store
        # Following DeepAgents' /conversation_history/ pattern
        if config.store and hasattr(config.store, "put"):
            try:
                thread_id = config.thread_id
                key = f"conversation_history/{thread_id}/summary"
                config.store.put(
                    key,
                    {
                        "messages": messages,
                        "summary": self._summary,
                    },
                )
            except Exception:
                pass  # Silently fail — summarization is best-effort


# ── Compact conversation tool ────────────────────────────────────────────


def compact_conversation(
    messages: list[dict[str, Any]],
    keep_last: int = 10,
) -> tuple[list[dict[str, Any]], str]:
    """Manually trigger conversation compaction.

    This is provided as a standalone function that can be exposed as a tool.

    Args:
        messages: Full message list.
        keep_last: Number of recent messages to keep.

    Returns:
        ``(compacted_messages, summary_text)``
    """
    if len(messages) <= keep_last:
        return messages, ""

    to_summarize = messages[:-keep_last]
    keep = messages[-keep_last:]

    # Build summary
    summary_parts: list[str] = []
    for msg in to_summarize:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str):
            content = _strip_base64(content)
        summary_parts.append(f"{role}: {str(content)[:200]}")

    summary = "\n".join(summary_parts)

    return keep, summary


__all__ = [
    "SummarizationConfig",
    "SummarizationMiddleware",
    "TriggerMode",
    "compact_conversation",
    "count_message_tokens",
    "count_tokens_approximately",
    "count_total_tokens",
]