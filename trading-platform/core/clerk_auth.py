"""Small, fail-closed adapter for Clerk browser session authentication."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from clerk_backend_api.jwks_helpers import (
    AuthenticateRequestOptions,
    authenticate_request,
)


def clerk_user_id_from_headers(
    headers: Mapping[str, str],
    secret_key: str | None,
) -> str | None:
    """Return the verified Clerk subject from a request's browser headers.

    Clerk web sessions arrive in the ``__session`` cookie.  The SDK also
    supports an Authorization header, which is useful for non-browser clients.
    Verification failures deliberately collapse to ``None`` so the API
    middleware can fail closed without exposing token-validation details.
    """

    if not secret_key:
        return None

    cookie_header = headers.get("cookie", "")
    authorization_header = headers.get("authorization", "")
    sdk_headers: dict[str, str] = {}
    if cookie_header:
        sdk_headers["cookie"] = cookie_header
    if authorization_header:
        sdk_headers["Authorization"] = authorization_header
    if not sdk_headers:
        return None

    try:
        state = authenticate_request(
            sdk_headers,
            AuthenticateRequestOptions(secret_key=secret_key),
        )
    except Exception:
        return None

    if not state.is_signed_in or not isinstance(state.payload, dict):
        return None

    subject = state.payload.get("sub")
    return str(subject) if subject else None