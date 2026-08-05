from __future__ import annotations

import dataclasses

import pytest

from uthcode.core.prompt import (
    PromptSection,
    SystemPromptContext,
    _render_sections,
    build_system_prompt,
)


def _context(**overrides: str) -> SystemPromptContext:
    values = {
        "workdir": "C:/workspace/re-uthcode",
        "platform_name": "Windows",
        "platform_release": "11",
        "current_date": "2026-08-05",
        "model_ref": "default/assistant",
        "provider_protocol": "responses",
        "remote_model_id": "gpt-test",
    }
    values.update(overrides)
    return SystemPromptContext(**values)


def test_system_prompt_orders_sections_and_uses_fixed_runtime_values() -> None:
    prompt = build_system_prompt(_context())

    headings = [
        "## 身份",
        "## 工作原则",
        "## 代码质量与安全",
        "## 沟通与结果真实性",
        "## 当前运行环境",
    ]
    positions = [prompt.index(heading) for heading in headings]

    assert positions == sorted(positions)
    assert "你是 UthCode" in prompt
    assert "C:/workspace/re-uthcode" in prompt
    assert "Windows / 11" in prompt
    assert "2026-08-05" in prompt
    assert "default/assistant" in prompt
    assert "responses" in prompt
    assert "gpt-test" in prompt


def test_system_prompt_is_deterministic_and_does_not_mutate_context() -> None:
    context = _context()
    before = dataclasses.asdict(context)

    first = build_system_prompt(context)
    second = build_system_prompt(context)

    assert first == second
    assert dataclasses.asdict(context) == before


def test_render_sections_sorts_stably_omits_blank_sections_and_trims_tail() -> None:
    sections = (
        PromptSection("同级后段", 10, "second"),
        PromptSection("空段", 5, " \n\t"),
        PromptSection("同级前段", 10, "first"),
        PromptSection("最先", 0, "early"),
    )

    rendered = _render_sections(sections)

    assert rendered == "## 最先\nearly\n\n## 同级后段\nsecond\n\n## 同级前段\nfirst"
    assert "空段" not in rendered
    assert not rendered.endswith((" ", "\t", "\n"))


def test_system_prompt_escapes_runtime_values_without_breaking_sections() -> None:
    workdir = 'C:\\repo\\`quoted`\n*unsafe* "value"'
    prompt = build_system_prompt(
        _context(
            workdir=workdir,
            platform_name="Windows\n# heading",
            platform_release="release`\n2",
            current_date="2026-08-05\nnext",
            model_ref="ref\\name",
            provider_protocol="protocol*name",
            remote_model_id="model_[x]",
        )
    )
    runtime = prompt[prompt.index("## 当前运行环境") :]

    assert workdir not in runtime
    assert "\\n" in runtime
    assert "\\`quoted\\`" in runtime
    assert "\\*unsafe\\*" in runtime
    assert "Windows\\n# heading" in runtime
    assert runtime.count("## ") == 1
    assert runtime.count("- ") == 6


def test_system_prompt_contains_only_current_capabilities() -> None:
    prompt = build_system_prompt(_context())
    forbidden_terms = (
        "Tool",
        "Permission",
        "Plan",
        "Memory",
        "Dream",
        "Hook",
        "Skill",
        "MCP",
        "Subagent",
        "Sandbox",
        "LangGraph",
        "LangChain",
        "Mew" + "Code",
    )

    assert all(term not in prompt for term in forbidden_terms)
    assert "文件" in prompt
    assert "命令" in prompt
    assert "测试" in prompt
    assert "事实" in prompt
    assert "未知" in prompt


def test_static_prompt_prefix_precedes_dynamic_runtime_suffix() -> None:
    first = build_system_prompt(_context(workdir="C:/one", model_ref="one"))
    second = build_system_prompt(_context(workdir="C:/two", model_ref="two"))
    marker = "## 当前运行环境"

    first_prefix, first_suffix = first.split(marker, 1)
    second_prefix, second_suffix = second.split(marker, 1)

    assert first_prefix == second_prefix
    assert first_suffix != second_suffix
    assert first.endswith("gpt-test")
    assert second.endswith("gpt-test")


@pytest.mark.parametrize(
    ("factory", "value"),
    [
        (lambda: PromptSection("", 0, "content"), "name"),
        (lambda: PromptSection("name", True, "content"), "priority"),
        (lambda: PromptSection("name", 0, 1), "content"),
    ],
)
def test_prompt_section_rejects_invalid_values(factory, value: str) -> None:
    with pytest.raises((TypeError, ValueError), match=value):
        factory()
