"""Phase 3: context management tests (deepagents 0.7.9).

Covers the three context-management techniques from plan 4.3:

1. **Summarization configuration** — a configured `SummarizationMiddleware`
   passed via `middleware=[...]` fires at a low tuned threshold and trims the
   message list to the `keep` window. We also prove the verified replace-not-stack
   semantics: with a model whose *default* fraction trigger is also crossed, only
   ONE summary pass occurs.
2. **Research subagent + context isolation** — the main agent delegates to a
   research subagent via the `task` tool; the subagent's internal working
   messages (raw `query_order` payload, system-prompt marker) never leak into
   the main conversation — only the compact final result returns.
3. **Tool-output limiter** — `LimitToolOutputMiddleware` truncates oversized
   tool results before they land in state (head/tail + marker).

All tests run with the shared deterministic fake model (Ruling M1: no network).
"""

from __future__ import annotations

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from deepagents import create_deep_agent
from deepagents.backends.state import StateBackend

from src.agent.context.limit_output import (
    DEFAULT_TRUNCATION_MARKER,
    LimitToolOutputMiddleware,
)
from src.agent.context.subagents import SUBAGENT_SYSTEM_MARKER

from tests.fake_model import ScriptedChatModel


def _system_text(model: ScriptedChatModel) -> str:
    for m in model.last_messages:
        if m.type == "system":
            return str(m.content)
    return ""


# --------------------------------------------------------------------------- #
# 1. Summarization configuration + override semantics                         #
# --------------------------------------------------------------------------- #
def test_custom_low_threshold_compacts_and_trims_to_keep_window():
    # No model profile -> the *default* trigger is ("tokens", 170000), far too
    # high to fire on a short fake conversation. A custom ("messages", 4)
    # threshold therefore proves the override config actually takes effect.
    model = ScriptedChatModel(reply="final-answer")
    mw = SummarizationMiddleware(model=model, trigger=("messages", 4), keep=("messages", 2))
    agent = create_deep_agent(
        model=model,
        middleware=[mw],
        backend=StateBackend(),
    )

    result = agent.invoke(
        {
            "messages": [
                HumanMessage(content="q1"),
                AIMessage(content="a1"),
                HumanMessage(content="q2"),
                AIMessage(content="a2"),
                HumanMessage(content="q3"),  # 5 messages -> crosses trigger 4
            ]
        }
    )

    summaries = [m for m in result["messages"] if m.additional_kwargs.get("lc_source") == "summarization"]
    assert len(summaries) == 1, "custom low threshold must fire exactly one summarization"

    remaining = result["messages"]
    # state now has: summary HumanMessage + the keep window + the final AI answer
    assert summaries[0].type == "human"
    # token budget untouched: q1/a1 were trimmed; q2 -> a2 kept (keep=2 messages)
    assert all("q1" not in str(m.content) for m in remaining if m.type == "human")
    assert len([m for m in remaining if m.type == "human"]) == 2  # summary + q3


def test_custom_middleware_replaces_default_not_stacked():
    # Give the model a small profile -> the *default* summarization trigger is
    # fraction-based: 0.85 * max_input_tokens = 85 tokens, which a 6-message
    # conversation comfortably crosses. If the custom middleware were STACKED on
    # top of the default, BOTH would fire -> 2 summary messages. Replacement by
    # name yields exactly 1.
    model = ScriptedChatModel(reply="final-answer")
    model.profile = {"max_input_tokens": 100}

    custom = SummarizationMiddleware(model=model, trigger=("messages", 4), keep=("messages", 2))
    agent = create_deep_agent(
        model=model,
        middleware=[custom],
        backend=StateBackend(),
    )

    result = agent.invoke(
        {
            "messages": [
                HumanMessage(content="Question one: tell me the status of the delivery of order one."),
                AIMessage(content="Answer one: the first order is still being processed at the warehouse."),
                HumanMessage(content="Question two: and what about the second order that was placed later today?"),
                AIMessage(content="Answer two: the second order has already been shipped out yesterday morning."),
                HumanMessage(content="Question three: could you also look into the third order for me right now?"),
            ]
        }
    )

    summaries = [m for m in result["messages"] if m.additional_kwargs.get("lc_source") == "summarization"]
    assert len(summaries) == 1, "default + custom must NOT stack into two summaries"


