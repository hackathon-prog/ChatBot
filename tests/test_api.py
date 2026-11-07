from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent import AnalyticsAgent
from app.db import AnalyticsDb
from app.main import create_app
from app.seed import seed_database


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(sql):
    return SimpleNamespace(type="tool_use", id="tu_1", name="run_sql_query", input={"sql": sql})


class FakeClient:
    """Scripted Anthropic client: first call asks for a query, second answers."""

    def __init__(self, sql):
        self.sql = sql
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(stop_reason="tool_use", content=[_tool(self.sql)])
        return SimpleNamespace(stop_reason="end_turn", content=[_text("done")])


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "lms.db"
    seed_database(f"sqlite:///{path}", students=20)
    return AnalyticsDb(f"sqlite:///{path}", blocked_columns=frozenset({"email"}), max_rows=50)


def test_db_runs_select(db):
    result = db.run_select("SELECT COUNT(*) AS n FROM students")
    assert result["columns"] == ["n"]
    assert result["rows"][0][0] == 20


def test_db_is_read_only(db):
    with pytest.raises(Exception):
        db.run_select("DELETE FROM students")


def test_db_caps_rows(db):
    result = db.run_select("SELECT * FROM quiz_attempts")
    assert len(result["rows"]) <= 50


def test_schema_hides_blocked_columns(db):
    assert "email" not in db.describe_schema()


def test_agent_runs_tool_then_answers(db):
    client = FakeClient("SELECT COUNT(*) FROM students")
    agent = AnalyticsAgent(client=client, db=db, model="m")
    reply = agent.chat([{"role": "user", "content": "how many students?"}])
    assert reply == "done"
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert "20" in tool_result["content"]


def test_agent_returns_guard_error_to_model(db):
    client = FakeClient("DROP TABLE students")
    agent = AnalyticsAgent(client=client, db=db, model="m")
    agent.chat([{"role": "user", "content": "drop it"}])
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True


def test_chat_endpoint(db):
    app = create_app(agent=AnalyticsAgent(client=FakeClient("SELECT 1"), db=db, model="m"))
    http = TestClient(app)
    r = http.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert r.json() == {"reply": "done"}


def test_chat_endpoint_validates_input(db):
    app = create_app(agent=AnalyticsAgent(client=FakeClient("SELECT 1"), db=db, model="m"))
    http = TestClient(app)
    assert http.post("/api/chat", json={"messages": []}).status_code == 422
    assert http.post("/api/chat", json={"messages": [{"role": "system", "content": "x"}]}).status_code == 422


class BrokenClient:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        raise RuntimeError("Your credit balance is too low")


def test_chat_endpoint_hides_provider_errors(db):
    app = create_app(agent=AnalyticsAgent(client=BrokenClient(), db=db, model="m"))
    r = TestClient(app).post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 502
    assert "credits" in r.json()["detail"]
    assert "credit balance is too low" not in r.text
