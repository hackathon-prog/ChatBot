import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent import AnalyticsAgent
from app.db import AnalyticsDb
from app.main import create_app
from app.seed import seed_database


def _reply(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


def _tool(sql):
    fn = SimpleNamespace(name="run_sql_query", arguments=json.dumps({"sql": sql}))
    return SimpleNamespace(id="tc_1", function=fn)


class FakeClient:
    """Scripted OpenAI-style client: first call asks for a query, second answers."""

    def __init__(self, sql):
        self.sql = sql
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return _reply(tool_calls=[_tool(self.sql)])
        return _reply(content="done")


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
    tool_msg = client.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "tc_1"
    assert "20" in tool_msg["content"]


def test_agent_returns_guard_error_to_model(db):
    client = FakeClient("DROP TABLE students")
    agent = AnalyticsAgent(client=client, db=db, model="m")
    agent.chat([{"role": "user", "content": "drop it"}])
    assert client.calls[1]["messages"][-1]["content"].startswith("Error:")


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
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        raise RuntimeError("Insufficient credits")


def test_chat_endpoint_hides_provider_errors(db):
    app = create_app(agent=AnalyticsAgent(client=BrokenClient(), db=db, model="m"))
    r = TestClient(app).post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 502
    assert "credits" in r.json()["detail"]
    assert "Insufficient credits" not in r.text


class FlakyClient:
    """First model fails, second works."""

    def __init__(self):
        self.models = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.models.append(kwargs["model"])
        if kwargs["model"] == "bad":
            raise RuntimeError("rate limited")
        return _reply(content="ok")


def test_agent_falls_back_to_next_model(db):
    client = FlakyClient()
    agent = AnalyticsAgent(client=client, db=db, model=["bad", "good"])
    assert agent.chat([{"role": "user", "content": "hi"}]) == "ok"
    assert client.models == ["bad", "good"]
