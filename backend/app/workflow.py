import json
from typing import TypedDict
from fastapi.encoders import jsonable_encoder
from langgraph.graph import StateGraph, START, END
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from .config import settings
from .security import internal_token
from .providers import plan_message, retrieve_policy
from .db import db


async def bank_tool(uid, name, arguments=None):
    if name not in {"list_my_accounts", "list_transactions"}:
        raise ValueError("Tool not permitted")
    async with streamablehttp_client(
        settings().mcp_url,
        headers={
            "Authorization": "Bearer " + internal_token(uid, "bank-tools", "tools:read")
        },
    ) as (reader, writer, _):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments or {})
            if result.isError:
                raise RuntimeError("Bank read unavailable")
            if result.structuredContent:
                return result.structuredContent
            return json.loads(next(c.text for c in result.content if c.type == "text"))


class State(TypedDict, total=False):
    uid: str
    message: str
    history: list
    memory: dict
    plan: dict
    model: str
    response: dict


async def route(state):
    plan, model = await plan_message(
        state["message"], state["history"], state["memory"]
    )
    return {"plan": plan.model_dump(), "model": model}


async def execute(state):
    p = state["plan"]
    uid = state["uid"]
    intent = p["intent"]
    memory = dict(state["memory"])
    data = {}
    answer = ""
    steps = ["Understand request"]
    if intent == "balance":
        result = await bank_tool(uid, "list_my_accounts")
        items = result["items"]
        if p["account_id"]:
            items = [a for a in items if a["id"] == p["account_id"]]
        answer = (
            "Here are the current balances returned by your demo bank."
            if items
            else "I could not find that account among your accounts."
        )
        data = {"kind": "accounts", "items": items}
        steps += ["Authorize account access", "Read bank balances"]
    elif intent in ("transactions", "dispute"):
        args = {
            k: p[k] for k in ("merchant", "account_id", "transaction_id") if p.get(k)
        }
        items = (await bank_tool(uid, "list_transactions", args))["items"]
        data = {
            "kind": "transactions",
            "items": items,
            "dispute_mode": intent == "dispute",
        }
        answer = (
            (
                "Select the charge below, then tell us why you want to dispute it. You will review the details before confirming."
                if intent == "dispute"
                else "These are the matching transactions from your demo bank."
            )
            if items
            else "I could not find a matching transaction in your accounts. Try a merchant name or select one from Transactions."
        )
        if len(items) == 1:
            memory["selected_transaction_id"] = items[0]["id"]
        memory["recent_transaction_ids"] = [r["id"] for r in items]
        steps += ["Authorize transaction access", "Read bank transactions"]
    elif intent == "policy":
        policies, mode = await retrieve_policy(p["query"] or state["message"])
        data = {"kind": "policies", "items": policies, "retrieval": mode}
        answer = (
            "Here is the relevant approved demo policy. The source text is shown below."
            if policies
            else "I could not find an applicable approved policy. Please clarify your question or request support."
        )
        steps += ["Retrieve approved policy", "Attach versioned evidence"]
    elif intent == "status":
        with db() as conn:
            rows = conn.execute(
                "SELECT id,kind,status,payload,bank_ref,created_at FROM actions WHERE customer_id=%s ORDER BY created_at DESC LIMIT 10",
                (uid,),
            ).fetchall()
        data = {"kind": "actions", "items": rows}
        answer = (
            "Here are your latest requests." if rows else "You have no requests yet."
        )
        steps += ["Read owned request status"]
    elif intent == "handoff":
        answer = "You can create a demo support case. Review the summary and consent to sharing it using the support form."
        data = {"kind": "handoff"}
    elif intent == "unsupported":
        answer = "This demo supports balances, transaction enquiries, policies, and disputes. Statements, address changes, cheque books, KYC, and payments are not available in this release."
    else:
        answer = "I can help with balances, recent transactions, dispute policies, or a charge you do not recognize. What would you like to check?"
    return {
        "memory": memory,
        "response": jsonable_encoder(
            {"answer": answer, "data": data, "steps": steps, "model": state["model"]}
        ),
    }


builder = StateGraph(State)
builder.add_node("coordinator", route)
builder.add_node("domain", execute)
builder.add_edge(START, "coordinator")
builder.add_edge("coordinator", "domain")
builder.add_edge("domain", END)
# Conversation state is durably committed by the API with optimistic revisions.
# This bounded graph has no autonomous loop or write-capable tool.
graph = builder.compile()
