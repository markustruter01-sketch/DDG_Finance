"""Server-side WebAuthn and application-session helpers.

The browser never receives a private key or a long-lived API secret.  It
returns a signed WebAuthn assertion, which this module verifies before issuing
an opaque, HttpOnly application session.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from db.postgres import get_conn
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

PASSKEY_SESSION_COOKIE = "fleet_passkey_session"
PASSKEY_FLOW_COOKIE = "fleet_passkey_flow"
PASSKEY_SESSION_TTL_SECONDS = 12 * 60 * 60
PASSKEY_FLOW_TTL_SECONDS = 5 * 60


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _forwarded_host(headers: Any, fallback: str) -> str:
    value = str(headers.get("x-forwarded-host") or fallback).split(",", 1)[0].strip()
    return value


def webauthn_context(headers: Any, fallback_host: str = "localhost") -> tuple[str, str]:
    """Return the relying-party ID and browser origin for this request.

    The shared Replit proxy forwards the public host and scheme.  Explicit
    environment overrides are available for a custom domain, while local
    development naturally uses the request host.
    """

    host = _forwarded_host(headers, fallback_host)
    rp_id = os.getenv("WEBAUTHN_RP_ID", "").strip()
    if not rp_id:
        rp_id = urlsplit(f"//{host}").hostname or "localhost"

    origin = os.getenv("WEBAUTHN_ORIGIN", "").strip()
    if not origin:
        scheme = str(headers.get("x-forwarded-proto") or "http").split(",", 1)[0].strip()
        origin = f"{scheme}://{host}"
    return rp_id, origin


def _new_id() -> str:
    return secrets.token_urlsafe(32)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_challenge(
    *,
    flow: str,
    clerk_user_id: str | None,
    challenge: bytes,
) -> str:
    challenge_id = _new_id()
    expires_at = _now() + timedelta(seconds=PASSKEY_FLOW_TTL_SECONDS)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fleet_passkey_challenges
                    (challenge_id, flow, clerk_user_id, challenge, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (challenge_id, flow, clerk_user_id, challenge, expires_at),
            )
    return challenge_id


def get_challenge(challenge_id: str) -> dict[str, Any] | None:
    if not challenge_id:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT challenge_id, flow, clerk_user_id, challenge, expires_at, used_at
                FROM fleet_passkey_challenges
                WHERE challenge_id = %s
                """,
                (challenge_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "challenge_id": row[0],
        "flow": row[1],
        "clerk_user_id": row[2],
        "challenge": bytes(row[3]),
        "expires_at": row[4],
        "used_at": row[5],
    }


def consume_challenge(challenge_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE fleet_passkey_challenges
                SET used_at = CURRENT_TIMESTAMP
                WHERE challenge_id = %s
                  AND used_at IS NULL
                  AND expires_at > CURRENT_TIMESTAMP
                """,
                (challenge_id,),
            )
            return cur.rowcount == 1


def list_credentials(clerk_user_id: str | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT credential_id, clerk_user_id, public_key, sign_count,
               label, created_at, last_used_at
        FROM fleet_passkey_credentials
    """
    params: tuple[Any, ...] = ()
    if clerk_user_id:
        query += " WHERE clerk_user_id = %s"
        params = (clerk_user_id,)
    query += " ORDER BY created_at ASC"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    return [
        {
            "credential_id": bytes(row[0]),
            "clerk_user_id": row[1],
            "public_key": bytes(row[2]),
            "sign_count": int(row[3]),
            "label": row[4],
            "created_at": row[5],
            "last_used_at": row[6],
        }
        for row in rows
    ]


def get_credential(credential_id: bytes) -> dict[str, Any] | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT credential_id, clerk_user_id, public_key, sign_count,
                       label, created_at, last_used_at
                FROM fleet_passkey_credentials
                WHERE credential_id = %s
                """,
                (credential_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "credential_id": bytes(row[0]),
        "clerk_user_id": row[1],
        "public_key": bytes(row[2]),
        "sign_count": int(row[3]),
        "label": row[4],
        "created_at": row[5],
        "last_used_at": row[6],
    }


def save_credential(
    *,
    credential_id: bytes,
    clerk_user_id: str,
    public_key: bytes,
    sign_count: int,
    label: str,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fleet_passkey_credentials
                    (credential_id, clerk_user_id, public_key, sign_count, label)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (credential_id, clerk_user_id, public_key, sign_count, label[:80]),
            )


def update_sign_count(credential_id: bytes, sign_count: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE fleet_passkey_credentials
                SET sign_count = %s, last_used_at = CURRENT_TIMESTAMP
                WHERE credential_id = %s
                """,
                (sign_count, credential_id),
            )


def delete_credential(credential_id: bytes, clerk_user_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM fleet_passkey_credentials
                WHERE credential_id = %s AND clerk_user_id = %s
                """,
                (credential_id, clerk_user_id),
            )
            return cur.rowcount == 1


def create_session(clerk_user_id: str) -> str:
    token = _new_id()
    expires_at = _now() + timedelta(seconds=PASSKEY_SESSION_TTL_SECONDS)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fleet_passkey_sessions
                    (session_hash, clerk_user_id, expires_at)
                VALUES (%s, %s, %s)
                """,
                (_hash_token(token), clerk_user_id, expires_at),
            )
    return token


def session_user_id(token: str | None) -> str | None:
    if not token:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT clerk_user_id
                FROM fleet_passkey_sessions
                WHERE session_hash = %s
                  AND revoked_at IS NULL
                  AND expires_at > CURRENT_TIMESTAMP
                """,
                (_hash_token(token),),
            )
            row = cur.fetchone()
    return str(row[0]) if row else None


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE fleet_passkey_sessions
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE session_hash = %s AND revoked_at IS NULL
                """,
                (_hash_token(token),),
            )


def registration_options(
    *,
    rp_id: str,
    clerk_user_id: str,
    existing_credentials: list[dict[str, Any]],
) -> tuple[bytes, str]:
    challenge = secrets.token_bytes(32)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name="Fleet Command",
        user_name="operator",
        user_display_name="Fleet Command operator",
        user_id=clerk_user_id.encode("utf-8")[:64],
        challenge=challenge,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=row["credential_id"])
            for row in existing_credentials
        ],
    )
    return challenge, options_to_json(options)


def authentication_options(
    *,
    rp_id: str,
    credentials: list[dict[str, Any]],
) -> tuple[bytes, str]:
    challenge = secrets.token_bytes(32)
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=row["credential_id"])
            for row in credentials
        ],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return challenge, options_to_json(options)


def verify_registration(
    *,
    credential: dict[str, Any],
    challenge: bytes,
    rp_id: str,
    origin: str,
) -> Any:
    return verify_registration_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=rp_id,
        expected_origin=origin,
        require_user_presence=True,
        require_user_verification=True,
    )


def verify_authentication(
    *,
    credential: dict[str, Any],
    challenge: bytes,
    rp_id: str,
    origin: str,
    stored_credential: dict[str, Any],
) -> Any:
    return verify_authentication_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=rp_id,
        expected_origin=origin,
        credential_public_key=stored_credential["public_key"],
        credential_current_sign_count=stored_credential["sign_count"],
        require_user_verification=True,
    )