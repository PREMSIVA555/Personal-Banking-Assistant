# Product specification — Banking Assistant

> Design baseline: DESIGN.md, accepted through the user's follow-up authorizing Docker and supplying development settings.

## Problem

Implement the approved synthetic conversational banking assistant with authorized enquiries and confirmed service requests.

## Users

Synthetic banking customers and developers evaluating secure workflows locally.

## Functional requirements

- FR-1: Customers can access only their accounts, transactions, conversations, and requests.
- FR-2: Configurable Groq chat routes requests through bounded workflows; Voyage supplies policy embeddings with a configured schema dimension.
- FR-3: Customers prepare, explicitly confirm, and track disputes with durable execution, reconciliation, and idempotency.
- FR-4: Approved policy citations, persistent history, and consented support handoffs work through an accessible React UI.

## Non-functional requirements

- NFR-1: Enforce ownership, CSRF, confirmation binding, concurrency, audit, and duplicate protection in code; keep credentials outside source and logs.
- NFR-2: Reproducible Docker startup and tests. LLM_MAX_TOKENS >=512, default 1024; timeout 60 seconds; retries 2. Validate embedding dimensions at migration and response boundaries.

## Constraints

- Local Docker, synthetic data only. User authorizes Groq and Voyage for development. Primary groq/openai/gpt-oss-120b; fallback groq/qwen/qwen3.8-27b; voyage/voyage-3.5, EMBEDDING_DIM=1024. Real-bank deployment requires separate controls and approvals.

## Non-goals

- No real financial transactions, production certification, cloud publishing, or phase-two KYC/address/cheque-book workflows.

## Acceptance criteria

- AC-1: Docker stack starts and read, policy, confirmed dispute, status, and handoff journeys work.
- AC-2: Tests reject cross-customer access, CSRF failures, changed/expired approvals, duplicate execution, and unsafe retries.
- AC-3: Empty model responses and invalid embedding dimensions cause explicit failure or fallback; source contains setup/test instructions without credentials.

## Risks

- Model errors require schema validation and deterministic authorization. Unknown bank writes require reconciliation. Recommend rotating chat-exposed keys and keep local runtime credentials outside deliverables.

## Open questions

- Production bank APIs, identity, residency, retention, staffing, and deployment remain out of scope for synthetic development.
