from __future__ import annotations

from dataclasses import dataclass

from uthcode.application import (
    ArgumentSpec,
    CommandAvailability,
    CommandDefinition,
    CommandKind,
    CommandRegistry,
    CompletionEngine,
    create_builtin_registry,
)


@dataclass(frozen=True)
class _CatalogModel:
    model_ref: str


class _CatalogApplication:
    def __init__(self, *refs: str) -> None:
        self._models = tuple(_CatalogModel(ref) for ref in refs)

    def model_catalog(self) -> tuple[_CatalogModel, ...]:
        return self._models


def test_root_completion_returns_all_visible_commands_and_help_last() -> None:
    registry = create_builtin_registry()
    candidates = CompletionEngine(registry).complete("/")
    names = [candidate.canonical for candidate in candidates]

    assert len(names) == 16
    assert len(names) == len(set(names))
    assert names[-1] == "help"
    assert names.count("help") == 1
    assert {candidate.canonical for candidate in candidates[:-1]} == {
        command.canonical
        for command in registry.list_commands(include_hidden=False)
        if command.canonical != "help"
    }


def test_prefix_completion_matches_canonical_and_aliases_and_marks_unimplemented() -> None:
    registry = create_builtin_registry()
    engine = CompletionEngine(registry)

    candidates = engine.complete("/c")
    names = [candidate.canonical for candidate in candidates]

    assert "clear" in names
    assert "compact" in names
    assert names[-1] == "help"
    assert names.count("help") == 1
    assert len(names) == len(set(names))
    assert any(
        candidate.canonical == "compact"
        and candidate.availability is CommandAvailability.NOT_IMPLEMENTED
        and "未实现" in candidate.display
        for candidate in candidates
    )

    model_alias = engine.complete("/models")
    assert [candidate.canonical for candidate in model_alias[:-1]] == ["model"]
    assert model_alias[-1].canonical == "help"


def test_usage_and_static_argument_candidates_come_from_definition() -> None:
    registry = CommandRegistry()
    definition = CommandDefinition(
        canonical="format",
        description="format",
        kind=CommandKind.LOCAL,
        arguments=(
            ArgumentSpec(
                "style",
                required=True,
                description="output style",
                choices=("plain", "markdown"),
            ),
        ),
    )
    registry.register(definition)
    engine = CompletionEngine(registry)

    assert engine.usage_for(definition) == "/format <style>"
    assert engine.argument_prompt_for(definition) == "style: output style"
    assert engine.argument_candidates("/format ") == ("plain", "markdown")


def test_model_candidates_are_read_from_application_model_catalog() -> None:
    registry = create_builtin_registry()
    application = _CatalogApplication("alpha/ref", "beta/ref")
    engine = CompletionEngine(registry, application)

    assert engine.argument_candidates("/model ") == ("alpha/ref", "beta/ref")


def test_permission_candidates_are_registry_backed_and_static() -> None:
    registry = create_builtin_registry()
    engine = CompletionEngine(registry)

    assert engine.argument_candidates("/permission ") == (
        "default",
        "auto",
        "full_access",
    )


def test_completion_candidates_follow_registry_changes_without_a_second_list() -> None:
    registry = create_builtin_registry()
    registry.register(
        CommandDefinition(
            canonical="custom",
            description="custom",
            kind=CommandKind.LOCAL,
        )
    )

    candidates = CompletionEngine(registry).complete("/")

    assert "custom" in [candidate.canonical for candidate in candidates]
    assert candidates[-1].canonical == "help"


def test_behavior_mode_help_and_completion_come_from_the_final_registry_entries() -> None:
    registry = create_builtin_registry()
    engine = CompletionEngine(registry)

    plan = next(candidate for candidate in engine.complete("/plan") if candidate.canonical == "plan")
    build = next(candidate for candidate in engine.complete("/build") if candidate.canonical == "do")

    assert plan.implemented
    assert plan.usage == "/plan"
    assert build.implemented
    assert build.matched_alias == "build"
    assert build.usage == "/do"
