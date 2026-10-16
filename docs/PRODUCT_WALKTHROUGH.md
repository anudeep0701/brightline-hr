# Brightline HR: operational product walkthrough

The overview starts with Brightline's problem: Ops should detect failing integrations from request telemetry before relying on a support ticket. Priority, evidence freshness and recent direction appear before supporting fleet counts. All numbers come from the existing API and deterministic pipeline.

## Prepare an isolated local demo

Stop `npm run dev` with Ctrl+C. From the repository root run:

```sh
.venv/bin/python scripts/run_demo.py --scenario all
```

In a second terminal:

```sh
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm --prefix frontend run dev
```

Open http://localhost:3000. This existing launcher creates a temporary SQLite database, generates seeded events, ingests them through the domain service, replays health windows, and starts the API. It never loads environment files or changes the configured customer database. Clear Workspace access if an in-memory token belongs to a different database. PostgreSQL workspaces still require a workspace bearer token.

The replay contains healthy traffic, sustained failures, low-volume evidence and a resolved incident. Earlier degraded states remain visible in transition history; prolonged degradation can correctly escalate to UNHEALTHY. The scenario controls explore the seeded evidence and explain what each scenario demonstrates. They do not silently regenerate events or overwrite databases. Regenerate immediately before a presentation: these are timestamped events, and freshness correctly expires.

OpenAI is disabled by default in this launcher. To use a manually exported backend key, append `--enable-ai`. Otherwise the same UI displays a clearly labeled deterministic fallback. No generated summary is presented as AI when a fallback was used.

## Four-minute evaluator journey

1. **0:00–0:40 — Overview.** Read the morning summary and highest-priority attention item. Show reason, error rate, latency, owner/workspace scope, last telemetry and incident age. No employee/customer impact count is inferred from request volume.
2. **0:40–1:40 — Authentication outage.** In Explore demo scenario choose Authentication outage, then Explore Slack Notifications. Read the deterministic decision and observed evidence. Generate an AI incident brief and ask “What should an operator investigate first?” Explain the advisory label and the fact that no operational actions are executed. If AI is unavailable, demonstrate monitoring continuing with the deterministic fallback.
3. **1:40–2:20 — Signal and evidence judgment.** Return to Overview. Choose Latency degradation and inspect DocuSign: successful HTTP requests can still be too slow. Inspect Twilio's low-volume UNKNOWN state; no errors does not establish health. Degradation history explains escalation through consecutive windows.
4. **2:20–3:05 — Recovery and outcomes.** Choose Recovery → ADP Payroll (Recovery). Show the healthy/degraded/unhealthy/healthy transitions, opening trigger, recovery start, required healthy windows and resolution. Return to the calculated demo impact: incidents detected, recovered incidents, mean confirmed duration and healthy share. These are synthetic outcomes, not proven customer ROI or customer-impact duration.
5. **3:05–4:00 — Customer onboarding.** Open Data sources. Show Upload historical logs → Validate → preview → explicit import confirmation → Evaluate current health. Show Set up Live API and its credential/test/verify/observe steps. Both paths feed the existing domain ingestion and health engine.

## Onboarding boundaries

- File pilot: registered integration IDs; CSV, JSON, NDJSON or JSONL; UTF-8; 2 MiB / 1,000 records. Unknown integration or tenant mismatch blocks import. Other invalid rows are reported, never silently imported. Backfill does not rewrite completed health decisions.
- Live API: an administrator issues an ingestion-only tenant credential; the customer exporter posts normalized events to `/api/ingest`. The UI never retrieves existing plaintext credentials. Workspace credentials and ingestion keys remain separate.
- Data arriving distinguishes receipt time from event time and evaluation time. Unknown provenance is displayed honestly for legacy records.
- Shadow mode remains observe → classify → advise → human acts. No remediation, threshold editing, cross-tenant assistance or incident resolution is delegated to AI.

## Verification for this refinement

- 30 frontend tests pass (12 new rendered-component/presentation tests), preserving the existing tests.
- 292 backend tests pass; no backend contracts or domain logic changed.
- 10 root developer-command tests pass.
- TypeScript, configured Prettier lint (`npm --prefix frontend run lint`) and production frontend build pass.
- Local browser validation uses an isolated database, actual domain-generated events and the production frontend build. Checked empty, healthy, degraded, unhealthy, stale/unknown, resolved recovery, AI-unavailable and Data Sources states. File selection, partial validation, explicit import and Live API setup were exercised.
- Live OpenAI output is not claimed as verified; rendering of grounded structured reports is covered by tests. The local browser exercise deliberately disabled OpenAI.

## Remaining pilot measurements

Confirmed incident duration is measurable now. MTTD, detection before customer tickets, operator investigation time, false-positive rate and verified customer-impact duration need independent production labels/timestamps. The UI does not invent them. Human investigations are not recorded, so the timeline does not claim an operator intervened. There is no one-click server-side demo reset or public credential-administration screen.
