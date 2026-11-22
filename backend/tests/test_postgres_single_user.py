"""Integration tests for the serverless / Postgres / single user mode.

Needs a throw-away Postgres and a fake OpenAI endpoint, so it is skipped unless
the environment is prepared, e.g.:

    DATABASE_URL=postgresql://... OPENUI_SESSION_KEY=test OPENUI_SINGLE_USER=true \
    OPENUI_ENVIRONMENT=production OPENUI_SERVERLESS=1 OPENAI_API_KEY=sk-test \
    OPENAI_BASE_URL=http://localhost:9100/v1 pytest tests/test_postgres_single_user.py
"""
import os
import subprocess
import sys
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not (os.getenv("DATABASE_URL") and os.getenv("OPENUI_SINGLE_USER")),
    reason="needs DATABASE_URL + OPENUI_SINGLE_USER (see module docstring)",
)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from openui.server import app

    # https so the Secure session cookie (production mode) is sent back
    with TestClient(app, base_url="https://localhost") as c:
        yield c


def test_session_is_created_for_owner_and_persists(client):
    from openui.db.models import database

    r = client.get("/v1/session")
    assert r.status_code == 200
    assert r.json()["username"] == os.getenv("OPENUI_SINGLE_USER_NAME", "owner")
    assert database.is_closed(), "connection must be closed after each request"
    r2 = client.get("/v1/session")
    assert r2.json()["username"] == r.json()["username"]


def test_session_survives_new_instance(client):
    """A different function instance only has the signed cookie + the DB."""
    from fastapi.testclient import TestClient
    from openui.server import app
    from openui.db.models import User

    with TestClient(app, base_url="https://localhost") as other:
        other.cookies.update(client.cookies)
        assert other.get("/v1/session").status_code == 200
    assert User.select().count() == 1


def test_tables_exist(client):
    from openui.db.models import database

    names = {
        r[0]
        for r in database.execute_sql(
            "select table_name from information_schema.tables where table_schema='public'"
        )
    }
    assert {
        "users",
        "sessions",
        "components",
        "votes",
        "usage",
        "shares",
        "credentials",
        "schema_migration",
    } <= names


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs OPENAI_API_KEY (mock)")
def test_chat_stream_records_usage(client):
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "stream": True,
            "messages": [{"role": "user", "content": "a button"}],
        },
    )
    assert r.status_code == 200
    assert "hello" in r.text and "[DONE]" in r.text
    assert client.get("/v1/session").json()["token_count"] > 0


def test_disabled_providers(client):
    r = client.post(
        "/v1/chat/completions",
        json={"model": "ollama/llava", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 400
    models = client.get("/v1/models").json()["models"]
    assert models["ollama"] == []
    if not os.getenv("OPENAI_COMPATIBLE_API_KEY"):
        assert models["litellm"] == []


def test_share_roundtrip(client):
    sid = uuid.uuid4().hex[:12]
    body = {"prompt": "p", "name": "n", "emoji": "x", "html": "<b>hi</b>"}
    assert client.post(f"/v1/share/{sid}", json=body).status_code == 201
    got = client.get(f"/v1/share/{sid}")
    assert got.status_code == 200 and got.json() == body
    assert client.get("/v1/share/does-not-exist").status_code == 404
    assert client.post("/v1/share/bad%20id!", json=body).status_code == 400


def test_vote(client):
    body = {"prompt": "p", "name": "n", "emoji": "x", "html": "<b>hi</b>", "vote": True}
    assert client.post("/v1/vote", json=body).status_code == 201


def test_github_login_disabled(client):
    assert client.get("/v1/login").status_code == 404


def test_frontend_is_served(client):
    r = client.get("/ai/new")
    assert r.status_code == 200 and "<div id=\"root\"" in r.text


def test_missing_session_key_fails_clearly():
    env = {k: v for k, v in os.environ.items() if k != "OPENUI_SESSION_KEY"}
    p = subprocess.run(
        [sys.executable, "-c", "import openui.config"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    assert "OPENUI_SESSION_KEY is required" in p.stderr


compatible = pytest.mark.skipif(
    not os.getenv("OPENAI_COMPATIBLE_API_KEY"),
    reason="needs OPENAI_COMPATIBLE_API_KEY / OPENAI_COMPATIBLE_ENDPOINT (mock)",
)


@compatible
def test_compatible_provider_listed_and_default_selectable(client):
    models = client.get("/v1/models").json()["models"]
    ids = [m["id"] for m in models["litellm"]]
    assert "deepseek-flash" in ids and "deepseek-v4-pro" in ids
    if not os.getenv("OPENAI_API_KEY"):
        # no OpenAI key: the UI falls back to the first "litellm" model
        assert models["openai"] == []


@compatible
def test_compatible_provider_streams_with_thinking_off(client):
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "litellm/deepseek-flash",
            "stream": True,
            "messages": [{"role": "user", "content": "a card"}],
        },
    )
    assert r.status_code == 200
    assert "hello" in r.text and "[DONE]" in r.text
    assert "thinking=disabled" in r.text and "model=deepseek-flash" in r.text
    bad = client.post(
        "/v1/chat/completions",
        json={"model": "litellm/not-a-model", "messages": [{"role": "user", "content": "x"}]},
    )
    assert bad.status_code == 400
