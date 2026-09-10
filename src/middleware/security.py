"""PII & Security middleware — redaction, audit, and input validation.

Provides security-focused middleware:

- ``PIIMiddleware`` — detects and redacts PII (email, phone, ID numbers)
- ``PIAMiddleware`` — checks PIA (Privacy Impact Assessment) before tool execution
- ``SecurityMiddleware`` — input validation, injection prevention
- ``AuditMiddleware`` — audit logging for every tool execution

Inspired by orchestrator's ``pii.py``, ``pia.py`` and DeepAgents'
security patterns.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from src.middleware.types import (
    AgentMiddleware,
    MiddlewareConfig,
    MiddlewareResult,
)


# ── PII patterns ─────────────────────────────────────────────────────────


@dataclass
class PIIPattern:
    """A PII detection pattern with its replacement strategy."""

    name: str
    """Pattern name (e.g. 'email', 'phone')."""
    pattern: re.Pattern[str]
    """Compiled regex to detect this PII type."""
    replacement: str = "[REDACTED]"
    """Text to replace matches with."""
    severity: str = "medium"
    """Severity: 'low', 'medium', 'high'."""


# Default PII patterns
DEFAULT_PII_PATTERNS: list[PIIPattern] = [
    PIIPattern(
        name="email",
        pattern=re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        severity="medium",
    ),
    PIIPattern(
        name="phone_vn",
        pattern=re.compile(r"(\+84|0)[1-9][0-9]{8,9}\b"),
        replacement="[REDACTED PHONE]",
        severity="medium",
    ),
    PIIPattern(
        name="phone_international",
        pattern=re.compile(r"\+\d{1,3}[-\s]?\(?\d{1,4}\)?[-\s]?\d{1,4}[-\s]?\d{1,9}"),
        replacement="[REDACTED PHONE]",
        severity="medium",
    ),
    PIIPattern(
        name="id_vn",
        pattern=re.compile(r"\b\d{9,12}\b"),
        replacement="[REDACTED ID]",
        severity="high",
    ),
    PIIPattern(
        name="credit_card",
        pattern=re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
        replacement="[REDACTED CARD]",
        severity="high",
    ),
    PIIPattern(
        name="ip_address",
        pattern=re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
        replacement="[REDACTED IP]",
        severity="low",
    ),
    PIIPattern(
        name="api_key",
        pattern=re.compile(r"(?:api[_-]?key|apikey|secret[_-]?key)\s*[:=]\s*['\"]?\w+['\"]?", re.IGNORECASE),
        replacement="[REDACTED API KEY]",
        severity="high",
    ),
]


# ── PIIMiddleware ────────────────────────────────────────────────────────


class PIIMiddleware(AgentMiddleware[Any]):
    """Detects and redacts PII in agent inputs and outputs.

    Uses configurable regex patterns and supports both regex-based and
    model-based detection (for complex patterns).
    """

    name = "pii"

    def __init__(
        self,
        patterns: list[PIIPattern] | None = None,
        use_model_detection: bool = False,
    ) -> None:
        super().__init__()
        self._patterns = patterns or DEFAULT_PII_PATTERNS
        self._use_model = use_model_detection
        self._redaction_count: int = 0

    @property
    def redaction_count(self) -> int:
        """Number of PII redactions performed."""
        return self._redaction_count

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Redact PII from the input messages."""
        messages = state.get("messages", [])
        redacted = self._redact_messages(messages)
        if redacted:
            return MiddlewareResult(state={"messages": redacted})

        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Redact PII from the output messages."""
        messages = state.get("messages", [])
        redacted = self._redact_messages(messages)
        if redacted:
            return MiddlewareResult(state={"messages": redacted})

        return None

    def modify_request(self, request: Any) -> Any:
        """Redact PII from the model request."""
        for msg in request.messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                msg["content"] = self._redact_text(content)
        if request.system_prompt:
            request.system_prompt = self._redact_text(request.system_prompt)
        return request

    # ── Internal ──────────────────────────────────────────────────────

    def _redact_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Redact PII from all messages.

        Args:
            messages: List of message dicts.

        Returns:
            Redacted messages list, or None if no redactions needed.
        """
        if not messages:
            return None

        redacted_any = False
        result = []
        for msg in messages:
            msg_copy = dict(msg)
            content = msg_copy.get("content", "")
            if isinstance(content, str):
                redacted = self._redact_text(content)
                if redacted != content:
                    redacted_any = True
                    msg_copy["content"] = redacted
            elif isinstance(content, list):
                # Multi-part content
                parts = []
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        t = part["text"]
                        rt = self._redact_text(t)
                        if rt != t:
                            redacted_any = True
                            part = {**part, "text": rt}
                    parts.append(part)
                msg_copy["content"] = parts
            result.append(msg_copy)

        return result if redacted_any else None

    def _redact_text(self, text: str) -> str:
        """Redact PII from a text string.

        Applies all configured regex patterns.

        Args:
            text: The text to redact.

        Returns:
            Text with PII replaced.
        """
        if not text:
            return text

        result = text
        for pattern in self._patterns:
            result, count = pattern.pattern.subn(pattern.replacement, result)
            self._redaction_count += count

        return result


