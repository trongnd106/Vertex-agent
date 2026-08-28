"""Phase 0 smoke test: deep agent builds and invokes end-to-end with a fake model.

No network, no LLM API keys (Ruling M1). Uses the shared fake chat model from
`tests.fake_model`; the deep-agent harness binds tools to the model, so the fake
overrides `bind_tools` / `bind_tools_by_provider` to no-op (return self).

Since Task 5, construction goes through the central `build_agent` factory
(store, per-user context, memory backend, custom tools) instead of calling
`create_deep_agent` directly; the assertions below are identical to the Phase 0
smoke test.
"""

from src.agent.graph import build_agent
from tests.fake_model import ScriptedChatModel

REPLY = "Xin chào! Tôi là một agent test, đây là câu trả lời scripted."


def test_hello_world():
    agent = build_agent(model=ScriptedChatModel(reply=REPLY))

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Xin chào, bạn có tool gì?"}]}
    )

    last = result["messages"][-1]
    assert last.type == "ai"
    assert last.content == REPLY
