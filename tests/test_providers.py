import asyncio
import json
import httpx
import pytest
from pydantic import SecretStr
from app import providers
from app.config import settings


def mock_client(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_primary_timeout_reaches_fallback(monkeypatch):
    seen = []
    monkeypatch.setattr(settings(), "groq_api_key", SecretStr("synthetic-test-key"))

    def handler(request):
        model = json.loads(request.content)["model"]
        seen.append(model)
        if "gpt-oss" in model:
            raise httpx.ReadTimeout("simulated outage", request=request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"intent":"balance"}'}}]}
        )

    mock_client(monkeypatch, handler)
    plan, model = asyncio.run(providers.plan_message("What is my balance?", [], {}))
    assert plan.intent == "balance"
    assert model == settings().llm_fallback_model
    assert len(seen) == 2


def test_empty_completion_falls_back(monkeypatch):
    monkeypatch.setattr(settings(), "groq_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(settings(), "llm_max_retries", 0)

    def handler(request):
        model = json.loads(request.content)["model"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": ""
                            if "gpt-oss" in model
                            else '{"intent":"transactions"}'
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    mock_client(monkeypatch, handler)
    plan, model = asyncio.run(providers.plan_message("Recent transactions", [], {}))
    assert plan.intent == "transactions" and model == settings().llm_fallback_model


def test_invalid_embedding_dimension_is_rejected(monkeypatch):
    monkeypatch.setattr(settings(), "voyage_api_key", SecretStr("synthetic-test-key"))
    mock_client(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]}
        ),
    )
    with pytest.raises(providers.ProviderUnavailable):
        asyncio.run(providers.embed(["synthetic policy"], "query"))


def test_embedding_request_uses_configured_dimension(monkeypatch):
    monkeypatch.setattr(settings(), "voyage_api_key", SecretStr("synthetic-test-key"))

    def handler(request):
        body = json.loads(request.content)
        assert body["output_dimension"] == settings().embedding_dim
        assert body["model"] == "voyage-3.5" and body["input_type"] == "query"
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.1] * settings().embedding_dim}],
                "usage": {"total_tokens": 3},
            },
        )

    mock_client(monkeypatch, handler)
    assert (
        len(asyncio.run(providers.embed(["synthetic policy"], "query"))[0])
        == settings().embedding_dim
    )


def test_irrelevant_policy_query_abstains(monkeypatch):
    # No network call; verify absence of lexical evidence produces abstention.
    async def unavailable(*args):
        raise providers.ProviderUnavailable("test")

    monkeypatch.setattr(providers, "embed", unavailable)
    rows, mode = asyncio.run(
        providers.retrieve_policy("astronomy telescope orbital mechanics")
    )
    assert rows == [] and mode == "text"
