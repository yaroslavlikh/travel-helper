from app.accounts.store import AccountStore


def test_import_is_idempotent_and_scoped_to_owner() -> None:
    store = AccountStore(":memory:")
    first = store.upsert_account(
        issuer="https://identity.example",
        subject="first",
        email="first@example.com",
        display_name="First",
    )
    second = store.upsert_account(
        issuer="https://identity.example",
        subject="second",
        email="second@example.com",
        display_name="Second",
    )

    imported = store.create_chat(
        owner_id=first.id,
        client_import_id="local-v1:chat-123",
        title="Стамбул",
        payload={"id": "anonymous-id", "recommendations": [{"score": 90}]},
    )
    repeated = store.create_chat(
        owner_id=first.id,
        client_import_id="local-v1:chat-123",
        title="Дубликат",
        payload={},
    )

    assert repeated.id == imported.id
    assert imported.payload["id"] == imported.id
    assert store.owns_chat(owner_id=first.id, chat_id=imported.id)
    assert not store.owns_chat(owner_id=second.id, chat_id=imported.id)
    assert store.get_chat(owner_id=second.id, chat_id=imported.id) is None
    store.close()


def test_delete_account_cascades_sessions_and_chats() -> None:
    store = AccountStore(":memory:")
    account = store.upsert_account(
        issuer="issuer",
        subject="subject",
        email=None,
        display_name=None,
    )
    chat = store.create_chat(owner_id=account.id, title="Поездка", payload={})
    store.create_session(
        account_id=account.id,
        token_hash="token-hash",
        expires_at="2999-01-01T00:00:00+00:00",
    )

    deleted_ids = store.delete_account(account.id)

    assert deleted_ids == [chat.id]
    assert store.list_chats(account.id) == []
    assert store.account_for_session(token_hash="token-hash", now="2026-01-01") is None
    store.close()
