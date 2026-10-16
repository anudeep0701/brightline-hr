# Evidence-grounded AI operations

The integration detail page now pairs a **Deterministic health policy** decision with an **AI incident brief**, six focused operator questions and resolved-incident recovery assistance. AI prioritizes relevant facts and read-only checks. Humans decide what to investigate; no operational actions or external workflow tools are executed.

## AI value and grounding

The new brief/copilot path uses the existing backend OpenAI client and Responses structured parsing, with an eight-second timeout, no retries and `store=False`. The optional backend process variable `OPENAI_MODEL` defaults to `gpt-6-luna`; its example placeholder stays blank. Luna uses `reasoning.effort=none` for this bounded fact-selection task. No new service, queue, identity provider, database table or migration is needed.

Structured output alone does not establish factual correctness; [official OpenAI guidance](https://developers.openai.com/api/docs/guides/structured-outputs#handling-user-generated-input) also describes hallucination risks despite schema adherence. The provider receives an allowlisted evidence packet and returns a **selection plan**, not unrestricted factual prose:

- Known summary/change fact IDs, ordered for the selected operational question.
- An observed issue-category hypothesis from the allowed categories.
- Known read-only investigation check IDs, prioritized for the operator.
- High/medium/low advisory confidence.

The backend validates every ID and category, then renders the selected facts from its own evidence. The model cannot insert an invented metric, customer, integration, timestamp, incident or action. Unknown IDs, invented categories, extra health-status fields, invalid confidence, incomplete output and provider failures yield deterministic fallback. Insufficient or stale evidence is explicitly flagged and advisory confidence is capped low. Missing previous-healthy comparison evidence is stated explicitly rather than manufactured.

This deliberately makes the AI contribution **relevance selection and investigation prioritization**, rather than unrestricted narrative generation. The public report retains summary, likely_issue_category, what_changed, suggested_checks and numeric confidence for compatibility; the UI presents High/Medium/Low confidence. No health/incident state field is accepted from the provider plan.

Evidence includes only the selected authenticated tenant/integration, immutable health snapshot/reason/metrics/thresholds, eligible statistical baseline, the previous healthy snapshot, recent transitions (from at most thirteen snapshots), and the relevant incident. Raw request payloads, raw error messages, credentials and unrelated tenants are excluded. Tenant/integration labels are known system context, not invented names. A previous healthy period and a statistical baseline are explicitly distinct.

## API and authorization

All new POST routes require the existing **workspace operator** authorization. Readers and ingestion-only credentials cannot invoke them. Optional tenant filters must match the authenticated tenant; a body cannot select a tenant or supply an arbitrary prompt.

- `POST /api/integrations/{id}/brief`: latest-snapshot incident brief, persisted in the existing enrichment row. Missing snapshot returns 409.
- `POST /api/integrations/{id}/investigate`: `{ "topic": "error_driver" }`, with fixed topics `why_unhealthy`, `previous_healthy`, `error_driver`, `investigate_first`, `escalation`, `error_or_latency`.
- Recovery uses the same investigation route: `{ "topic": "recovery", "incident_id": "<owned-resolved-incident-id>" }`. An absent/foreign incident returns 404; an unresolved owned incident returns 409. Recovery evidence comes from the **selected resolution snapshot**, not the latest snapshot today.

Legacy `/explain` and `/api/v1/.../explanation` remain compatible with their existing narrative-enrichment contract. The new product UI uses `/brief` and `/investigate` with the stricter fact-selection contract. No second AI-only demo implementation was added.

The focused copilot is stateless: it accepts no chat transcript, arbitrary tenant query or tool/action payload. Answers expose audit metadata, but are not retained as conversation history. It cannot restart services, change policy, revoke credentials, modify integrations or resolve incidents. Checks are human recommendations only.

## Audit and storage

Each new response exposes tenant/integration/incident and snapshot references, recorded health, current-evidence status, freshness classification, evidence-window timestamp, generation time, model identifier, fallback flag, evidence SHA-256 and selected fact/check IDs. The UI exposes these under **AI evidence and provenance**.

Briefs persist in the existing enrichment table. The requested model is recorded separately from the provider-returned model identifier; changing `OPENAI_MODEL` invalidates a cached brief when an API key is configured. The stored payload contains compact snapshot references, freshness-at-generation, transition times and audit metadata; it does not duplicate the fact catalog/metrics or store raw prompt text, provider instructions, keys or request logs. Existing immutable snapshots retain source evidence. The digest identifies the exact structured input sent to the model. The version identifies the deterministic fact renderer. This is enough to locate and review source evidence; it is not an append-only record of every brief regeneration.

The per-snapshot cache retries a deterministic fallback when an existing backend key becomes available. Explicit refresh also retries provider failure. Freshness changes invalidate an earlier confidently healthy brief, so stale evidence is flagged rather than reusing its earlier confidence. GET endpoints only read cached artifacts and never invoke AI.

## Freshness and health

The deterministic engine already uses request sufficiency, freshness and hysteresis. It still owns persisted HEALTHY/DEGRADED/UNHEALTHY/UNKNOWN decisions and incidents.

Read responses now expose `freshness`:

- `RECENT_TRAFFIC`, `STALE_TELEMETRY` or `NO_TELEMETRY`.
- Last event observed, last event received and last evaluation.
- Current evidence status and evaluation-overdue flag.

Freshness uses each integration's configurable `max_gap_minutes`; overdue evaluation uses twice its configurable refresh cadence, matching the existing UI rule. Receiving an old event now does not make the original event time recent. Zero observed failures do not establish sufficient or fresh traffic.

A stale/absent event stream or overdue evaluation presents **current evidence UNKNOWN**. The original snapshot and its recorded decision remain immutable and visible in history; an actual next evaluation persists UNKNOWN under the deterministic engine. Dashboard cards/status filters use current evidence, while history remains an audit of recorded decisions. `/api/health-summary` retains historical `status_counts` and adds `current_evidence_status_counts`. Existing API health-status/time-range filters continue to describe recorded snapshots; freshness fields describe the current evidence overlay.

## Recovery intelligence

Incident details expose opening time and deterministic reason, final recovery-streak start time, resolution time, actual healthy windows observed/required, and the recorded recovery condition. The policy comes from the incident's last/resolution snapshot, so changing today's thresholds does not rewrite the historical requirement.

The condition includes sufficient fresh traffic, recovery error/timeout margins, target-relative P95, applicable healthy-baseline margin and adjacent healthy-window count. A borderline/insufficient window resets the streak. Recovery assistance uses these recorded facts and does not resolve or reopen anything.

## Evaluator walkthrough

Run the existing seeded demo and frontend. No key is required:

```bash
.venv/bin/python scripts/run_demo.py --scenario all --tenants 2
```

In another terminal, `npm --prefix frontend run dev`. For a real AI demonstration, export the existing OPENAI_API_KEY privately in the backend terminal and opt in with `scripts/run_demo.py --scenario all --enable-ai`; no key still falls back. The root `npm run dev` launcher also forwards an exported backend key normally. No environment file is loaded or edited by these workflows.

1. Open **Workday Payroll (Sustained failures)**. Its history shows HEALTHY → DEGRADED → UNHEALTHY, with a confirmed incident and opening reason.
2. Generate the AI incident brief. Inspect source facts, model/fallback status and evidence timestamp. If no key is configured, the deterministic explanation remains useful and visible.
3. Ask which category drives the incident, compare with the previous healthy period, then request escalation facts. The operator chooses the investigation; no action runs.
4. Open **ADP Payroll (Recovery)**. Its single real domain replay shows HEALTHY → DEGRADED → UNHEALTHY → recovery confirmation → HEALTHY and a resolved incident.
5. Inspect opening reason, recovery beginning, two required clean windows and resolution. Request its recovery summary and confirm the audit points to the resolution snapshot.
6. Inspect latency-only DocuSign, low-volume Twilio, and the brief-spike series. Latency can escalate without HTTP failures; insufficient traffic is UNKNOWN; the brief spike opens no persistent incident.
7. Let evidence age without new traffic: current evidence becomes UNKNOWN while recorded decisions and incident history remain available. Generated events are deterministic for an explicit seed plus anchor time.

Generation, synthetic replay and authenticated external ingestion all call the same domain ingestion service, metric calculation, health policy and incident lifecycle. The AI buttons use the same authorized application services for demo and real data. Keyless fallback is not a fake model response. Successful and malicious provider responses are simulated only at the provider boundary in automated tests.

## Verification and limits

New tests cover factual-plan grounding, audit/minimal storage, cache retry/staleness, absent key, timeouts/failures, malformed/hallucinated outputs and action IDs, unchanged health/incidents, every question, previous-healthy insufficiency, selected resolved recovery, cross-tenant/reader restrictions, late old events, and current evidence versus historical state. Frontend tests cover freshness presentation, confidence labels, structured scoped requests and safe request errors. The HTTP smoke workflow exercises brief and recovery fallback through real routes.

No live provider call was made during implementation. Operator question answers are transient, brief regeneration is not append-only audit history, and explicit operator calls have bounded request time/output but no new AI quota/rate-limiting subsystem. Those are pilot considerations rather than automatic-action or infrastructure features.
