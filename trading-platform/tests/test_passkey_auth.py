from __future__ import annotations

from fastapi.testclient import TestClient

from core import passkey_auth
from main import app


def test_passkey_encoding_round_trips_binary_values():
    value = bytes(range(256))
    assert passkey_auth.b64url_decode(passkey_auth.b64url_encode(value)) == value


def test_webauthn_context_uses_public_browser_origin_behind_a_proxy(monkeypatch):
    monkeypatch.delenv("WEBAUTHN_RP_ID", raising=False)
    monkeypatch.delenv("WEBAUTHN_ORIGIN", raising=False)

    rp_id, origin = passkey_auth.webauthn_context(
        {"origin": "https://fleet.example.test"},
        fallback_host="localhost:8000",
    )

    assert rp_id == "fleet.example.test"
    assert origin == "https://fleet.example.test"


def test_published_webauthn_requires_an_explicit_origin(monkeypatch):
    monkeypatch.delenv("WEBAUTHN_RP_ID", raising=False)
    monkeypatch.delenv("WEBAUTHN_ORIGIN", raising=False)
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")

    try:
        passkey_auth.webauthn_context({"origin": "https://fleet.example.test"})
    except RuntimeError as exc:
        assert "WEBAUTHN_ORIGIN" in str(exc)
    else:
        raise AssertionError("published passkey context must fail closed")


def test_passkey_session_route_is_public_but_requires_a_valid_cookie(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)

    client = TestClient(app)
    response = client.get("/auth/passkey/session")
    client.close()

    assert response.status_code == 401
    assert response.json() == {"detail": "No active passkey session."}


def test_passkey_options_route_is_public_and_reports_missing_setup(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    monkeypatch.setattr(passkey_auth, "list_credentials", lambda clerk_user_id=None: [])

    client = TestClient(app)
    response = client.post("/auth/passkey/authentication/options")
    client.close()

    assert response.status_code == 404
    assert "No device passkey is registered" in response.json()["detail"]


def test_verified_passkey_session_can_access_protected_routes(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    monkeypatch.setattr(passkey_auth, "session_user_id", lambda token: "user_operator")

    client = TestClient(app)
    client.cookies.set(passkey_auth.PASSKEY_SESSION_COOKIE, "opaque-session")
    response = client.get("/trading-api/version")
    client.close()

    assert response.status_code == 200
    assert "running_hash" in response.json()


def test_invalid_passkey_session_does_not_bypass_api_auth(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    monkeypatch.setattr(passkey_auth, "session_user_id", lambda token: None)

    client = TestClient(app)
    client.cookies.set(passkey_auth.PASSKEY_SESSION_COOKIE, "invalid-session")
    response = client.get("/trading-api/version")
    client.close()

    assert response.status_code == 401