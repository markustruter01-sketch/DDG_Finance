from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_health_is_minimal_and_does_not_require_secret(monkeypatch):
    monkeypatch.delenv("TRADING_API_SECRET", raising=False)

    client = TestClient(app)
    response = client.get("/health")
    client.close()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_route_rejects_missing_secret(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)

    client = TestClient(app)
    response = client.get("/trading-api/version")
    client.close()

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing internal API secret."}


def test_protected_route_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)

    client = TestClient(app)
    response = client.get(
        "/trading-api/version",
        headers={"X-Trading-API-Internal-Secret": "wrong-secret"},
    )
    client.close()

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing internal API secret."}


def test_protected_route_accepts_correct_secret(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)

    client = TestClient(app)
    response = client.get(
        "/trading-api/version",
        headers={"X-Trading-API-Internal-Secret": "test-api-secret"},
    )
    client.close()

    assert response.status_code == 200
    assert "running_hash" in response.json()


def test_unset_server_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("TRADING_API_SECRET", raising=False)
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)

    client = TestClient(app)
    response = client.get("/trading-api/version")
    client.close()

    assert response.status_code == 503
    assert response.json() == {"detail": "Trading API authentication is not configured."}


def test_source_export_routes_are_removed(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    headers = {"X-Trading-API-Internal-Secret": "test-api-secret"}

    client = TestClient(app)
    parts = client.get("/export/code-parts", headers=headers)
    audit = client.get("/export/code-audit", headers=headers)
    client.close()

    assert parts.status_code == 404
    assert audit.status_code == 404


def test_legacy_browser_secret_header_is_rejected(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)

    client = TestClient(app)
    response = client.get(
        "/trading-api/version",
        headers={"X-Trading-API-Secret": "test-api-secret"},
    )
    client.close()

    assert response.status_code == 401


def test_clerk_session_can_access_protected_route(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.setenv("CLERK_SECRET_KEY", "clerk-test-secret")

    import core.clerk_auth as clerk_auth

    monkeypatch.setattr(
        clerk_auth,
        "clerk_user_id_from_headers",
        lambda headers, secret_key: "user_operator",
    )

    client = TestClient(app)
    response = client.get(
        "/trading-api/version",
        headers={"cookie": "__session=verified-session"},
    )
    client.close()

    assert response.status_code == 200
    assert "running_hash" in response.json()


def test_invalid_clerk_session_is_rejected(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.setenv("CLERK_SECRET_KEY", "clerk-test-secret")

    import core.clerk_auth as clerk_auth

    monkeypatch.setattr(
        clerk_auth,
        "clerk_user_id_from_headers",
        lambda headers, secret_key: None,
    )

    client = TestClient(app)
    response = client.get(
        "/trading-api/version",
        headers={"cookie": "__session=invalid-session"},
    )
    client.close()

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required."}