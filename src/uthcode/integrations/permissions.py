"""Permission rule file lifecycle, parsing, and default application guards."""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tomlkit import parse

from uthcode.core.permission import (
    CircuitBreaker,
    Decision,
    Effect,
    ResourceScope,
    Rule,
    RuleAuthority,
    RuleKind,
    RuleSet,
)

from .config.loader import (
    discover_scoped_paths,
    physical_path,
    resolve_user_home,
)


class PermissionConfigurationError(ValueError):
    """A permission source cannot be safely loaded or evaluated."""

    def __init__(
        self,
        message: str,
        *,
        path: Path | None = None,
        field: str | None = None,
    ) -> None:
        self.message = message
        self.path = path
        self.field = field
        parts: list[str] = []
        if path is not None:
            parts.append(str(path))
        if field is not None:
            parts.append(field)
        prefix = ": ".join(parts)
        super().__init__(f"{prefix}: {message}" if prefix else message)


BASH_GUARD_FACT_MARKER = "__uthcode_guard_fact__"
BASH_ACTION_FACT_MARKER = "__uthcode_bash_action__"
BASH_SENSITIVE_TARGET_MARKER = "__uthcode_bash_sensitive_target__"


_SENSITIVE_RESOURCE_REGEX = (
    r"(?i)(?:"
    r"(?<![A-Za-z0-9_])\.env(?:\.(?!example(?:$|[/\s:,\]\)]))[^\s/]+)?"
    r"(?=$|[/\s:,\]\)])"
    r"|(?:^|[/\s])\.ssh(?:[/\s]|$)"
    r"|(?:^|[/\s])(?:\.aws/credentials|\.config/gcloud|"
    r"\.azure/[^/\s]+|\.kube/config|\.docker/config\.json|"
    r"\.config/gh/hosts\.yml|\.git-credentials|\.netrc|\.npmrc|\.pypirc)"
    r"(?=$|[/\s:,\]\)])"
    r"|(?:^|[/\s])[^/\s]*(?:\.pem|\.key)(?=$|[/\s:,\]\)])"
    r"|(?:^|[/\s])(?:id_(?:rsa|ed25519|ecdsa|dsa)|private[_-]?key)"
    r"(?=$|[/\s:,\]\)])"
    r")"
)
_SENSITIVE_RESOURCE_PATTERN = re.compile(_SENSITIVE_RESOURCE_REGEX)
_BASH_SENSITIVE_RESOURCE_REGEX = (
    rf"(?i)\[{re.escape(BASH_ACTION_FACT_MARKER)}:"
    rf"(?:content-read|content-search|write|mixed|unknown)\]"
    rf"\s*\[{re.escape(BASH_SENSITIVE_TARGET_MARKER)}\]"
)


def is_sensitive_resource(resource: str) -> bool:
    """Return whether a display-safe resource summary names secret material."""

    if not isinstance(resource, str):
        return False
    normalized = resource.replace("\\", "/")
    return _SENSITIVE_RESOURCE_PATTERN.search(normalized) is not None


_BASH_GUARD_REGEXES: tuple[tuple[str, str], ...] = (
    (
        "default-bash-segment-guard-fact",
        rf"(?i)\[{re.escape(BASH_GUARD_FACT_MARKER)}:[a-z0-9-]+(?:,[a-z0-9-]+)*\]",
    ),
)


def default_guard_rules() -> tuple[Rule, ...]:
    """Return the immutable default Guard seed used below user rules."""

    rules: list[Rule] = [
        Rule(
            kind=RuleKind.GUARD,
            decision=Decision.ASK,
            source="default",
            priority=0,
            rule_id=f"default-sensitive-{tool}",
            tool=tool,
            action=action,
            resource_regex=_SENSITIVE_RESOURCE_REGEX,
            authority=RuleAuthority.BUILTIN,
        )
        for tool, action in (
            ("ReadFile", "read"),
            ("WriteFile", "write"),
            ("EditFile", "edit"),
            ("Grep", "grep"),
        )
    ]
    rules.append(
        Rule(
            kind=RuleKind.GUARD,
            decision=Decision.ASK,
            source="default",
            priority=0,
            rule_id="default-sensitive-Bash",
            tool="Bash",
            action="execute",
            resource_regex=_BASH_SENSITIVE_RESOURCE_REGEX,
            authority=RuleAuthority.BUILTIN,
        )
    )
    rules.extend(
        Rule(
            kind=RuleKind.GUARD,
            decision=Decision.ASK,
            source="default",
            priority=0,
            rule_id=rule_id,
            tool="Bash",
            action="execute",
            resource_regex=pattern,
            authority=RuleAuthority.BUILTIN,
        )
        for rule_id, pattern in _BASH_GUARD_REGEXES
    )
    rules.extend(
        Rule(
            kind=RuleKind.GUARD,
            decision=Decision.ASK,
            source="default",
            priority=0,
            rule_id=f"default-circuit-breaker-{breaker.value}",
            tool="Bash",
            action="execute",
            authority=RuleAuthority.CIRCUIT_BREAKER,
            circuit_breaker=breaker,
        )
        for breaker in CircuitBreaker
    )
    return tuple(rules)


