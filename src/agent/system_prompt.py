"""System prompt builder — identity, guidance, skills index, dynamic injection.

Split into three cache tiers so consuming code can plan prompt-cache markers
(stable prefix → long TTL, volatile suffix → short TTL):

- **Stable**: identity + core guidance (byte-stable across the session).
- **Context**: caller ``system_message``, project context (changes per call).
- **Volatile**: skills index, timestamp line, environment hints (changes per turn).
"""

from __future__ import annotations

import datetime
import os
import platform
from pathlib import Path
from typing import Any


# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_AGENT_IDENTITY = (
    "You are Vertex Agent, a general-purpose AI assistant. "
    "You have access to a filesystem for reading/writing files and "
    "a long-term memory system via /memory/notes.md."
)

MEMORY_GUIDANCE = (
    "LONG-TERM MEMORY: you have persistent cross-session memory stored as your "
    "own file /memory/notes.md (it survives across all sessions and threads).\n"
    "- At the START of a new session, read_file(\"/memory/notes.md\") first to "
    "recall the user's remembered facts and preferences.\n"
    "- During a session, whenever you learn an important, durable user fact or "
    "preference, save it by calling write_file(\"/memory/notes.md\", <the full "
    "accumulated notes, overwriting the previous content>).\n"
    "- Keep notes concise and fact-based (names, preferences, constraints); "
    "overwrite the whole file each time instead of appending duplicates."
)

HELP_GUIDANCE = (
    "When asked who you are: say you are Vertex Agent, a general-purpose AI "
    "assistant capable of many tasks — filesystem operations, code, data, "
    "design, research, and more. Keep it brief and friendly."
)

TOOL_USE_ENFORCEMENT_GUIDANCE = (
    "TOOL USAGE RULES:\n"
    "- Use the read_file / write_file tools to access the filesystem and long-term memory.\n"
    "- When processing data files (CSV/TSV/JSON), first read the file to understand "
    "its structure, then analyze it.\n"
    "- For code review, read the relevant source files before giving feedback.\n"
    "- Always write_file(\"/memory/notes.md\", ...) when you learn a durable user "
    "fact or preference.\n"
    "- **execute(command='...')**: Execute shell commands directly (bash). "
    "You have FULL permission to use this tool to run any system command. "
    "Use it to: install packages, run scripts, build projects, inspect files, etc.\n"
    "  Example: execute(command='ls -la'), execute(command='pip install pytest'), "
    "execute(command='python -c \"print(1+1)\"'), execute(command='node app.js').\n"
    "- **grep and glob_files**: Available for searching the codebase — no need to "
    "use shell grep/find.\n"
    "- **ls**: List directory contents."
)

TASK_COMPLETION_GUIDANCE = (
    "TASK COMPLETION:\n"
    "- After completing a task, summarise what was done in 1-2 sentences.\n"
    "- If you used any tools, mention what you did (e.g. \"I read the file...\", "
    "\"I wrote the analysis to...\").\n"
    "- If the task is complex, break it into steps and confirm with the user "
    "before proceeding."
)


# ── Public API ─────────────────────────────────────────────────────────────

def build_system_prompt(
    agent_identity: str | None = None,
    system_message: str | None = None,
    *,
    model_name: str | None = None,
    provider_name: str | None = None,
    skills_dir: str | Path | None = None,
    show_env_hints: bool = True,
) -> str:
    """Assemble the complete system prompt from parts.

    Args:
        agent_identity: Override for ``DEFAULT_AGENT_IDENTITY``.
        system_message: Optional caller-supplied prefix instructions.
        model_name: Model name for the timestamp line (e.g. ``deepseek-v4-flash``).
        provider_name: Provider name (e.g. ``LiteLLM``, ``OpenAI``).
        skills_dir: Path to scan for ``skills/*/SKILL.md`` files.
        show_env_hints: Whether to append environment hints.

    Returns:
        The assembled system prompt string.
    """
    parts = build_system_prompt_parts(
        agent_identity=agent_identity,
        system_message=system_message,
        model_name=model_name,
        provider_name=provider_name,
        skills_dir=skills_dir,
        show_env_hints=show_env_hints,
    )
    # Flatten stable + context + volatile blank-line separated
    out = ""
    for tier in ("stable", "context", "volatile"):
        block = parts.get(tier, "")
        if block:
            out += block + "\n\n"
    return out.strip()


