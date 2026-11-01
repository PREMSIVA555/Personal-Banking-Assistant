import asyncio
from datetime import datetime, timezone
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Annotated
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from psycopg.types.json import Jsonb
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from .config import settings
from .db import db, new_id, digest, audit
from .security import (
    principal,
    password_ok,
    token_hash,
    csrf_for,
    rate_limit,
    verify_internal,
)
from .providers import ProviderUnavailable
from .workflow import graph, bank_tool

logging.basicConfig(level=logging.INFO, format="%(message)s")
for logger in ("httpx", "httpcore", "mcp", "mcp.client.streamable_http"):
    logging.getLogger(logger).setLevel(logging.ERROR)
log = logging.getLogger("bank")
app = FastAPI(
    title="Aurora synthetic banking",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)
REQUESTS = Counter(
    "bank_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
LATENCY = Histogram("bank_http_seconds", "HTTP latency", ["route"])
Principal = Annotated[dict, Depends(principal)]


@app.middleware("http")
async def boundary(request: Request, call_next):
    trace_id = secrets.token_hex(16)
    request.state.trace_id = trace_id
    start = time.monotonic()
    length = request.headers.get("content-length", "0")
    if not length.isdigit() or int(length) > 16000:
        return JSONResponse({"detail": "Request too large."}, status_code=413)
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse(
                {"detail": "Cross-origin request rejected."}, status_code=403
            )
        if "application/json" not in request.headers.get("content-type", ""):
            return JSONResponse({"detail": "JSON request required."}, status_code=415)
    try:
        response = await call_next(request)
    except Exception as error:
        log.error(
            json.dumps(
                {
                    "event": "unhandled_error",
                    "type": type(error).__name__,
                    "trace_id": trace_id,
                }
            )
        )
        response = JSONResponse(
            {
                "detail": "The service could not complete this request. Please try again.",
                "trace_id": trace_id,
            },
            status_code=500,
        )
    route = request.scope.get("route")
    label = getattr(route, "path", "static")
    REQUESTS.labels(request.method, label, str(response.status_code)).inc()
    LATENCY.labels(label).observe(time.monotonic() - start)
    response.headers.update(
        {
            "X-Request-ID": trace_id,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        }
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    log.info(
        json.dumps(
            {
                "event": "http",
                "method": request.method,
                "route": label,
                "status": response.status_code,
                "ms": round((time.monotonic() - start) * 1000),
                "trace_id": trace_id,
            }
        )
    )
    return response


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@app.get("/api/health")
def health():
    with db() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "mode": "synthetic"}


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    rate_limit("login:" + token_hash(ip), 20, 60)
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM customers WHERE email=%s", (body.email.lower(),)
        ).fetchone()
        if not row or not password_ok(body.password, row["password_hash"]):
            raise HTTPException(401, "Email or password was not recognized.")
        token = secrets.token_urlsafe(40)
        csrf = csrf_for(token)
        old = request.cookies.get("bank_session")
        if old:
            conn.execute("DELETE FROM sessions WHERE token_hash=%s", (token_hash(old),))
        conn.execute(
            "INSERT INTO sessions VALUES (%s,%s,%s,now()+interval '8 hours')",
            (token_hash(token), row["id"], token_hash(csrf)),
        )
        audit(
            conn,
            row["id"],
            "session.created",
            "session",
            trace_id=request.state.trace_id,
        )
    # HTTP loopback only in development. Production must use TLS and Secure cookies.
    response.set_cookie(
        "bank_session",
        token,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=28800,
        path="/",
    )
    return {
        "customer": {"id": row["id"], "name": row["name"], "email": row["email"]},
        "csrf_token": csrf,
    }


@app.get("/api/me")
def me(request: Request, p: Principal):
    # Stable per session, so opening another tab does not invalidate existing tabs.
    csrf = csrf_for(request.cookies["bank_session"])
    return {
        "customer": {"id": p["customer_id"], "name": p["name"], "email": p["email"]},
        "csrf_token": csrf,
    }


