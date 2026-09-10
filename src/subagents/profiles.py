"""Subagent profiles, resource management, and lifecycle control.

Provides:
- ``SubagentProfile`` — reusable subagent configuration templates
- ``GeneralPurposeSubagentProfile`` — default profile
- ``ResourceManager`` — resource limits, token budgets, orphan detection
- ``LifecycleManager`` — subagent lifecycle (create → execute → cleanup)
- Profile inheritance: child profiles inherit from parent
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.subagents.sync import SubAgent, SubAgentRegistry
from src.tools.filesystem import ToolResult
from src.tools.registry import ToolRegistry


# ── Subagent profiles ───────────────────────────────────────────────────


@dataclass
class SubagentProfile:
    """Reusable subagent configuration template.

    Profiles define defaults that can be inherited and overridden.
    """

    name: str
    description: str = ""
    system_prompt: str = "You are a helpful assistant."
    model: str = "default"
    tool_visibility: list[str] = field(default_factory=lambda: ["*"])
    max_subagents: int = 5
    max_concurrent_async: int = 3
    token_budget: int = 4000
    timeout: float = 60.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def create_subagent(self, registry: ToolRegistry | None = None) -> SubAgent:
        """Create a ``SubAgent`` from this profile.

        Args:
            registry: Optional tool registry to attach.

        Returns:
            A ``SubAgent`` spec configured from this profile.
        """
        tools = []
        if registry:
            if "*" in self.tool_visibility:
                tools = registry.list_tools()
            else:
                for pattern in self.tool_visibility:
                    if pattern == "*":
                        tools = registry.list_tools()
                        break
                    tools.extend(registry.search(pattern))

        return SubAgent(
            name=self.name,
            description=self.description,
            system_prompt=self.system_prompt,
            model=self.model,
            tools=tools,
        )

    def inherit(self, overrides: dict[str, Any]) -> SubagentProfile:
        """Create a new profile inheriting from this one with overrides.

        Args:
            overrides: Fields to override.

        Returns:
            A new ``SubagentProfile``.
        """
        kwargs = {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "model": self.model,
            "tool_visibility": list(self.tool_visibility),
            "max_subagents": self.max_subagents,
            "max_concurrent_async": self.max_concurrent_async,
            "token_budget": self.token_budget,
            "timeout": self.timeout,
            "metadata": dict(self.metadata),
        }
        kwargs.update(overrides)
        return SubagentProfile(**kwargs)


def GeneralPurposeSubagentProfile(
    name: str = "general_purpose",
    **overrides: Any,
) -> SubagentProfile:
    """Create a general-purpose subagent profile.

    This is the default profile for generic subagents.

    Args:
        name: Profile name.
        **overrides: Override any default field.

    Returns:
        Configured ``SubagentProfile``.
    """
    profile = SubagentProfile(
        name=name,
        description="A general-purpose assistant for any task.",
        system_prompt="You are a general-purpose AI assistant.",
        model="default",
        tool_visibility=["*"],
        max_subagents=5,
        max_concurrent_async=3,
        token_budget=4000,
        timeout=60.0,
    )
    if overrides:
        profile = profile.inherit(overrides)
    return profile


# ── Resource manager ────────────────────────────────────────────────────


class ResourceExhaustedError(Exception):
    """Raised when a resource limit is exceeded."""
    pass


class ResourceManager:
    """Manages resource allocation for subagents.

    Tracks and enforces:
    - Max subagents per turn
    - Max concurrent async subagents
    - Token budget per subagent
    - Timeout per subagent execution
    """

    def __init__(
        self,
        default_profile: SubagentProfile | None = None,
    ) -> None:
        self._profile = default_profile or GeneralPurposeSubagentProfile()
        self._active_subagents: dict[str, float] = {}
        """subagent_id -> start_time"""
        self._active_async: dict[str, float] = {}
        self._token_usage: dict[str, int] = {}
        self._lock = threading.Lock()
        self._counter = 0

    @property
    def profile(self) -> SubagentProfile:
        return self._profile

    def set_profile(self, profile: SubagentProfile) -> None:
        self._profile = profile

    def acquire_slot(self, subagent_name: str) -> str:
        """Acquire a subagent execution slot.

        Args:
            subagent_name: Name for diagnostic purposes.

        Returns:
            A unique slot ID.

        Raises:
            ResourceExhaustedError: If max subagents exceeded.
        """
        with self._lock:
            self._counter += 1
            slot_id = f"{subagent_name}_{self._counter}_{int(time.time())}"

            current = len(self._active_subagents)
            if current >= self._profile.max_subagents:
                raise ResourceExhaustedError(
                    f"Max subagents per turn exceeded ({self._profile.max_subagents}). "
                    f"Active: {current}"
                )

            self._active_subagents[slot_id] = time.time()
            return slot_id

    def release_slot(self, slot_id: str) -> None:
        """Release a subagent slot."""
        with self._lock:
            self._active_subagents.pop(slot_id, None)
            self._token_usage.pop(slot_id, None)

    def acquire_async_slot(self, subagent_name: str) -> str:
        """Acquire a slot for an async subagent.

        Raises:
            ResourceExhaustedError: If max concurrent async exceeded.
        """
        with self._lock:
            self._counter += 1
            slot_id = f"async_{subagent_name}_{self._counter}"

            current = len(self._active_async)
            if current >= self._profile.max_concurrent_async:
                raise ResourceExhaustedError(
                    f"Max concurrent async subagents exceeded ({self._profile.max_concurrent_async}). "
                    f"Active: {current}"
                )

            self._active_async[slot_id] = time.time()
            return slot_id

    def release_async_slot(self, slot_id: str) -> None:
        with self._lock:
            self._active_async.pop(slot_id, None)

    def check_token_budget(self, slot_id: str, additional: int = 0) -> bool:
        """Check if the token budget would be exceeded.

        Args:
            slot_id: The subagent slot.
            additional: Additional tokens to account for.

        Returns:
            True if within budget.
        """
        with self._lock:
            used = self._token_usage.get(slot_id, 0)
            return (used + additional) <= self._profile.token_budget

    def record_token_usage(self, slot_id: str, tokens: int) -> None:
        with self._lock:
            self._token_usage[slot_id] = self._token_usage.get(slot_id, 0) + tokens

    def active_count(self) -> int:
        with self._lock:
            return len(self._active_subagents)

    def async_active_count(self) -> int:
        with self._lock:
            return len(self._active_async)

    def clean_orphans(self, max_age_seconds: float = 300.0) -> int:
        """Remove orphaned subagent slots.

        Args:
            max_age_seconds: Max age before considering orphaned.

        Returns:
            Number of orphaned slots cleaned.
        """
        now = time.time()
        count = 0
        with self._lock:
            for slot_id, start in list(self._active_subagents.items()):
                if (now - start) > max_age_seconds:
                    del self._active_subagents[slot_id]
                    self._token_usage.pop(slot_id, None)
                    count += 1
            for slot_id, start in list(self._active_async.items()):
                if (now - start) > max_age_seconds:
                    del self._active_async[slot_id]
                    count += 1
        return count


# ── Lifecycle manager ───────────────────────────────────────────────────


class SubagentState(Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass
class SubagentLifecycle:
    """Tracks lifecycle state for a single subagent instance."""

    id: str = ""
    profile_name: str = ""
    state: SubagentState = SubagentState.CREATED
    created_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    result: ToolResult | None = None
    error: str = ""


class LifecycleManager:
    """Manages the full lifecycle of subagent instances.

    Handles creation → execution → result collection → cleanup.
    Supports force-terminate on timeout.
    """

    def __init__(
        self,
        resource_manager: ResourceManager | None = None,
    ) -> None:
        self._resource_manager = resource_manager or ResourceManager()
        self._instances: dict[str, SubagentLifecycle] = {}
        self._lock = threading.Lock()
        self._counter = 0

    @property
    def resource_manager(self) -> ResourceManager:
        return self._resource_manager

    def create(self, profile_name: str) -> SubagentLifecycle:
        """Create a new subagent lifecycle instance.

        Returns:
            ``SubagentLifecycle`` in CREATED state.
        """
        with self._lock:
            self._counter += 1
            instance = SubagentLifecycle(
                id=f"sa_{self._counter}_{int(time.time())}",
                profile_name=profile_name,
                state=SubagentState.CREATED,
                created_at=time.time(),
            )
            self._instances[instance.id] = instance
            return instance

    def start(self, instance_id: str) -> SubagentLifecycle | None:
        """Transition to RUNNING state.

        Returns:
            The updated lifecycle, or None if not found.
        """
        with self._lock:
            instance = self._instances.get(instance_id)
            if instance is None:
                return None
            instance.state = SubagentState.RUNNING
            instance.started_at = time.time()
            return instance

    def complete(self, instance_id: str, result: ToolResult) -> SubagentLifecycle | None:
        """Mark as COMPLETED.

        Returns:
            The updated lifecycle, or None.
        """
        with self._lock:
            instance = self._instances.get(instance_id)
            if instance is None:
                return None
            instance.state = SubagentState.COMPLETED if result.success else SubagentState.FAILED
            instance.completed_at = time.time()
            instance.result = result
            if not result.success:
                instance.error = result.error
            return instance

    def timeout(self, instance_id: str) -> SubagentLifecycle | None:
        """Force-terminate due to timeout."""
        with self._lock:
            instance = self._instances.get(instance_id)
            if instance is None:
                return None
            instance.state = SubagentState.TIMED_OUT
            instance.completed_at = time.time()
            instance.error = f"Timed out after {self._resource_manager.profile.timeout}s"
            return instance

    def cancel(self, instance_id: str) -> SubagentLifecycle | None:
        """Cancel a subagent."""
        with self._lock:
            instance = self._instances.get(instance_id)
            if instance is None:
                return None
            instance.state = SubagentState.CANCELLED
            instance.completed_at = time.time()
            return instance

    def get(self, instance_id: str) -> SubagentLifecycle | None:
        with self._lock:
            instance = self._instances.get(instance_id)
            return instance

    def list_active(self) -> list[SubagentLifecycle]:
        with self._lock:
            return [
                inst for inst in self._instances.values()
                if inst.state in (SubagentState.CREATED, SubagentState.RUNNING)
            ]

    def list_all(self) -> list[SubagentLifecycle]:
        with self._lock:
            return list(self._instances.values())

    def cleanup(self, max_age_seconds: float = 3600) -> int:
        """Remove old completed/failed/timed-out instances.

        Returns:
            Number of instances cleaned up.
        """
        now = time.time()
        count = 0
        with self._lock:
            for inst_id, inst in list(self._instances.items()):
                if inst.state in (
                    SubagentState.COMPLETED,
                    SubagentState.FAILED,
                    SubagentState.TIMED_OUT,
                    SubagentState.CANCELLED,
                ):
                    if inst.completed_at and (now - inst.completed_at) > max_age_seconds:
                        del self._instances[inst_id]
                        count += 1
        return count


__all__ = [
    "GeneralPurposeSubagentProfile",
    "LifecycleManager",
    "ResourceExhaustedError",
    "ResourceManager",
    "SubagentLifecycle",
    "SubagentProfile",
    "SubagentState",
]