import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from app.main import app
from app.db import db, digest
from app.config import Settings, settings
from app.providers import parse_plan
from app.security import internal_token, verify_internal
from app.worker import process_action


@pytest.fixture
def clients():
    with db() as conn:
        conn.execute("DELETE FROM rate_limits")
    result = []
    for email in ("ava@demo.bank", "noah@demo.bank"):
        client = TestClient(app)
        response = client.post(
            "/api/login", json={"email": email, "password": "DemoBank!2026"}
        )
        assert response.status_code == 200
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        result.append(client)
    yield result
    for client in result:
        client.close()


def fixture_transaction(uid="customer-ava", amount=-123400):
    tid = "test-" + uuid.uuid4().hex
    account = "acc-ava-main" if uid == "customer-ava" else "acc-noah-main"
    with db() as conn:
        conn.execute(
            "INSERT INTO transactions(id,account_id,merchant,amount_minor,currency,posted_at,category) VALUES (%s,%s,'Synthetic test merchant',%s,'INR',now(),'Testing')",
            (tid, account, amount),
        )
    return tid


def draft(client, tid=None):
    cid = client.post("/api/conversations", json={}).json()["id"]
    response = client.post(
        "/api/actions",
        json={
            "conversation_id": cid,
            "transaction_id": tid or fixture_transaction(),
            "reason": "Synthetic test: I did not authorize this transaction.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json(), cid


def confirm(client, action, key=None, version=1):
    return client.post(
        "/api/actions/" + action["id"] + "/confirm",
        json={"version": version, "idempotency_key": key or str(uuid.uuid4())},
    )


def expected(action):
    return {
        k: action["payload"][k]
        for k in ("merchant", "amount_minor", "currency", "posted_at", "last_four")
    }


def test_auth_csrf_and_session_tabs(clients):
    ava, _ = clients
    assert TestClient(app).get("/api/accounts").status_code == 401
    token = ava.headers["X-CSRF-Token"]
    assert ava.get("/api/me").json()["csrf_token"] == token
    assert (
        ava.post(
            "/api/conversations", json={}, headers={"X-CSRF-Token": "bad"}
        ).status_code
        == 403
    )
    assert (
        ava.post(
            "/api/conversations",
            json={},
            headers={"Origin": "https://attacker.invalid"},
        ).status_code
        == 403
    )
    assert ava.post("/api/conversations", json={}).status_code == 200


def test_resource_and_mcp_isolation(clients):
    ava, noah = clients
    assert {a["id"] for a in ava.get("/api/accounts").json()} == {
        "acc-ava-main",
        "acc-ava-save",
    }
    assert noah.get("/api/transactions?account_id=acc-ava-main").json() == []
    a, cid = draft(ava)
    assert noah.get("/api/conversations/" + cid).status_code == 404
    assert noah.get("/api/actions/" + a["id"]).status_code == 404
    assert confirm(noah, a).status_code == 404
    other = noah.post("/api/conversations", json={}).json()["id"]
    assert (
        noah.post(
            "/api/actions",
            json={
                "conversation_id": other,
                "transaction_id": "txn-example",
                "reason": "Synthetic test reason for foreign transaction.",
            },
        ).status_code
        == 404
    )


def test_confirm_is_atomic_and_idempotent(clients):
    ava, _ = clients
    a, _ = draft(ava)
    key = str(uuid.uuid4())
    results = []
    # Independent HTTP requests exercise database locks and the unique confirmation key.
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _: confirm(ava, a, key).status_code, range(2))
        )
    assert results == [202, 202]
    with db() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM approvals WHERE action_id=%s", (a["id"],)
            ).fetchone()["n"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM outbox WHERE action_id=%s", (a["id"],)
            ).fetchone()["n"]
            == 1
        )
    asyncio.run(process_action(a["id"]))
    asyncio.run(process_action(a["id"]))
    with db() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM bank_disputes WHERE idempotency_key=%s",
                (a["id"],),
            ).fetchone()["n"]
            == 1
        )
    assert ava.get("/api/actions/" + a["id"]).json()["status"] == "submitted"


def test_expiry_version_and_payload_binding(clients):
    ava, _ = clients
    a, _ = draft(ava)
    assert confirm(ava, a, version=99).status_code == 409
    with db() as conn:
        conn.execute(
            "UPDATE actions SET expires_at=now()-interval '1 second' WHERE id=%s",
            (a["id"],),
        )
    assert confirm(ava, a).status_code == 409
    b, _ = draft(ava)
    with db() as conn:
        conn.execute(
            "UPDATE actions SET payload=jsonb_set(payload,'{reason}',%s) WHERE id=%s",
            (Jsonb("Changed by a simulated tampering attempt"), b["id"]),
        )
    assert confirm(ava, b).status_code == 409
    assert ava.post("/api/actions/" + b["id"] + "/cancel", json={}).status_code == 200
    assert confirm(ava, b).status_code == 409