PERMISSIONS_USER_TEMPLATE = f"""# UthCode permission rules for the current user
#
# Guard rules written here run in every permission mode. Built-in ordinary
# guards are skipped by full_access; catastrophic circuit breakers are not.
# Policy rules are ignored only by full_access. Approvals never persist rules.
# A resource_regex is matched against a normalized, display-safe action summary.

[guard]
# Add explicit user Guard rules here when they must remain active in full_access.

[policy]
# Example:
# [[policy.rules]]
# id = "allow-readme-write"
# decision = "ask"
# tool = "WriteFile"
# action = "write"
# effect = "write"
# resource = "README.md"
"""

PROJECT_PERMISSION_PLACEHOLDER = "# Project-specific permission rules.\n"


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _atomic_create(path: Path, content: str) -> Path:
    target = physical_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _chmod_private(temporary)
        os.replace(temporary, target)
        _chmod_private(target)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return target


def _ensure_file(path: Path, content: str, *, user: bool) -> Path:
    target = physical_path(path)
    if target.is_file():
        return target
    if target.exists():
        raise PermissionConfigurationError(
            "permission path is not a file",
            path=target,
        )
    try:
        return _atomic_create(target, content)
    except Exception:
        label = "user" if user else "project"
        raise PermissionConfigurationError(
            f"{label} permission file could not be created",
            path=target,
        ) from None


def discover_permission_paths(
    *,
    cwd: str | os.PathLike[str] | Path | None = None,
    home: str | os.PathLike[str] | Path | None = None,
) -> tuple[tuple[str, Path], ...]:
    """Create missing lifecycle files and return the stable source snapshot."""

    cwd_path = physical_path(cwd or Path.cwd())
    home_path = resolve_user_home(physical_path(home) if home is not None else None)
    user_path = _ensure_file(
        home_path / ".uthcode" / "permissions.toml",
        PERMISSIONS_USER_TEMPLATE,
        user=True,
    )
    _ensure_file(
        cwd_path / ".uthcode" / "permissions.toml",
        PROJECT_PERMISSION_PLACEHOLDER,
        user=False,
    )
    return discover_scoped_paths(
        cwd_path,
        user_path,
        ".uthcode/permissions.toml",
    )


def _plain(value: Any) -> Any:
    unwrap = getattr(value, "unwrap", None)
    if callable(unwrap):
        value = unwrap()
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _read_permission_mapping(path: Path) -> Mapping[str, Any]:
    try:
        document = parse(path.read_text(encoding="utf-8"))
        plain = _plain(document)
    except Exception:
        raise PermissionConfigurationError(
            "permission file cannot be parsed",
            path=path,
        ) from None
    if not isinstance(plain, Mapping):
        raise PermissionConfigurationError(
            "permission file root must be a table",
            path=path,
        )
    return plain


def _normalize_resource(value: str, *, path: Path, field: str) -> str:
    if "\x00" in value:
        raise PermissionConfigurationError("resource contains a null byte", path=path, field=field)
    normalized = value.replace("\\", "/")
    return os.path.normpath(normalized).replace("\\", "/")


