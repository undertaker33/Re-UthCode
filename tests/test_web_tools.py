from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from uthcode.application.configuration import SearchConfiguration
from uthcode.core import CancellationToken, ToolCallPart
from uthcode.integrations.tools.web_tools import FetchWebTool, TavilySearchTool


def _response_handler(payload: dict[str, object], *, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        payload["request"] = json.loads(request.content)
        return httpx.Response(status, json={"results": [], "usage": {"credits": 1}}, request=request)

    return handler


@pytest.mark.asyncio
async def test_tavily_uses_fixed_basic_request_and_redacts_answer(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "answer": "should not be projected",
                "results": [{"title": "Example", "url": "https://example.com", "content": "summary"}],
                "usage": {"credits": 1},
            },
            request=request,
        )

    tool = TavilySearchTool(
        SearchConfiguration(enabled=True, api_key="secret-value"),
        transport=httpx.MockTransport(handler),
    )
    provider_call = ToolCallPart(
        "search-domains",
        "WebSearch",
        {"query": "hello", "domains": ["example.com"]},
    )
    result = await tool.execute(provider_call.arguments, cancellation=CancellationToken())
    assert result.is_error is False
    payload = seen["payload"]
    assert payload["search_depth"] == "basic"
    assert payload["auto_parameters"] is False
    assert payload["include_answer"] is False
    assert payload["include_usage"] is True
    assert payload["max_results"] == 5
    assert payload["include_domains"] == ["example.com"]
    assert "secret-value" not in str(result.content)
    assert "should not be projected" not in str(result.content)


@pytest.mark.asyncio
@pytest.mark.parametrize("status, kind", [(401, "permission_denied"), (429, "resource_limit")])
async def test_tavily_failure_classification(status: int, kind: str) -> None:
    tool = TavilySearchTool(
        SearchConfiguration(enabled=True, api_key="secret-value"),
        transport=httpx.MockTransport(lambda request: httpx.Response(status, request=request)),
    )
    result = await tool.execute({"query": "hello"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    assert result.is_error is True
    assert result.failure is not None
    assert result.failure.kind == kind


@pytest.mark.asyncio
async def test_tavily_unconfigured_and_response_limit_are_controlled() -> None:
    unavailable = TavilySearchTool(
        SearchConfiguration(enabled=False),
        transport=httpx.MockTransport(lambda request: httpx.Response(500, request=request)),
    )
    result = await unavailable.execute(
        {"query": "hello"}, cancellation=CancellationToken()  # type: ignore[arg-type]
    )
    assert result.is_error is True
    assert result.failure is not None and result.failure.kind == "unavailable"

    limited = TavilySearchTool(
        SearchConfiguration(enabled=True, api_key="secret-value", max_fetch_bytes=128),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"x" * 129,
                headers={"content-type": "application/json"},
                request=request,
            )
        ),
    )
    oversized = await limited.execute(
        {"query": "hello"}, cancellation=CancellationToken()  # type: ignore[arg-type]
    )
    assert oversized.is_error is True
    assert oversized.failure is not None and oversized.failure.kind == "resource_limit"
    assert "secret-value" not in str(oversized.content)


