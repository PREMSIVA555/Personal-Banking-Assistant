import asyncio
import json
import logging
import re
import time
import aio_pika
import httpx
from .config import settings
from .db import db, audit, digest
from .security import internal_token
from .providers import index_policies, ProviderUnavailable

log = logging.getLogger("bank.worker")
logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.ERROR)
QUEUE = "bank.disputes"


def finish(aid, status, bank_ref=None, error=None):
    with db() as conn:
        row = conn.execute(
            "UPDATE actions SET status=%s,bank_ref=COALESCE(%s,bank_ref),last_error=%s,lease_until=NULL,updated_at=now() WHERE id=%s RETURNING customer_id",
            (status, bank_ref, error, aid),
        ).fetchone()
        audit(
            conn,
            row["customer_id"],
            "action." + status,
            aid,
            {"bank_ref": bank_ref, "error_code": error},
        )


def retry(aid, attempt, uncertain):
    if attempt >= 5:
        finish(aid, "manual_review", error="submission_requires_review")
        return
    with db() as conn:
        status = "reconciling" if uncertain else "retry_scheduled"
        row = conn.execute(
            "UPDATE actions SET status=%s,lease_until=NULL,updated_at=now(),last_error=%s WHERE id=%s RETURNING customer_id",
            (status, "bank_outcome_unknown" if uncertain else "bank_unavailable", aid),
        ).fetchone()
        conn.execute(
            "INSERT INTO outbox(action_id,available_at) VALUES (%s,now()+(%s * interval '1 second'))",
            (aid, min(2**attempt, 30)),
        )
        audit(conn, row["customer_id"], "action." + status, aid, {"attempt": attempt})


async def process_action(aid):
    with db() as conn:
        row = conn.execute(
            "SELECT *,lease_until>now() AS leased FROM actions WHERE id=%s FOR UPDATE",
            (aid,),
        ).fetchone()
        if (
            not row
            or row["status"]
            in (
                "submitted",
                "failed",
                "manual_review",
                "cancelled",
                "expired",
                "awaiting_confirmation",
            )
            or row["leased"]
        ):
            return
        approval = conn.execute(
            "SELECT * FROM approvals WHERE action_id=%s", (aid,)
        ).fetchone()
        valid = (
            approval
            and approval["customer_id"] == row["customer_id"]
            and approval["version"] == row["version"]
            and approval["payload_hash"]
            == row["payload_hash"]
            == digest(row["payload"])
            and approval["approved_at"] <= row["expires_at"]
        )
        if not valid:
            conn.execute(
                "UPDATE actions SET status='failed',last_error='invalid_approval',updated_at=now() WHERE id=%s",
                (aid,),
            )
            audit(
                conn,
                row["customer_id"],
                "action.failed",
                aid,
                {"error_code": "invalid_approval"},
            )
            return
        conn.execute(
            "UPDATE actions SET status='processing',attempts=attempts+1,lease_until=now()+interval '90 seconds',updated_at=now() WHERE id=%s",
            (aid,),
        )
    attempt = row["attempts"] + 1
    key = aid
    headers = {
        "Authorization": "Bearer "
        + internal_token(row["customer_id"], "mock-bank", "bank:write")
    }
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            # Always reconcile first: safe after a worker crash or ambiguous previous response.
            lookup = await client.get(
                settings().bank_url + "/disputes/by-key/" + key, headers=headers
            )
            if lookup.status_code == 200:
                finish(aid, "submitted", lookup.json()["reference"])
                return
            if lookup.status_code != 404:
                retry(aid, attempt, True)
                return
            expected = {
                k: row["payload"][k]
                for k in (
                    "merchant",
                    "amount_minor",
                    "currency",
                    "posted_at",
                    "last_four",
                )
            }
            response = await client.post(
                settings().bank_url + "/disputes",
                headers=headers,
                json={
                    "transaction_id": row["payload"]["transaction_id"],
                    "reason": row["payload"]["reason"],
                    "idempotency_key": key,
                    "expected": expected,
                },
            )
            if response.status_code == 200:
                finish(aid, "submitted", response.json()["reference"])
            elif response.status_code in (400, 401, 403, 404, 409, 422):
                finish(aid, "failed", error="bank_rejected_request")
            else:
                retry(aid, attempt, True)
        except (httpx.HTTPError, ValueError, KeyError):
            retry(aid, attempt, True)


async def relay(exchange):
    while True:
        try:
            with db() as conn:
                # Recover expired worker leases; duplicate redelivery is harmless.
                stale = conn.execute(
                    "UPDATE actions SET status='reconciling',lease_until=NULL WHERE status='processing' AND lease_until<now() RETURNING id"
                ).fetchall()
                for row in stale:
                    conn.execute(
                        "INSERT INTO outbox(action_id) VALUES (%s)", (row["id"],)
                    )
            # Commit lease recovery before awaiting RabbitMQ. No database locks span network I/O.
            with db() as conn:
                events = conn.execute(
                    "SELECT id,action_id FROM outbox WHERE published_at IS NULL AND available_at<=now() ORDER BY id LIMIT 20"
                ).fetchall()
            for event in events:
                await exchange.publish(
                    aio_pika.Message(
                        json.dumps({"action_id": event["action_id"]}).encode(),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        message_id=str(event["id"]),
                    ),
                    routing_key=QUEUE,
                    mandatory=True,
                )
                with db() as conn:
                    conn.execute(
                        "UPDATE outbox SET published_at=now() WHERE id=%s",
                        (event["id"],),
                    )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.warning(
                json.dumps({"event": "relay_retry", "type": type(error).__name__})
            )
        await asyncio.sleep(1)


async def main():
    try:
        count = await index_policies()
        log.info(json.dumps({"event": "policies_indexed", "count": count}))
    except ProviderUnavailable:
        log.warning(
            json.dumps(
                {"event": "policy_embeddings_unavailable", "fallback": "text_search"}
            )
        )
    connection = await aio_pika.connect_robust(settings().rabbit_url.get_secret_value())
    async with connection:
        channel = await connection.channel(publisher_confirms=True)
        await channel.set_qos(prefetch_count=1)
        await channel.declare_queue("bank.dead", durable=True)
        queue = await channel.declare_queue(
            QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": "bank.dead",
            },
        )
        relay_task = asyncio.create_task(relay(channel.default_exchange))
        try:
            async with queue.iterator() as iterator:
                async for message in iterator:
                    await handle_message(message)
        finally:
            relay_task.cancel()


async def handle_message(message):
    try:
        aid = json.loads(message.body)["action_id"]
        if not isinstance(aid, str) or not re.fullmatch(r"act_[0-9a-f]{32}", aid):
            raise ValueError("Invalid action identifier")
    except (ValueError, KeyError, TypeError):
        await message.reject(requeue=False)
        log.warning(json.dumps({"event": "invalid_queue_payload"}))
        return
    try:
        await process_action(aid)
    except asyncio.CancelledError:
        await message.nack(requeue=True)
        raise
    except Exception as error:
        log.error(json.dumps({"event": "worker_retry", "type": type(error).__name__}))
        # A transient failure before claim must not lose the only queued delivery.
        await asyncio.sleep(2)
        await message.nack(requeue=True)
    else:
        await message.ack()


if __name__ == "__main__":
    asyncio.run(main())
