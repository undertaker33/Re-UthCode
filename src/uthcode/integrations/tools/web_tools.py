"""Bounded Web Search and Fetch Integration tools.

The tools keep all SDK/HTTP/parser objects in ``integrations``.  Search uses
the fixed Tavily basic endpoint; Fetch downloads bytes locally before running
the optional text extractor.  Neither tool receives conversation history or
browser credentials.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import re
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from uthcode.core.permission import Decision, Effect, PermissionAction, PermissionDecision, ResourceScope
from uthcode.core.provider import CancellationToken, JsonPayload, ToolDefinition
from uthcode.core.tool import (
    ToolExecutionResult,
    ToolFailure,
    ToolFailureKind,
    ToolPlanningAccess,
    ToolPreparation,
    ToolSideEffect,
)
from uthcode.core.secrets import SecretValue


TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5
_DEFAULT_MAX_FETCH_BYTES = 2 * 1024 * 1024
_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})


@dataclass(frozen=True, slots=True)
class _SearchSettings:
    """Small Integration-side snapshot of the Application search contract.

    Keeping this adapter local avoids a reverse dependency from Integrations
    into Application.  The formal bootstrap passes ``EffectiveConfig.search``
    while direct tests and embedders may provide a plain mapping.
    """

    enabled: bool = False
    provider: str = "tavily"
    api_key: SecretValue | str | None = None
    max_results: int = 5
    max_fetch_bytes: int = _DEFAULT_MAX_FETCH_BYTES
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("search.enabled must be a boolean")
        if not isinstance(self.provider, str) or self.provider.casefold() != "tavily":
            raise ValueError("search.provider must be tavily")
        if isinstance(self.api_key, str):
            object.__setattr__(self, "api_key", SecretValue(self.api_key) if self.api_key.strip() else None)
        elif self.api_key is not None and not isinstance(self.api_key, SecretValue):
            raise TypeError("search.api_key must be a SecretValue or string")
        if isinstance(self.max_results, bool) or not isinstance(self.max_results, int) or not 1 <= self.max_results <= 20:
            raise ValueError("search.max_results must be between 1 and 20")
        if isinstance(self.max_fetch_bytes, bool) or not isinstance(self.max_fetch_bytes, int) or not 1 <= self.max_fetch_bytes <= 16 * 1024 * 1024:
            raise ValueError("search.max_fetch_bytes is outside the bounded range")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not 0 < self.timeout_seconds <= 120:
            raise ValueError("search.timeout_seconds is outside the bounded range")

    @classmethod
    def from_value(cls, value: object) -> "_SearchSettings":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            raw = dict(value)
            key = raw.get("api_key")
            # ``api_key_configured`` is a safe settings projection.  It must
            # never be treated as a credential and therefore leaves the tool
            # unavailable when no opaque SecretValue was supplied.
            if key is None and raw.get("api_key_configured") is True:
                key = None
            return cls(
                enabled=raw.get("enabled", False),
                provider=raw.get("provider", "tavily"),
                api_key=key,
                max_results=raw.get("max_results", 5),
                max_fetch_bytes=raw.get("max_fetch_bytes", _DEFAULT_MAX_FETCH_BYTES),
                timeout_seconds=raw.get("timeout_seconds", 20.0),
            )
        return cls(
            enabled=getattr(value, "enabled", False),
            provider=getattr(value, "provider", "tavily"),
            api_key=getattr(value, "api_key", None),
            max_results=getattr(value, "max_results", 5),
            max_fetch_bytes=getattr(value, "max_fetch_bytes", _DEFAULT_MAX_FETCH_BYTES),
            timeout_seconds=getattr(value, "timeout_seconds", 20.0),
        )


@dataclass(frozen=True, slots=True)
class WebSource:
    """Safe source metadata attached to a Web result."""

    requested_url: str
    final_url: str
    title: str | None = None
    fetched_at: str | None = None
    content_type: str | None = None
    status_code: int | None = None
    position: str | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
        }
        for name in ("title", "fetched_at", "content_type", "status_code", "position"):
            item = getattr(self, name)
            if item is not None:
                value[name] = item
        return value


def _failure(
    message: str,
    kind: ToolFailureKind | str,
    *,
    retryable: bool = False,
    details: Mapping[str, object] | None = None,
    side_effect: ToolSideEffect = ToolSideEffect.NONE,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        message,
        is_error=True,
        failure=ToolFailure(str(getattr(kind, "value", kind)), retryable=retryable),
        side_effect=side_effect,
        details={} if details is None else details,
    )


def _cancelled() -> ToolExecutionResult:
    return _failure(
        "Error: tool call cancelled",
        ToolFailureKind.CANCELLED,
        retryable=True,
    )


def _bounded_text(value: object, limit: int = 512) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", value)
    value = " ".join(value.split())
    return value[:limit]


def _validate_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Error: url must be a non-empty string")
    if "\x00" in value:
        raise ValueError("Error: url contains a null byte")
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Error: only HTTP(S) URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Error: URL credentials are not supported")
    if parsed.fragment:
        parsed = parsed._replace(fragment="")
    return urlunsplit(parsed)


def _host_is_public(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.rstrip(".").lower()
    if normalized in {"localhost", "localhost.localdomain", "127.0.0.1", "::1"}:
        return False
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        # Avoid DNS resolution inside the tool.  An explicit redirect
        # authorizer may apply a stricter policy after this lexical check.
        return not normalized.endswith((".local", ".internal", ".localhost"))
    return not (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved)


def _safe_public_url(url: str) -> bool:
    return _host_is_public(urlsplit(url).hostname)


async def _authorized_redirect(
    callback: Callable[..., object] | None,
    url: str,
    *,
    cancellation: CancellationToken,
) -> bool:
    if not _safe_public_url(url):
        return False
    approved = getattr(cancellation, "_uthcode_web_approved_redirect", None)
    if isinstance(approved, PermissionAction) and approved.resource == url:
        delattr(cancellation, "_uthcode_web_approved_redirect")
        return True
    if callback is None:
        # A formal Application always injects the current Run resolver.  A
        # direct Integration embed without one must fail closed at a hop.
        return False
    try:
        value = callback(url, cancellation)
    except TypeError:
        # Preserve the small one-argument callback contract used by direct
        # embedders while formal bootstrap uses the execution token.
        value = callback(url)
    if asyncio.iscoroutine(value) or isinstance(value, Awaitable):
        value = await value
    if isinstance(value, PermissionDecision):
        if value.decision is Decision.ASK:
            raise RedirectPermissionRequired(value.action)
        return value.decision is Decision.ALLOW
    return value is True


class RedirectPermissionRequired(RuntimeError):
    """One redirect hop needs the current Run's Application approval."""

    def __init__(self, action: PermissionAction) -> None:
        self.action = action
        super().__init__("redirect permission approval required")