def test_worker_rejects_missing_approval(clients):
    ava, _ = clients
    a, _ = draft(ava)
    with db() as conn:
        conn.execute("UPDATE actions SET status='queued' WHERE id=%s", (a["id"],))
    asyncio.run(process_action(a["id"]))
    assert ava.get("/api/actions/" + a["id"]).json()["status"] == "failed"
    with db() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM bank_disputes WHERE idempotency_key=%s",
                (a["id"],),
            ).fetchone()["n"]
            == 0
        )


def test_reconcile_accepted_write_after_worker_crash(clients):
    ava, _ = clients
    a, _ = draft(ava)
    assert confirm(ava, a).status_code == 202
    with httpx.Client(timeout=10) as bank:
        r = bank.post(
            settings().bank_url + "/disputes",
            headers={
                "Authorization": "Bearer "
                + internal_token("customer-ava", "mock-bank", "bank:write")
            },
            json={
                "transaction_id": a["payload"]["transaction_id"],
                "reason": a["payload"]["reason"],
                "idempotency_key": a["id"],
                "expected": expected(a),
            },
        )
        assert r.status_code == 200, r.text
    # Simulate bank success followed by loss of application acknowledgement.
    with db() as conn:
        conn.execute(
            "UPDATE actions SET status='reconciling',lease_until=NULL WHERE id=%s",
            (a["id"],),
        )
    asyncio.run(process_action(a["id"]))
    row = ava.get("/api/actions/" + a["id"]).json()
    assert row["status"] == "submitted" and row["bank_ref"] == r.json()["reference"]


def test_customer_entitlement_rechecked_before_execution(clients):
    ava, _ = clients
    a, _ = draft(ava)
    confirm(ava, a)
    with db() as conn:
        conn.execute(
            "UPDATE transactions SET account_id=%s WHERE id=%s",
            ("acc-noah-main", a["payload"]["transaction_id"]),
        )
    asyncio.run(process_action(a["id"]))
    assert ava.get("/api/actions/" + a["id"]).json()["status"] == "failed"


def test_support_requires_consent(clients):
    ava, noah = clients
    assert (
        ava.post(
            "/api/support",
            json={"summary": "Synthetic support issue for testing", "consent": False},
        ).status_code
        == 422
    )
    r = ava.post(
        "/api/support",
        json={"summary": "Synthetic support issue for testing", "consent": True},
    )
    assert r.status_code == 200
    assert r.json()["id"] not in [c["id"] for c in noah.get("/api/support").json()]


def test_provider_schema_and_configuration():
    with pytest.raises(ValueError):
        parse_plan({"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]})
    with pytest.raises(ValueError):
        parse_plan(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"intent":"transfer","customer_id":"other"}'
                        }
                    }
                ]
            }
        )
    assert (
        parse_plan(
            {"choices": [{"message": {"content": '{"intent":"balance"}'}}]}
        ).intent
        == "balance"
    )
    with pytest.raises(ValueError):
        Settings(llm_max_tokens=128)
    with pytest.raises(ValueError):
        Settings(embedding_dim=1536)
    with pytest.raises(ValueError):
        Settings(app_mode="production")
    with db() as conn:
        dimension = conn.execute(
            "SELECT format_type(atttypid,atttypmod) AS typ FROM pg_attribute WHERE attrelid='memories'::regclass AND attname='embedding'"
        ).fetchone()["typ"]
    assert dimension == f"vector({settings().embedding_dim})"


def test_service_tokens_are_scoped():
    token = internal_token("customer-ava", "bank-tools", "tools:read")
    assert verify_internal(token, "bank-tools", "tools:read") == "customer-ava"
    with pytest.raises(Exception):
        verify_internal(token, "mock-bank", "bank:write")


def test_cancelled_actions_never_execute(clients):
    ava, _ = clients
    a, _ = draft(ava)
    assert ava.post("/api/actions/" + a["id"] + "/cancel", json={}).status_code == 200
    asyncio.run(process_action(a["id"]))
    assert ava.get("/api/actions/" + a["id"]).json()["status"] == "cancelled"


def test_financial_reads_are_exact_and_bank_writes_require_scope(clients):
    ava, _ = clients
    a, _ = draft(ava)
    values = {r["id"]: r["balance_minor"] for r in ava.get("/api/accounts").json()}
    assert values["acc-ava-main"] == 12845075
    with httpx.Client(timeout=10) as bank:
        r = bank.post(
            settings().bank_url + "/disputes",
            headers={
                "Authorization": "Bearer "
                + internal_token("customer-ava", "mock-bank", "bank:read")
            },
            json={
                "transaction_id": "txn-example",
                "reason": "Synthetic denial test",
                "idempotency_key": str(uuid.uuid4()),
                "expected": expected(a),
            },
        )
    assert r.status_code == 403


def test_changed_transaction_requires_new_confirmation(clients):
    ava, _ = clients
    a, _ = draft(ava)
    confirm(ava, a)
    with db() as conn:
        conn.execute(
            "UPDATE transactions SET amount_minor=amount_minor-100 WHERE id=%s",
            (a["payload"]["transaction_id"],),
        )
    asyncio.run(process_action(a["id"]))
    assert ava.get("/api/actions/" + a["id"]).json()["status"] == "failed"
    with db() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM bank_disputes WHERE idempotency_key=%s",
                (a["id"],),
            ).fetchone()["n"]
            == 0
        )