@app.post("/api/logout")
def logout(response: Response, p: Principal):
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=%s", (p["token_hash"],))
    response.delete_cookie("bank_session", path="/")
    return {"ok": True}


@app.get("/api/accounts")
async def accounts(p: Principal):
    try:
        return (await bank_tool(p["customer_id"], "list_my_accounts"))["items"]
    except Exception:
        raise HTTPException(503, "Account service is unavailable. Please try again.")


@app.get("/api/transactions")
async def transactions(p: Principal, merchant: str = "", account_id: str | None = None):
    if len(merchant) > 120:
        raise HTTPException(422, "Search is too long.")
    try:
        return (
            await bank_tool(
                p["customer_id"],
                "list_transactions",
                {"merchant": merchant, "account_id": account_id},
            )
        )["items"]
    except Exception:
        raise HTTPException(
            503, "Transaction service is unavailable. Please try again."
        )


@app.get("/api/policies")
def policies(p: Principal):
    with db() as conn:
        return conn.execute(
            "SELECT id,title,content,version,effective_from FROM memories WHERE approved AND effective_from<=CURRENT_DATE AND (effective_to IS NULL OR effective_to>CURRENT_DATE) ORDER BY id"
        ).fetchall()


@app.get("/api/conversations")
def conversations(p: Principal):
    with db() as conn:
        return conn.execute(
            "SELECT id,title,revision,updated_at FROM conversations WHERE customer_id=%s ORDER BY updated_at DESC LIMIT 30",
            (p["customer_id"],),
        ).fetchall()


@app.post("/api/conversations")
def create_conversation(p: Principal):
    cid = new_id("chat")
    with db() as conn:
        conn.execute(
            "INSERT INTO conversations(id,customer_id) VALUES (%s,%s)",
            (cid, p["customer_id"]),
        )
    return {"id": cid, "revision": 0, "title": "New conversation", "messages": []}


def owned_conversation(conn, cid, uid, lock=False):
    row = conn.execute(
        "SELECT * FROM conversations WHERE id=%s AND customer_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (cid, uid),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found.")
    return row


@app.get("/api/conversations/{cid}")
def conversation(cid: str, p: Principal):
    with db() as conn:
        row = owned_conversation(conn, cid, p["customer_id"])
        messages = conn.execute(
            "SELECT role,content,data,created_at FROM (SELECT * FROM messages WHERE conversation_id=%s ORDER BY id DESC LIMIT 100) recent ORDER BY id",
            (cid,),
        ).fetchall()
    return {
        "id": cid,
        "title": row["title"],
        "revision": row["revision"],
        "messages": messages,
        "busy": bool(
            row["busy_until"] and row["busy_until"] > datetime.now(timezone.utc)
        ),
    }


class ChatMessage(Input):
    message: str = Field(min_length=1, max_length=2000)
    client_id: str = Field(min_length=8, max_length=80)
    expected_revision: int = Field(ge=0)


