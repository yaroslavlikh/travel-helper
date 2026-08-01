import httpx
import pytest

from app.accounts.auth import SESSION_COOKIE
from app.core.config import Settings
from app.main import create_app


def configured_settings() -> Settings:
    return Settings(
        app_env="test",
        demo_mode=True,
        langfuse_enabled=False,
        oidc_issuer="https://identity.example",
        oidc_authorization_url="https://identity.example/authorize",
        oidc_token_url="https://identity.example/token",
        oidc_userinfo_url="https://identity.example/userinfo",
        oidc_client_id="travel-client",
        oidc_client_secret="client-secret",
        auth_session_secret="a-secure-test-secret-with-more-than-32-characters",
        auth_cookie_secure_override=False,
        _env_file=None,
    )


async def login(resources: object, client: httpx.AsyncClient, subject: str) -> tuple[str, str]:
    store = resources.account_store  # type: ignore[attr-defined]
    auth = resources.auth_service  # type: ignore[attr-defined]
    account = await store.upsert_account(
        issuer="https://identity.example",
        subject=subject,
        email=f"{subject}@example.com",
        display_name=subject,
    )
    token, _expires = await auth.issue_session(account)
    client.cookies.set(SESSION_COOKIE, token)
    return account.id, auth.csrf_token(token)


