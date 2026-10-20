# Optional grounded incident assistance

Health classification, rollups, snapshots and incident transitions use the deterministic engine. Refresh/cron never invokes OpenAI. The backend key is optional and never enters frontend configuration. Assistance requires an operator workspace identity, the constrained automatic hosted demo session, or the explicitly credential-free local SQLite demo. With DEMO_MODE disabled, PostgreSQL requires workspace authentication even when APP_ENV is demo. Hosted reviewers never supply a workspace or OpenAI key.

## One grounded public contract

`POST /api/integrations/{id}/brief`, `/investigate`, `/explain`, and compatibility `/api/v1/integrations/{id}/explanation` use the same evidence-constrained incident-assistance service. The compatibility explanation endpoints retain their response shape; UNKNOWN deterministic fallbacks retain exact snapshot reason text. Older free-prose cache records are regenerated on the next operator request. The historical narrative helper remains unit-tested for compatibility but is not called by API routes.

AI receives scoped aggregate telemetry, deterministic policy evidence, incident/recovery context, freshness and available comparisons. It selects and orders **existing fact and read-only check IDs** using Pydantic structured output. The backend validates every selection/category and renders factual text itself. Model-written factual prose, unknown facts, invented categories, extra status fields and malformed output are rejected. Insufficient/stale evidence is stated explicitly and advisory confidence is limited. The model has no tools or operational mutation capability. See [AI operations](AI_OPERATIONS.md) for the evidence catalog, UI and focused topics.

The response includes summary, likely issue category, suggested checks, advisory confidence and what changed. Source, generation time, evidence digest, prompt version, model, snapshot/incident references, fallback status and selected IDs support review. Read endpoints never call AI. HTTP health/incident decisions are unaffected by any report.

## Provider and failure behavior

The backend reads optional `OPENAI_API_KEY` and `OPENAI_MODEL` from exported process variables. It does not load environment files. Model default: `gpt-6-luna`; Luna requests use `reasoning.effort=none` for this bounded fact-selection task. Other model overrides must support Responses structured outputs. No new variable or migration is required for the review fixes.

Provider requests use `store=False`, an eight-second transport timeout, zero retries and a 1,000-token output budget. The transport timeout is not a strict whole-operation deadline. Clients close after each call. No raw request logs/messages or credentials are included. Tenant/integration context labels are supplied as data, never instructions; they cannot become generated actions.

A missing key returns deterministic evidence with `MISSING_API_KEY`. Timeouts, failures, incomplete/refused/invalid responses and ungrounded output return `AI_UNAVAILABLE`. Errors are sanitized. Operators can always inspect deterministic reasons and recovery evidence without AI.

Briefs persist in the existing enrichment table with compact source-evidence references and audit metadata, not full prompt text. Successful results are cached by snapshot, prompt version, requested model and freshness; configured-key fallbacks may retry on the next explicit request. Keyless readers can reuse a cached advisory without initiating a call. Changing the configured model invalidates its cache when a provider key is configured. Concurrent requests may duplicate an upstream call but recheck the cache under a tenant lock before persistence. These fixed-topic brief routes have no paid-call quota/rate limiter. The separate interactive assistant has bounded evidence and a best-effort per-worker tenant budget of ten questions per minute; see [AI operations](AI_OPERATIONS.md).

The existing source column has a 32-character limit. Long provider model identifiers use `openai:see-audit` as the source label; the full validated identifier is retained in audit metadata. The audit is not an append-only log of every regeneration. Investigation/recovery answers expose metadata but do not persist conversations.

## Offline verification

Run `.venv/bin/python -m pytest -q backend/tests`. Tests replace only time/provider boundaries: grounding, malicious output, missing credentials, timeout/failure, tenant/role boundaries, recovery context and immutable health decisions are verified. Both explanation aliases are tested for factual-prose rejection. No live OpenAI request is required or claimed.