# --------------------------------------------------------------------------- #
# 2. Research subagent + context isolation                                    #
# --------------------------------------------------------------------------- #
class ResearchDriver(ScriptedChatModel):
    """Shared fake model that distinguishes main-agent vs research-subagent
    context by the subagent's system-prompt marker, drives a task -> tool loop,
    and keeps the subagent's raw payload internal."""

    def _next_message(self) -> AIMessage:
        system = _system_text(self)
        in_sub = SUBAGENT_SYSTEM_MARKER in system
        tool_res = None
        for m in reversed(self.last_messages):
            if m.type == "tool":
                tool_res = str(m.content)

        if in_sub:
            # Research subagent: lookup the order, then emit ONLY a compact result.
            if tool_res is None:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "query_order",
                            "args": {"order_id": "A-1001"},
                            "id": "sub_c1",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(content="RESEARCH-COMPLETE")

        # Main agent: delegate via the built-in task tool, then summarize.
        if tool_res is None:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {"subagent_type": "research", "description": "research A-1001"},
                        "id": "main_c1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="FINAL-RESEARCH-ANSWER: " + tool_res)


def test_research_subagent_context_isolation():
    from src.agent.context.subagents import build_research_subagent

    model = ResearchDriver()
    agent = create_deep_agent(
        model=model,
        subagents=[build_research_subagent()],
        backend=StateBackend(),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "research A-1001"}]})
    messages = result["messages"]

    # The main answer reflects the subagent's result.
    last = messages[-1]
    assert last.type == "ai"
    assert "FINAL-RESEARCH-ANSWER: RESEARCH-COMPLETE" in str(last.content)

    # Exactly one tool message in the MAIN conversation, and it is the task tool.
    tool_msgs = [m for m in messages if m.type == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].name == "task"
    assert "RESEARCH-COMPLETE" in str(tool_msgs[0].content)

    # --- Context isolation proof ---
    # 1. The research subagent's system-prompt marker never leaked to the main.
    assert SUBAGENT_SYSTEM_MARKER not in str(messages)
    # 2. The raw query_order payload, which existed ONLY in the subagent's
    #    internal working context (the main agent has no query_order tool), did
    #    not reach the main conversation.
    assert all("Ergonomic Keyboard" not in str(m.content) for m in messages)
    assert all("$89" not in str(m.content) for m in messages)


# --------------------------------------------------------------------------- #
# 3. Tool-output limiter                                                      #
# --------------------------------------------------------------------------- #
@tool
def _big_payload(n: int) -> str:
    """Return a deterministic oversized payload."""
    return "Y" * n


class BigToolDriver(ScriptedChatModel):
    """Calls _big_payload, then echoes whatever tool result it saw."""

    def __init__(self, n: int):
        super().__init__()
        self._n = n
        self._turn = 0

    def _next_message(self) -> AIMessage:
        self._turn += 1
        if self._turn == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "_big_payload", "args": {"n": self._n}, "id": "big1", "type": "tool_call"}
                ],
            )
        for m in reversed(self.last_messages):
            if m.type == "tool":
                return AIMessage(content="ECHO:" + str(m.content))
        return AIMessage(content="no tool")


def test_tool_output_limiter_truncates_oversized_result():
    model = BigToolDriver(n=100)
    agent = create_deep_agent(
        model=model,
        tools=[_big_payload],
        middleware=[LimitToolOutputMiddleware(max_length=20)],
        backend=StateBackend(),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "go"}]})

    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    assert len(tool_msgs) == 1
    content = str(tool_msgs[0].content)
    # Truncated to 20 chars (head) + the default marker; full payload absent.
    assert len(content) == 20 + len(DEFAULT_TRUNCATION_MARKER)
    assert "Y" * 20 in content
    assert DEFAULT_TRUNCATION_MARKER in content
    assert "Y" * 40 not in content, "full payload must not enter state"


def test_tool_output_limiter_tail_strategy_and_short_results_untouched():
    model = BigToolDriver(n=100)
    agent = create_deep_agent(
        model=model,
        tools=[_big_payload],
        middleware=[LimitToolOutputMiddleware(max_length=20, strategy="tail", truncation_marker="[CUT]")],
        backend=StateBackend(),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "go"}]})
    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    content = str(tool_msgs[0].content)
    assert content.startswith("[CUT]")
    assert content.endswith("Y" * 20)
    assert "Y" * 40 not in content


def test_tool_output_limiter_leaves_small_results_untouched():
    model = BigToolDriver(n=5)
    agent = create_deep_agent(
        model=model,
        tools=[_big_payload],
        middleware=[LimitToolOutputMiddleware(max_length=20)],
        backend=StateBackend(),
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "go"}]})
    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    assert str(tool_msgs[0].content) == "Y" * 5
