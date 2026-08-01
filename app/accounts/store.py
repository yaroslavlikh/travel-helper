"""Account repositories for local SQLite and production PostgreSQL storage."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp(value: object) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    issuer: str
    subject: str
    email: str | None
    display_name: str | None


@dataclass(frozen=True, slots=True)
class ChatRecord:
    id: str
    owner_id: str
    client_import_id: str | None
    title: str
    payload: dict[str, Any]
    created_at: str
    updated_at: str


class AccountRepository(Protocol):
    """The async account boundary used by HTTP handlers."""

    async def upsert_account(
        self, *, issuer: str, subject: str, email: str | None, display_name: str | None
    ) -> Account: ...

    async def create_session(
        self, *, account_id: str, token_hash: str, expires_at: str
    ) -> None: ...

    async def create_password_account(
        self, *, email: str, password_hash: str, display_name: str | None = None
    ) -> Account | None: ...

    async def password_account(self, email: str) -> tuple[Account, str] | None: ...

    async def account_for_session(self, *, token_hash: str, now: str) -> Account | None: ...

    async def delete_session(self, token_hash: str) -> None: ...

    async def create_chat(
        self,
        *,
        owner_id: str,
        title: str,
        payload: dict[str, Any],
        client_import_id: str | None = None,
    ) -> ChatRecord: ...

    async def list_chats(self, owner_id: str) -> list[ChatRecord]: ...

    async def get_chat(self, *, owner_id: str, chat_id: str) -> ChatRecord | None: ...

    async def owns_chat(self, *, owner_id: str, chat_id: str) -> bool: ...

    async def is_account_chat(self, chat_id: str) -> bool: ...

    async def update_chat(
        self, *, owner_id: str, chat_id: str, title: str, payload: dict[str, Any]
    ) -> ChatRecord | None: ...

    async def delete_chat(self, *, owner_id: str, chat_id: str) -> bool: ...

    async def delete_account(self, account_id: str) -> list[str]: ...

    async def aclose(self) -> None: ...


class AccountStore:
    """SQLite implementation for development and isolated tests only."""

    def __init__(self, database_path: str) -> None:
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL,
                    email TEXT, display_name TEXT, password_hash TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE (issuer, subject)
                );
                CREATE TABLE IF NOT EXISTS account_sessions (
                    token_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS account_sessions_expiry_idx
                    ON account_sessions(expires_at);
                CREATE TABLE IF NOT EXISTS account_chats (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    client_import_id TEXT, title TEXT NOT NULL, payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE (owner_id, client_import_id)
                );
                CREATE INDEX IF NOT EXISTS account_chats_owner_updated_idx
                    ON account_chats(owner_id, updated_at DESC);
                """
            )
            self._connection.commit()

    async def aclose(self) -> None:
        with self._lock:
            self._connection.close()

    async def upsert_account(
        self, *, issuer: str, subject: str, email: str | None, display_name: str | None
    ) -> Account:
        timestamp = _now()
        with self._lock:
            row = self._connection.execute(
                "SELECT id FROM accounts WHERE issuer = ? AND subject = ?", (issuer, subject)
            ).fetchone()
            account_id = str(row["id"]) if row else str(uuid4())
            if row:
                self._connection.execute(
                    "UPDATE accounts SET email = ?, display_name = ?, updated_at = ? WHERE id = ?",
                    (email, display_name, timestamp, account_id),
                )
            else:
                self._connection.execute(
                    """INSERT INTO accounts
                    (id, issuer, subject, email, display_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (account_id, issuer, subject, email, display_name, timestamp, timestamp),
                )
            self._connection.commit()
        return Account(account_id, issuer, subject, email, display_name)

    async def create_session(self, *, account_id: str, token_hash: str, expires_at: str) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT INTO account_sessions(token_hash, account_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)""",
                (token_hash, account_id, expires_at, _now()),
            )
            self._connection.commit()

    async def create_password_account(
        self, *, email: str, password_hash: str, display_name: str | None = None
    ) -> Account | None:
        timestamp, account_id = _now(), str(uuid4())
        with self._lock:
            try:
                self._connection.execute(
                    """INSERT INTO accounts
                    (id, issuer, subject, email, display_name, password_hash,
                     created_at, updated_at)
                    VALUES (?, 'password', ?, ?, ?, ?, ?, ?)""",
                    (account_id, email, email, display_name, password_hash, timestamp, timestamp),
                )
            except sqlite3.IntegrityError:
                return None
            self._connection.commit()
        return Account(account_id, "password", email, email, display_name)

    async def password_account(self, email: str) -> tuple[Account, str] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT id, issuer, subject, email, display_name, password_hash FROM accounts
                WHERE issuer = 'password' AND subject = ? AND password_hash IS NOT NULL""",
                (email,),
            ).fetchone()
        return (self._account(row), str(row["password_hash"])) if row else None

    async def account_for_session(self, *, token_hash: str, now: str) -> Account | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT a.id, a.issuer, a.subject, a.email, a.display_name
                FROM account_sessions s JOIN accounts a ON a.id = s.account_id
                WHERE s.token_hash = ? AND s.expires_at > ?""",
                (token_hash, now),
            ).fetchone()
        return self._account(row) if row else None

    async def delete_session(self, token_hash: str) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM account_sessions WHERE token_hash = ?", (token_hash,)
            )
            self._connection.commit()

    async def create_chat(
        self,
        *,
        owner_id: str,
        title: str,
        payload: dict[str, Any],
        client_import_id: str | None = None,
    ) -> ChatRecord:
        with self._lock:
            if client_import_id:
                existing = self._connection.execute(
                    "SELECT * FROM account_chats WHERE owner_id = ? AND client_import_id = ?",
                    (owner_id, client_import_id),
                ).fetchone()
                if existing:
                    return self._chat(existing)
            chat_id, timestamp = str(uuid4()), _now()
            encoded = json.dumps(
                {**payload, "id": chat_id}, ensure_ascii=False, separators=(",", ":")
            )
            self._connection.execute(
                """INSERT INTO account_chats
                (id, owner_id, client_import_id, title, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (chat_id, owner_id, client_import_id, title, encoded, timestamp, timestamp),
            )
            self._connection.commit()
            row = self._connection.execute(
                "SELECT * FROM account_chats WHERE id = ?", (chat_id,)
            ).fetchone()
        if row is None:  # pragma: no cover - SQLite returns inserted rows
            raise RuntimeError("Created chat could not be loaded")
        return self._chat(row)

    async def list_chats(self, owner_id: str) -> list[ChatRecord]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM account_chats WHERE owner_id = ? ORDER BY updated_at DESC",
                (owner_id,),
            ).fetchall()
        return [self._chat(row) for row in rows]

    async def get_chat(self, *, owner_id: str, chat_id: str) -> ChatRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM account_chats WHERE owner_id = ? AND id = ?", (owner_id, chat_id)
            ).fetchone()
        return self._chat(row) if row else None

    async def owns_chat(self, *, owner_id: str, chat_id: str) -> bool:
        return await self.get_chat(owner_id=owner_id, chat_id=chat_id) is not None

    async def is_account_chat(self, chat_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM account_chats WHERE id = ?", (chat_id,)
            ).fetchone()
        return row is not None

    async def update_chat(
        self, *, owner_id: str, chat_id: str, title: str, payload: dict[str, Any]
    ) -> ChatRecord | None:
        encoded = json.dumps({**payload, "id": chat_id}, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            result = self._connection.execute(
                """UPDATE account_chats SET title = ?, payload_json = ?, updated_at = ?
                WHERE owner_id = ? AND id = ?""",
                (title, encoded, _now(), owner_id, chat_id),
            )
            self._connection.commit()
            if result.rowcount == 0:
                return None
            row = self._connection.execute(
                "SELECT * FROM account_chats WHERE owner_id = ? AND id = ?", (owner_id, chat_id)
            ).fetchone()
        return self._chat(row) if row else None

    async def delete_chat(self, *, owner_id: str, chat_id: str) -> bool:
        with self._lock:
            result = self._connection.execute(
                "DELETE FROM account_chats WHERE owner_id = ? AND id = ?", (owner_id, chat_id)
            )
            self._connection.commit()
        return result.rowcount > 0

    async def delete_account(self, account_id: str) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id FROM account_chats WHERE owner_id = ?", (account_id,)
            ).fetchall()
            chat_ids = [str(row["id"]) for row in rows]
            self._connection.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            self._connection.commit()
        return chat_ids

    @staticmethod
    def _account(row: sqlite3.Row) -> Account:
        return Account(
            id=str(row["id"]),
            issuer=str(row["issuer"]),
            subject=str(row["subject"]),
            email=str(row["email"]) if row["email"] is not None else None,
            display_name=str(row["display_name"]) if row["display_name"] is not None else None,
        )

    @staticmethod
    def _chat(row: sqlite3.Row) -> ChatRecord:
        payload = json.loads(str(row["payload_json"]))
        return ChatRecord(
            id=str(row["id"]),
            owner_id=str(row["owner_id"]),
            client_import_id=str(row["client_import_id"])
            if row["client_import_id"] is not None
            else None,
            title=str(row["title"]),
            payload=payload if isinstance(payload, dict) else {},
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


class PostgresAccountStore:
    """Durable account repository backed by the dedicated ``app`` schema."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def aclose(self) -> None:
        """The application owns and closes the shared pool."""

    async def upsert_account(
        self, *, issuer: str, subject: str, email: str | None, display_name: str | None
    ) -> Account:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """INSERT INTO app.accounts
                    (id, issuer, subject, email, display_name)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (issuer, subject) DO UPDATE
                    SET email = EXCLUDED.email,
                        display_name = EXCLUDED.display_name,
                        updated_at = now()
                    RETURNING id, issuer, subject, email, display_name""",
                    (uuid4(), issuer, subject, email, display_name),
                )
            ).fetchone()
        if row is None:  # pragma: no cover - RETURNING always returns an account
            raise RuntimeError("Upserted account could not be loaded")
        return self._account(row)

    async def create_session(self, *, account_id: str, token_hash: str, expires_at: str) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """INSERT INTO app.account_sessions(token_hash, account_id, expires_at)
                VALUES (%s, %s, %s)""",
                (token_hash, account_id, expires_at),
            )

    async def create_password_account(
        self, *, email: str, password_hash: str, display_name: str | None = None
    ) -> Account | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """INSERT INTO app.accounts
                    (id, issuer, subject, email, display_name, password_hash)
                    VALUES (%s, 'password', %s, %s, %s, %s)
                    ON CONFLICT (issuer, subject) DO NOTHING
                    RETURNING id, issuer, subject, email, display_name""",
                    (uuid4(), email, email, display_name, password_hash),
                )
            ).fetchone()
        return self._account(row) if row else None

    async def password_account(self, email: str) -> tuple[Account, str] | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """SELECT id, issuer, subject, email, display_name, password_hash
                    FROM app.accounts
                    WHERE issuer = 'password' AND subject = %s AND password_hash IS NOT NULL""",
                    (email,),
                )
            ).fetchone()
        return (self._account(row), str(row["password_hash"])) if row else None

    async def account_for_session(self, *, token_hash: str, now: str) -> Account | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """SELECT a.id, a.issuer, a.subject, a.email, a.display_name
                    FROM app.account_sessions AS s
                    JOIN app.accounts AS a ON a.id = s.account_id
                    WHERE s.token_hash = %s AND s.expires_at > %s""",
                    (token_hash, now),
                )
            ).fetchone()
        return self._account(row) if row else None

    async def delete_session(self, token_hash: str) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                "DELETE FROM app.account_sessions WHERE token_hash = %s", (token_hash,)
            )

    async def create_chat(
        self,
        *,
        owner_id: str,
        title: str,
        payload: dict[str, Any],
        client_import_id: str | None = None,
    ) -> ChatRecord:
        chat_id = uuid4()
        stored_payload = {**payload, "id": str(chat_id)}
        async with self._pool.connection() as connection:
            if client_import_id:
                query = """INSERT INTO app.account_chats
                    (id, owner_id, client_import_id, title, payload)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (owner_id, client_import_id) DO UPDATE
                    SET owner_id = EXCLUDED.owner_id
                    RETURNING id, owner_id, client_import_id, title, payload,
                              created_at, updated_at"""
            else:
                query = """INSERT INTO app.account_chats
                    (id, owner_id, client_import_id, title, payload)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, owner_id, client_import_id, title, payload,
                              created_at, updated_at"""
            row = await (
                await connection.execute(
                    query, (chat_id, owner_id, client_import_id, title, Jsonb(stored_payload))
                )
            ).fetchone()
        if row is None:  # pragma: no cover - RETURNING always returns a chat
            raise RuntimeError("Created chat could not be loaded")
        return self._chat(row)

    async def list_chats(self, owner_id: str) -> list[ChatRecord]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """SELECT id, owner_id, client_import_id, title, payload, created_at, updated_at
                    FROM app.account_chats WHERE owner_id = %s ORDER BY updated_at DESC""",
                    (owner_id,),
                )
            ).fetchall()
        return [self._chat(row) for row in rows]

    async def get_chat(self, *, owner_id: str, chat_id: str) -> ChatRecord | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """SELECT id, owner_id, client_import_id, title, payload, created_at, updated_at
                    FROM app.account_chats WHERE owner_id = %s AND id = %s""",
                    (owner_id, chat_id),
                )
            ).fetchone()
        return self._chat(row) if row else None

    async def owns_chat(self, *, owner_id: str, chat_id: str) -> bool:
        return await self.get_chat(owner_id=owner_id, chat_id=chat_id) is not None

    async def is_account_chat(self, chat_id: str) -> bool:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    "SELECT 1 FROM app.account_chats WHERE id = %s", (chat_id,)
                )
            ).fetchone()
        return row is not None

    async def update_chat(
        self, *, owner_id: str, chat_id: str, title: str, payload: dict[str, Any]
    ) -> ChatRecord | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """UPDATE app.account_chats
                    SET title = %s, payload = %s, updated_at = now()
                    WHERE owner_id = %s AND id = %s
                    RETURNING id, owner_id, client_import_id, title, payload,
                              created_at, updated_at""",
                    (title, Jsonb({**payload, "id": chat_id}), owner_id, chat_id),
                )
            ).fetchone()
        return self._chat(row) if row else None

    async def delete_chat(self, *, owner_id: str, chat_id: str) -> bool:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    "DELETE FROM app.account_chats WHERE owner_id = %s AND id = %s RETURNING id",
                    (owner_id, chat_id),
                )
            ).fetchone()
        return row is not None

    async def delete_account(self, account_id: str) -> list[str]:
        async with self._pool.connection() as connection:
            async with connection.transaction():
                rows = await (
                    await connection.execute(
                        "SELECT id FROM app.account_chats WHERE owner_id = %s", (account_id,)
                    )
                ).fetchall()
                await connection.execute("DELETE FROM app.accounts WHERE id = %s", (account_id,))
        return [str(row["id"]) for row in rows]

    @staticmethod
    def _account(row: dict[str, Any]) -> Account:
        return Account(
            id=str(row["id"]),
            issuer=str(row["issuer"]),
            subject=str(row["subject"]),
            email=str(row["email"]) if row["email"] is not None else None,
            display_name=str(row["display_name"]) if row["display_name"] is not None else None,
        )

    @staticmethod
    def _chat(row: dict[str, Any]) -> ChatRecord:
        payload = row["payload"]
        return ChatRecord(
            id=str(row["id"]),
            owner_id=str(row["owner_id"]),
            client_import_id=str(row["client_import_id"])
            if row["client_import_id"] is not None
            else None,
            title=str(row["title"]),
            payload=payload if isinstance(payload, dict) else {},
            created_at=_timestamp(row["created_at"]),
            updated_at=_timestamp(row["updated_at"]),
        )
