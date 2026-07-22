"""OIDC login flow and opaque application-session helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, status

from app.accounts.store import Account, AccountStore
from app.core.config import Settings

SESSION_COOKIE = "travel_account_session"
FLOW_COOKIE = "travel_oidc_flow"
SESSION_DAYS = 30
FLOW_MINUTES = 10
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
PASSWORD_SALT_BYTES = 16
PASSWORD_HASH_BYTES = 32
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LoginFlow:
    state: str
    verifier: str
    return_to: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class AccountSession:
    account: Account
    token: str


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        store: AccountStore,
        http_client: httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.store = store
        self.http_client = http_client
        self._session_secret = settings.auth_session_secret_value or secrets.token_urlsafe(48)

    @property
    def enabled(self) -> bool:
        return self.settings.account_auth_is_configured

    @property
    def oidc_enabled(self) -> bool:
        return self.settings.auth_is_configured

    @property
    def password_enabled(self) -> bool:
        return self.settings.password_auth_is_configured

    @property
    def cookie_secure(self) -> bool:
        return self.settings.auth_cookie_secure

    def begin_login(self, return_to: str) -> tuple[str, str]:
        if not self.oidc_enabled:
            raise HTTPException(status_code=503, detail="Account login is not configured")
        safe_return_to = (
            return_to if return_to.startswith("/") and not return_to.startswith("//") else "/"
        )
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(24)
        challenge = _b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        expires = datetime.now(UTC) + timedelta(minutes=FLOW_MINUTES)
        flow = LoginFlow(state, verifier, safe_return_to, expires.isoformat())
        query = urlencode(
            {
                "client_id": self.settings.oidc_client_id,
                "redirect_uri": self.settings.oidc_redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self.settings.oidc_authorization_url}?{query}", self._sign_flow(flow)

    async def complete_login(
        self, *, code: str, state: str, signed_flow: str
    ) -> tuple[str, str, str]:
        flow = self._verify_flow(signed_flow)
        if not hmac.compare_digest(flow.state, state):
            raise HTTPException(status_code=400, detail="Invalid login state")
        if datetime.fromisoformat(flow.expires_at) <= datetime.now(UTC):
            raise HTTPException(status_code=400, detail="Login attempt expired")
        token_response = await self.http_client.post(
            str(self.settings.oidc_token_url),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.oidc_redirect_uri,
                "client_id": self.settings.oidc_client_id,
                "client_secret": self.settings.oidc_client_secret_value,
                "code_verifier": flow.verifier,
            },
        )
        if token_response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Identity provider rejected the login")
        access_token = token_response.json().get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise HTTPException(
                status_code=502, detail="Identity provider returned no access token"
            )
        user_response = await self.http_client.get(
            str(self.settings.oidc_userinfo_url),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Could not load the authenticated identity")
        identity: Any = user_response.json()
        subject = identity.get("sub") if isinstance(identity, dict) else None
        if not isinstance(subject, str) or not subject:
            raise HTTPException(status_code=502, detail="Identity provider returned no subject")
        email = identity.get("email") if isinstance(identity.get("email"), str) else None
        name = identity.get("name") if isinstance(identity.get("name"), str) else None
        account = self.store.upsert_account(
            issuer=str(self.settings.oidc_issuer),
            subject=subject,
            email=email,
            display_name=name,
        )
        token, expires_at = self.issue_session(account)
        return token, flow.return_to, expires_at

    def register_password(self, *, email: str, password: str) -> tuple[str, str, Account]:
        if not self.password_enabled:
            raise HTTPException(status_code=503, detail="Password login is not configured")
        normalized_email = self._normalize_email(email)
        self._validate_password(password)
        account = self.store.create_password_account(
            email=normalized_email,
            password_hash=self._hash_password(password),
        )
        if account is None:
            raise HTTPException(status_code=409, detail="Account already exists")
        token, expires_at = self.issue_session(account)
        return token, expires_at, account

    def login_password(self, *, email: str, password: str) -> tuple[str, str, Account]:
        if not self.password_enabled:
            raise HTTPException(status_code=503, detail="Password login is not configured")
        normalized_email = self._normalize_email(email)
        account_and_hash = self.store.password_account(normalized_email)
        if account_and_hash is None or not self._verify_password(password, account_and_hash[1]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        token, expires_at = self.issue_session(account_and_hash[0])
        return token, expires_at, account_and_hash[0]

    def issue_session(self, account: Account) -> tuple[str, str]:
        """Create an opaque application session after identity verification."""

        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(days=SESSION_DAYS)
        self.store.create_session(
            account_id=account.id,
            token_hash=_token_hash(token),
            expires_at=expires.isoformat(),
        )
        return token, expires.isoformat()

    def current_session(self, request: Request) -> AccountSession | None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        account = self.store.account_for_session(
            token_hash=_token_hash(token), now=datetime.now(UTC).isoformat()
        )
        return AccountSession(account, token) if account else None

    def require_session(self, request: Request, *, csrf: bool = False) -> AccountSession:
        session = self.current_session(request)
        if session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
        if csrf:
            supplied = request.headers.get("X-CSRF-Token", "")
            expected = self.csrf_token(session.token)
            if not supplied or not hmac.compare_digest(supplied, expected):
                raise HTTPException(status_code=403, detail="Invalid CSRF token")
        return session

    def csrf_token(self, session_token: str) -> str:
        return _b64encode(
            hmac.new(self._secret(), f"csrf:{session_token}".encode(), hashlib.sha256).digest()
        )

    def logout(self, session_token: str) -> None:
        self.store.delete_session(_token_hash(session_token))

    def _secret(self) -> bytes:
        return self._session_secret.encode("utf-8")

    @staticmethod
    def _normalize_email(value: str) -> str:
        email = value.strip().casefold()
        if not EMAIL_PATTERN.fullmatch(email):
            raise HTTPException(status_code=422, detail="Enter a valid email address")
        return email

    @staticmethod
    def _validate_password(value: str) -> None:
        if not 12 <= len(value) <= 256:
            raise HTTPException(
                status_code=422, detail="Password must contain from 12 to 256 characters"
            )

    @staticmethod
    def _hash_password(value: str) -> str:
        salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
        derived = hashlib.scrypt(
            value.encode("utf-8"),
            salt=salt,
            n=PASSWORD_SCRYPT_N,
            r=PASSWORD_SCRYPT_R,
            p=PASSWORD_SCRYPT_P,
            dklen=PASSWORD_HASH_BYTES,
        )
        return f"scrypt${_b64encode(salt)}${_b64encode(derived)}"

    @staticmethod
    def _verify_password(value: str, stored: str) -> bool:
        try:
            algorithm, encoded_salt, encoded_hash = stored.split("$", 2)
            if algorithm != "scrypt":
                return False
            salt = base64.urlsafe_b64decode(encoded_salt + "=" * (-len(encoded_salt) % 4))
            expected = base64.urlsafe_b64decode(encoded_hash + "=" * (-len(encoded_hash) % 4))
            actual = hashlib.scrypt(
                value.encode("utf-8"),
                salt=salt,
                n=PASSWORD_SCRYPT_N,
                r=PASSWORD_SCRYPT_R,
                p=PASSWORD_SCRYPT_P,
                dklen=len(expected),
            )
        except (TypeError, ValueError):
            return False
        return hmac.compare_digest(actual, expected)

    def _sign_flow(self, flow: LoginFlow) -> str:
        payload = _b64encode(json.dumps(asdict(flow), separators=(",", ":")).encode("utf-8"))
        signature = _b64encode(hmac.new(self._secret(), payload.encode(), hashlib.sha256).digest())
        return f"{payload}.{signature}"

    def _verify_flow(self, value: str) -> LoginFlow:
        try:
            payload, supplied = value.split(".", 1)
            expected = _b64encode(
                hmac.new(self._secret(), payload.encode(), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied, expected):
                raise ValueError
            padding = "=" * (-len(payload) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload + padding))
            return LoginFlow(**data)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid login flow") from exc
