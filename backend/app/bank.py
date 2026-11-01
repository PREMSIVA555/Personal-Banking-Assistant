from datetime import datetime
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from psycopg.errors import UniqueViolation
from .db import db, digest, new_id
from .security import verify_internal

app = FastAPI(title="Synthetic bank internal API", docs_url=None, redoc_url=None)


@app.get("/health")
def health():
    with db() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


def actor(auth, scope="bank:read"):
    return verify_internal(auth.removeprefix("Bearer "), "mock-bank", scope)


@app.get("/accounts")
def accounts(authorization: str = Header("")):
    uid = actor(authorization)
    with db() as conn:
        return conn.execute(
            "SELECT id,label,last_four,balance_minor,currency FROM accounts WHERE customer_id=%s ORDER BY id",
            (uid,),
        ).fetchall()


@app.get("/transactions")
def transactions(
    authorization: str = Header(""),
    merchant: str = Query("", max_length=120),
    account_id: str | None = None,
    transaction_id: str | None = None,
    limit: int = Query(12, ge=1, le=50),
):
    uid = actor(authorization)
    with db() as conn:
        return conn.execute(
            """SELECT t.*,a.label AS account_label,a.last_four FROM transactions t JOIN accounts a ON a.id=t.account_id
          WHERE a.customer_id=%s AND (%s::text IS NULL OR a.id=%s) AND (%s::text IS NULL OR t.id=%s)
          AND (%s='' OR strpos(lower(t.merchant),lower(%s))>0) ORDER BY t.posted_at DESC LIMIT %s""",
            (
                uid,
                account_id,
                account_id,
                transaction_id,
                transaction_id,
                merchant,
                merchant,
                limit,
            ),
        ).fetchall()


class ExpectedTransaction(BaseModel):
    merchant: str
    amount_minor: int = Field(gt=0)
    currency: str
    posted_at: datetime
    last_four: str


class Submission(BaseModel):
    transaction_id: str = Field(max_length=80)
    reason: str = Field(min_length=10, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=100)
    expected: ExpectedTransaction


@app.post("/disputes")
def submit(body: Submission, authorization: str = Header("")):
    uid = actor(authorization, "bank:write")
    request_hash = digest(
        {"customer": uid, **body.model_dump(mode="json", exclude={"idempotency_key"})}
    )
    with db() as conn:
        # Serialize by logical execution key; unique transaction constraint is a second guard.
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (body.idempotency_key,),
        )
        existing = conn.execute(
            "SELECT * FROM bank_disputes WHERE idempotency_key=%s",
            (body.idempotency_key,),
        ).fetchone()
        if existing:
            if (
                existing["customer_id"] != uid
                or existing["request_hash"] != request_hash
            ):
                raise HTTPException(409, "Idempotency key conflict.")
            return {"reference": existing["id"], "status": existing["status"]}
        tx = conn.execute(
            "SELECT t.*,a.last_four FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.id=%s AND a.customer_id=%s AND t.status='posted' AND t.amount_minor<0 AND t.posted_at>now()-interval '60 days' FOR UPDATE OF t",
            (body.transaction_id, uid),
        ).fetchone()
        if not tx:
            raise HTTPException(422, "Transaction is not eligible for a dispute.")
        current = {
            "merchant": tx["merchant"],
            "amount_minor": abs(tx["amount_minor"]),
            "currency": tx["currency"],
            "posted_at": tx["posted_at"],
            "last_four": tx["last_four"],
        }
        if body.expected.model_dump() != current:
            raise HTTPException(
                409,
                "Transaction details changed after confirmation. Prepare a new review.",
            )
        previous = conn.execute(
            "SELECT id FROM bank_disputes WHERE customer_id=%s AND transaction_id=%s",
            (uid, body.transaction_id),
        ).fetchone()
        if previous:
            raise HTTPException(409, "This transaction already has a dispute.")
        ref = "DSP-" + new_id("")[1:11].upper()
        try:
            conn.execute(
                "INSERT INTO bank_disputes(id,customer_id,transaction_id,reason,idempotency_key,request_hash) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    ref,
                    uid,
                    body.transaction_id,
                    body.reason,
                    body.idempotency_key,
                    request_hash,
                ),
            )
        except UniqueViolation:
            raise HTTPException(409, "This transaction already has a dispute.")
        return {"reference": ref, "status": "received"}


@app.get("/disputes/by-key/{key}")
def lookup(key: str, authorization: str = Header("")):
    uid = actor(authorization, "bank:write")
    with db() as conn:
        row = conn.execute(
            "SELECT id,status FROM bank_disputes WHERE idempotency_key=%s AND customer_id=%s",
            (key, uid),
        ).fetchone()
        if not row:
            raise HTTPException(404, "No submission with this key.")
        return {"reference": row["id"], "status": row["status"]}