@app.post("/api/conversations/{cid}/messages")
async def send_message(cid: str, body: ChatMessage, p: Principal, request: Request):
    uid = p["customer_id"]
    rate_limit("chat:" + uid, 20, 60)
    run_token = new_id("run")
    fingerprint = digest({"message": body.message})
    with db() as conn:
        row = owned_conversation(conn, cid, uid, True)
        prior = conn.execute(
            "SELECT * FROM requests WHERE conversation_id=%s AND client_id=%s",
            (cid, body.client_id),
        ).fetchone()
        if prior:
            if prior["request_hash"] != fingerprint:
                raise HTTPException(409, "Request ID already used for another message.")
            if prior["status"] == "complete":
                return prior["response"]
            if row["busy_until"] and row["busy_until"] > datetime.now(timezone.utc):
                raise HTTPException(409, "This message is still processing.")
        if row["revision"] != body.expected_revision:
            raise HTTPException(
                409, "Conversation changed. Refresh before sending again."
            )
        if row["busy_until"] and row["busy_until"] > datetime.now(timezone.utc):
            raise HTTPException(409, "Please wait for the current response.")
        history = conn.execute(
            "SELECT role,content FROM (SELECT * FROM messages WHERE conversation_id=%s ORDER BY id DESC LIMIT 6) recent ORDER BY id",
            (cid,),
        ).fetchall()
        conn.execute(
            "UPDATE conversations SET busy_until=now()+interval '150 seconds',run_token=%s WHERE id=%s",
            (run_token, cid),
        )
        conn.execute(
            "INSERT INTO requests(conversation_id,client_id,request_hash,status) VALUES (%s,%s,%s,'running') ON CONFLICT(conversation_id,client_id) DO UPDATE SET status='running'",
            (cid, body.client_id, fingerprint),
        )
    memory = row["state"]
    try:
        async with asyncio.timeout(135):
            result = await graph.ainvoke(
                {
                    "uid": uid,
                    "message": body.message,
                    "history": history,
                    "memory": memory,
                },
                {"recursion_limit": 4},
            )
        response = result["response"]
        memory = result["memory"]
    except (ProviderUnavailable, TimeoutError):
        response = {
            "answer": "The AI service is unavailable right now. Your accounts, transactions, policy library, and request tracking are still available from the navigation. Please try chat again later.",
            "data": {"kind": "unavailable"},
            "steps": [],
            "model": None,
        }
    except Exception as error:
        log.warning(
            json.dumps(
                {
                    "event": "workflow_failed",
                    "type": type(error).__name__,
                    "trace_id": request.state.trace_id,
                }
            )
        )
        response = {
            "answer": "I could not retrieve a verified result. No banking action was submitted. Please try again or use the account views.",
            "data": {"kind": "unavailable"},
            "steps": [],
            "model": None,
        }
    with db() as conn:
        current = owned_conversation(conn, cid, uid, True)
        if current["run_token"] != run_token:
            raise HTTPException(409, "This run expired. Reload the conversation.")
        new_revision = current["revision"] + 1
        response.update(
            {
                "revision": new_revision,
                "conversation_id": cid,
                "trace_id": request.state.trace_id,
            }
        )
        conn.execute(
            "INSERT INTO messages(conversation_id,role,content) VALUES (%s,'user',%s)",
            (cid, body.message),
        )
        conn.execute(
            "INSERT INTO messages(conversation_id,role,content,data) VALUES (%s,'assistant',%s,%s)",
            (cid, response["answer"], Jsonb(response)),
        )
        conn.execute(
            "UPDATE conversations SET revision=%s,state=%s,busy_until=NULL,run_token=NULL,updated_at=now(),title=CASE WHEN revision=0 THEN %s ELSE title END WHERE id=%s",
            (new_revision, Jsonb(memory), body.message[:65], cid),
        )
        conn.execute(
            "UPDATE requests SET status='complete',response=%s WHERE conversation_id=%s AND client_id=%s",
            (Jsonb(response), cid, body.client_id),
        )
        audit(
            conn,
            uid,
            "chat.completed",
            cid,
            {
                "model": response.get("model"),
                "kind": response.get("data", {}).get("kind"),
            },
            request.state.trace_id,
        )
    return response


class Draft(Input):
    conversation_id: str = Field(max_length=80)
    transaction_id: str = Field(max_length=80)
    reason: str = Field(min_length=10, max_length=1000)


def public_action(row):
    return {
        k: row[k]
        for k in (
            "id",
            "kind",
            "payload",
            "version",
            "status",
            "expires_at",
            "created_at",
            "updated_at",
            "bank_ref",
            "last_error",
        )
    }


