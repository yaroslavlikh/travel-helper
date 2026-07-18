"""Small SQLite account repository with explicit ownership boundaries."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(UTC).isoformat()


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


class AccountStore:
    """Persist accounts, application sessions, and browser chat snapshots."""

    def __init__(self, database_path: str) -> None:
        if database_path != ":memory:":
            path = Path(database_path)
            path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    issuer TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    email TEXT,
                    display_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (issuer, subject)
                );
                CREATE TABLE IF NOT EXISTS account_sessions (
                    token_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS account_sessions_owner_idx
                    ON account_sessions(account_id);
                CREATE TABLE IF NOT EXISTS account_chats (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    client_import_id TEXT,
                    title TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (owner_id, client_import_id)
                );
                CREATE INDEX IF NOT EXISTS account_chats_owner_updated_idx
                    ON account_chats(owner_id, updated_at DESC);
                """
            )
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def upsert_account(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        display_name: str | None,
    ) -> Account:
        timestamp = _now()
        with self._lock:
            row = self._connection.execute(
                "SELECT id FROM accounts WHERE issuer = ? AND subject = ?",
                (issuer, subject),
            ).fetchone()
            account_id = str(row["id"]) if row else str(uuid4())
            if row:
                self._connection.execute(
                    """
                    UPDATE accounts SET email = ?, display_name = ?, updated_at = ? WHERE id = ?
                    """,
                    (email, display_name, timestamp, account_id),
                )
            else:
                self._connection.execute(
                    """
                    INSERT INTO accounts
                        (id, issuer, subject, email, display_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (account_id, issuer, subject, email, display_name, timestamp, timestamp),
                )
            self._connection.commit()
        return Account(account_id, issuer, subject, email, display_name)

    def create_session(self, *, account_id: str, token_hash: str, expires_at: str) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO account_sessions(token_hash, account_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash, account_id, expires_at, _now()),
            )
            self._connection.commit()

    def account_for_session(self, *, token_hash: str, now: str) -> Account | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT a.id, a.issuer, a.subject, a.email, a.display_name
                FROM account_sessions s
                JOIN accounts a ON a.id = s.account_id
                WHERE s.token_hash = ? AND s.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
        return self._account(row) if row else None

    def delete_session(self, token_hash: str) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM account_sessions WHERE token_hash = ?", (token_hash,)
            )
            self._connection.commit()

    def create_chat(
        self,
        *,
        owner_id: str,
        title: str,
        payload: dict[str, Any],
        client_import_id: str | None = None,
    ) -> ChatRecord:
        timestamp = _now()
        with self._lock:
            if client_import_id:
                existing = self._connection.execute(
                    """
                    SELECT * FROM account_chats
                    WHERE owner_id = ? AND client_import_id = ?
                    """,
                    (owner_id, client_import_id),
                ).fetchone()
                if existing:
                    return self._chat(existing)
            chat_id = str(uuid4())
            stored_payload = {**payload, "id": chat_id}
            encoded = json.dumps(stored_payload, ensure_ascii=False, separators=(",", ":"))
            self._connection.execute(
                """
                INSERT INTO account_chats
                    (id, owner_id, client_import_id, title, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (chat_id, owner_id, client_import_id, title, encoded, timestamp, timestamp),
            )
            self._connection.commit()
            row = self._connection.execute(
                "SELECT * FROM account_chats WHERE id = ?", (chat_id,)
            ).fetchone()
        if row is None:  # pragma: no cover - SQLite returns the inserted row
            raise RuntimeError("Created chat could not be loaded")
        return self._chat(row)

    def list_chats(self, owner_id: str) -> list[ChatRecord]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM account_chats WHERE owner_id = ? ORDER BY updated_at DESC",
                (owner_id,),
            ).fetchall()
        return [self._chat(row) for row in rows]

    def get_chat(self, *, owner_id: str, chat_id: str) -> ChatRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM account_chats WHERE owner_id = ? AND id = ?",
                (owner_id, chat_id),
            ).fetchone()
        return self._chat(row) if row else None

    def owns_chat(self, *, owner_id: str, chat_id: str) -> bool:
        return self.get_chat(owner_id=owner_id, chat_id=chat_id) is not None

    def update_chat(
        self, *, owner_id: str, chat_id: str, title: str, payload: dict[str, Any]
    ) -> ChatRecord | None:
        stored_payload = {**payload, "id": chat_id}
        encoded = json.dumps(stored_payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            result = self._connection.execute(
                """
                UPDATE account_chats
                SET title = ?, payload_json = ?, updated_at = ?
                WHERE owner_id = ? AND id = ?
                """,
                (title, encoded, _now(), owner_id, chat_id),
            )
            self._connection.commit()
            if result.rowcount == 0:
                return None
            row = self._connection.execute(
                "SELECT * FROM account_chats WHERE owner_id = ? AND id = ?",
                (owner_id, chat_id),
            ).fetchone()
        return self._chat(row) if row else None

    def delete_chat(self, *, owner_id: str, chat_id: str) -> bool:
        with self._lock:
            result = self._connection.execute(
                "DELETE FROM account_chats WHERE owner_id = ? AND id = ?",
                (owner_id, chat_id),
            )
            self._connection.commit()
        return result.rowcount > 0

    def delete_account(self, account_id: str) -> list[str]:
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
            display_name=(str(row["display_name"]) if row["display_name"] is not None else None),
        )

    @staticmethod
    def _chat(row: sqlite3.Row) -> ChatRecord:
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict):
            payload = {}
        return ChatRecord(
            id=str(row["id"]),
            owner_id=str(row["owner_id"]),
            client_import_id=(
                str(row["client_import_id"]) if row["client_import_id"] is not None else None
            ),
            title=str(row["title"]),
            payload=payload,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