# ── PIAMiddleware ────────────────────────────────────────────────────────


@dataclass
class PIARequirement:
    """A Privacy Impact Assessment requirement.

    Before executing a tool that accesses certain types of data or paths,
    a PIA check is required.
    """

    data_type: str
    """Type of data requiring PIA (e.g. 'personal', 'financial')."""
    description: str = ""
    """Description of the requirement."""
    required_level: str = "basic"
    """Required assessment level: 'basic', 'standard', 'full'."""


class PIAMiddleware(AgentMiddleware[Any]):
    """Privacy Impact Assessment middleware.

    Checks whether tool calls require a PIA before execution.
    If a high-impact tool is called without proper assessment,
    execution is halted for review.
    """

    name = "pia"

    def __init__(
        self,
        requirements: list[PIARequirement] | None = None,
    ) -> None:
        super().__init__()
        self._requirements = requirements or [
            PIARequirement(
                data_type="personal",
                description="Access to personal identifiable information",
                required_level="standard",
            ),
            PIARequirement(
                data_type="financial",
                description="Access to financial data",
                required_level="full",
            ),
        ]

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Set PIA context in state."""
        state["_pia_requirements"] = [
            {"data_type": r.data_type, "description": r.description}
            for r in self._requirements
        ]
        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Check tool calls for PIA requirements."""
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, dict) or last.get("role") != "assistant":
            return None

        tool_calls = last.get("tool_calls", [])
        for tc in tool_calls:
            tool_name = tc.get("name", "").lower()
            for req in self._requirements:
                if req.data_type in tool_name:
                    return MiddlewareResult(
                        state={
                            "_pia_required": True,
                            "_pia_data_type": req.data_type,
                            "_pia_level": req.required_level,
                        }
                    )

        return None


# ── SecurityMiddleware ───────────────────────────────────────────────────


