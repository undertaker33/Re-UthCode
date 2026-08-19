from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest

from uthcode.application import (
    EffectiveConfig,
    ModelProfile,
    ProviderKind,
    ProviderProfile,
    create_application,
    load_effective_config,
)
from uthcode.application.tools import ApplicationToolService
from uthcode.core.provider import (
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ModelLimits,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    Usage,
)
from uthcode.core.secrets import SecretValue
from uthcode.integrations.config.loader import (
    ConfigurationError,
    ConfigurationInitializationRequired,
    load_config_data,
)
from uthcode.integrations.tools.factory import create_default_tools
from uthcode.integrations.providers.fake import FakeProvider


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


def _write_user(home: Path, text: str) -> Path:
    path = home / ".uthcode" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _valid_config(*, provider: str = "fake", api_key: str = "") -> str:
    return f'''default_model = "m/ref"

[providers.{provider}]
kind = "fake"
api_key = "{api_key}"

[models."m/ref"]
provider = "{provider}"
remote_id = "remote-model"
'''


def test_first_run_template_is_three_blank_slots_and_stops(tmp_path: Path) -> None:
    home = tmp_path / "home"

    with pytest.raises(ConfigurationInitializationRequired) as raised:
        load_config_data(cwd=tmp_path, home=home)

    template = raised.value.template_path.read_text(encoding="utf-8")
    assert 'default_model = ""' in template
    assert 'default_permission_mode = "default"' in template
    assert all(f"[providers.slot-{index}]" in template for index in (1, 2, 3))
    assert all(f'[models."slot-{index}"]' in template for index in (1, 2, 3))
    assert "env:" in template
    assert template.count('# reasoning_effort = ""') == 3
    assert '# reasoning_effort = "medium"' not in template
    assert "delete unused slots" in template.lower()
    for forbidden in (
        "fake",
        "anthropic",
        "openai_responses",
        "openai_compat",
        "DEEPSEEK",
        "https://",
        "sk-",
        "literal-secret",
        "VARIABLE_NAME",
        "your-key",
    ):
        assert forbidden not in template


def test_empty_slots_are_ignored_but_partial_slots_fail(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user(
        home,
        '''default_model = "slot-1"

[providers.slot-1]
kind = "fake"
api_key = ""

[providers.slot-2]
kind = ""
api_key = ""

[models."slot-1"]
provider = "slot-1"
remote_id = "remote"

[models."slot-2"]
provider = ""
remote_id = ""
''',
    )

    data = load_config_data(cwd=tmp_path, home=home)
    assert tuple(data.providers) == ("slot-1",)
    assert tuple(data.models) == ("slot-1",)

    partial_provider = _write_user(
        home,
        '''default_model = "slot-1"
[providers.slot-1]
api_key = "literal"
[models."slot-1"]
provider = "slot-1"
remote_id = "remote"
''',
    )
    with pytest.raises(ConfigurationError) as provider_error:
        load_config_data(cwd=tmp_path, home=home)
    assert provider_error.value.path == partial_provider.resolve()
    assert provider_error.value.field == "providers.slot-1"

    _write_user(
        home,
        '''default_model = "slot-1"
[providers.slot-1]
kind = "fake"
[models."slot-1"]
provider = "slot-1"
''',
    )
    with pytest.raises(ConfigurationError, match="invalid Model profile"):
        load_config_data(cwd=tmp_path, home=home)


@pytest.mark.parametrize(
    "body",
    [
        'model = "m/ref"\n',
        '[models."m/ref"]\nprovider = "fake"\nmodel = "remote"\n',
        '[models."m/ref"]\nprovider = "fake"\nremote_id = "remote"\nlabel = "old"\n',
        '[providers.fake]\nkind = "fake"\napi_key_env = "OLD_KEY"\n',
    ],
)
def test_old_configuration_fields_fail_explicitly(tmp_path: Path, body: str) -> None:
    home = tmp_path / "home"
    _write_user(home, body)

    with pytest.raises(ConfigurationError) as raised:
        load_config_data(cwd=tmp_path, home=home)

    assert raised.value.field is not None
    assert "unsupported configuration field" in str(raised.value)


def test_api_key_literal_and_env_are_opaque_and_projects_cannot_define_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    literal = "literal-contract-secret-9"
    home = tmp_path / "home"
    user = _write_user(
        home,
        _valid_config(provider="remote", api_key=literal).replace(
            'kind = "fake"', 'kind = "openai_responses"'
        ),
    )
    data = load_config_data(cwd=tmp_path, home=home)
    secret = data.providers["remote"]["api_key"]
    assert isinstance(secret, SecretValue)
    assert secret.reveal() == literal
    assert literal not in repr(data)

    monkeypatch.setenv("CONTRACT_KEY", "env-contract-secret-7")
    _write_user(
        home,
        _valid_config(provider="remote", api_key="env:CONTRACT_KEY").replace(
            'kind = "fake"', 'kind = "openai_responses"'
        ),
    )
    env_data = load_config_data(cwd=tmp_path, home=home)
    assert env_data.providers["remote"]["api_key"].reveal() == "env-contract-secret-7"  # type: ignore[union-attr]

    root = tmp_path / "repo"
    cwd = root / "child"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    project = root / ".uthcode" / "config.toml"
    project.parent.mkdir()
    project.write_text(
        '[models."m/ref"]\napi_key = "project-secret"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError) as project_error:
        load_config_data(cwd=cwd, home=home)
    assert project.resolve() == project_error.value.path
    assert "project-secret" not in str(project_error.value)
    assert user.resolve() != project.resolve()


@pytest.mark.parametrize("value", ["env:BAD-NAME", "env:", "env:UNKNOWN_CONTRACT_KEY"])
def test_api_key_env_syntax_and_missing_values_fail_closed(
    tmp_path: Path,
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UNKNOWN_CONTRACT_KEY", raising=False)
    home = tmp_path / "home"
    _write_user(home, _valid_config(provider="remote", api_key=value).replace(
        'kind = "fake"', 'kind = "openai_responses"'
    ))

    with pytest.raises(ConfigurationError) as raised:
        load_config_data(cwd=tmp_path, home=home)
    assert "UNKNOWN_CONTRACT_KEY" not in str(raised.value)
    assert "BAD-NAME" not in str(raised.value)


def test_default_model_must_reference_an_enabled_model(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user(home, _valid_config().replace('default_model = "m/ref"', 'default_model = "missing"'))

    with pytest.raises(ConfigurationError, match="enabled Model profile"):
        load_config_data(cwd=tmp_path, home=home)


@pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high", "xhigh", "max"])
def test_reasoning_effort_is_a_generic_contract_value(tmp_path: Path, effort: str) -> None:
    home = tmp_path / "home"
    _write_user(
        home,
        _valid_config().replace(
            'remote_id = "remote-model"',
            f'remote_id = "remote-model"\nreasoning_effort = "{effort}"',
        ),
    )
    config = load_effective_config(cwd=tmp_path, home=home)
    assert config.current_model.reasoning_effort == effort


def test_reasoning_effort_invalid_or_unsupported_provider_fails_closed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user(
        home,
        _valid_config().replace(
            'remote_id = "remote-model"',
            'remote_id = "remote-model"\nreasoning_effort = "turbo"',
        ),
    )
    with pytest.raises(ConfigurationError, match="invalid Model profile"):
        load_config_data(cwd=tmp_path, home=home)

    _write_user(
        home,
        _valid_config(provider="anthropic", api_key="synthetic").replace(
            'kind = "fake"', 'kind = "anthropic"'
        ).replace(
            'remote_id = "remote-model"',
            'remote_id = "remote-model"\nreasoning_effort = "high"',
        ),
    )
    with pytest.raises(ValueError, match="does not support reasoning_effort"):
        load_effective_config(cwd=tmp_path, home=home)


def _completed() -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart("done"),)),
            usage=Usage(),
            finish_reason=FinishReason.STOP,
        )
    )


