from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from anthropic import (
    APITimeoutError,
    AuthenticationError as SDKAuthenticationError,
    InternalServerError as SDKInternalServerError,
    NotFoundError as SDKNotFoundError,
    RateLimitError as SDKRateLimitError,
)

from uthcode.application import (
    ApplicationRuntimeContext,
    ConfigurationError,
    EffectiveConfig,
    ModelProfile,
    ProviderKind,
    ProviderProfile,
    create_application,
    load_effective_config,
)
from uthcode.core.provider import GenerationRequest, Message, ModelLimits, TextPart
from uthcode.integrations.providers.anthropic import AnthropicProvider


def _write_user_config(home: Path, *, context_window: int | None = None) -> Path:
    path = home / ".uthcode" / "config.toml"
    path.parent.mkdir(parents=True)
    context = "" if context_window is None else f"context_window = {context_window}\n"
    path.write_text(
        "default_model = \"base/ref\"\n"
        "\n[providers.local]\nkind = \"fake\"\n"
        "\n[models.\"base/ref\"]\nprovider = \"local\"\n"
        "remote_id = \"base-remote\"\n"
        f"{context}",
        encoding="utf-8",
    )
    return path


def test_model_limits_keep_input_output_and_combined_dimensions_independent() -> None:
    limits = ModelLimits(max_input_tokens=25_000, max_output_tokens=2_000)

    assert limits.max_input_tokens == 25_000
    assert limits.max_output_tokens == 2_000
    assert limits.max_combined_tokens is None
    with pytest.raises(ValueError):
        ModelLimits(max_input_tokens=0)


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_model_profile_context_window_is_positive_int(value: object) -> None:
    with pytest.raises(ValueError, match="context_window"):
        ModelProfile("base/ref", "local", "remote", context_window=value)  # type: ignore[arg-type]


def test_project_context_window_can_only_tighten_user_value(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user_config(home, context_window=25_000)
    root = tmp_path / "repo"
    root.mkdir()
    project = root / ".uthcode" / "config.toml"
    project.parent.mkdir()
    project.write_text(
        '[models."base/ref"]\ncontext_window = 20_000\n',
        encoding="utf-8",
    )

    config = load_effective_config(cwd=root, home=home)
    assert config.models["base/ref"].context_window == 20_000

    project.write_text(
        '[models."base/ref"]\ncontext_window = 30_000\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="cannot expand"):
        load_effective_config(cwd=root, home=home)


def test_project_context_window_cannot_create_missing_user_limit(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    root = tmp_path / "repo"
    root.mkdir()
    project = root / ".uthcode" / "config.toml"
    project.parent.mkdir()
    project.write_text(
        '[models."base/ref"]\ncontext_window = 20_000\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="missing user limit"):
        load_effective_config(cwd=root, home=home)


class _FakeAnthropicClient:
    class _Models:
        async def retrieve(self, model: str) -> object:
            assert model == "claude-test"
            return SimpleNamespace(max_input_tokens=25_000, max_tokens=2_000)

    class _Messages:
        async def count_tokens(self, **kwargs: object) -> object:
            assert kwargs["model"] == "claude-test"
            assert "messages" in kwargs
            return SimpleNamespace(input_tokens=123)

    def __init__(self) -> None:
        self.models = self._Models()
        self.messages = self._Messages()


def _sdk_status_error(
    error_type: type[Exception],
    status_code: int,
) -> Exception:
    request = httpx.Request("GET", "https://example.test/v1/models/claude-test")
    response = httpx.Response(status_code, request=request)
    return error_type("metadata request failed", response=response, body=None)


@pytest.mark.asyncio
async def test_anthropic_runtime_limits_and_count_use_fake_client_only() -> None:
    provider = AnthropicProvider("claude-test", _FakeAnthropicClient())  # type: ignore[arg-type]
    limits = await provider.resolve_model_limits("claude-test")
    count = await provider.count_input_tokens(
        GenerationRequest(messages=(Message("user", (TextPart("hello"),)),))
    )

    assert limits == ModelLimits(
        max_input_tokens=25_000,
        max_output_tokens=2_000,
        source="anthropic.models",
    )
    assert count is not None
    assert count.input_tokens == 123
    assert count.kind == "preflight_provider_count"
    assert count.source == "anthropic.messages.count_tokens"


@pytest.mark.asyncio
async def test_anthropic_missing_optional_model_metadata_returns_none() -> None:
    failure = _sdk_status_error(SDKNotFoundError, 404)

    async def retrieve(_model: str) -> object:
        raise failure

    client = SimpleNamespace(models=SimpleNamespace(retrieve=retrieve))
    provider = AnthropicProvider("claude-test", client)  # type: ignore[arg-type]

    assert await provider.resolve_model_limits("claude-test") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "status_code"),
    (
        (SDKAuthenticationError, 401),
        (SDKRateLimitError, 429),
        (SDKInternalServerError, 500),
    ),
)
async def test_anthropic_model_metadata_propagates_non_404_sdk_status_errors(
    error_type: type[Exception],
    status_code: int,
) -> None:
    failure = _sdk_status_error(error_type, status_code)

    async def retrieve(_model: str) -> object:
        raise failure

    client = SimpleNamespace(models=SimpleNamespace(retrieve=retrieve))
    provider = AnthropicProvider("claude-test", client)  # type: ignore[arg-type]

    with pytest.raises(error_type) as raised:
        await provider.resolve_model_limits("claude-test")

    assert raised.value is failure


@pytest.mark.asyncio
async def test_anthropic_model_metadata_propagates_sdk_timeout() -> None:
    failure = APITimeoutError(
        request=httpx.Request("GET", "https://example.test/v1/models/claude-test")
    )

    async def retrieve(_model: str) -> object:
        raise failure

    client = SimpleNamespace(models=SimpleNamespace(retrieve=retrieve))
    provider = AnthropicProvider("claude-test", client)  # type: ignore[arg-type]

    with pytest.raises(APITimeoutError) as raised:
        await provider.resolve_model_limits("claude-test")

    assert raised.value is failure


@pytest.mark.asyncio
async def test_new_session_preflight_keeps_configured_budget_when_model_metadata_is_missing(
    tmp_path: Path,
) -> None:
    async def retrieve(_model: str) -> object:
        raise _sdk_status_error(SDKNotFoundError, 404)

    provider = AnthropicProvider(
        "claude-test",
        SimpleNamespace(models=SimpleNamespace(retrieve=retrieve)),  # type: ignore[arg-type]
    )
    project = tmp_path / "project"
    project.mkdir()
    config = EffectiveConfig(
        default_model="anthropic/test",
        providers={
            "anthropic": ProviderProfile(
                "anthropic",
                ProviderKind.ANTHROPIC,
                api_key="test-key",
            ),
        },
        models={
            "anthropic/test": ModelProfile(
                "anthropic/test",
                "anthropic",
                "claude-test",
                context_window=42_000,
                max_output_tokens=2_000,
            ),
        },
    )
    application = create_application(
        config,
        provider_builder=lambda _profile, _model: provider,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=project),
        storage_root=tmp_path / "sessions",
    )
    try:
        session = await application.ensure_session_async()

        assert session is not None
        assert application.status().context_status.budget_tokens == 42_000
        assert application.session_service is not None
        assert application.session_service.active_session is session
    finally:
        application.close()