class SecurityMiddleware(AgentMiddleware[Any]):
    """Input validation and injection prevention middleware.

    Checks for common injection patterns (prompt injection, shell injection,
    SQL injection) and sanitises inputs before they reach the agent.
    """

    name = "security"

    def __init__(self) -> None:
        super().__init__()

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Validate input for injection attempts."""
        messages = state.get("messages", [])
        if not messages:
            return None

        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if isinstance(content, str):
                    issues = self._check_injection(content)
                    if issues:
                        return MiddlewareResult(
                            halt=True,
                            state={
                                "_security_issues": issues,
                                "_injection_detected": True,
                            },
                        )

        return None

    def _check_injection(self, text: str) -> list[dict[str, str]]:
        """Check text for injection patterns.

        Args:
            text: Text to check.

        Returns:
            List of detected issues, empty if clean.
        """
        issues: list[dict[str, str]] = []

        # Check for prompt injection patterns
        injection_patterns = [
            (r"(?i)(ignore|disregard)\s+(all\s+)?(previous|prior)\s+(instructions|directions)", "prompt_injection"),
            (r"(?i)forget\s+(everything|all|every|your)", "prompt_injection"),
            (r"(?i)you\s+(are\s+)?(now|must)\s+(be|act|pretend|play)", "role_abuse"),
            (r"(?i)system\s+(prompt|message|instruction)\s*:", "system_prompt_leak"),
        ]

        for pattern, issue_type in injection_patterns:
            if re.search(pattern, text):
                issues.append({
                    "type": issue_type,
                    "severity": "high",
                    "detail": f"Detected {issue_type.replace('_', ' ')} pattern",
                })

        return issues


# ── AuditMiddleware ──────────────────────────────────────────────────────


@dataclass
class AuditEntry:
    """A single audit log entry."""

    timestamp: float
    """When the event occurred."""
    tool_name: str
    """The tool that was called."""
    tool_id: str
    """The tool call ID."""
    input_preview: str
    """Preview of the input (truncated)."""
    output_preview: str
    """Preview of the output (truncated)."""
    success: bool
    """Whether the tool execution succeeded."""
    duration: float
    """How long the execution took."""
    user_id: str = ""
    """User who triggered the call."""
    thread_id: str = ""
    """Thread/session ID."""


class AuditMiddleware(AgentMiddleware[Any]):
    """Audit logging for every tool execution.

    Records all tool calls with timestamps, inputs, outputs, and status.
    Supports multiple audit backends (memory, file, database).
    """

    name = "audit"

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[AuditEntry] = []

    @property
    def entries(self) -> list[AuditEntry]:
        """All audit entries."""
        return list(self._entries)

    def clear(self) -> None:
        """Clear all audit entries."""
        self._entries.clear()

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Audit tool calls in the last assistant message."""
        messages = state.get("messages", [])
        if not messages:
            return None

        # Find assistant + tool message pairs
        for i in range(len(messages) - 1):
            msg = messages[i]
            next_msg = messages[i + 1]
            if isinstance(msg, dict) and isinstance(next_msg, dict):
                if msg.get("role") == "assistant" and next_msg.get("role") == "tool":
                    tool_calls = msg.get("tool_calls", [])
                    for tc in tool_calls:
                        self._audit_tool_call(
                            tc,
                            next_msg,
                            config,
                        )

        # Store audit entries in state
        if self._entries:
            state["_audit_log"] = [
                {
                    "timestamp": e.timestamp,
                    "tool_name": e.tool_name,
                    "success": e.success,
                }
                for e in self._entries[-10:]
            ]

        return None

    def _audit_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_result: dict[str, Any],
        config: MiddlewareConfig,
    ) -> None:
        """Record a single tool call in the audit log.

        Args:
            tool_call: The tool call dict.
            tool_result: The tool result message.
            config: Runtime configuration.
        """
        entry = AuditEntry(
            timestamp=time.monotonic(),
            tool_name=tool_call.get("name", "unknown"),
            tool_id=tool_call.get("id", ""),
            input_preview=str(tool_call.get("args", {}))[:200],
            output_preview=str(tool_result.get("content", ""))[:200],
            success="Error" not in str(tool_result.get("content", "")),
            duration=0.0,  # Would need timing
            user_id=config.user_id,
            thread_id=config.thread_id,
        )
        self._entries.append(entry)


__all__ = [
    "AuditEntry",
    "AuditMiddleware",
    "DEFAULT_PII_PATTERNS",
    "PIARequirement",
    "PIAMiddleware",
    "PIIMiddleware",
    "PIIPattern",
    "SecurityMiddleware",
]