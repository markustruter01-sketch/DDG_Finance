from types import SimpleNamespace

import core.clerk_auth as clerk_auth


def test_clerk_user_id_requires_a_configured_secret(monkeypatch):
    called = False

    def fake_authenticate(*args, **kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(is_signed_in=True, payload={"sub": "user_1"})

    monkeypatch.setattr(clerk_auth, "authenticate_request", fake_authenticate)

    assert clerk_auth.clerk_user_id_from_headers({}, None) is None
    assert called is False


def test_clerk_user_id_reads_verified_session_subject(monkeypatch):
    captured = {}

    def fake_authenticate(headers, options):
        captured["headers"] = headers
        captured["secret_key"] = options.secret_key
        return SimpleNamespace(is_signed_in=True, payload={"sub": "user_operator"})

    monkeypatch.setattr(clerk_auth, "authenticate_request", fake_authenticate)

    user_id = clerk_auth.clerk_user_id_from_headers(
        {"cookie": "__session=verified", "authorization": ""},
        "clerk-secret",
    )

    assert user_id == "user_operator"
    assert captured == {
        "headers": {"cookie": "__session=verified", "Authorization": ""},
        "secret_key": "clerk-secret",
    }


def test_clerk_user_id_rejects_unsigned_or_missing_subject(monkeypatch):
    monkeypatch.setattr(
        clerk_auth,
        "authenticate_request",
        lambda headers, options: SimpleNamespace(is_signed_in=False, payload=None),
    )
    assert clerk_auth.clerk_user_id_from_headers(
        {"cookie": "__session=invalid"},
        "clerk-secret",
    ) is None

    monkeypatch.setattr(
        clerk_auth,
        "authenticate_request",
        lambda headers, options: SimpleNamespace(is_signed_in=True, payload={}),
    )
    assert clerk_auth.clerk_user_id_from_headers(
        {"cookie": "__session=missing-sub"},
        "clerk-secret",
    ) is None


def test_clerk_user_id_fails_closed_on_verification_error(monkeypatch):
    def fail_authenticate(*args, **kwargs):
        raise RuntimeError("jwks unavailable")

    monkeypatch.setattr(clerk_auth, "authenticate_request", fail_authenticate)

    assert clerk_auth.clerk_user_id_from_headers(
        {"cookie": "__session=unavailable"},
        "clerk-secret",
    ) is None