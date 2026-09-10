"""Conditional and dynamic routing for agent graphs.

Provides:
- ``RouteCondition`` — declarative routing condition
- ``ConditionalRouter`` — routes to nodes based on state evaluation
- ``PathMap`` — maps route outputs to target node names
- ``DynamicRouter`` — runtime-determined routing via Send/Command
- ``MapReduceRouter`` — fan-out to parallel nodes, then aggregate
- ``BranchSpec`` — path function + path map trigger targets
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from src.graph.types import Command
from src.tools.filesystem import ToolResult


# ── Route condition ───────────────────────────────────────────────────


RouterFn = Callable[[dict[str, Any]], str]
"""State -> target node name."""

SendFn = Callable[[dict[str, Any]], Any]
"""State -> Send or Command."""


@dataclass
class RouteCondition:
    """A single routing condition.

    Attributes:
        name: Unique condition name.
        description: Human-readable description.
        route_fn: Function that takes state and returns a target node name,
                  or raises ``NoRouteMatch``.
        priority: Higher priority conditions evaluated first.
    """

    name: str = ""
    description: str = ""
    route_fn: RouterFn | None = None
    priority: int = 0


class NoRouteMatch(Exception):
    """Raised when no routing condition matches the current state."""
    pass


# ── Conditional router ────────────────────────────────────────────────


@dataclass
class PathMap:
    """Maps route function outputs to node names.

    Example:
        path_map = PathMap(
            routes={"weather": "weather_node", "news": "news_node"},
            default="fallback_node",
        )
    """

    routes: dict[str, str] = field(default_factory=dict)
    default: str = "__end__"

    def resolve(self, route_result: str) -> str:
        """Resolve a route result to a target node name.

        Args:
            route_result: The output from a route function.

        Returns:
            Target node name, or the default if not found.
        """
        return self.routes.get(route_result, self.default)


class ConditionalRouter:
    """Evaluates state against multiple conditions and routes to the
    first matching target node.

    Useful for complex branching logic where multiple conditions
    are checked in priority order.
    """

    def __init__(self, conditions: list[RouteCondition] | None = None) -> None:
        self._conditions = sorted(
            conditions or [],
            key=lambda c: -c.priority,
        )

    def add_condition(self, condition: RouteCondition) -> None:
        self._conditions.append(condition)
        self._conditions.sort(key=lambda c: -c.priority)

    def route(self, state: dict[str, Any]) -> str:
        """Evaluate conditions and return the target node name.

        Args:
            state: Current agent state.

        Returns:
            Target node name.

        Raises:
            NoRouteMatch: If no condition matches.
        """
        for condition in self._conditions:
            if condition.route_fn is None:
                continue
            try:
                result = condition.route_fn(state)
                if result:
                    return result
            except NoRouteMatch:
                continue
        raise NoRouteMatch(
            f"No routing condition matched for state keys: {list(state.keys())}"
        )

    def route_with_default(
        self, state: dict[str, Any], default: str = "__end__"
    ) -> str:
        """Route with fallback default."""
        try:
            return self.route(state)
        except NoRouteMatch:
            return default

    @property
    def conditions(self) -> list[RouteCondition]:
        return list(self._conditions)


# ── Dynamic router ────────────────────────────────────────────────────


@dataclass
class DynamicRoute:
    """A single dynamic route definition for runtime dispatch."""

    name: str
    description: str = ""
    target: str = ""
    condition_fn: Callable[[dict[str, Any]], bool] | None = None
    """Optional predicate; if None the route is always available."""


class DynamicRouter:
    """Routes to nodes at runtime based on state content.

    Supports ``Send`` and ``Command`` patterns for dynamic graph
    topology changes.
    """

    def __init__(self, routes: list[DynamicRoute] | None = None) -> None:
        self._routes = routes or []

    def add_route(self, route: DynamicRoute) -> None:
        self._routes.append(route)

    def find_target(self, state: dict[str, Any]) -> DynamicRoute | None:
        """Find the first matching dynamic route for the given state.

        Args:
            state: Current agent state.

        Returns:
            The matching route, or None.
        """
        for route in self._routes:
            if route.condition_fn is None:
                continue
            if route.condition_fn(state):
                return route
        return None

    def route(self, state: dict[str, Any], default: str = "__end__") -> str:
        """Resolve state to a target node name.

        Args:
            state: Current agent state.
            default: Fallback node.

        Returns:
            Target node name.
        """
        route = self.find_target(state)
        if route is not None:
            return route.target
        return default

    def route_all(self, state: dict[str, Any]) -> list[DynamicRoute]:
        """Find all matching dynamic routes (for fan-out)."""
        return [r for r in self._routes if r.condition_fn is None or r.condition_fn(state)]

    def to_send(self, state: dict[str, Any], input_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> list[Any]:
        """Generate ``Send`` objects for all matching routes.

        Args:
            state: Current agent state.
            input_fn: Optional function to transform state for each Send.

        Returns:
            List of ``Send()`` or ``Command(goto=Send(...))`` objects.
        """
        from langgraph.types import Send

        targets = self.route_all(state)
        results: list[Any] = []
        for target in targets:
            send_state = input_fn(state) if input_fn else dict(state)
            results.append(Send(target.target, send_state))
        return results


# ── Map-reduce router ─────────────────────────────────────────────────


class MapReduceRouter:
    """Fan-out to multiple parallel nodes, then aggregate results.

    Implements the Map-Reduce pattern:
    1. Map phase: fan out state to N parallel worker nodes
    2. Reduce phase: collect all results into a single aggregator node
    """

    def __init__(
        self,
        map_node: str,
        reduce_node: str,
        worker_nodes: list[str] | None = None,
    ) -> None:
        self._map_node = map_node
        self._reduce_node = reduce_node
        self._worker_nodes = worker_nodes or []

    def add_worker(self, node_name: str) -> None:
        self._worker_nodes.append(node_name)

    @property
    def map_node(self) -> str:
        return self._map_node

    @property
    def reduce_node(self) -> str:
        return self._reduce_node

    @property
    def worker_nodes(self) -> list[str]:
        return list(self._worker_nodes)

    def fan_out(self, items: list[Any], input_fn: Callable[[Any], dict[str, Any]]) -> list[Any]:
        """Generate ``Send`` objects for each item.

        Args:
            items: Iterable of items to fan out to workers.
            input_fn: Transforms each item into worker input state.

        Returns:
            List of ``Send()`` objects.
        """
        from langgraph.types import Send

        if not self._worker_nodes:
            return []

        sends: list[Any] = []
        for i, item in enumerate(items):
            worker = self._worker_nodes[i % len(self._worker_nodes)]
            state = input_fn(item)
            state["_map_index"] = i
            sends.append(Send(worker, state))
        return sends

    def fan_all(self, state: dict[str, Any]) -> list[Any]:
        """Fan out the same state to all workers.

        Args:
            state: State to distribute.

        Returns:
            List of ``Send()`` objects.
        """
        from langgraph.types import Send

        return [Send(node, dict(state)) for node in self._worker_nodes]


# ── Branch spec ───────────────────────────────────────────────────────


@dataclass
class BranchSpec:
    """Declarative branch specification for conditional edges.

    Mimics LangGraph's ``add_conditional_edges`` interface.

    Attributes:
        path_fn: Function that takes state and returns a route string.
        path_map: Maps route strings to target node names.
        condition: Optional extra condition function for fine-grained control.
    """

    path_fn: RouterFn | None = None
    path_map: dict[str, str] = field(default_factory=dict)
    condition: Callable[[dict[str, Any]], bool] | None = None

    def resolve(self, state: dict[str, Any]) -> str:
        """Resolve state to a target node.

        Args:
            state: Current agent state.

        Returns:
            Target node name, or ``"__end__"`` if no path matches.
        """
        if self.path_fn is not None and (self.condition is None or self.condition(state)):
            result = self.path_fn(state)
            return self.path_map.get(result, "__end__")
        return "__end__"

    def to_path_map(self) -> dict[str, str]:
        """Return a copy of the path map."""
        return dict(self.path_map)


__all__ = [
    "BranchSpec",
    "ConditionalRouter",
    "DynamicRoute",
    "DynamicRouter",
    "MapReduceRouter",
    "NoRouteMatch",
    "PathMap",
    "RouteCondition",
    "RouterFn",
    "SendFn",
]