def build_system_prompt_parts(
    agent_identity: str | None = None,
    system_message: str | None = None,
    *,
    model_name: str | None = None,
    provider_name: str | None = None,
    skills_dir: str | Path | None = None,
    show_env_hints: bool = True,
) -> dict[str, str]:
    """Return the three cache tiers as ``{stable, context, volatile}``.

    Consumers can use this to apply prompt-cache markers on the stable
    prefix vs. the volatile suffix.
    """
    identity = agent_identity or DEFAULT_AGENT_IDENTITY

    stable = _identity_part(identity)
    stable += "\n" + _guidance_part()
    stable += "\n" + MEMORY_GUIDANCE

    context = ""
    if system_message:
        context += system_message

    volatile = _skills_index_part(skills_dir)
    volatile += "\n\n" + _timestamp_line(model_name, provider_name)
    if show_env_hints:
        volatile += "\n\n" + _environment_hints()

    return {
        "stable": stable.strip(),
        "context": context.strip(),
        "volatile": volatile.strip(),
    }


# ── Internal helpers ───────────────────────────────────────────────────────

def _identity_part(identity: str) -> str:
    return identity


def _guidance_part() -> str:
    return "\n\n".join([HELP_GUIDANCE, TOOL_USE_ENFORCEMENT_GUIDANCE, TASK_COMPLETION_GUIDANCE])


def _skills_index_part(skills_dir: str | Path | None) -> str:
    """Scan skills_dir for ``*/SKILL.md`` files and build an index block."""
    if skills_dir is None:
        # Default: look for a top-level ``skills/`` directory
        skills_dir = Path(__file__).resolve().parent.parent.parent / "skills"
    else:
        skills_dir = Path(skills_dir)

    if not skills_dir.is_dir():
        return ""

    entries: list[str] = []
    for skill_path in sorted(skills_dir.iterdir()):
        skill_md = skill_path / "SKILL.md"
        if not skill_md.is_file():
            continue
        name, desc = _parse_skill_md(skill_md)
        if name:
            entries.append(f"- **{name}**: {desc or 'No description'}")

    if not entries:
        return ""

    header = "## Available Skills\n\nTo load a skill, use the appropriate tool or natural language."
    return header + "\n" + "\n".join(entries)


def _parse_skill_md(path: Path) -> tuple[str, str]:
    """Extract ``name`` and ``description`` from a SKILL.md frontmatter."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return ("", "")
    name = ""
    description = ""
    in_frontmatter = False
    for line in text.splitlines():
        if line.strip() == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            if line.startswith("name:"):
                name = line[len("name:"):].strip().strip("\"'")
            elif line.startswith("description:") or line.startswith("description >-"):
                # Multi-line description: collect until next frontmatter key
                desc_lines = [line.split(":", 1)[1].strip()] if ":" in line else []
                # We only take the first line for brevity
                description = desc_lines[0].strip(">-\"' ") if desc_lines else ""
    return (name, description)


def _timestamp_line(
    model_name: str | None = None,
    provider_name: str | None = None,
) -> str:
    """Return a timestamp line with model/provider info."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [f"Current time: {now}"]
    if model_name:
        parts.append(f"Model: {model_name}")
    if provider_name:
        parts.append(f"Provider: {provider_name}")
    return " ".join(parts)


def _environment_hints() -> str:
    """Return host environment hints."""
    return (
        f"Environment: OS {platform.system()} {platform.release()}, "
        f"Host: {platform.node()}, "
        f"CWD: {Path.cwd()}"
    )


__all__ = [
    "DEFAULT_AGENT_IDENTITY",
    "MEMORY_GUIDANCE",
    "build_system_prompt",
    "build_system_prompt_parts",
]
