"""Phase 0 smoke test: deep agent builds and invokes end-to-end with a fake model.

No network, no LLM API keys. A deterministic `BaseChatModel` subclass (Ruling
M1) serves as a scripted stand-in for a real model. The deep-agent harness binds
tools to the model, so the fake overrides `bind_tools` / `bind_tools_by_provider`
to no-op (return self), which stock `GenericFakeChatModel` does not.
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from deepagents import create_deep_agent

REPLY = "Xin chào! Tôi là một agent test, đây là câu trả lời scripted."


class ScriptedChatModel(BaseChatModel):
    """Minimal chat model that always replies with the scripted content.

    Overrides `_generate` to avoid any network/API call and `bind_tools` to
    accept whatever tools the harness binds (returning self).
    """

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
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=REPLY))])

    def bind_tools(
        self,
        tools: Sequence[BaseTool | type | dict[str, Any] | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable:
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


def test_hello_world():
    agent = create_deep_agent(model=ScriptedChatModel())

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Xin chào, bạn có tool gì?"}]}
    )

    last = result["messages"][-1]
    assert last.type == "ai"
    assert last.content == REPLY