@pytest.mark.asyncio
async def test_failed_oidc_callback_returns_to_login_without_flow_cookie() -> None:
    app = create_app(configured_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as client:
            response = await client.get("/auth/callback?code=expired-code&state=wrong-state")

    assert response.status_code == 303
    assert response.headers["location"] == "/login?error=login_failed"
    assert 'travel_oidc_flow=""' in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_password_registration_and_login_issue_account_sessions() -> None:
    app = create_app(configured_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            registered = await client.post(
                "/auth/password/register",
                json={"email": "Traveler@Example.com", "password": "a safe password"},
            )
            profile = await client.get("/account/me")
            duplicate = await client.post(
                "/auth/password/register",
                json={"email": "traveler@example.com", "password": "another safe password"},
            )
            csrf = registered.json()["csrf_token"]
            logged_out = await client.post("/auth/logout", headers={"X-CSRF-Token": csrf})

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            wrong_password = await client.post(
                "/auth/password/login",
                json={"email": "traveler@example.com", "password": "wrong password"},
            )
            logged_in = await client.post(
                "/auth/password/login",
                json={"email": "TRAVELER@example.com", "password": "a safe password"},
            )

    assert registered.status_code == 201
    assert profile.json()["authenticated"] is True
    assert profile.json()["account"]["email"] == "traveler@example.com"
    assert duplicate.status_code == 409
    assert logged_out.status_code == 204
    assert wrong_password.status_code == 401
    assert logged_in.status_code == 200
    assert logged_in.json()["authenticated"] is True


@pytest.mark.asyncio
async def test_account_chat_import_sync_and_delete_are_owner_scoped() -> None:
    app = create_app(configured_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as first:
            _first_id, first_csrf = await login(app.state.resources, first, "first")
            forbidden = await first.post(
                "/account/chats",
                json={"title": "Без CSRF", "payload": {}},
            )
            imported = await first.post(
                "/account/chats/import",
                headers={"X-CSRF-Token": first_csrf},
                json={
                    "client_import_id": "local-v1:existing-chat",
                    "title": "Локальная поездка",
                    "payload": {"id": "old-id", "recommendations": [{"total_score": 88}]},
                },
            )
            repeated = await first.post(
                "/account/chats/import",
                headers={"X-CSRF-Token": first_csrf},
                json={
                    "client_import_id": "local-v1:existing-chat",
                    "title": "Повтор",
                    "payload": {},
                },
            )
            chat_id = imported.json()["id"]

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as second:
                _second_id, second_csrf = await login(app.state.resources, second, "second")
                чужой = await second.delete(
                    f"/account/chats/{chat_id}",
                    headers={"X-CSRF-Token": second_csrf},
                )

            deleted = await first.delete(
                f"/account/chats/{chat_id}",
                headers={"X-CSRF-Token": first_csrf},
            )
            remaining = await first.get("/account/chats")

    assert forbidden.status_code == 403
    assert imported.status_code == 201
    assert imported.json()["payload"]["id"] == chat_id
    assert repeated.json()["id"] == chat_id
    assert чужой.status_code == 404
    assert deleted.status_code == 204
    assert remaining.json() == []


@pytest.mark.asyncio
async def test_full_chat_presentation_snapshot_round_trips_through_account_storage() -> None:
    app = create_app(configured_settings())
    payload = {
        "messages": [{"role": "user", "text": "Из Москвы с 20 августа"}],
        "snapshot": {"request_id": "request-1", "parsed_request": {"origin_city": "Москва"}},
        "recommendations": [{"candidate": {"destination_id": "sochi"}, "total_score": 84}],
        "destinationThreads": {"sochi": {"messages": [{"role": "user", "text": "Где жить?"}]}},
    }

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _account_id, csrf = await login(app.state.resources, client, "snapshot-owner")
            created = await client.post(
                "/account/chats",
                headers={"X-CSRF-Token": csrf},
                json={"title": "Летняя поездка", "payload": payload},
            )
            listed = await client.get("/account/chats")

    assert created.status_code == 201
    stored = listed.json()[0]
    assert stored["title"] == "Летняя поездка"
    assert stored["payload"]["snapshot"] == payload["snapshot"]
    assert stored["payload"]["recommendations"] == payload["recommendations"]
    assert stored["payload"]["destinationThreads"] == payload["destinationThreads"]


@pytest.mark.asyncio
async def test_authenticated_recommendation_rejects_another_users_chat() -> None:
    app = create_app(configured_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as first:
            _first_id, first_csrf = await login(app.state.resources, first, "first")
            created = await first.post(
                "/account/chats",
                headers={"X-CSRF-Token": first_csrf},
                json={"title": "Моя поездка", "payload": {}},
            )
            chat_id = created.json()["id"]

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as second:
                _second_id, second_csrf = await login(app.state.resources, second, "second")
                response = await second.post(
                    "/recommend",
                    headers={"X-CSRF-Token": second_csrf},
                    json={"session_id": chat_id, "query": "Из Москвы на море"},
                )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_guest_cannot_access_an_account_owned_planning_session() -> None:
    app = create_app(configured_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as owner:
            _account_id, csrf = await login(app.state.resources, owner, "owner")
            created = await owner.post(
                "/account/chats",
                headers={"X-CSRF-Token": csrf},
                json={"title": "Личная поездка", "payload": {}},
            )
            chat_id = created.json()["id"]
            initialized = await owner.post(
                "/recommend",
                headers={"X-CSRF-Token": csrf},
                json={"session_id": chat_id, "query": "Из Москвы на море в августе"},
            )
            destination_id = initialized.json()["recommendations"][0]["candidate"]["destination_id"]

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as guest:
            recommendation = await guest.post(
                "/recommend",
                json={"session_id": chat_id, "query": "Покажи историю"},
            )
            destination_chat = await guest.post(
                "/destination-chat",
                json={
                    "session_id": chat_id,
                    "destination_id": destination_id,
                    "query": "Где остановиться?",
                },
            )

    assert created.status_code == 201
    assert initialized.status_code == 200
    assert recommendation.status_code == 404
    assert destination_chat.status_code == 404


@pytest.mark.asyncio
async def test_imported_chat_snapshot_can_be_refined_under_new_owned_id() -> None:
    app = create_app(configured_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _account_id, csrf = await login(app.state.resources, client, "traveler")
            imported = await client.post(
                "/account/chats/import",
                headers={"X-CSRF-Token": csrf},
                json={
                    "client_import_id": "local-v1:refinable-chat",
                    "title": "Море в августе",
                    "payload": {
                        "messages": [
                            {
                                "role": "user",
                                "text": "Из Москвы на море в августе, бюджет 180 тысяч",
                            }
                        ],
                        "snapshot": {
                            "request_id": "old-request-id",
                            "parsed_request": {
                                "raw_query": "Из Москвы на море в августе, бюджет 180 тысяч",
                                "origin_city": "Москва",
                                "month": 8,
                                "budget_total_rub": 180000,
                                "sea_required": True,
                            },
                        },
                        "recommendations": [],
                    },
                },
            )
            refined = await client.post(
                "/recommend",
                headers={"X-CSRF-Token": csrf},
                json={
                    "session_id": imported.json()["id"],
                    "query": "Перелёт максимум четыре часа",
                },
            )

    body = refined.json()
    assert refined.status_code == 200
    assert body["turn_kind"] == "refinement"
    assert body["parsed_request"]["origin_city"] == "Москва"
    assert body["parsed_request"]["budget_total_rub"] == 180000
    assert body["parsed_request"]["max_flight_duration_hours"] == 4


@pytest.mark.asyncio
async def test_logout_keeps_server_history_for_next_login() -> None:
    app = create_app(configured_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            account_id, csrf = await login(app.state.resources, client, "returning")
            created = await client.post(
                "/account/chats",
                headers={"X-CSRF-Token": csrf},
                json={"title": "Сохранённая поездка", "payload": {}},
            )
            logged_out = await client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
            account = await app.state.resources.account_store.upsert_account(
                issuer="https://identity.example",
                subject="returning",
                email="returning@example.com",
                display_name="returning",
            )
            token, _expires = await app.state.resources.auth_service.issue_session(account)
            client.cookies.set(SESSION_COOKIE, token)
            history = await client.get("/account/chats")

    assert account.id == account_id
    assert created.status_code == 201
    assert logged_out.status_code == 204
    assert [chat["title"] for chat in history.json()] == ["Сохранённая поездка"]


@pytest.mark.asyncio
async def test_delete_account_removes_all_owned_data_and_session() -> None:
    app = create_app(configured_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _account_id, csrf = await login(app.state.resources, client, "delete-me")
            created = await client.post(
                "/account/chats",
                headers={"X-CSRF-Token": csrf},
                json={"title": "Удалить", "payload": {}},
            )
            deleted = await client.request(
                "DELETE",
                "/account",
                headers={"X-CSRF-Token": csrf},
                json={"confirmation": "DELETE"},
            )
            status_response = await client.get("/account/me")

    assert created.status_code == 201
    assert deleted.status_code == 204
    assert status_response.json()["authenticated"] is False


@pytest.mark.asyncio
async def test_deleting_chat_deletes_its_langgraph_checkpoint() -> None:
    app = create_app(configured_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _account_id, csrf = await login(app.state.resources, client, "checkpoint-owner")
            created = await client.post(
                "/account/chats",
                headers={"X-CSRF-Token": csrf},
                json={"title": "С памятью", "payload": {}},
            )
            chat_id = created.json()["id"]
            initialized = await client.post(
                "/recommend",
                headers={"X-CSRF-Token": csrf},
                json={"session_id": chat_id, "query": "Из Москвы на море в августе"},
            )
            deleted = await client.delete(
                f"/account/chats/{chat_id}", headers={"X-CSRF-Token": csrf}
            )
            state = await app.state.resources.checkpointer.aget_tuple(
                {"configurable": {"thread_id": chat_id}}
            )

    assert created.status_code == 201
    assert initialized.status_code == 200
    assert deleted.status_code == 204
    assert state is None