def _required_text(value: Any, *, path: Path, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PermissionConfigurationError("value must be a non-empty string", path=path, field=field)
    return value.strip()


def _enum_text(value: Any, enum_type: type[Decision] | type[Effect] | type[ResourceScope], *, path: Path, field: str) -> Any:
    text = _required_text(value, path=path, field=field).lower()
    try:
        return enum_type(text)
    except ValueError:
        allowed = ", ".join(item.value for item in enum_type)
        raise PermissionConfigurationError(
            f"value must be one of: {allowed}",
            path=path,
            field=field,
        ) from None


def _parse_rule(
    raw: Any,
    *,
    kind: RuleKind,
    index: int,
    path: Path,
    source: str,
    priority: int,
) -> Rule:
    if not isinstance(raw, Mapping):
        raise PermissionConfigurationError(
            "rule must be a table",
            path=path,
            field=f"{kind.value}.rules[{index}]",
        )
    allowed = {
        "id",
        "decision",
        "tool",
        "action",
        "effect",
        "resource",
        "resource_regex",
        "scope",
        "resource_prefix",
    }
    field_prefix = f"{kind.value}.rules[{index}]"
    unknown = set(raw) - allowed
    if unknown:
        name = sorted(str(item) for item in unknown)[0]
        raise PermissionConfigurationError(
            "unsupported rule field",
            path=path,
            field=f"{field_prefix}.{name}",
        )

    decision = _enum_text(raw.get("decision"), Decision, path=path, field=f"{field_prefix}.decision")
    rule_id = raw.get("id", f"{kind.value}-{index + 1}")
    rule_id = _required_text(rule_id, path=path, field=f"{field_prefix}.id")

    tool = raw.get("tool")
    action = raw.get("action")
    effect = raw.get("effect")
    resource = raw.get("resource")
    resource_regex = raw.get("resource_regex")
    scope = raw.get("scope")
    resource_prefix = raw.get("resource_prefix", False)

    if tool is not None:
        tool = _required_text(tool, path=path, field=f"{field_prefix}.tool")
    if action is not None:
        action = _required_text(action, path=path, field=f"{field_prefix}.action")
    if effect is not None:
        effect = _enum_text(effect, Effect, path=path, field=f"{field_prefix}.effect")
    if scope is not None:
        scope = _enum_text(scope, ResourceScope, path=path, field=f"{field_prefix}.scope")
    if resource is not None:
        resource = _normalize_resource(
            _required_text(resource, path=path, field=f"{field_prefix}.resource"),
            path=path,
            field=f"{field_prefix}.resource",
        )
    if resource_regex is not None:
        resource_regex = _required_text(
            resource_regex,
            path=path,
            field=f"{field_prefix}.resource_regex",
        )
        try:
            re.compile(resource_regex)
        except re.error:
            raise PermissionConfigurationError(
                "resource_regex cannot be compiled",
                path=path,
                field=f"{field_prefix}.resource_regex",
            ) from None
    if resource is not None and resource_regex is not None:
        raise PermissionConfigurationError(
            "resource and resource_regex are mutually exclusive",
            path=path,
            field=field_prefix,
        )
    if isinstance(resource_prefix, bool) is False:
        raise PermissionConfigurationError(
            "resource_prefix must be a boolean",
            path=path,
            field=f"{field_prefix}.resource_prefix",
        )
    if resource_prefix and resource is None:
        raise PermissionConfigurationError(
            "resource_prefix requires resource",
            path=path,
            field=f"{field_prefix}.resource_prefix",
        )
    if not any(value is not None for value in (tool, action, effect, resource, resource_regex, scope)):
        raise PermissionConfigurationError(
            "rule must define at least one match target",
            path=path,
            field=field_prefix,
        )

    try:
        return Rule(
            kind=kind,
            decision=decision,
            source=source,
            priority=priority,
            rule_id=rule_id,
            tool=tool,
            action=action,
            effect=effect,
            resource=resource,
            resource_regex=resource_regex,
            scope=scope,
            resource_prefix=resource_prefix,
        )
    except (TypeError, ValueError):
        raise PermissionConfigurationError(
            "rule fields are invalid",
            path=path,
            field=field_prefix,
        ) from None


def parse_permission_file(
    path: str | os.PathLike[str] | Path,
    *,
    source: str,
    priority: int,
) -> tuple[Rule, ...]:
    """Parse and validate one permissions.toml source into Core Rules."""

    file_path = physical_path(path)
    mapping = _read_permission_mapping(file_path)
    allowed_sections = {"guard", "policy"}
    unknown = set(mapping) - allowed_sections
    if unknown:
        name = sorted(str(item) for item in unknown)[0]
        raise PermissionConfigurationError(
            "unsupported permission section",
            path=file_path,
            field=name,
        )

    rules: list[Rule] = []
    for kind in (RuleKind.GUARD, RuleKind.POLICY):
        section = mapping.get(kind.value, {})
        if not isinstance(section, Mapping):
            raise PermissionConfigurationError(
                "section must be a table",
                path=file_path,
                field=kind.value,
            )
        if set(section) - {"rules"}:
            name = sorted(str(item) for item in set(section) - {"rules"})[0]
            raise PermissionConfigurationError(
                "unsupported permission section field",
                path=file_path,
                field=f"{kind.value}.{name}",
            )
        raw_rules = section.get("rules", [])
        if not isinstance(raw_rules, list):
            raise PermissionConfigurationError(
                "rules must be an array of tables",
                path=file_path,
                field=f"{kind.value}.rules",
            )
        for index, raw_rule in enumerate(raw_rules):
            rules.append(
                _parse_rule(
                    raw_rule,
                    kind=kind,
                    index=index,
                    path=file_path,
                    source=source,
                    priority=priority,
                )
            )
    return tuple(rules)


def load_permission_rules(
    *,
    cwd: str | os.PathLike[str] | Path | None = None,
    home: str | os.PathLike[str] | Path | None = None,
) -> RuleSet:
    """Create files if needed and return one immutable permission snapshot."""

    paths = discover_permission_paths(cwd=cwd, home=home)
    rules: list[Rule] = list(default_guard_rules())
    project_index = 0
    for kind, path in paths:
        if kind == "user":
            source = "user"
            priority = 10
        else:
            source = f"project:{path}"
            priority = 20 + project_index
            project_index += 1
        rules.extend(
            parse_permission_file(
                path,
                source=source,
                priority=priority,
            )
        )
    return RuleSet(tuple(rules))


__all__ = [
    "BASH_ACTION_FACT_MARKER",
    "BASH_GUARD_FACT_MARKER",
    "BASH_SENSITIVE_TARGET_MARKER",
    "PERMISSIONS_USER_TEMPLATE",
    "PROJECT_PERMISSION_PLACEHOLDER",
    "PermissionConfigurationError",
    "default_guard_rules",
    "discover_permission_paths",
    "is_sensitive_resource",
    "load_permission_rules",
    "parse_permission_file",
]
