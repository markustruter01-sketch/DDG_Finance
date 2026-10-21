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

    client = TestClient(app)
    response = client.get("/trading-api/version")
    client.close()

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing trading API secret."}


def test_protected_route_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")

    client = TestClient(app)
    response = client.get(
        "/trading-api/version",
        headers={"X-Trading-API-Secret": "wrong-secret"},
    )
    client.close()

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing trading API secret."}


def test_protected_route_accepts_correct_secret(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")

    client = TestClient(app)
    response = client.get(
        "/trading-api/version",
        headers={"X-Trading-API-Secret": "test-api-secret"},
    )
    client.close()

    assert response.status_code == 200
    assert "running_hash" in response.json()


def test_unset_server_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("TRADING_API_SECRET", raising=False)

    client = TestClient(app)
    response = client.get("/trading-api/version")
    client.close()

    assert response.status_code == 503
    assert response.json() == {"detail": "Trading API authentication is not configured."}


def test_source_export_routes_are_removed(monkeypatch):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    headers = {"X-Trading-API-Secret": "test-api-secret"}

    client = TestClient(app)
    parts = client.get("/export/code-parts", headers=headers)
    audit = client.get("/export/code-audit", headers=headers)
    client.close()

    assert parts.status_code == 404
    assert audit.status_code == 404

def _kill_client(monkeypatch, key="ctrl-key"):
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    if key is None:
        monkeypatch.delenv("FOREX_AI_KILL_KEY", raising=False)
    else:
        monkeypatch.setenv("FOREX_AI_KILL_KEY", key)
    import core.forex_ai_kill as k
    monkeypatch.setattr(k, "ai_kill_state", lambda: {"on": False, "reason": "", "at": None})
    monkeypatch.setattr(k, "set_ai_kill", lambda on, reason="": None)
    return TestClient(app)


def test_control_key_opens_only_the_forex_ai_kill_routes(monkeypatch):
    from main import API_PREFIX
    p = API_PREFIX.rstrip("/")
    client = _kill_client(monkeypatch)
    h = {"X-Forex-AI-Kill-Key": "ctrl-key"}
    assert client.get(f"{p}/forex-ai/kill", headers=h).status_code == 200
    assert client.post(f"{p}/forex-ai/kill?reason=owner", headers=h).status_code == 200
    assert client.post(f"{p}/forex-ai/kill/clear?reason=owner", headers=h).status_code == 200
    # the same key opens nothing else
    assert client.get("/trading-api/version", headers=h).status_code == 401
    assert client.post(f"{p}/kill", headers=h).status_code == 401
    assert client.get(f"{p}/bots/pause-state", headers=h).status_code == 401
    assert client.get(f"{p}/forex-ai/kill", headers={"X-Forex-AI-Kill-Key": "wrong"}).status_code == 401
    client.close()


def test_control_key_unset_means_closed(monkeypatch):
    client = _kill_client(monkeypatch, key=None)
    from main import API_PREFIX
    assert client.get(f"{API_PREFIX.rstrip('/')}/forex-ai/kill",
                      headers={"X-Forex-AI-Kill-Key": "anything"}).status_code == 401
    client.close()
