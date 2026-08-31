"""Passwordless device authentication routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from core.passkey_auth import (
    PASSKEY_FLOW_COOKIE,
    PASSKEY_SESSION_COOKIE,
    authentication_options,
    b64url_decode,
    b64url_encode,
    consume_challenge,
    create_challenge,
    create_session,
    delete_credential,
    get_challenge,
    get_credential,
    list_credentials,
    registration_options,
    record_event,
    revoke_session,
    save_credential,
    session_user_id,
    update_sign_count,
    verify_authentication,
    verify_registration,
    webauthn_context,
)

router = APIRouter(prefix="/auth/passkey", tags=["Passkey authentication"])


def _secure_cookie(request: Request) -> bool:
    origin = request.headers.get("origin", "").strip()
    if origin:
        return origin.lower().startswith("https://")
    return (
        request.headers.get("x-forwarded-proto", request.url.scheme)
        .split(",", 1)[0]
        .strip()
        .lower()
        == "https"
    )


def _set_flow_cookie(response: JSONResponse, request: Request, challenge_id: str) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        PASSKEY_FLOW_COOKIE,
        challenge_id,
        max_age=300,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="lax",
        path="/",
    )


def _set_session_cookie(response: JSONResponse, request: Request, token: str) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        PASSKEY_SESSION_COOKIE,
        token,
        max_age=12 * 60 * 60,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="lax",
        path="/",
    )


def _clear_flow_cookie(response: JSONResponse) -> None:
    response.delete_cookie(PASSKEY_FLOW_COOKIE, path="/")


def _clear_session_cookie(response: JSONResponse) -> None:
    response.delete_cookie(PASSKEY_SESSION_COOKIE, path="/")


def _auth_user_id(request: Request) -> str | None:
    return getattr(request.state, "clerk_user_id", None)


def _json_body(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid passkey response.")
    return body


@router.post("/registration/options")
async def passkey_registration_options(request: Request) -> JSONResponse:
    user_id = _auth_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    rp_id, _ = webauthn_context(request.headers, request.url.hostname or "localhost")
    credentials = list_credentials(user_id)
    challenge, options_json = registration_options(
        rp_id=rp_id,
        clerk_user_id=user_id,
        existing_credentials=credentials,
    )
    challenge_id = create_challenge(
        flow="registration",
        clerk_user_id=user_id,
        challenge=challenge,
    )
    record_event(
        event_type="registration_options_issued",
        clerk_user_id=user_id,
        success=True,
    )
    response = JSONResponse(content=json.loads(options_json))
    _set_flow_cookie(response, request, challenge_id)
    return response


@router.post("/registration/verify")
async def passkey_registration_verify(
    request: Request,
    body: dict[str, Any],
) -> JSONResponse:
    user_id = _auth_user_id(request)
    flow_id = request.cookies.get(PASSKEY_FLOW_COOKIE, "")
    challenge_record = get_challenge(flow_id)
    if (
        not user_id
        or not challenge_record
        or challenge_record["flow"] != "registration"
        or challenge_record["clerk_user_id"] != user_id
    ):
        record_event(
            event_type="registration_failed",
            clerk_user_id=user_id,
            success=False,
            failure_code="expired_or_mismatched_challenge",
        )
        raise HTTPException(status_code=400, detail="Passkey setup expired. Start again.")
    try:
        rp_id, origin = webauthn_context(request.headers, request.url.hostname or "localhost")
        verified = verify_registration(
            credential=_json_body(body),
            challenge=challenge_record["challenge"],
            rp_id=rp_id,
            origin=origin,
        )
        if not consume_challenge(flow_id):
            raise HTTPException(status_code=400, detail="Passkey setup expired. Start again.")
        save_credential(
            credential_id=verified.credential_id,
            clerk_user_id=user_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            label="This device",
        )
        record_event(
            event_type="registration_succeeded",
            clerk_user_id=user_id,
            credential_id=verified.credential_id,
            success=True,
        )
    except HTTPException:
        record_event(
            event_type="registration_failed",
            clerk_user_id=user_id,
            success=False,
            failure_code="verification_rejected",
        )
        raise
    except Exception as exc:
        record_event(
            event_type="registration_failed",
            clerk_user_id=user_id,
            success=False,
            failure_code=type(exc).__name__,
        )
        logger.warning(f"Passkey registration rejected: {type(exc).__name__}")
        raise HTTPException(status_code=400, detail="Passkey registration failed.") from exc
    response = JSONResponse(content={"registered": True})
    _clear_flow_cookie(response)
    return response


@router.post("/authentication/options")
async def passkey_authentication_options(request: Request) -> JSONResponse:
    rp_id, _ = webauthn_context(request.headers, request.url.hostname or "localhost")
    credentials = list_credentials()
    if not credentials:
        raise HTTPException(
            status_code=404,
            detail="No device passkey is registered. Use recovery sign-in to set one up.",
        )
    challenge, options_json = authentication_options(
        rp_id=rp_id,
        credentials=credentials,
    )
    challenge_id = create_challenge(
        flow="authentication",
        clerk_user_id=None,
        challenge=challenge,
    )
    record_event(
        event_type="authentication_options_issued",
        success=True,
    )
    response = JSONResponse(content=json.loads(options_json))
    _set_flow_cookie(response, request, challenge_id)
    return response


@router.post("/authentication/verify")
async def passkey_authentication_verify(
    request: Request,
    body: dict[str, Any],
) -> JSONResponse:
    flow_id = request.cookies.get(PASSKEY_FLOW_COOKIE, "")
    challenge_record = get_challenge(flow_id)
    if (
        not challenge_record
        or challenge_record["flow"] != "authentication"
        or challenge_record["used_at"] is not None
    ):
        record_event(
            event_type="authentication_failed",
            success=False,
            failure_code="expired_or_mismatched_challenge",
        )
        raise HTTPException(status_code=400, detail="Passkey sign-in expired. Start again.")
    try:
        credential = _json_body(body)
        credential_id = b64url_decode(str(credential.get("rawId", "")))
        stored = get_credential(credential_id)
        if not stored:
            raise HTTPException(status_code=401, detail="Passkey sign-in failed.")
        rp_id, origin = webauthn_context(request.headers, request.url.hostname or "localhost")
        verified = verify_authentication(
            credential=credential,
            challenge=challenge_record["challenge"],
            rp_id=rp_id,
            origin=origin,
            stored_credential=stored,
        )
        if not consume_challenge(flow_id):
            raise HTTPException(status_code=400, detail="Passkey sign-in expired. Start again.")
        update_sign_count(credential_id, verified.new_sign_count)
        token = create_session(stored["clerk_user_id"])
        record_event(
            event_type="authentication_succeeded",
            clerk_user_id=stored["clerk_user_id"],
            credential_id=credential_id,
            success=True,
        )
    except HTTPException:
        record_event(
            event_type="authentication_failed",
            success=False,
            failure_code="verification_rejected",
        )
        raise
    except Exception as exc:
        record_event(
            event_type="authentication_failed",
            success=False,
            failure_code=type(exc).__name__,
        )
        logger.warning(f"Passkey authentication rejected: {type(exc).__name__}")
        raise HTTPException(status_code=401, detail="Passkey sign-in failed.") from exc
    response = JSONResponse(content={"authenticated": True})
    _clear_flow_cookie(response)
    _set_session_cookie(response, request, token)
    return response


@router.get("/session")
async def passkey_session(request: Request) -> JSONResponse:
    user_id = session_user_id(request.cookies.get(PASSKEY_SESSION_COOKIE))
    if not user_id:
        raise HTTPException(status_code=401, detail="No active passkey session.")
    response = JSONResponse(content={"authenticated": True})
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/logout")
async def passkey_logout(request: Request) -> JSONResponse:
    try:
        revoke_session(request.cookies.get(PASSKEY_SESSION_COOKIE))
    except Exception as exc:
        # Clearing the browser cookie is still useful if the database is
        # temporarily unavailable. The persisted session remains bounded by
        # its expiry and cannot be reused from this browser afterward.
        logger.warning(f"Passkey logout revocation deferred: {type(exc).__name__}")
    record_event(
        event_type="logout",
        clerk_user_id=_auth_user_id(request),
        success=True,
    )
    response = JSONResponse(content={"signed_out": True})
    response.headers["Cache-Control"] = "no-store"
    _clear_session_cookie(response)
    _clear_flow_cookie(response)
    return response


@router.get("/credentials")
async def passkey_credentials(request: Request) -> JSONResponse:
    user_id = _auth_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    rows = list_credentials(user_id)
    return JSONResponse(
        content={
            "credentials": [
                {
                    "id": b64url_encode(row["credential_id"]),
                    "label": row["label"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "last_used_at": row["last_used_at"].isoformat()
                    if row["last_used_at"]
                    else None,
                }
                for row in rows
            ]
        }
    )


@router.delete("/credentials/{credential_id}")
async def passkey_credential_delete(request: Request, credential_id: str) -> JSONResponse:
    user_id = _auth_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        decoded_id = b64url_decode(credential_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid passkey identifier.") from exc
    if not delete_credential(decoded_id, user_id):
        record_event(
            event_type="credential_revocation_failed",
            clerk_user_id=user_id,
            credential_id=decoded_id,
            success=False,
            failure_code="not_found",
        )
        raise HTTPException(status_code=404, detail="Passkey not found.")
    record_event(
        event_type="credential_revoked",
        clerk_user_id=user_id,
        credential_id=decoded_id,
        success=True,
    )
    return JSONResponse(content={"deleted": True})