async def _request_with_cancellation(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    cancellation: CancellationToken,
    **kwargs: object,
) -> httpx.Response:
    """Race one HTTP operation against the Application cancellation token."""

    request_task = asyncio.create_task(client.request(method, url, **kwargs))
    cancel_task = asyncio.create_task(cancellation.wait())
    done, pending = await asyncio.wait(
        {request_task, cancel_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    if cancel_task in done or cancellation.cancelled:
        request_task.cancel()
        try:
            await request_task
        except asyncio.CancelledError:
            pass
        raise asyncio.CancelledError
    return request_task.result()


def _client(
    *,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        transport=transport,
        headers={"User-Agent": "uthcode/0.1"},
    )


class TavilySearchTool:
    """Search Tavily with a user-level opaque SecretValue."""

    _definition = ToolDefinition(
        "WebSearch",
        "Search public web sources with the configured Tavily basic search service.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 4000},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                "domains": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "maxItems": 20,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )

    def __init__(
        self,
        configuration: Mapping[str, object] | object | None,
        *,
        endpoint: str = TAVILY_SEARCH_ENDPOINT,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: Callable[..., httpx.AsyncClient] | None = None,
    ) -> None:
        self._configuration = _SearchSettings.from_value(configuration)
        if self._configuration.provider != "tavily":
            raise ValueError("search provider is fixed to tavily")
        if endpoint != TAVILY_SEARCH_ENDPOINT:
            raise ValueError("Tavily endpoint is fixed")
        self._endpoint = endpoint
        self._transport = transport
        self._client_factory = client_factory

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.READ_ONLY

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Error: query must be a non-empty string")
        return ToolPreparation(
            action=PermissionAction(
                tool=self._definition.name,
                action="search",
                effect=Effect.EXTERNAL,
                resource=self._endpoint,
                scope=ResourceScope.OUTSIDE,
            ),
            execution_arguments=arguments,
        )

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        if cancellation.cancelled:
            return _cancelled()
        config = self._configuration
        if not config.enabled or config.api_key is None:
            return _failure(
                "Error: WebSearch is unavailable because search is not configured",
                ToolFailureKind.UNAVAILABLE,
                retryable=False,
            )
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            return _failure("Error: query must be a non-empty string of at most 4000 characters", ToolFailureKind.INVALID_INPUT)
        max_results = arguments.get("max_results", config.max_results)
        if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= min(20, config.max_results):
            return _failure("Error: max_results exceeds the configured search limit", ToolFailureKind.INVALID_INPUT)
        domains = arguments.get("domains")
        if domains is not None and (
            isinstance(domains, (str, bytes, bytearray))
            or not isinstance(domains, (list, tuple))
            or len(domains) > 20
            or not all(isinstance(item, str) and item.strip() for item in domains)
        ):
            return _failure("Error: domains must be a list of non-empty strings", ToolFailureKind.INVALID_INPUT)
        key = config.api_key
        if not isinstance(key, SecretValue):
            key = SecretValue(key)
        payload: dict[str, object] = {
            "api_key": key.reveal(),
            "query": query.strip(),
            "search_depth": "basic",
            "auto_parameters": False,
            "include_answer": False,
            "include_usage": True,
            "max_results": max_results,
        }
        if domains:
            payload["include_domains"] = list(domains)
        try:
            factory = self._client_factory or _client
            async with factory(timeout=config.timeout_seconds, transport=self._transport) as client:
                response = await _request_with_cancellation(
                    client,
                    "POST",
                    self._endpoint,
                    cancellation=cancellation,
                    json=payload,
                )
                if response.status_code == 429:
                    return _failure("Error: Tavily rate limit or credits exhausted", ToolFailureKind.RESOURCE_LIMIT, retryable=True)
                if response.status_code in {401, 403}:
                    return _failure("Error: Tavily authentication was rejected", ToolFailureKind.PERMISSION_DENIED)
                if response.status_code >= 400:
                    return _failure(f"Error: Tavily request failed with HTTP {response.status_code}", ToolFailureKind.NETWORK_ERROR, retryable=response.status_code >= 500)
                raw = response.content
        except asyncio.CancelledError:
            return _cancelled()
        except httpx.TimeoutException:
            return _failure("Error: Tavily request timed out", ToolFailureKind.TIMEOUT, retryable=True)
        except httpx.HTTPError:
            return _failure("Error: Tavily request failed", ToolFailureKind.NETWORK_ERROR, retryable=True)
        except Exception:
            return _failure("Error: Tavily service is unavailable", ToolFailureKind.UNAVAILABLE, retryable=True)
        if len(raw) > config.max_fetch_bytes:
            return _failure("Error: Tavily response exceeds the configured limit", ToolFailureKind.RESOURCE_LIMIT)
        try:
            document = response.json()
        except (ValueError, json.JSONDecodeError):
            return _failure("Error: Tavily returned invalid JSON", ToolFailureKind.NETWORK_ERROR)
        if not isinstance(document, Mapping):
            return _failure("Error: Tavily returned an invalid response", ToolFailureKind.NETWORK_ERROR)
        rows = document.get("results", [])
        if not isinstance(rows, list):
            return _failure("Error: Tavily returned invalid results", ToolFailureKind.NETWORK_ERROR)
        projected: list[dict[str, object]] = []
        sources: list[dict[str, object]] = []
        for raw_row in rows[:max_results]:
            if not isinstance(raw_row, Mapping):
                continue
            url = raw_row.get("url")
            if not isinstance(url, str):
                continue
            try:
                safe_url = _validate_url(url)
            except ValueError:
                continue
            source = WebSource(
                requested_url=safe_url,
                final_url=safe_url,
                title=_bounded_text(raw_row.get("title")) or None,
                position="search-result",
            )
            sources.append(source.to_dict())
            row: dict[str, object] = {"title": source.title or "", "url": safe_url}
            for key_name in ("content", "published_date", "score"):
                value = raw_row.get(key_name)
                if isinstance(value, (str, int, float)):
                    row[key_name] = _bounded_text(value) if isinstance(value, str) else value
            projected.append(row)
        usage = document.get("usage")
        usage_value = usage if isinstance(usage, Mapping) else None
        result = {
            "query": query.strip(),
            "results": projected,
            "sources": sources,
            "usage": dict(usage_value) if usage_value is not None else {"credits": None, "known": False},
        }
        return ToolExecutionResult(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            details={"sources": sources, "usage": result["usage"]},
        )


class FetchWebTool:
    """Download one public HTTP(S) URL with explicit redirect hops."""

    _definition = ToolDefinition(
        "WebFetch",
        "Fetch a bounded public HTTP(S) page or PDF and extract local text.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string", "minLength": 1},
                "max_bytes": {"type": "integer", "minimum": 1024, "maximum": 16 * 1024 * 1024},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    )

    def __init__(
        self,
        *,
        max_bytes: int = _DEFAULT_MAX_FETCH_BYTES,
        timeout_seconds: float = 20.0,
        max_redirects: int = _MAX_REDIRECTS,
        redirect_authorizer: Callable[..., object] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: Callable[..., httpx.AsyncClient] | None = None,
        asset_writer: Callable[[str, bytes, str, str], Mapping[str, object]] | None = None,
    ) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = min(max_bytes, 16 * 1024 * 1024)
        self._timeout = max(0.1, min(float(timeout_seconds), 120.0))
        self._max_redirects = max(0, min(max_redirects, _MAX_REDIRECTS))
        self._redirect_authorizer = redirect_authorizer
        self._transport = transport
        self._client_factory = client_factory
        self._asset_writer = asset_writer

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.READ_ONLY

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        url = _validate_url(arguments.get("url"))
        if not _safe_public_url(url):
            raise ValueError("Error: URL target is not a public address")
        return ToolPreparation(
            action=PermissionAction(
                tool=self._definition.name,
                action="fetch",
                effect=Effect.EXTERNAL,
                resource=url,
                scope=ResourceScope.OUTSIDE,
            ),
            execution_arguments=arguments,
        )

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        if cancellation.cancelled:
            return _cancelled()
        try:
            requested_url = _validate_url(arguments.get("url"))
            max_bytes = arguments.get("max_bytes", self._max_bytes)
            if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1024 or max_bytes > self._max_bytes:
                return _failure("Error: max_bytes exceeds the configured fetch limit", ToolFailureKind.INVALID_INPUT)
            if not _safe_public_url(requested_url):
                return _failure("Error: URL target is not a public address", ToolFailureKind.PERMISSION_DENIED)
        except ValueError as exc:
            return _failure(str(exc), ToolFailureKind.INVALID_INPUT)
        current = requested_url
        redirects = 0
        pending = getattr(cancellation, "_uthcode_web_pending_redirect", None)
        if isinstance(pending, Mapping) and pending.get("requested_url") == requested_url:
            target = pending.get("target")
            pending_redirects = pending.get("redirects")
            if isinstance(target, str) and isinstance(pending_redirects, int):
                current = target
                redirects = pending_redirects
            delattr(cancellation, "_uthcode_web_pending_redirect")
        try:
            factory = self._client_factory or _client
            async with factory(timeout=self._timeout, transport=self._transport) as client:
                while True:
                    response = await _request_with_cancellation(
                        client,
                        "GET",
                        current,
                        cancellation=cancellation,
                        headers={"Accept": "text/html,text/plain,application/pdf;q=0.9,*/*;q=0.1"},
                    )
                    if response.status_code not in _REDIRECT_CODES:
                        break
                    location = response.headers.get("location")
                    if not location or redirects >= self._max_redirects:
                        return _failure("Error: redirect limit exceeded", ToolFailureKind.RESOURCE_LIMIT)
                    target = _validate_url(urljoin(current, location))
                    try:
                        authorized = await _authorized_redirect(
                            self._redirect_authorizer,
                            target,
                            cancellation=cancellation,
                        )
                    except RedirectPermissionRequired as exc:
                        # Retain only the safe URL/counter needed to continue
                        # after the Core PermissionApproval response.  The
                        # target request has not started yet.
                        cancellation._uthcode_web_pending_redirect = {  # type: ignore[attr-defined]
                            "requested_url": requested_url,
                            "target": target,
                            "redirects": redirects + 1,
                        }
                        return ToolExecutionResult(
                            "Error: redirect permission approval required",
                            is_error=True,
                            failure=ToolFailure(ToolFailureKind.PERMISSION_DENIED.value),
                            permission_action=exc.action,
                            details={"permission_required": True},
                        )
                    if not authorized:
                        return _failure("Error: redirect target was denied", ToolFailureKind.PERMISSION_DENIED)
                    current = target
                    redirects += 1
                status = response.status_code
                if status >= 400:
                    kind = ToolFailureKind.NOT_FOUND if status == 404 else ToolFailureKind.NETWORK_ERROR
                    return _failure(f"Error: fetch failed with HTTP {status}", kind, retryable=status >= 500)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    if cancellation.cancelled:
                        return _cancelled()
                    size += len(chunk)
                    if size > max_bytes:
                        return _failure("Error: fetched response exceeds the configured byte limit", ToolFailureKind.RESOURCE_LIMIT)
                    chunks.append(chunk)
                body = b"".join(chunks)
        except asyncio.CancelledError:
            return _cancelled()
        except httpx.TimeoutException:
            return _failure("Error: fetch timed out", ToolFailureKind.TIMEOUT, retryable=True)
        except httpx.HTTPError:
            return _failure("Error: fetch request failed", ToolFailureKind.NETWORK_ERROR, retryable=True)
        except ValueError as exc:
            return _failure(str(exc), ToolFailureKind.INVALID_INPUT)
        except Exception:
            return _failure("Error: fetch service is unavailable", ToolFailureKind.UNAVAILABLE, retryable=True)
        source = WebSource(
            requested_url=requested_url,
            final_url=current,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            content_type=content_type or None,
            status_code=status,
            position="body",
        )
        if content_type == "application/pdf" or current.lower().split("?", 1)[0].endswith(".pdf"):
            if self._asset_writer is None:
                return _failure(
                    "Error: fetched PDF requires a Session asset writer before it can be read",
                    ToolFailureKind.UNAVAILABLE,
                    details={"source": source.to_dict()},
                )
            try:
                ref = self._asset_writer("fetched.pdf", body, "application/pdf", source.final_url)
            except Exception:
                return _failure("Error: fetched PDF could not be saved as a Session asset", ToolFailureKind.UNAVAILABLE, details={"source": source.to_dict()})
            projected = {"source": source.to_dict(), "asset": dict(ref), "mode": "pdf"}
            return ToolExecutionResult(json.dumps(projected, ensure_ascii=False, separators=(",", ":")), details=projected)
        try:
            text = _extract_local_text(body, content_type)
        except UnicodeDecodeError:
            return _failure("Error: fetched body is not supported text", ToolFailureKind.UNSUPPORTED, details={"source": source.to_dict()})
        if _looks_like_login_page(text):
            return _failure("Error: login or dynamic page content is not supported", ToolFailureKind.UNSUPPORTED, details={"source": source.to_dict()})
        if not text.strip():
            return _failure("Error: fetched page has no readable text", ToolFailureKind.UNSUPPORTED, details={"source": source.to_dict()})
        lines = text.splitlines()
        numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(lines, start=1) if line.strip())
        result = {
            "source": source.to_dict(),
            "content": numbered[: max_bytes * 2],
            "line_count": len(lines),
        }
        return ToolExecutionResult(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            details={"source": source.to_dict(), "line_count": len(lines)},
        )


def _extract_local_text(body: bytes, content_type: str) -> str:
    if content_type not in _HTML_CONTENT_TYPES and content_type:
        if content_type.startswith("text/"):
            return body.decode("utf-8")
        raise UnicodeDecodeError("web", body, 0, min(1, len(body)), "unsupported content type")
    decoded = body.decode("utf-8", errors="replace")
    try:
        import trafilatura

        extracted = trafilatura.extract(decoded, include_comments=False, include_tables=True)
    except Exception:
        extracted = None
    if extracted:
        return extracted
    text = re.sub(r"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>", " ", decoded)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _looks_like_login_page(text: str) -> bool:
    sample = text.casefold()
    return bool(
        re.search(r"\b(password|sign in|log in|登录|登入)\b", sample)
        and ("password" in sample or "sign in" in sample or "log in" in sample or "登录" in sample or "登入" in sample)
    )


__all__ = [
    "FetchWebTool",
    "RedirectPermissionRequired",
    "TAVILY_SEARCH_ENDPOINT",
    "TavilySearchTool",
    "WebSource",
]
