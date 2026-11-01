# Personal Banking Assistant · Aurora

A local, synthetic banking application: authenticated account enquiries, AI-assisted transaction navigation, approved policy retrieval, and explicitly confirmed dispute requests.

**Development only.** All customer records are fictional. Groq processes demo chat; Voyage embeds approved sample policies and search queries. Do not enter real personal or financial data. This is not a production banking system.

## Design

- [System design and delivery plan](DESIGN.md)
- [Accepted development scope](SPEC.md)
- [Architecture diagram](docs/system-design.png) · [editable SVG](docs/system-design.svg)

The design is the target architecture. Implementation and runtime verification are in progress; the final verification report will distinguish implemented controls from production rollout requirements.

## Development configuration

Requires Docker Desktop with Linux containers. The planned local interface binds to `127.0.0.1:8765`.

Provider settings are configuration, not source-code constants:

```dotenv
LLM_MODEL=groq/openai/gpt-oss-120b
LLM_FALLBACK_MODEL=groq/qwen/qwen3.8-27b
LLM_MAX_TOKENS=1024
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2
EMBEDDING_MODEL=voyage/voyage-3.5
EMBEDDING_DIM=1024
```

`LLM_MAX_TOKENS` must be at least 512. Empty completions are errors, not successful answers. The vector dimension is inserted into schema DDL from validated configuration. Changing the embedding model or dimension for an existing database requires an explicit reindex migration; startup rejects mismatches.

Store credentials outside the checkout. `.env.example` contains names and placeholders only. Never commit API keys, environment files, database dumps, or raw customer traces. Rotate any credential shared in chat or other persistent logs.

## Delivery sequence

1. Design baseline and development constraints.
2. Secure synthetic API, MCP reads, provider adapters, and durable dispute execution.
3. React customer workspace and Docker startup.
4. Isolated integration tests, browser verification, dependency audit, and operating instructions.

Statements, address changes, cheque-book requests, and KYC intake are later-phase features. Real-bank identity, per-service database roles, private model deployment, external immutable audit, and bank-specific governance are production rollout work.
