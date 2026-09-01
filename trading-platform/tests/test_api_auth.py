from __future__ import annotations

from fastapi.testclient import TestClient

import main
from main import app


def test_health_is_minimal_and_does_not_require_secret(monkeypatch):
    monkeypatch.delenv("TRADING_API_SECRET", raising=False)
    monkeypatch.delenv("TRADING_API_AUTH_MODE", raising=False)

    client = TestClient(app)
    response = client.get("/health")
    client.close()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "auth_mode": "enforced"}


def test_health_reports_bypass_mode_without_requiring_secret(monkeypatch):
    monkeypatch.delenv("TRADING_API_SECRET", raising=False)
    monkeypatch.setenv("TRADING_API_AUTH_MODE", "bypass")

    client = TestClient(app)
    response = client.get("/health")
    client.close()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "auth_mode": "bypass"}


def test_protected_route_rejects_missing_secret(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    monkeypatch.delenv("TRADING_API_AUTH_MODE", raising=False)

    client = TestClient(app)
    response = client.get("/trading-api/version")
    client.close()

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing internal API secret."}


def test_protected_route_bypasses_user_auth_only_when_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.setenv("TRADING_API_AUTH_MODE", "bypass")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)

    client = TestClient(app)
    response = client.get("/trading-api/version")
    client.close()

    assert response.status_code == 200
    assert "running_hash" in response.json()


def test_bypass_mode_logs_each_request_and_keeps_internal_secret_first(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.setenv("TRADING_API_AUTH_MODE", "bypass")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    warnings = []
    monkeypatch.setattr(
        main.logger,
        "warning",
        lambda *args, **kwargs: warnings.append(args),
    )

    client = TestClient(app)
    health_response = client.get("/health")
    internal_response = client.get(
        "/trading-api/version",
        headers={"X-Trading-API-Internal-Secret": "test-api-secret"},
    )
    client.close()

    assert health_response.status_code == 200
    assert internal_response.status_code == 200
    bypass_warnings = [
        args[0]
        for args in warnings
        if args and "Trading API authentication bypassed" in str(args[0])
    ]
    assert len(bypass_warnings) == 2


def test_invalid_auth_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.setenv("TRADING_API_AUTH_MODE", "unexpected")
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
    monkeypatch.setenv("TRADING_API_OPERATOR_ALLOWLIST", "user_operator")

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
    monkeypatch.setenv("TRADING_API_OPERATOR_ALLOWLIST", "user_operator")

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


def test_non_allowlisted_clerk_session_is_rejected(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.setenv("CLERK_SECRET_KEY", "clerk-test-secret")
    monkeypatch.setenv("TRADING_API_OPERATOR_ALLOWLIST", "user_operator")

    import core.clerk_auth as clerk_auth

    monkeypatch.setattr(
        clerk_auth,
        "clerk_user_id_from_headers",
        lambda headers, secret_key: "user_other",
    )

    client = TestClient(app)
    response = client.get(
        "/trading-api/version",
        headers={"cookie": "__session=verified-other"},
    )
    client.close()

    assert response.status_code == 403
    assert response.json() == {"detail": "Operator access is not authorized."}


def test_internal_scheduler_secret_is_not_subject_to_operator_allowlist(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    monkeypatch.delenv("TRADING_API_OPERATOR_ALLOWLIST", raising=False)
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")

    client = TestClient(app)
    response = client.get(
        "/trading-api/version",
        headers={"X-Trading-API-Internal-Secret": "test-api-secret"},
    )
    client.close()

    assert response.status_code == 200


def test_internal_scheduler_secret_is_checked_before_clerk_session(
    monkeypatch,
):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.setenv("CLERK_SECRET_KEY", "clerk-test-secret")
    monkeypatch.delenv("TRADING_API_OPERATOR_ALLOWLIST", raising=False)

    import core.clerk_auth as clerk_auth

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Clerk verification must not run for internal requests")

    monkeypatch.setattr(clerk_auth, "clerk_user_id_from_headers", fail_if_called)

    client = TestClient(app)
    response = client.get(
        "/trading-api/version",
        headers={"X-Trading-API-Internal-Secret": "test-api-secret"},
    )
    client.close()

    assert response.status_code == 200


def test_unset_allowlist_in_published_context_rejects_clerk_user(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.setenv("CLERK_SECRET_KEY", "clerk-test-secret")
    monkeypatch.delenv("TRADING_API_OPERATOR_ALLOWLIST", raising=False)
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")

    import core.clerk_auth as clerk_auth

    monkeypatch.setattr(
        clerk_auth,
        "clerk_user_id_from_headers",
        lambda headers, secret_key: "user_operator",
    )

    client = TestClient(app)
    response = client.get(
        "/trading-api/version",
        headers={"cookie": "__session=verified"},
    )
    client.close()

    assert response.status_code == 403
    assert response.json() == {"detail": "Operator access is not authorized."}