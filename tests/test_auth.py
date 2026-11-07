import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent import AnalyticsAgent
from app.auth import AuthError, RateLimiter, SupabaseAdminVerifier
from app.config import Settings
from app.db import AnalyticsDb
from app.main import create_app
from app.seed import seed_database
from app.sql_guard import SqlGuardError, validate_select
from tests.test_api import FakeClient


def _supabase(users: dict[str, tuple[str, str | None]]):
    """Mock Supabase: token -> (user id, role or None for no profile row)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token not in users:
            return httpx.Response(401, json={"msg": "bad token"})
        uid, role = users[token]
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": uid})
        if request.url.path == "/rest/v1/profiles":
            assert request.url.params["id"] == f"eq.{uid}"
            return httpx.Response(200, json=[{"role": role}] if role else [])
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseAdminVerifier("https://x.supabase.co", "anon", client=client), calls


@pytest.fixture()
def agent(tmp_path):
    path = tmp_path / "lms.db"
    seed_database(f"sqlite:///{path}", students=5)
    db = AnalyticsDb(f"sqlite:///{path}", blocked_columns=frozenset({"email"}), max_rows=50)
    return AnalyticsAgent(client=FakeClient("SELECT 1"), db=db, model="m")


def _body():
    return {"messages": [{"role": "user", "content": "hi"}]}


def test_admin_token_is_accepted(agent):
    verifier, _ = _supabase({"good": ("u1", "admin")})
    http = TestClient(create_app(agent, verifier))
    r = http.post("/api/chat", json=_body(), headers={"Authorization": "Bearer good"})
    assert r.status_code == 200 and r.json() == {"reply": "done"}


def test_missing_token_is_401(agent):
    verifier, _ = _supabase({})
    http = TestClient(create_app(agent, verifier))
    assert http.post("/api/chat", json=_body()).status_code == 401
    assert http.post("/api/chat", json=_body(), headers={"Authorization": "Basic abc"}).status_code == 401


def test_invalid_token_is_401(agent):
    verifier, _ = _supabase({"good": ("u1", "admin")})
    http = TestClient(create_app(agent, verifier))
    assert http.post("/api/chat", json=_body(), headers={"Authorization": "Bearer nope"}).status_code == 401


def test_learner_is_403_and_agent_is_not_called(agent):
    verifier, _ = _supabase({"learn": ("u2", "learner")})
    client = agent._client
    http = TestClient(create_app(agent, verifier))
    r = http.post("/api/chat", json=_body(), headers={"Authorization": "Bearer learn"})
    assert r.status_code == 403
    assert client.calls == []


def test_user_without_profile_is_403(agent):
    verifier, _ = _supabase({"ghost": ("u3", None)})
    http = TestClient(create_app(agent, verifier))
    assert http.post("/api/chat", json=_body(), headers={"Authorization": "Bearer ghost"}).status_code == 403


def test_supabase_down_is_503(agent):
    def boom(request):
        raise httpx.ConnectError("down")

    verifier = SupabaseAdminVerifier("https://x.supabase.co", "anon", client=httpx.Client(transport=httpx.MockTransport(boom)))
    http = TestClient(create_app(agent, verifier))
    assert http.post("/api/chat", json=_body(), headers={"Authorization": "Bearer t"}).status_code == 503


def test_verified_token_is_cached(agent):
    verifier, calls = _supabase({"good": ("u1", "admin")})
    verifier.verify("good")
    first = calls["n"]
    verifier.verify("good")
    assert calls["n"] == first


def test_verifier_raises_autherror_with_status():
    verifier, _ = _supabase({"learn": ("u2", "learner")})
    with pytest.raises(AuthError) as err:
        verifier.verify("learn")
    assert err.value.status == 403


def test_rate_limit_returns_429(agent):
    verifier, _ = _supabase({"good": ("u1", "admin")})
    http = TestClient(create_app(agent, verifier, requests_per_minute=2))
    h = {"Authorization": "Bearer good"}
    assert http.post("/api/chat", json=_body(), headers=h).status_code == 200
    assert http.post("/api/chat", json=_body(), headers=h).status_code == 200
    assert http.post("/api/chat", json=_body(), headers=h).status_code == 429


def test_rate_limiter_is_per_user():
    lim = RateLimiter(1, 60)
    assert lim.allow("a") and not lim.allow("a") and lim.allow("b")


def test_cors_allows_only_listed_origin(agent):
    http = TestClient(create_app(agent, None, ["https://app.example"]))
    ok = http.options("/api/chat", headers={"Origin": "https://app.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})
    assert ok.headers.get("access-control-allow-origin") == "https://app.example"
    bad = http.options("/api/chat", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_settings_require_supabase_when_auth_on(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(Exception):
        Settings(_env_file=None)
    assert Settings(_env_file=None, require_auth=False).require_auth is False
    assert Settings(_env_file=None, supabase_url="https://x", supabase_anon_key="a").require_auth is True


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT * FROM information_schema.tables",
        "SELECT current_setting('role')",
        "SELECT set_config('role','postgres',false)",
        "SELECT * FROM pg_catalog.pg_roles",
        "SELECT lo_import('/etc/passwd')",
    ],
)
def test_guard_blocks_postgres_internals(sql):
    with pytest.raises(SqlGuardError):
        validate_select(sql, frozenset())


def test_guard_blocks_new_default_columns():
    with pytest.raises(SqlGuardError):
        validate_select("SELECT user_id FROM attempts", frozenset({"user_id"}))
    assert validate_select("SELECT learner_ref, score_pct FROM attempts", frozenset({"user_id"}))