@pytest.mark.asyncio
async def test_tavily_cancellation_closes_pending_request() -> None:
    started = asyncio.Event()

    async def delayed(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(1)
        return httpx.Response(200, json={"results": []}, request=request)

    token = CancellationToken()
    client = httpx.AsyncClient(transport=httpx.MockTransport(delayed))
    tool = TavilySearchTool(
        SearchConfiguration(enabled=True, api_key="secret-value"),
        client_factory=lambda **_kwargs: client,
    )
    task = asyncio.create_task(
        tool.execute({"query": "hello"}, cancellation=token)  # type: ignore[arg-type]
    )
    await started.wait()
    token.cancel()
    result = await task
    assert result.is_error is True
    assert result.failure is not None and result.failure.kind == "cancelled"
    assert client.is_closed is True


@pytest.mark.asyncio
async def test_fetch_rechecks_each_redirect_and_bounds_body(tmp_path: Path) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url).endswith("/start"):
            return httpx.Response(302, headers={"location": "/final"}, request=request)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<p>final text</p>", request=request)

    authorized: list[str] = []

    async def authorize(url: str) -> bool:
        authorized.append(url)
        return True

    tool = FetchWebTool(
        transport=httpx.MockTransport(handler),
        redirect_authorizer=authorize,
        max_bytes=4096,
    )
    result = await tool.execute({"url": "https://example.com/start"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    assert result.is_error is False
    assert requested == ["https://example.com/start", "https://example.com/final"]
    assert authorized == ["https://example.com/final"]
    assert "final text" in str(result.content)
    assert result.details["source"]["requested_url"] == "https://example.com/start"
    assert result.details["source"]["final_url"] == "https://example.com/final"

    oversized = FetchWebTool(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 2048, request=request)
        ),
        max_bytes=1024,
    )
    too_large = await oversized.execute({"url": "https://example.com"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    assert too_large.is_error is True
    assert too_large.failure is not None
    assert too_large.failure.kind == "resource_limit"


@pytest.mark.asyncio
async def test_fetch_cancellation_and_login_pages_are_controlled() -> None:
    started = asyncio.Event()

    async def delayed(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(1)
        return httpx.Response(200, text="late", request=request)

    token = CancellationToken()
    client = httpx.AsyncClient(transport=httpx.MockTransport(delayed))
    tool = FetchWebTool(client_factory=lambda **_kwargs: client)
    task = asyncio.create_task(tool.execute({"url": "https://example.com"}, cancellation=token))  # type: ignore[arg-type]
    await started.wait()
    token.cancel()
    cancelled = await task
    assert cancelled.is_error is True
    assert cancelled.failure is not None
    assert cancelled.failure.kind == "cancelled"
    assert client.is_closed is True

    login = FetchWebTool(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="Sign in password",
                request=request,
            )
        )
    )
    result = await login.execute({"url": "https://example.com"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    assert result.is_error is True
    assert result.failure is not None
    assert result.failure.kind == "unsupported"

    explicit_prompt = FetchWebTool(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="Sign in. Enter your password.",
                request=request,
            )
        )
    )
    prompt_result = await explicit_prompt.execute(
        {"url": "https://example.com/login"},
        cancellation=CancellationToken(),  # type: ignore[arg-type]
    )
    assert prompt_result.is_error is True
    assert prompt_result.failure is not None
    assert prompt_result.failure.kind == "unsupported"

    password_form = FetchWebTool(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=(
                    "<html><body><main><h1>Sign in</h1>"
                    '<form action="/login"><label>Password'
                    '<input type="password" name="password"></label>'
                    '<button type="submit">Sign in</button></form>'
                    "</main></body></html>"
                ),
                request=request,
            )
        )
    )
    form_result = await password_form.execute(
        {"url": "https://example.com/login"},
        cancellation=CancellationToken(),  # type: ignore[arg-type]
    )
    assert form_result.is_error is True
    assert form_result.failure is not None
    assert form_result.failure.kind == "unsupported"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page, expected_text",
    [
        (
            "<html><body><nav><a href='/account'>Account</a></nav>"
            "<p>Public news is freely available.</p></body></html>",
            "Public news is freely available.",
        ),
        (
            "<html><body><nav><a href='/login'>Sign in</a></nav>"
            "<p>Public news is freely available.</p></body></html>",
            "Public news is freely available.",
        ),
        (
            "<html><body><a href='/account'>Account</a><h1>News</h1>"
            "<ul><li>Public research update</li><li>New model released today</li></ul>"
            "</body></html>",
            "New model released today",
        ),
        (
            "<html><body><a href='/login'>Sign in</a><h1>News</h1>"
            "<ul><li>Public research update</li><li>New model released today</li></ul>"
            "</body></html>",
            "New model released today",
        ),
        (
            "<html><body><header><form action='/login'>"
            '<input type="password"><button>Sign in</button></form></header>'
            "<article><h1>Public news</h1>"
            "<p>A public research update is freely available to everyone.</p>"
            "</article></body></html>",
            "A public research update is freely available to everyone.",
        ),
        (
            "<html><body><article><h1>Public sign in tutorial</h1>"
            "<p>Use your username and password to sign in</p>"
            "</article></body></html>",
            "Use your username and password to sign in",
        ),
        (
            "<html><body><article><h1>Public sign in tutorial</h1>"
            "<p>Enter your password to sign in</p>"
            "</article></body></html>",
            "Enter your password to sign in",
        ),
        (
            "<html><body><article><h1>Public sign in tutorial</h1>"
            "<p>This public documentation explains how to sign in safely with a password. "
            "Its text is freely readable and is not protected by authentication.</p>"
            "</article></body></html>",
            "not protected by authentication",
        ),
    ],
    ids=[
        "short-account-navigation",
        "short-sign-in-navigation",
        "listing-account-navigation",
        "listing-sign-in-navigation",
        "password-form-with-public-article",
        "short-public-sign-in-tutorial",
        "tutorial-with-credential-instruction",
        "public-login-tutorial",
    ],
)
async def test_fetch_keeps_public_content_with_login_related_text(
    page: str,
    expected_text: str,
) -> None:
    tool = FetchWebTool(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=page,
                request=request,
            )
        )
    )

    result = await tool.execute(
        {"url": "https://example.com/public"},
        cancellation=CancellationToken(),  # type: ignore[arg-type]
    )

    assert result.is_error is False
    assert expected_text in json.loads(str(result.content))["content"]


@pytest.mark.asyncio
async def test_fetch_does_not_treat_client_rendered_script_as_page_text() -> None:
    html = (
        '<!doctype html><html><body><div id="root"></div>'
        '<script>document.getElementById("root").textContent = "rendered only in browser";</script>'
        "</body></html>"
    )
    tool = FetchWebTool(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=html,
                request=request,
            )
        )
    )

    result = await tool.execute(
        {"url": "https://example.com/client-rendered"},
        cancellation=CancellationToken(),  # type: ignore[arg-type]
    )

    assert result.is_error is True
    assert result.failure is not None and result.failure.kind == "unsupported"
    assert "rendered only in browser" not in str(result.content)
    assert "document.getElementById" not in str(result.content)