@app.post("/api/actions")
def prepare(body: Draft, p: Principal, request: Request):
    uid = p["customer_id"]
    rate_limit("draft:" + uid, 20, 60)
    with db() as conn:
        owned_conversation(conn, body.conversation_id, uid)
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (uid + body.transaction_id,),
        )
        tx = conn.execute(
            "SELECT t.*,a.last_four FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.id=%s AND a.customer_id=%s AND t.status='posted' AND t.amount_minor<0 AND t.posted_at>now()-interval '60 days'",
            (body.transaction_id, uid),
        ).fetchone()
        if not tx:
            raise HTTPException(404, "Eligible transaction not found.")
        prior = conn.execute(
            "SELECT * FROM actions WHERE customer_id=%s AND payload->>'transaction_id'=%s AND status NOT IN ('cancelled','expired','failed') ORDER BY created_at DESC LIMIT 1",
            (uid, body.transaction_id),
        ).fetchone()
        if prior:
            if prior["status"] == "awaiting_confirmation" and prior[
                "expires_at"
            ] <= datetime.now(timezone.utc):
                conn.execute(
                    "UPDATE actions SET status='expired',updated_at=now() WHERE id=%s",
                    (prior["id"],),
                )
            elif (
                prior["status"] == "awaiting_confirmation"
                and prior["payload"]["reason"] == body.reason
            ):
                return public_action(prior)
            else:
                raise HTTPException(
                    409,
                    "This transaction already has an active request. Review or cancel it in Requests.",
                )
        payload = {
            "transaction_id": tx["id"],
            "merchant": tx["merchant"],
            "amount_minor": abs(tx["amount_minor"]),
            "currency": tx["currency"],
            "last_four": tx["last_four"],
            "posted_at": tx["posted_at"].isoformat(),
            "reason": body.reason,
            "policy_version": "demo-1",
        }
        aid = new_id("act")
        row = conn.execute(
            "INSERT INTO actions(id,customer_id,conversation_id,kind,payload,payload_hash) VALUES (%s,%s,%s,'dispute',%s,%s) RETURNING *",
            (aid, uid, body.conversation_id, Jsonb(payload), digest(payload)),
        ).fetchone()
        audit(
            conn,
            uid,
            "action.prepared",
            aid,
            {"version": 1, "payload_hash": row["payload_hash"]},
            request.state.trace_id,
        )
        return public_action(row)


class Confirm(Input):
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=80)


