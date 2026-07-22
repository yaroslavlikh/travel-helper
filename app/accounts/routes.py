"""Optional login and server-synced account chat API."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.accounts.auth import FLOW_COOKIE, SESSION_COOKIE
from app.accounts.store import Account, ChatRecord
from app.core.resources import AppResources

router = APIRouter()
MAX_CHAT_BYTES = 2_000_000


class AccountApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountSummary(AccountApiModel):
    id: str
    email: str | None
    display_name: str | None


class AccountStatus(AccountApiModel):
    auth_enabled: bool
    password_enabled: bool
    oidc_enabled: bool
    authenticated: bool
    account: AccountSummary | None = None
    csrf_token: str | None = None


class ChatInput(AccountApiModel):
    title: str = Field(default="Новая поездка", min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatImportInput(ChatInput):
    client_import_id: str = Field(min_length=8, max_length=160)


class ChatOutput(AccountApiModel):
    id: str
    title: str
    payload: dict[str, Any]
    created_at: str
    updated_at: str


class DeleteAccountInput(AccountApiModel):
    confirmation: Literal["DELETE"]


class PasswordCredentials(AccountApiModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


def _resources(request: Request) -> AppResources:
    resources = request.app.state.resources
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are unavailable")
    return resources


def _summary(account: Account) -> AccountSummary:
    return AccountSummary(
        id=account.id,
        email=account.email,
        display_name=account.display_name,
    )


def _chat_output(chat: ChatRecord) -> ChatOutput:
    return ChatOutput(
        id=chat.id,
        title=chat.title,
        payload=chat.payload,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def _account_status(resources: AppResources, account: Account, token: str) -> AccountStatus:
    return AccountStatus(
        auth_enabled=resources.auth_service.enabled,
        password_enabled=resources.auth_service.password_enabled,
        oidc_enabled=resources.auth_service.oidc_enabled,
        authenticated=True,
        account=_summary(account),
        csrf_token=resources.auth_service.csrf_token(token),
    )


def _set_session_cookie(response: Response, resources: AppResources, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=resources.auth_service.cookie_secure,
        samesite="lax",
        path="/",
    )


def _validate_payload(payload: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="Chat snapshot must be JSON serializable"
        ) from exc
    if len(encoded) > MAX_CHAT_BYTES:
        raise HTTPException(status_code=413, detail="Chat snapshot is too large")


@router.get("/auth/login", include_in_schema=False)
async def login(request: Request, return_to: str = "/") -> RedirectResponse:
    resources = _resources(request)
    url, signed_flow = resources.auth_service.begin_login(return_to)
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        FLOW_COOKIE,
        signed_flow,
        max_age=600,
        httponly=True,
        secure=resources.auth_service.cookie_secure,
        samesite="lax",
        path="/auth",
    )
    return response


@router.get("/auth/callback", include_in_schema=False)
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    resources = _resources(request)
    signed_flow = request.cookies.get(FLOW_COOKIE, "")
    if error or not code or not state:
        return _failed_login_response()
    try:
        token, return_to, _expires_at = await resources.auth_service.complete_login(
            code=code,
            state=state,
            signed_flow=signed_flow,
        )
    except HTTPException:
        return _failed_login_response()
    response = RedirectResponse(return_to, status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(FLOW_COOKIE, path="/auth")
    _set_session_cookie(response, resources, token)
    return response


def _failed_login_response() -> RedirectResponse:
    response = RedirectResponse("/login?error=login_failed", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(FLOW_COOKIE, path="/auth")
    return response


@router.post(
    "/auth/password/register",
    response_model=AccountStatus,
    status_code=status.HTTP_201_CREATED,
    tags=["account"],
)
async def password_register(
    payload: PasswordCredentials, request: Request, response: Response
) -> AccountStatus:
    resources = _resources(request)
    token, _expires_at, account = resources.auth_service.register_password(
        email=payload.email, password=payload.password
    )
    _set_session_cookie(response, resources, token)
    return _account_status(resources, account, token)


@router.post("/auth/password/login", response_model=AccountStatus, tags=["account"])
async def password_login(
    payload: PasswordCredentials, request: Request, response: Response
) -> AccountStatus:
    resources = _resources(request)
    token, _expires_at, account = resources.auth_service.login_password(
        email=payload.email, password=payload.password
    )
    _set_session_cookie(response, resources, token)
    return _account_status(resources, account, token)


@router.get("/account/me", response_model=AccountStatus, tags=["account"])
async def account_status(request: Request) -> AccountStatus:
    resources = _resources(request)
    session = resources.auth_service.current_session(request)
    if session is None:
        return AccountStatus(
            auth_enabled=resources.auth_service.enabled,
            password_enabled=resources.auth_service.password_enabled,
            oidc_enabled=resources.auth_service.oidc_enabled,
            authenticated=False,
        )
    return _account_status(resources, session.account, session.token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["account"])
async def logout(request: Request) -> Response:
    resources = _resources(request)
    session = resources.auth_service.require_session(request, csrf=True)
    resources.auth_service.logout(session.token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/account/chats", response_model=list[ChatOutput], tags=["account"])
async def list_chats(request: Request) -> list[ChatOutput]:
    resources = _resources(request)
    session = resources.auth_service.require_session(request)
    return [_chat_output(chat) for chat in resources.account_store.list_chats(session.account.id)]


@router.post(
    "/account/chats",
    response_model=ChatOutput,
    status_code=status.HTTP_201_CREATED,
    tags=["account"],
)
async def create_chat(payload: ChatInput, request: Request) -> ChatOutput:
    resources = _resources(request)
    session = resources.auth_service.require_session(request, csrf=True)
    _validate_payload(payload.payload)
    return _chat_output(
        resources.account_store.create_chat(
            owner_id=session.account.id,
            title=payload.title,
            payload=payload.payload,
        )
    )


@router.post(
    "/account/chats/import",
    response_model=ChatOutput,
    status_code=status.HTTP_201_CREATED,
    tags=["account"],
)
async def import_chat(payload: ChatImportInput, request: Request) -> ChatOutput:
    resources = _resources(request)
    session = resources.auth_service.require_session(request, csrf=True)
    _validate_payload(payload.payload)
    return _chat_output(
        resources.account_store.create_chat(
            owner_id=session.account.id,
            title=payload.title,
            payload=payload.payload,
            client_import_id=payload.client_import_id,
        )
    )


@router.put("/account/chats/{chat_id}", response_model=ChatOutput, tags=["account"])
async def update_chat(chat_id: str, payload: ChatInput, request: Request) -> ChatOutput:
    resources = _resources(request)
    session = resources.auth_service.require_session(request, csrf=True)
    _validate_payload(payload.payload)
    chat = resources.account_store.update_chat(
        owner_id=session.account.id,
        chat_id=chat_id,
        title=payload.title,
        payload=payload.payload,
    )
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return _chat_output(chat)


@router.delete("/account/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["account"])
async def delete_chat(chat_id: str, request: Request) -> Response:
    resources = _resources(request)
    session = resources.auth_service.require_session(request, csrf=True)
    if not resources.account_store.delete_chat(owner_id=session.account.id, chat_id=chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    await resources.checkpointer.adelete_thread(chat_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT, tags=["account"])
async def delete_account(payload: DeleteAccountInput, request: Request) -> Response:
    resources = _resources(request)
    session = resources.auth_service.require_session(request, csrf=True)
    chat_ids = resources.account_store.delete_account(session.account.id)
    for chat_id in chat_ids:
        await resources.checkpointer.adelete_thread(chat_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
