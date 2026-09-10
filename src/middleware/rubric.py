"""Rubric/Self-Evaluation middleware — grades agent output and triggers revision.

Provides a self-evaluation loop where agent output is graded against a rubric,
and if it fails, feedback is sent back to the agent for revision.

Inspired by DeepAgents' ``middleware/rubric.py`` and orchestrator's
quality evaluation patterns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from src.middleware.types import (
    AgentMiddleware,
    MiddlewareConfig,
    MiddlewareResult,
)


# ── Rubric types ─────────────────────────────────────────────────────────


class CriterionSeverity(Enum):
    """Severity level for rubric criteria."""

    CRITICAL = auto()
    """Must pass — output is invalid if this fails."""
    IDENTITY = auto()
    """Assesses identity preservation (e.g. tone, style)."""
    SIMPLE = auto()
    """Simple check (e.g. output length, format)."""


@dataclass
class Criterion:
    """A single criterion in a rubric.

    Each criterion is a named check with a description and severity level.
    """

    name: str
    """Short name for the criterion."""
    description: str
    """Description of what to check."""
    severity: CriterionSeverity = CriterionSeverity.SIMPLE
    """How severe a failure of this criterion is."""
    passing_threshold: float = 0.6
    """Minimum score (0.0-1.0) required to pass."""


@dataclass
class Rubric:
    """A rubric for grading agent output.

    A rubric consists of multiple criteria, a passing threshold, and
    optionally nested rubrics for sub-agent evaluation.
    """

    name: str
    """Name of this rubric."""
    criteria: list[Criterion] = field(default_factory=list)
    """List of criteria to evaluate."""
    passing_threshold: float = 0.7
    """Overall score (0.0-1.0) required to pass."""
    max_revisions: int = 2
    """Maximum number of revision attempts."""
    nested_rubrics: list[Rubric] = field(default_factory=list)
    """Sub-rubrics for sub-agent output evaluation."""


@dataclass
class CriterionScore:
    """Score for a single criterion."""

    criterion_name: str
    """Name of the criterion."""
    score: float
    """Score 0.0-1.0."""
    passed: bool
    """Whether this criterion passed."""
    feedback: str = ""
    """Feedback explaining the score."""


@dataclass
class GradingResult:
    """Result of grading agent output against a rubric."""

    rubric_name: str
    """Name of the rubric used."""
    scores: list[CriterionScore] = field(default_factory=list)
    """Scores for each criterion."""
    overall_score: float = 0.0
    """Weighted overall score."""
    passed: bool = False
    """Whether the output passed overall."""
    feedback: str = ""
    """Aggregated feedback for revision."""
    revision_count: int = 0
    """Number of revision attempts made."""
    nested_results: list[GradingResult] = field(default_factory=list)
    """Results from nested rubrics."""


# ── Built-in rubrics ────────────────────────────────────────────────────


class RubricLibrary:
    """Collection of built-in rubrics."""

    @staticmethod
    def quality_default() -> Rubric:
        """Default quality rubric with common criteria."""
        return Rubric(
            name="quality_default",
            criteria=[
                Criterion(
                    name="relevance",
                    description="Output addresses the user's query directly",
                    severity=CriterionSeverity.CRITICAL,
                ),
                Criterion(
                    name="accuracy",
                    description="Output is factually correct and well-supported",
                    severity=CriterionSeverity.CRITICAL,
                ),
                Criterion(
                    name="completeness",
                    description="Output fully answers all parts of the query",
                    severity=CriterionSeverity.IDENTITY,
                ),
                Criterion(
                    name="clarity",
                    description="Output is clear, well-structured, and easy to follow",
                    severity=CriterionSeverity.SIMPLE,
                ),
                Criterion(
                    name="conciseness",
                    description="Output is appropriately concise without being terse",
                    severity=CriterionSeverity.SIMPLE,
                ),
            ],
            passing_threshold=0.7,
            max_revisions=2,
        )

    @staticmethod
    def code_generation() -> Rubric:
        """Rubric for code generation tasks."""
        return Rubric(
            name="code_generation",
            criteria=[
                Criterion(
                    name="correctness",
                    description="Code compiles/runs and produces correct output",
                    severity=CriterionSeverity.CRITICAL,
                ),
                Criterion(
                    name="safety",
                    description="Code handles edge cases and errors gracefully",
                    severity=CriterionSeverity.CRITICAL,
                ),
                Criterion(
                    name="style",
                    description="Code follows language conventions and is readable",
                    severity=CriterionSeverity.IDENTITY,
                ),
                Criterion(
                    name="efficiency",
                    description="Code uses appropriate algorithms and is efficient",
                    severity=CriterionSeverity.SIMPLE,
                ),
            ],
            passing_threshold=0.8,
            max_revisions=3,
        )

    @staticmethod
    def summarization() -> Rubric:
        """Rubric for summarization tasks."""
        return Rubric(
            name="summarization",
            criteria=[
                Criterion(
                    name="faithfulness",
                    description="Summary accurately reflects the source and does not hallucinate",
                    severity=CriterionSeverity.CRITICAL,
                ),
                Criterion(
                    name="completeness",
                    description="Summary covers key points without omitting critical information",
                    severity=CriterionSeverity.IDENTITY,
                ),
                Criterion(
                    name="conciseness",
                    description="Summary is appropriately brief for the target length",
                    severity=CriterionSeverity.SIMPLE,
                ),
            ],
            passing_threshold=0.7,
            max_revisions=2,
        )


# ── Grader function ──────────────────────────────────────────────────────


def grade_output(
    output: str,
    rubric: Rubric,
    history: list[dict[str, Any]] | None = None,
) -> GradingResult:
    """Grade agent output against a rubric.

    In a full implementation, this would call a grader sub-agent (LLM).
    Here we use a heuristic evaluation.

    Args:
        output: The agent's output text.
        rubric: The rubric to grade against.
        history: Optional conversation history for context.

    Returns:
        A ``GradingResult`` with per-criterion scores.
    """
    scores: list[CriterionScore] = []
    feedback_parts: list[str] = []
    total_score = 0.0

    for criterion in rubric.criteria:
        score, feedback = _evaluate_criterion(output, criterion, history)
        passed = score >= criterion.passing_threshold
        scores.append(
            CriterionScore(
                criterion_name=criterion.name,
                score=score,
                passed=passed,
                feedback=feedback,
            )
        )
        total_score += score
        if not passed:
            feedback_parts.append(f"- **{criterion.name}**: {feedback}")

    overall = total_score / len(rubric.criteria) if rubric.criteria else 0.0
    passed = overall >= rubric.passing_threshold and all(
        s.passed
        for s in scores
        if rubric.criteria[
            [c.name for c in rubric.criteria].index(s.criterion_name)
        ].severity
        == CriterionSeverity.CRITICAL
    )

    return GradingResult(
        rubric_name=rubric.name,
        scores=scores,
        overall_score=overall,
        passed=passed,
        feedback="\n".join(feedback_parts),
    )


def _evaluate_criterion(
    output: str,
    criterion: Criterion,
    history: list[dict[str, Any]] | None = None,
) -> tuple[float, str]:
    """Evaluate a single criterion against the output.

    Heuristic evaluation:
    - CRITICAL: checks for minimum content
    - IDENTITY: checks for structure/style
    - SIMPLE: checks for length/format constraints

    Args:
        output: Agent output text.
        criterion: The criterion to evaluate.
        history: Optional conversation history.

    Returns:
        ``(score, feedback)`` tuple.
    """
    if not output:
        return 0.0, "Output is empty"

    match criterion.severity:
        case CriterionSeverity.CRITICAL:
            # Critical: check for substantial content
            word_count = len(output.split())
            if word_count < 5:
                return 0.2, f"Output too short ({word_count} words)"
            if word_count > 10_000:
                return 0.4, f"Output excessively long ({word_count} words)"
            return 0.9, "Output has adequate length and substance"

        case CriterionSeverity.IDENTITY:
            # Identity: check for structure (paragraphs, lists)
            has_structure = False
            feedback = ""
            if "\n\n" in output:
                has_structure = True
                feedback = "Well-structured with paragraphs"
            if "- " in output or "1. " in output:
                has_structure = True
                feedback = "Good use of lists/formatting"
            if not has_structure:
                return 0.5, "Output lacks clear structure"
            return 0.8, feedback

        case CriterionSeverity.SIMPLE:
            # Simple: length appropriateness
            word_count = len(output.split())
            if word_count < 3:
                return 0.4, "Output is too brief"
            if word_count > 5000:
                return 0.6, "Output may be too verbose"
            return 1.0, "Output length is appropriate"

    return 0.5, "Could not evaluate"


# ── Rubric middleware ────────────────────────────────────────────────────


class RubricMiddleware(AgentMiddleware[Any]):
    """Self-evaluation middleware that grades agent output against a rubric.

    If the output fails the rubric, the middleware provides feedback to the
    agent and triggers a revision cycle (up to ``max_revisions`` attempts).
    """

    name = "rubric"

    def __init__(
        self,
        rubric: Rubric | None = None,
        grader_fn: Any = None,
    ) -> None:
        super().__init__()
        self._rubric = rubric or RubricLibrary.quality_default()
        self._grader_fn = grader_fn or grade_output
        self._revision_count: int = 0

    @property
    def tools(self) -> list[Any]:
        return []

    @property
    def revision_count(self) -> int:
        """Number of revision cycles performed."""
        return self._revision_count

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Inject rubric instructions into system prompt."""
        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Grade the agent output and trigger revision if needed."""
        messages = state.get("messages", [])
        if not messages:
            return None

        last_message = messages[-1]
        output = last_message.get("content", "") if isinstance(last_message, dict) else str(last_message)
        if not output:
            return None

        # Run the grader
        result = self._grader_fn(output, self._rubric, messages)

        # Report grading result
        if config.stream_callback:
            config.stream_callback(
                {
                    "type": "rubric_result",
                    "rubric": self._rubric.name,
                    "score": result.overall_score,
                    "passed": result.passed,
                    "feedback": result.feedback,
                }
            )

        if result.passed:
            return None

        # Check revision limit
        self._revision_count += 1
        if self._revision_count > self._rubric.max_revisions:
            return MiddlewareResult(
                state=state,
                feedback=f"Max revisions ({self._rubric.max_revisions}) reached. Output may not meet quality standards.",
            )

        # Trigger revision: inject feedback and let the agent try again
        feedback_msg = {
            "role": "user",
            "content": (
                f"Please revise your previous response to address these issues:\n\n"
                f"{result.feedback}\n\n"
                f"Overall score: {result.overall_score:.1%} "
                f"(passing: {self._rubric.passing_threshold:.0%}). "
                f"Attempt {self._revision_count}/{self._rubric.max_revisions}."
            ),
        }

        return MiddlewareResult(
            state={
                "messages": messages + [feedback_msg],
                "_rubric_feedback": result.feedback,
                "_rubric_score": result.overall_score,
                "_rubric_revision": self._revision_count,
            },
            feedback=result.feedback,
        )


__all__ = [
    "Criterion",
    "CriterionScore",
    "CriterionSeverity",
    "GradingResult",
    "Rubric",
    "RubricLibrary",
    "RubricMiddleware",
    "grade_output",
]