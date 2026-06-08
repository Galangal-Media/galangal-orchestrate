"""Security tests for hub auth: API gating, session tokens, websocket auth."""

import pytest

from galangal_hub import auth


@pytest.fixture(autouse=True)
def _reset_auth():
    auth.set_api_key(None)
    auth.set_dashboard_credentials(None, None)
    auth.set_session_secret("test-secret")
    yield
    auth.set_api_key(None)
    auth.set_dashboard_credentials(None, None)


# --- session tokens ---------------------------------------------------------


def test_session_token_roundtrip():
    assert auth.verify_session_token(auth.create_session_token()) is True


def test_forged_length_token_rejected():
    # The old impl accepted any 64-hex-char string.
    assert auth.verify_session_token("a" * 64) is False


def test_tampered_signature_rejected():
    tok = auth.create_session_token()
    assert auth.verify_session_token(tok[:-1] + ("0" if tok[-1] != "0" else "1")) is False


def test_expired_token_rejected(monkeypatch):
    tok = auth.create_session_token()
    future = auth.time.time() + auth.SESSION_TTL_SECONDS + 10  # capture before patching
    monkeypatch.setattr(auth.time, "time", lambda: future)
    assert auth.verify_session_token(tok) is False


# --- password hashing -------------------------------------------------------


def test_password_salted_and_verified():
    auth.set_dashboard_credentials("admin", "pw")
    assert auth.verify_dashboard_credentials("admin", "pw") is True
    assert auth.verify_dashboard_credentials("admin", "nope") is False
    assert auth.verify_dashboard_credentials("nobody", "pw") is False
    assert "$" in auth._password_hash  # salt$hash, not a bare sha256


def test_unconfigured_dashboard_rejects_login():
    # No creds set -> verify must fail closed (not "True when unconfigured").
    assert auth.verify_dashboard_credentials("x", "y") is False


# --- API auth wiring (integration) ------------------------------------------


def _client(tmp_path):
    from fastapi.testclient import TestClient

    from galangal_hub.server import create_app

    return TestClient(create_app(db_path=str(tmp_path / "hub.db")))


def test_api_open_when_no_auth_configured(tmp_path):
    with _client(tmp_path) as c:
        assert c.get("/api/agents").status_code == 200


def test_api_requires_key_when_configured(tmp_path):
    auth.set_api_key("secret-key")
    with _client(tmp_path) as c:
        assert c.get("/api/agents").status_code == 401
        ok = c.get("/api/agents", headers={"Authorization": "Bearer secret-key"})
        assert ok.status_code == 200
        assert c.get("/api/agents", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_api_accepts_valid_session_cookie(tmp_path):
    auth.set_dashboard_credentials("admin", "pw")  # enables session auth
    token = auth.create_session_token()
    with _client(tmp_path) as c:
        assert c.get("/api/agents").status_code == 401
        c.cookies.set(auth.SESSION_COOKIE, token)
        assert c.get("/api/agents").status_code == 200


# --- websocket auth ---------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_auth_rejects_without_key_and_no_query_fallback():
    auth.set_api_key("k")
    # No query-param fallback anymore.
    assert await auth.verify_websocket_auth({}, {"api_key": "k"}) is False
    assert await auth.verify_websocket_auth({"authorization": "Bearer k"}, {}) is True
    assert await auth.verify_websocket_auth({"x-api-key": "k"}, {}) is True
    assert await auth.verify_websocket_auth({"x-api-key": "nope"}, {}) is False
