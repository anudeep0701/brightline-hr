# Operations dashboard and demo walkthrough

Overview leads with the morning summary, top three attention items, freshness, recent incidents/recovery and calculated impact. Fleet counts support that story. Integrations owns search/status/type filters and all integration rows; Incidents separates active failures and resolved recovery; AI assistant answers workspace questions. Each detail page leads with the deterministic reason, first check and evidence before advisory AI.

Stale/absent telemetry or overdue evaluation makes **current evidence UNKNOWN**. The historical decision remains unchanged in history, rather than being shown as confidently healthy today. Reload view and sixty-second polling fetch stored evidence; **Evaluate now** runs the deterministic engine at server time without generating traffic. Requests are cancelled on navigation/scope changes. Failed refreshes retain prior evidence with a warning.

Recent direction compares adjacent persisted snapshots. State changes take precedence; otherwise error-rate deltas use percentage points and P95 uses relative percentage change. Insufficient traffic displays Limited evidence rather than a confident numeric trend. Comparisons between rolling windows can overlap and do not constitute an anomaly model.

Detail pages provide current recorded state/reason, metrics, three compact histories (errors, P95, volume), exact accessible measurements, health transitions, latest twenty incidents, top error categories, policy/audit details and sanitized recent logs. Snapshot history is bounded to the latest 288 observations in 24 hours. Zero requests produce missing rate/latency measurements, not fabricated zeros. Charts preserve null gaps and scale their x-axis by time. Text/labels accompany status colors, keyboard focus is visible and reduced-motion preferences are respected.

A cached summary for the current snapshot displays automatically, including for readers. No GET or browser poll invokes OpenAI. If no cached enrichment exists, exact deterministic reason_text is immediately visible. Operators may explicitly request assistance; missing key/API failures keep the deterministic fallback. AI confidence describes advisory interpretation and never the health decision. Readers can inspect but cannot evaluate or request paid enrichment.

## Run or reload synthetic scenarios

Install backend/frontend dependencies using the root README. From the repository root:

```bash
.venv/bin/python scripts/run_demo.py --scenario all
```

In a second terminal:

```bash
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

Open `http://localhost:3000`. The launcher generates deterministic synthetic requests relative to the current completed five-minute boundary, replays historical evaluations and starts FastAPI on loopback port 8000. It uses a new temporary SQLite database each run, ignores any inherited DATABASE_URL, disables OpenAI in its child process and removes the temporary database on shutdown. It does not modify the parent shell, existing databases, .env files or hosted schemas. Vercel execution is refused. The default is ninety minutes, three tenants and seed 42; optional arguments are `--duration`, `--tenants`, `--seed` and `--port`. If changing the port, update the frontend process's public backend URL accordingly. Allow the first seed to finish before reloading the browser.

To switch scenarios, stop the demo backend with Ctrl+C and run one of:

| Scenario | Fresh launch command |
| --- | --- |
| Healthy | `.venv/bin/python scripts/run_demo.py --scenario healthy` |
| Authentication outage | `.venv/bin/python scripts/run_demo.py --scenario authentication-outage` |
| Latency degradation | `.venv/bin/python scripts/run_demo.py --scenario latency-degradation` |
| Complete outage | `.venv/bin/python scripts/run_demo.py --scenario complete-outage` |
| Recovery | `.venv/bin/python scripts/run_demo.py --scenario recovery` |

Click Reload view after the new backend starts. Each focused scenario applies to all seven base providers. The `all` scenario instead assigns different scenarios to ten provider series and includes sparse traffic, intermittent failures, isolated spikes and sustained bad windows. Its collapsible demo guide links directly to representative detail pages; those links inspect data rather than reset it. In explicit public DEMO_MODE, **Refresh demo data** separately registers missing fixed scenario integrations and generates bounded fresh events through normal ingestion/evaluation; **Evaluate now** never does so. Link IDs apply to `all`; focused datasets use the seven base provider IDs.

Latency-only degradation can escalate to UNHEALTHY after the policy's sustained-warning windows. Recovery shows a resolved historical incident and the required clean recovery windows. A scenario name describes generated behavior; the deterministic engine controls the resulting state. These datasets are finite replays: they do not continuously emit requests, so freshness/traffic can expire over time. Rerun the launcher to get fresh evidence; browser Reload view and Evaluate now do not reseed.

For persistent demo files, the existing `scripts/seed.py` workflow remains available. See [synthetic generation](../data/synthetic/README.md) for reproducibility and precise scenario construction.

## Tenant access and frontend configuration

`GET /api/workspace` supplies identity, role and authorized tenant options. Credential-free `APP_ENV=demo` with SQLite permits switching among synthetic tenants via tenant_id. Token-based access always returns only the token's tenant, including in demo mode. Normal PostgreSQL/production authorization does not allow credential-free tenant switching. The explicitly enabled public assessment instead opens a fixed-tenant secure demo session automatically, with no reviewer token entry; browser refresh preserves access. This session cannot select another tenant or authorize ingestion/policy/credential administration. In those modes, change Workspace access to an independently provisioned tenant token. A mismatching tenant filter returns 403. Tenant names/records from other production workspaces are not enumerated.

Workspace tokens are held in browser memory and sent only as Authorization headers to the configured backend; they are not saved in localStorage/sessionStorage or URLs. A hard reload clears manually entered bearer access and tenant selection; the separate hosted demo session is renewed automatically. The input is for workspace tokens, never an OpenAI key.

Production uses one Vercel Services project and same-origin `/api/*`; leave NEXT_PUBLIC_API_BASE_URL unset. Its optional local override points to `http://localhost:8000`. No secret belongs in a NEXT_PUBLIC variable; only backend code consumes OPENAI_API_KEY. For local browser access use `http://localhost:3000`, matching default CORS_ALLOWED_ORIGINS; a different browser origin requires corresponding backend CORS configuration. No env file was created or modified by this implementation.

## Verification

Run frontend `npm test`, `npm run typecheck` and `npm run build`, plus the backend Pytest suite. The small frontend tests exercise production presentation helpers for recorded-state preservation, evidence gaps, percentage units, priority and chronological transitions. API tests cover token-confined tenant options, local-demo switching, previous snapshots and cached enrichment reads that cannot call AI. GitHub Actions runs both suites and the existing PostgreSQL checks.

## AI-enabled operations walkthrough

See [AI operations](AI_OPERATIONS.md) for incident briefs, six focused questions, audit evidence, freshness and resolved recovery summaries. The regular demo stays keyless by default; `--enable-ai` explicitly permits operator-requested OpenAI using the existing exported backend key. It uses the same services as the real application. Current dashboard evidence becomes UNKNOWN when stale, while original recorded decisions remain in detail/history.
