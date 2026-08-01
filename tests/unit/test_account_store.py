import pytest

from app.accounts.store import AccountStore


@pytest.mark.asyncio
async def test_import_is_idempotent_and_scoped_to_owner() -> None:
    store = AccountStore(":memory:")
    first = await store.upsert_account(
        issuer="https://identity.example",
        subject="first",
        email="first@example.com",
        display_name="First",
    )
    second = await store.upsert_account(
        issuer="https://identity.example",
        subject="second",
        email="second@example.com",
        display_name="Second",
    )

    imported = await store.create_chat(
        owner_id=first.id,
        client_import_id="local-v1:chat-123",
        title="Стамбул",
        payload={"id": "anonymous-id", "recommendations": [{"score": 90}]},
    )
    repeated = await store.create_chat(
        owner_id=first.id,
        client_import_id="local-v1:chat-123",
        title="Дубликат",
        payload={},
    )

    assert repeated.id == imported.id
    assert imported.payload["id"] == imported.id
    assert await store.owns_chat(owner_id=first.id, chat_id=imported.id)
    assert not await store.owns_chat(owner_id=second.id, chat_id=imported.id)
    assert await store.get_chat(owner_id=second.id, chat_id=imported.id) is None
    await store.aclose()


@pytest.mark.asyncio
async def test_delete_account_cascades_sessions_and_chats() -> None:
    store = AccountStore(":memory:")
    account = await store.upsert_account(
        issuer="issuer",
        subject="subject",
        email=None,
        display_name=None,
    )
    chat = await store.create_chat(owner_id=account.id, title="Поездка", payload={})
    await store.create_session(
        account_id=account.id,
        token_hash="token-hash",
        expires_at="2999-01-01T00:00:00+00:00",
    )

    deleted_ids = await store.delete_account(account.id)

    assert deleted_ids == [chat.id]
    assert await store.list_chats(account.id) == []
    assert await store.account_for_session(token_hash="token-hash", now="2026-01-01") is None
    await store.aclose()


@pytest.mark.asyncio
async def test_chat_update_list_and_delete_and_expired_session() -> None:
    store = AccountStore(":memory:")
    account = await store.upsert_account(
        issuer="issuer", subject="subject", email=None, display_name=None
    )
    chat = await store.create_chat(owner_id=account.id, title="Черновик", payload={"step": 1})
    updated = await store.update_chat(
        owner_id=account.id, chat_id=chat.id, title="Готово", payload={"step": 2}
    )
    await store.create_session(
        account_id=account.id,
        token_hash="expired-token",
        expires_at="2020-01-01T00:00:00+00:00",
    )

    assert updated is not None
    assert updated.title == "Готово"
    assert updated.payload == {"step": 2, "id": chat.id}
    assert [item.id for item in await store.list_chats(account.id)] == [chat.id]
    assert (
        await store.account_for_session(token_hash="expired-token", now="2026-01-01T00:00:00+00:00")
        is None
    )
    assert await store.delete_chat(owner_id=account.id, chat_id=chat.id)
    assert not await store.is_account_chat(chat.id)
    await store.aclose()
