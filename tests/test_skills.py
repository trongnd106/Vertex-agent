"""Phase 1: skill system tests (deepagents 0.7.9 SkillsMiddleware).

Discovery reading (`deepagents/middleware/skills.py`): SkillsMiddleware registers
NO `list_skills` / `read_skill` tools. Skills are loaded from `skills=` sources
into `state["skills_metadata"]` and injected into the SYSTEM PROMPT (name +
description + `Read <path>` line only — progressive disclosure); the full
SKILL.md body is fetched by the agent via the built-in `read_file` tool on the
skill's `/skills/<name>/SKILL.md` path. Tests assert that real mechanism.
"""

from pathlib import Path

from langchain_core.messages import AIMessage

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.state import StateBackend
from deepagents.backends.utils import create_file_data

from tests.fake_model import ScriptedChatModel

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

SKILL_NAMES = ["customer-support", "data-analysis", "code-review"]

BODY_MARKER = "Đọc dữ liệu"


def _flatten(content: str | list) -> str:
    """Flatten a message content (string or list of content blocks) to plain text."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text") or block.get("content")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _system_text(model: ScriptedChatModel) -> str:
    """Return the flattened system prompt from the model's last generation."""
    for message in model.last_messages:
        if message.type == "system":
            return _flatten(message.content)
    return ""


def _filesystem_agent(model):
    return create_deep_agent(
        model=model,
        backend=FilesystemBackend(root_dir=str(REPO_ROOT)),
        skills=["/skills/"],
    )


def _load_skill_files() -> dict:
    """Read the three on-disk SKILL.md files as FileData for StateBackend injection."""
    files = {}
    for name in SKILL_NAMES:
        path = SKILLS_DIR / name / "SKILL.md"
        files[f"/skills/{name}/SKILL.md"] = create_file_data(path.read_text(encoding="utf-8"))
    return files


# --------------------------------------------------------------------------- #
# a) Backend loading: FilesystemBackend exposes the 3 configured skills       #
# --------------------------------------------------------------------------- #
def test_backend_loading_exposes_three_skills_via_system_prompt():
    model = ScriptedChatModel()
    _filesystem_agent(model).invoke(
        {"messages": [{"role": "user", "content": "Bạn có kỹ năng gì?"}]}
    )

    system = _system_text(model)
    assert "## Skills System" in system
    for name in SKILL_NAMES:
        assert f"- **{name}**:" in system
        assert f"Read `/skills/{name}/SKILL.md` for full instructions" in system

    # The real tool surface: SkillsMiddleware registers no discovery tools;
    # skill bodies are fetched through the built-in read_file file-op.
    assert "read_file" in model.bound_tools
    assert "read_skill" not in model.bound_tools
    assert "list_skills" not in model.bound_tools


# --------------------------------------------------------------------------- #
# b) Progressive disclosure: only front-matter name + description preloaded   #
# --------------------------------------------------------------------------- #
def test_progressive_disclosure_only_frontmatter_is_preloaded():
    model = ScriptedChatModel()
    _filesystem_agent(model).invoke(
        {"messages": [{"role": "user", "content": "Bạn có kỹ năng gì?"}]}
    )

    system = _system_text(model)
    # Description (front-matter) IS disclosed...
    assert "analyze a data file (CSV/TSV/table)" in system
    # ...but the SKILL.md body is NOT: a distinctive body-only line is absent.
    assert BODY_MARKER not in system


# --------------------------------------------------------------------------- #
# c) Activation: model calls read_file for data-analysis, answer uses guidance#
# --------------------------------------------------------------------------- #
class SkillReaderModel(ScriptedChatModel):
    """Two-turn fake model: reads a skill body via read_file, then answers with it."""

    def __init__(self, file_path: str, marker: str):
        super().__init__()
        self._file_path = file_path
        self._marker = marker
        self._turn = 0

    def _next_message(self) -> AIMessage:
        self._turn += 1
        if self._turn == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": self._file_path},
                        "id": "call_skill_read",
                        "type": "tool_call",
                    }
                ],
            )
        body = self._tool_result_text()
        line = next((ln for ln in body.splitlines() if self._marker in ln), "")
        return AIMessage(content=f"Đã kích hoạt skill data-analysis. Trích: {line}")

    def _tool_result_text(self) -> str:
        for message in reversed(self.last_messages):
            if message.type == "tool":
                return _flatten(message.content)
        return ""


def test_skill_activation_answers_with_skill_guidance():
    model = SkillReaderModel(file_path="/skills/data-analysis/SKILL.md", marker=BODY_MARKER)
    result = _filesystem_agent(model).invoke(
        {"messages": [{"role": "user", "content": "Tổng kết file doanh-thu.csv giúp tôi"}]}
    )

    messages = result["messages"]
    assert any(m.type == "tool" for m in messages)
    tool_messages = [m for m in messages if m.type == "tool"]
    assert any(BODY_MARKER in _flatten(m.content) for m in tool_messages)

    last = messages[-1]
    assert last.type == "ai"
    assert BODY_MARKER in str(last.content)


# --------------------------------------------------------------------------- #
# d) StateBackend variant: skills injected via invoke(files={...})            #
# --------------------------------------------------------------------------- #
def test_state_backend_skills_injected_via_files():
    model = ScriptedChatModel()
    agent = create_deep_agent(model=model, backend=StateBackend(), skills=["/skills/"])

    result = agent.invoke(
        {
            "messages": [{"role": "user", "content": "Bạn có kỹ năng gì?"}],
            "files": _load_skill_files(),
        }
    )

    system = _system_text(model)
    assert "## Skills System" in system
    for name in SKILL_NAMES:
        assert f"- **{name}**:" in system

    injected = result.get("files", {})
    for name in SKILL_NAMES:
        assert f"/skills/{name}/SKILL.md" in injected