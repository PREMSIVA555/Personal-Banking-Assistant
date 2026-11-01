import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from psycopg import OperationalError
from app import worker


def message(body):
    return SimpleNamespace(
        body=body, ack=AsyncMock(), nack=AsyncMock(), reject=AsyncMock()
    )


def test_database_failure_before_claim_is_redelivered(monkeypatch):
    task = message(json.dumps({"action_id": "act_" + "a" * 32}).encode())
    process = AsyncMock(
        side_effect=[OperationalError("synthetic database outage"), None]
    )
    monkeypatch.setattr(worker, "process_action", process)
    monkeypatch.setattr(worker.asyncio, "sleep", AsyncMock())
    asyncio.run(worker.handle_message(task))
    task.nack.assert_awaited_once_with(requeue=True)
    task.ack.assert_not_awaited()
    task.reject.assert_not_awaited()
    asyncio.run(worker.handle_message(task))
    task.ack.assert_awaited_once()


def test_poison_message_is_dead_lettered(monkeypatch):
    task = message(b'{"action_id":"not-an-action"}')
    process = AsyncMock()
    monkeypatch.setattr(worker, "process_action", process)
    asyncio.run(worker.handle_message(task))
    task.reject.assert_awaited_once_with(requeue=False)
    process.assert_not_awaited()
