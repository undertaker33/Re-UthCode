from __future__ import annotations

import socket

import pytest

from uthcode.application import UthCodeApplication
from uthcode.core.provider import (
    GenerationRequest,
    Message,
    MissingSecretError,
    ProviderConfigurationError,
    ProviderIdentity,
    TextPart,
)
from uthcode.core.secrets import SecretValue
from uthcode.integrations.providers.config import ProviderConfig, ProviderKind
from uthcode.integrations.providers.factory import create_provider
from uthcode.integrations.providers.fake import FakeProvider


def _request() -> GenerationRequest:
    return GenerationRequest(messages=(Message("user", (TextPart("hello"),)),))


@pytest.mark.parametrize(
    ("config", "identity"),
    [
        (
            ProviderConfig(kind=ProviderKind.FAKE, model="fake-model"),
            ProviderIdentity("fake", "script", "fake-model"),
        ),
        (
            ProviderConfig(
                kind=ProviderKind.ANTHROPIC,
                model="deepseek-test",
                api_key="sk-factory-test-secret",
                base_url="https://mock.invalid/anthropic",
            ),
            ProviderIdentity("anthropic", "messages", "deepseek-test"),
        ),
        (
            ProviderConfig(
                kind=ProviderKind.OPENAI_RESPONSES,
                model="deepseek-test",
                api_key="sk-factory-test-secret",
                base_url="https://mock.invalid/v1",
            ),
            ProviderIdentity("openai", "responses", "deepseek-test"),
        ),
        (
            ProviderConfig(
                kind=ProviderKind.OPENAI_COMPAT,
                model="deepseek-test",
                api_key="sk-factory-test-secret",
                base_url="https://mock.invalid/v1",
            ),
            ProviderIdentity("openai", "chat_completions", "deepseek-test"),
        ),
    ],
)
def test_factory_constructs_each_provider_without_network(
    config: ProviderConfig,
    identity: ProviderIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def blocked(*_args: object, **_kwargs: object) -> None:
        attempts.append("network")
        raise AssertionError("provider construction must not access the network")

    secret = "sk-factory-test-secret"

    with monkeypatch.context() as socket_patch:
        socket_patch.setattr(socket, "create_connection", blocked)
        socket_patch.setattr(socket.socket, "connect", blocked)
        socket_patch.setattr(socket.socket, "connect_ex", blocked)
        provider = create_provider(config)

    assert provider.identity == identity
    assert attempts == []
    assert secret not in repr(config)
    assert secret not in repr(provider)
    assert secret not in str(provider)


def test_fake_provider_does_not_require_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    provider = create_provider(
        ProviderConfig(kind=ProviderKind.FAKE, model="fake-model")
    )

    assert isinstance(provider, FakeProvider)
    assert provider.identity == ProviderIdentity("fake", "script", "fake-model")


@pytest.mark.parametrize(
    "kind",
    [ProviderKind.ANTHROPIC, ProviderKind.OPENAI_RESPONSES, ProviderKind.OPENAI_COMPAT],
)
def test_missing_secret_fails_with_only_safe_field_name(
    kind: ProviderKind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_variable = "api_key"
    config = ProviderConfig(
        kind=kind,
        model="test-model",
        api_key=None,
        base_url="https://mock.invalid/v1" if kind is not ProviderKind.ANTHROPIC else None,
    )

    with pytest.raises(MissingSecretError) as raised:
        create_provider(config)

    assert raised.value.environment_variable == environment_variable
    assert str(raised.value) == f"Provider credential is missing: {environment_variable}"
    assert "sk-factory-test-secret" not in repr(config)
    assert "sk-factory-test-secret" not in repr(raised.value)


@pytest.mark.parametrize("base_url", [None])
def test_openai_compatible_provider_requires_explicit_base_url(
    base_url: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ProviderConfig(
        kind=ProviderKind.OPENAI_COMPAT,
        model="test-model",
        api_key=SecretValue("sk-factory-test-secret"),
        base_url=base_url,
    )

    with pytest.raises(ProviderConfigurationError, match="base URL"):
        create_provider(config)


def test_provider_configuration_rejects_unknown_reasoning_effort_and_unsupported_kind() -> None:
    with pytest.raises(ValueError, match="reasoning_effort"):
        ProviderConfig(
            kind=ProviderKind.OPENAI_RESPONSES,
            model="test-model",
            api_key=SecretValue("synthetic"),
            reasoning_effort="turbo",
        )

    config = ProviderConfig(
        kind=ProviderKind.ANTHROPIC,
        model="test-model",
        api_key=SecretValue("synthetic"),
        reasoning_effort="high",
    )
    with pytest.raises(ProviderConfigurationError, match="does not support reasoning_effort"):
        create_provider(config)


def test_provider_constructor_exception_cannot_echo_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "constructor-secret-891"
    config = ProviderConfig(
        kind=ProviderKind.OPENAI_RESPONSES,
        model="test-model",
        api_key=SecretValue(secret),
        base_url="https://mock.invalid/v1",
    )

    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(secret)

    import uthcode.integrations.providers.factory as factory

    monkeypatch.setattr(factory, "build_openai_responses_provider", fail)
    with pytest.raises(ProviderConfigurationError, match="construction failed") as raised:
        create_provider(config)
    assert secret not in str(raised.value)
    assert secret not in repr(raised.value)


def test_config_rejects_unknown_kind_and_does_not_store_secret() -> None:
    with pytest.raises(ValueError, match="unknown provider kind"):
        ProviderConfig(kind="future-provider", model="test-model")

    config = ProviderConfig(kind="fake", model="test-model")
    assert config.api_key is None
    assert config.kind is ProviderKind.FAKE


def test_factory_instances_do_not_share_fake_state() -> None:
    config = ProviderConfig(kind=ProviderKind.FAKE, model="fake-model")
    first = create_provider(config)
    second = create_provider(config)

    assert isinstance(first, FakeProvider)
    assert isinstance(second, FakeProvider)
    first.requests.append(_request())

    assert first is not second
    assert len(first.recorded_requests) == 1
    assert second.recorded_requests == ()


def test_factory_provider_can_enter_the_headless_application() -> None:
    provider = create_provider(
        ProviderConfig(kind=ProviderKind.FAKE, model="factory-fake")
    )
    application = UthCodeApplication(provider)

    assert application.provider is provider
