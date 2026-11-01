import hashlib
import hmac
import os
import secrets
import time
import jwt
from fastapi import HTTPException, Request
from .config import settings
from .db import db


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_for(token):
    return hmac.new(
        settings().session_secret.get_secret_value().encode(),
        token.encode(),
        hashlib.sha256,
    ).hexdigest()


def password_hash(password, salt=None):
    salt = salt or os.urandom(16).hex()
    result = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
    ).hex()
    return salt + ":" + result


def password_ok(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(":")[0]), stored)


def principal(request: Request):
    token = request.cookies.get("bank_session", "")
    with db() as conn:
        session = conn.execute(
            "SELECT s.*, c.name, c.email FROM sessions s JOIN customers c ON c.id=s.customer_id WHERE s.token_hash=%s AND s.expires_at>now()",
            (token_hash(token),),
        ).fetchone()
    if not session:
        raise HTTPException(401, "Please sign in again.")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not hmac.compare_digest(token_hash(csrf), session["csrf_hash"]):
            raise HTTPException(403, "Invalid request verification token.")
    return session


def internal_token(customer_id, audience, scope):
    key = (
        settings().bank_write_secret
        if scope == "bank:write"
        else settings().internal_secret
    )
    if len(key.get_secret_value()) < 32:
        raise ValueError("This service has no write credential")
    return jwt.encode(
        {
            "sub": customer_id,
            "aud": audience,
            "scope": scope,
            "iss": "aurora-synthetic",
            "iat": int(time.time()),
            "exp": int(time.time()) + 120,
        },
        key.get_secret_value(),
        algorithm="HS256",
    )


def verify_internal(token, audience, scope):
    try:
        key = (
            settings().bank_write_secret
            if scope == "bank:write"
            else settings().internal_secret
        )
        if len(key.get_secret_value()) < 32:
            raise ValueError("No verification credential")
        claims = jwt.decode(
            token,
            key.get_secret_value(),
            algorithms=["HS256"],
            audience=audience,
            issuer="aurora-synthetic",
            options={"require": ["exp", "sub", "aud", "scope", "iss"]},
        )
        if claims["scope"] != scope:
            raise ValueError("wrong scope")
        return claims["sub"]
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(403, "Service authorization failed.")


def rate_limit(bucket, maximum=30, seconds=60):
    # Database-backed counter works across API processes; keys contain no raw IP/email.
    with db() as conn:
        row = conn.execute(
            """INSERT INTO rate_limits(bucket,count,expires_at) VALUES (%s,1,now()+(%s * interval '1 second'))
          ON CONFLICT(bucket) DO UPDATE SET count=CASE WHEN rate_limits.expires_at<now() THEN 1 ELSE rate_limits.count+1 END,
          expires_at=CASE WHEN rate_limits.expires_at<now() THEN excluded.expires_at ELSE rate_limits.expires_at END RETURNING count""",
            (bucket, seconds),
        ).fetchone()
    if row["count"] > maximum:
        raise HTTPException(
            429,
            "Please pause briefly before trying again.",
            headers={"Retry-After": str(seconds)},
        )
