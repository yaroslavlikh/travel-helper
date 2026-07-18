from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.accounts.auth import AuthService
from app.accounts.store import AccountStore
from app.core.config import Settings


def auth_settings() -> Settings:
    return Settings(
        app_env="test",
        demo_mode=True,
        oidc_issuer="https://identity.example",
        oidc_authorization_url="https://identity.example/authorize",
        oidc_token_url="https://identity.example/token",
        oidc_userinfo_url="https://identity.example/userinfo",
        oidc_client_id="travel-client",
        oidc_client_secret="client-secret",
        oidc_redirect_uri="http://test/auth/callback",
        auth_session_secret="a-secure-test-secret-with-more-than-32-characters",
        _env_file=None,
    )


@pytest.mark.asyncio
async def test_oidc_pkce_flow_creates_local_session() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "provider-token"})
        return httpx.Response(
            200,
            json={"sub": "user-1", "email": "user@example.com", "name": "User"},
        )

    store = AccountStore(":memory:")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        auth = AuthService(settings=auth_settings(), store=store, http_client=client)
        authorization_url, flow_cookie = auth.begin_login("/trips")
        query = parse_qs(urlparse(authorization_url).query)

        token, return_to, _expires = await auth.complete_login(
            code="authorization-code",
            state=query["state"][0],
            signed_flow=flow_cookie,
        )

    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["openid email profile"]
    assert return_to == "/trips"
    assert token
    assert requests[0].url.path == "/token"
    assert requests[1].headers["Authorization"] == "Bearer provider-token"
    store.close()


@pytest.mark.asyncio
async def test_login_rejects_external_return_url() -> None:
    store = AccountStore(":memory:")
    async with httpx.AsyncClient() as client:
        auth = AuthService(settings=auth_settings(), store=store, http_client=client)

        url, flow_cookie = auth.begin_login("//evil.example/path")

    assert url.startswith("https://identity.example/authorize?")
    assert flow_cookie
    store.close()