@pytest.mark.asyncio
async def test_direct_and_agent_run_use_remote_id_and_reasoning_snapshot() -> None:
    config = EffectiveConfig(
        default_model="logic/one",
        providers={
            "fake": ProviderProfile("fake", ProviderKind.FAKE),
        },
        models={
            "logic/one": ModelProfile("logic/one", "fake", "remote-one", reasoning_effort="high"),
            "logic/two": ModelProfile("logic/two", "fake", "remote-two", reasoning_effort="low"),
        },
    )
    providers: dict[str, FakeProvider] = {}

    def builder(_provider: object, model: object) -> FakeProvider:
        remote_id = model.remote_id  # type: ignore[attr-defined]
        provider = FakeProvider(
            identity=ProviderIdentity("fake", "script", remote_id),
            events=(_completed(),),
            model_limits=TEST_LIMITS,
        )
        providers[model.model_ref] = provider  # type: ignore[attr-defined]
        return provider

    application = create_application(config, provider_builder=builder)
    request = GenerationRequest(messages=(Message("user", (TextPart("hello"),)),))
    await _collect_direct(application, request)
    assert providers["logic/one"].recorded_requests[0].model == "remote-one"
    assert providers["logic/one"].recorded_requests[0].reasoning is not None
    assert providers["logic/one"].recorded_requests[0].reasoning.effort == "high"

    run = application.create_run()
    active = run.start_turn("snapshot")
    application.select_model("logic/two")
    await active.result()
    request_one = providers["logic/one"].recorded_requests[-1]
    assert request_one.model == "remote-one"
    assert request_one.reasoning is not None and request_one.reasoning.effort == "high"

    await run.start_turn("new model").result()
    request_two = providers["logic/two"].recorded_requests[-1]
    assert request_two.model == "remote-two"
    assert request_two.reasoning is not None and request_two.reasoning.effort == "low"


async def _collect_direct(application: object, request: GenerationRequest) -> None:
    async for _event in application.stream_generation(request):  # type: ignore[attr-defined]
        pass


def test_secret_value_never_serializes_or_leaks_through_tool_summary(tmp_path: Path) -> None:
    secret_text = "synthetic-config-secret-441"
    secret = SecretValue(secret_text)
    assert secret_text not in repr(secret)
    assert secret_text not in str(secret)
    with pytest.raises(TypeError):
        json.dumps({"credential": secret})
    with pytest.raises(TypeError):
        pickle.dumps(secret)

    service = ApplicationToolService(
        create_default_tools(tmp_path),
        workdir=tmp_path,
        secret_values=(secret,),
    )
    summary = service.describe_tool_call(
        ToolCallPart("call", "Bash", {"command": f"echo {secret_text}"})
    )
    assert secret_text not in summary
    assert "<redacted>" in summary
