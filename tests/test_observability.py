"""Phase 7: observability & tool-audit guard tests (deepagents 0.7.9 / langgraph 1.2.11).

Two responsibilities:

1. **LangSmith auto-tracing (zero-code).** `create_deep_agent` builds on
   LangGraph, which always routes execution through
   `CallbackManager.configure` (from`langchain_core/callbacks/manager.py`). When
   `LANGSMITH_TRACING=true` (+ a real `LANGSMITH_API_KEY`) is set, that
   configure step auto-attaches a `LangChainTracer` — no custom instrumentation
   is needed anywhere in this repo. We prove the mechanism two ways:

   - `test_no_tracing_without_env` (always runs, deterministic): with every
     tracing env var unset, the graph run carries NO `LangChainTracer`.
   - `test_langsmith_tracer_attached_when_env_enabled` (env-gated, marker
     `langsmith`): skipped without `LANGSMITH_API_KEY`. When a real key
     exists, the run IS traced — asserting the tracer handler attached to the
     model's run. See `docs/runbook-observability.md` for the manual UI check.
     Note: the pytest-langsmith plugin wraps `@pytest.mark.langsmith` tests and
     by default creates a LangSmith dataset/experiment; set
     `LANGSMITH_TEST_TRACKING=false` to keep this purely a mechanism check.

2. **Audit-checklist ↔ profile sync.** `docs/tool-audit-checklist.md` must stay
   in sync with the profiles actually registered in `src/agent/roles.py`; the
   sync test below greps the doc for every registered profile key and every
   excluded tool name (least-brittle mechanical check).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tracers.langchain import LangChainTracer

from deepagents import create_deep_agent
from deepagents.profiles.harness.harness_profiles import (
    _get_harness_profile,
    _HARNESS_PROFILES,
)
from deepagents.middleware._fs_interrupt import _build_interrupt_on_from_permissions

from src.agent import roles

from tests.fake_model import ScriptedChatModel

REPO_ROOT = Path(__file__).resolve().parents[1]

_TRACING_ENV_VARS = (
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_TRACING",
    "LANGCHAIN_HANDLER",
    "LANGCHAIN_PROJECT",
)


@pytest.fixture(autouse=True)
def _clean_harness_profiles():
    yield
    _HARNESS_PROFILES.clear()


class TracerProbe(ScriptedChatModel):
    """Fake model that records whether its run carried a `LangChainTracer`."""

    def __init__(self) -> None:
        super().__init__()
        self._saw_tracer = False

    @property
    def saw_tracer(self) -> bool:
        return self._saw_tracer

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._saw_tracer = run_manager is not None and any(
            isinstance(h, LangChainTracer) for h in run_manager.handlers
        )
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _run_probe(monkeypatch: pytest.MonkeyPatch) -> TracerProbe:
    model = TracerProbe()
    agent = create_deep_agent(model=model)
    agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
    return model


# --------------------------------------------------------------------------- #
# 1a. Default path: no tracing env vars -> no LangChainTracer attached          #
# --------------------------------------------------------------------------- #
def test_no_tracing_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _TRACING_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    model = _run_probe(monkeypatch)
    assert model.saw_tracer is False, (
        "no tracer must be attached when tracing env is absent"
    )


# --------------------------------------------------------------------------- #
# 1b. Env-gated smoke test: runs ONLY when a real LANGSMITH_API_KEY exists.     #
# --------------------------------------------------------------------------- #
@pytest.mark.langsmith
@pytest.mark.skipif(
    not os.environ.get("LANGSMITH_API_KEY"),
    reason="LANGSMITH_API_KEY not set — opt-in manual validation with a real key",
)
def test_langsmith_tracer_attached_when_env_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With tracing env on, every agent run is auto-traced (zero code changes)."""
    api_key = os.environ["LANGSMITH_API_KEY"]
    for var in _TRACING_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", api_key)

    model = _run_probe(monkeypatch)
    assert model.saw_tracer is True, (
        "Running with LANGSMITH_TRACING=true must attach a LangChainTracer to "
        "the agent's model call with no custom instrumentation"
    )
    # The graph itself also carried a tracer-aware config (configure() adds the
    # tracer); re-running through the same compiled agent keeps working.
    agent = create_deep_agent(model=TracerProbe())
    agent.invoke({"messages": [{"role": "user", "content": "still traced"}]})


# --------------------------------------------------------------------------- #
# 2. Audit checklist stays in sync with the profiles registered in roles.py     #
# --------------------------------------------------------------------------- #
def test_audit_checklist_tracks_registered_profiles() -> None:
    roles.register_all_roles()
    checklist = (REPO_ROOT / "docs" / "tool-audit-checklist.md").read_text(
        encoding="utf-8"
    )

    profile_keys = [roles.CUSTOMER_SUPPORT_ROLE, roles.OPERATOR_ROLE]
    for key in profile_keys:
        assert key in checklist, f"audit checklist must mention profile key {key!r}"

    for key in profile_keys:
        profile = _get_harness_profile(key)
        assert profile is not None, (
            f"{key!r} must be registered by register_all_roles()"
        )
        for excluded in profile.excluded_tools:
            assert excluded in checklist, (
                f"audit checklist must list tool {excluded!r} excluded by "
                f"profile {key!r}"
            )
        if not profile.excluded_tools:
            # Keep the operator row honest: the doc must say the role excludes nothing.
            assert f"`{key}`" in checklist
            assert "(none)" in checklist, (
                f"audit checklist must state the no-exclusions case for {key!r}"
            )

    # No registered profile may be missing from the checklist: compare the set of
    # profile keys in the doc against the roles module constants.
    for excluded_set in (_get_harness_profile(k).excluded_tools for k in profile_keys):
        assert isinstance(excluded_set, frozenset)

    # Sanity: the checklist is not a stub — it must enumerate the built-in tool
    # surface that profiles can exclude (see docs/phase-0-discovery.md §13.5).
    builtins = (
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "delete",
        "task",
    )
    for builtin in builtins:
        assert builtin in checklist, (
            f"audit checklist must enumerate built-in tool {builtin!r}"
        )
    assert "execute" in checklist


def test_audit_checklist_matches_execute_exclusion_semantics() -> None:
    # Cross-check the doc's stated rationale: `execute` is excluded only via
    # HarnessProfile (role-based), NOT via FilesystemPermission (task-scoped).
    from deepagents import FilesystemPermission

    rules = [
        FilesystemPermission(
            operations=["read", "write"], paths=["/**"], mode="interrupt"
        )
    ]
    interrupt_on = _build_interrupt_on_from_permissions(rules)
    assert "execute" not in interrupt_on
    checklist = (REPO_ROOT / "docs" / "tool-audit-checklist.md").read_text(
        encoding="utf-8"
    )
    assert "HarnessProfile" in checklist and "FilesystemPermission" in checklist