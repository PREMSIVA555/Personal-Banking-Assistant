import json
import httpx
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from .config import settings
from .security import verify_internal, internal_token
from .db import db, audit

mcp = FastMCP(
    "Aurora bank read tools",
    host="0.0.0.0",
    port=8001,
    stateless_http=True,
    json_response=True,
    log_level="WARNING",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["tools:8001", "localhost:8001", "127.0.0.1:8001"],
        allowed_origins=[],
    ),
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok"})


def customer(ctx):
    request = ctx.request_context.request
    return verify_internal(
        request.headers.get("authorization", "").removeprefix("Bearer "),
        "bank-tools",
        "tools:read",
    )


async def read_bank(ctx, path, params=None):
    uid = customer(ctx)
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            settings().bank_url + path,
            params=params,
            headers={
                "Authorization": "Bearer "
                + internal_token(uid, "mock-bank", "bank:read")
            },
        )
        response.raise_for_status()
    with db() as conn:
        audit(conn, uid, "tool.read", path, {"outcome": "ok"})
    return {"source": "synthetic-bank", "items": response.json()}


@mcp.tool()
async def list_my_accounts(ctx: Context) -> dict:
    """Return accounts and exact balances for the authenticated customer only."""
    return await read_bank(ctx, "/accounts")


@mcp.tool()
async def list_transactions(
    ctx: Context,
    merchant: str = "",
    account_id: str | None = None,
    transaction_id: str | None = None,
) -> dict:
    """Read only owned transactions. Optional exact transaction/account IDs and merchant phrase."""
    params = {
        k: v
        for k, v in {
            "merchant": merchant,
            "account_id": account_id,
            "transaction_id": transaction_id,
        }.items()
        if v is not None
    }
    return await read_bank(ctx, "/transactions", params)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
