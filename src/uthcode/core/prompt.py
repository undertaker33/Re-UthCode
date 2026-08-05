"""Pure, deterministic System Prompt semantics owned by UthCode Core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class PromptSection:
    """An immutable, ordered unit of System Prompt content."""

    name: str
    priority: int
    content: str

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")


@dataclass(frozen=True, slots=True)
class SystemPromptContext:
    """Explicit runtime values used by the Core System Prompt."""

    workdir: str
    platform_name: str
    platform_release: str
    current_date: str
    model_ref: str
    provider_protocol: str
    remote_model_id: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _require_text(getattr(self, field_name), field_name)


def _escape_runtime_value(value: str) -> str:
    """Render a runtime value without allowing it to create Markdown structure."""

    replacements = {
        "\\": "\\\\",
        "\r": "\\r",
        "\n": "\\n",
        "\t": "\\t",
        "`": "\\`",
        "*": "\\*",
        "_": "\\_",
        "[": "\\[",
        "]": "\\]",
        "<": "\\<",
        ">": "\\>",
        "&": "\\&",
        "|": "\\|",
    }
    return "".join(replacements.get(character, character) for character in value)


def _render_sections(sections: Sequence[PromptSection]) -> str:
    rendered: list[str] = []
    for section in sorted(sections, key=lambda item: item.priority):
        content = section.content.strip()
        if not content:
            continue
        rendered.append(f"## {section.name}\n{content}")
    return "\n\n".join(rendered).rstrip()


def build_system_prompt(context: SystemPromptContext) -> str:
    """Build the fixed five-section System Prompt for one explicit context."""

    if not isinstance(context, SystemPromptContext):
        raise TypeError("context must be a SystemPromptContext")

    sections = (
        PromptSection(
            name="身份",
            priority=0,
            content=(
                "你是 UthCode，面向软件工程任务。当前通过文本帮助用户理解、设计、"
                "审查和编写代码相关内容。保持 UthCode 的产品身份，不绑定具体模型或其他项目品牌人格。"
            ),
        ),
        PromptSection(
            name="工作原则",
            priority=10,
            content=(
                "聚焦用户当前请求，不凭空假定未提供的代码和环境事实，不为假设性需求增加功能或抽象。"
                "对未知信息明确说明未知，不输出内部思考链路。"
            ),
        ),
        PromptSection(
            name="代码质量与安全",
            priority=20,
            content=(
                "优先正确、清晰、可维护的实现。避免命令注入、SQL 注入、XSS、路径遍历和秘密泄漏等常见风险。"
                "不把未经验证的代码或命令描述为已经可用，不伪造测试、编译和运行结果。"
            ),
        ),
        PromptSection(
            name="沟通与结果真实性",
            priority=30,
            content=(
                "默认使用简洁、直接、专业的中文；用户指定其他语言或格式时遵循用户要求。"
                "区分已知事实、合理推断和未验证内容。除非当前请求上下文确有对应能力和结果，"
                "不声称已经读取文件、修改代码、运行命令或执行测试。"
            ),
        ),
        PromptSection(
            name="当前运行环境",
            priority=100,
            content=(
                f"- 工作目录：{_escape_runtime_value(context.workdir)}\n"
                f"- 平台：{_escape_runtime_value(context.platform_name)} / "
                f"{_escape_runtime_value(context.platform_release)}\n"
                f"- 当前日期：{_escape_runtime_value(context.current_date)}\n"
                f"- 模型选择：{_escape_runtime_value(context.model_ref)}\n"
                f"- Provider 协议：{_escape_runtime_value(context.provider_protocol)}\n"
                f"- 远端模型：{_escape_runtime_value(context.remote_model_id)}"
            ),
        ),
    )
    return _render_sections(sections)


__all__ = ["PromptSection", "SystemPromptContext", "build_system_prompt"]
