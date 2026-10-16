# Implementation checklist
- [x] Scaffold directories and dependency manifests.
- [x] Record database model plan and API contract before business logic.
- [x] Implement schema, tenant isolation and ingestion validation.
- [x] Implement Polars metrics and versioned deterministic health policy.
- [x] Persist evidence and incident lifecycle with idempotent refresh.
- [x] Add optional grounded AI with deterministic fallback.
- [x] Build responsive dashboard and integration detail UI.
- [x] Generate repeatable synthetic scenarios and local run path.
- [x] Verify thresholds, auth, isolation, ingestion, incidents and AI failure.
- [x] Document credentials, Git/Vercel/Supabase deployment and limits.

Verification boundary: local SQLite/API tests, frontend tests/build, browser checks, and disposable PostgreSQL migration/concurrency checks passed. Live OpenAI and hosted Supabase/Vercel deployment remain unverified. See [the latest verification record](VERIFICATION.md) for commands and counts.
