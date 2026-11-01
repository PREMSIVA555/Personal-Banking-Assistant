from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
import uuid
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from psycopg.types.json import Jsonb
from .config import settings


@lru_cache
def pool():
    return ConnectionPool(
        settings().database_url.get_secret_value(),
        min_size=1,
        max_size=12,
        kwargs={"row_factory": dict_row},
        open=True,
    )


@contextmanager
def db():
    with pool().connection() as conn:
        with conn.transaction():
            yield conn


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def audit(conn, actor, event, resource, detail=None, trace_id=None):
    # Never include credentials, raw messages, hidden reasoning, or bank payloads.
    conn.execute(
        "INSERT INTO audit_events(actor,event,resource,detail,trace_id) VALUES (%s,%s,%s,%s,%s)",
        (actor, event, resource, Jsonb(detail or {}), trace_id),
    )