@app.post("/api/actions/{aid}/confirm", status_code=202)
def confirm(aid: str, body: Confirm, p: Principal, request: Request):
    uid = p["customer_id"]
    with db() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (uid + body.idempotency_key,),
        )
        row = conn.execute(
            "SELECT * FROM actions WHERE id=%s AND customer_id=%s FOR UPDATE",
            (aid, uid),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Request not found.")
        if (
            body.version != row["version"]
            or digest(row["payload"]) != row["payload_hash"]
        ):
            raise HTTPException(409, "Review details changed. Start a new proposal.")
        if row["confirmation_key"] == body.idempotency_key and row["status"] not in (
            "awaiting_confirmation",
            "expired",
            "cancelled",
        ):
            return public_action(row)
        if row["status"] != "awaiting_confirmation" or row[
            "expires_at"
        ] <= datetime.now(timezone.utc):
            raise HTTPException(
                409, "This proposal cannot be confirmed. Review its current status."
            )
        existing = conn.execute(
            "SELECT id FROM actions WHERE customer_id=%s AND confirmation_key=%s",
            (uid, body.idempotency_key),
        ).fetchone()
        if existing:
            raise HTTPException(409, "Confirmation key already used.")
        conn.execute(
            "INSERT INTO approvals(action_id,customer_id,version,payload_hash) VALUES (%s,%s,%s,%s)",
            (aid, uid, row["version"], row["payload_hash"]),
        )
        row = conn.execute(
            "UPDATE actions SET status='queued',confirmation_key=%s,updated_at=now() WHERE id=%s RETURNING *",
            (body.idempotency_key, aid),
        ).fetchone()
        conn.execute("INSERT INTO outbox(action_id) VALUES (%s)", (aid,))
        audit(
            conn,
            uid,
            "action.confirmed",
            aid,
            {"version": row["version"], "payload_hash": row["payload_hash"]},
            request.state.trace_id,
        )
        return public_action(row)


@app.post("/api/actions/{aid}/cancel")
def cancel(aid: str, p: Principal, request: Request):
    with db() as conn:
        row = conn.execute(
            "UPDATE actions SET status='cancelled',updated_at=now() WHERE id=%s AND customer_id=%s AND status='awaiting_confirmation' RETURNING *",
            (aid, p["customer_id"]),
        ).fetchone()
        if not row:
            raise HTTPException(409, "This proposal cannot be cancelled.")
        audit(
            conn,
            p["customer_id"],
            "action.cancelled",
            aid,
            trace_id=request.state.trace_id,
        )
        return public_action(row)


@app.get("/api/actions")
def actions(p: Principal):
    with db() as conn:
        conn.execute(
            "UPDATE actions SET status='expired',updated_at=now() WHERE customer_id=%s AND status='awaiting_confirmation' AND expires_at<=now()",
            (p["customer_id"],),
        )
        return [
            public_action(row)
            for row in conn.execute(
                "SELECT * FROM actions WHERE customer_id=%s ORDER BY created_at DESC LIMIT 50",
                (p["customer_id"],),
            ).fetchall()
        ]


@app.get("/api/actions/{aid}")
def action(aid: str, p: Principal):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM actions WHERE id=%s AND customer_id=%s",
            (aid, p["customer_id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Request not found.")
        return public_action(row)


class Handoff(Input):
    summary: str = Field(min_length=10, max_length=1000)
    consent: bool


@app.post("/api/support")
def support(body: Handoff, p: Principal, request: Request):
    if not body.consent:
        raise HTTPException(422, "Consent is required to share the summary.")
    rate_limit("support:" + p["customer_id"], 10, 60)
    sid = new_id("case")
    with db() as conn:
        conn.execute(
            "INSERT INTO support_cases(id,customer_id,summary) VALUES (%s,%s,%s)",
            (sid, p["customer_id"], body.summary),
        )
        audit(
            conn,
            p["customer_id"],
            "support.consented",
            sid,
            trace_id=request.state.trace_id,
        )
    return {
        "id": sid,
        "status": "open",
        "message": "Demo case created. No external staff notification was sent.",
    }


@app.get("/api/support")
def support_cases(p: Principal):
    with db() as conn:
        return conn.execute(
            "SELECT id,summary,status,created_at FROM support_cases WHERE customer_id=%s ORDER BY created_at DESC LIMIT 30",
            (p["customer_id"],),
        ).fetchall()


@app.get("/api/system")
def system(p: Principal):
    s = settings()
    with db() as conn:
        providers = conn.execute(
            "SELECT DISTINCT ON(provider) provider,model,outcome,created_at FROM usage_events ORDER BY provider,created_at DESC"
        ).fetchall()
        docs = conn.execute(
            "SELECT count(*) AS total,count(embedding) AS indexed FROM memories WHERE approved"
        ).fetchone()
        events = conn.execute(
            "SELECT event,resource,created_at FROM audit_events WHERE actor=%s ORDER BY id DESC LIMIT 12",
            (p["customer_id"],),
        ).fetchall()
    return {
        "mode": "synthetic",
        "chat_model": s.llm_model,
        "fallback_model": s.llm_fallback_model,
        "embedding_model": s.embedding_model,
        "embedding_dim": s.embedding_dim,
        "max_tokens": s.llm_max_tokens,
        "providers": providers,
        "policies": docs,
        "audit": events,
    }


@app.get("/internal/metrics")
def metrics(request: Request):
    verify_internal(
        request.headers.get("authorization", "").removeprefix("Bearer "),
        "metrics",
        "metrics:read",
    )
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


STATIC = Path(__file__).parents[1] / "static"
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/{path:path}")
def index(path: str):
    if path.startswith(("api/", "internal/")):
        raise HTTPException(404, "Not found.")
    return FileResponse(STATIC / "index.html")
