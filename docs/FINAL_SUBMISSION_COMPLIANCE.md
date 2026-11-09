# Final submission compliance

Audit date: 2026-11-09. Scope: the current repository and focused submission ZIP, checked against the supplied official materials. PASS means implementation/artifact evidence was inspected, not merely claimed in a README. Candidate-only submission actions remain separate from software readiness.

## Official sources inspected

- **CS4:** `case-study-4-api-integration-health/case-study-brief.md`, all sections.
- **Starter:** `starter_kit/README.md`, `integration_utils.py`, and all 60 records in `data/integration_logs.json`. The utility is explicitly optional. Host `.DS_Store` metadata is irrelevant and excluded.
- **Guide:** `CaseStudySubmission-StudentQuickGuide.pdf`, all four pages, text and rendered layout. Dated Nov 3, 2026; that is the document date, not a submission deadline. The linked full student guide was not supplied and is not represented as reviewed.

## Official requirement matrix

| Official requirement | Status | Evidence |
| --- | --- | --- |
| CS4: Brightline/Marcus needs a morning view before customer tickets, without raw-log digging | PASS | Overview's morning summary, fleet states, top issues, reason/first check/freshness; `frontend/src/components/operations-view.tsx` and integration detail |
| CS4: decide and explain error threshold/window | PASS | Design Assumptions; `backend/app/health/config.py`; provided-sample profile explicitly separate in `scripts/replay_official_data.py` |
| CS4: weigh errors against latency | PASS | Worst signal wins; timeouts included in all-attempt denominator; `metrics/calculation.py`, `health/policy.py` |
| CS4: combine integrations into an overall picture | PASS | Tenant counts and severity-ranked attention queue; no healthy-average masking of failures; design Fleet picture |
| CS4: decide refresh frequency | PASS | Five-minute intended evaluation, 60-second read polling, Hobby on-demand; protected scheduler path preserved |
| CS4: run end to end against the supplied input | PASS | Unchanged required fixture `data/provided/integration_logs.json`; normal ingestion -> rollups -> snapshots/incidents -> CLI/UI via `scripts/replay_official_data.py` |
| Starter: handle status values beyond success/error | PASS | Five Greenhouse timeouts mapped explicitly; 6/12 failures, 5/12 timeouts, P95 30,000 ms; exact regression tests |
| Starter: optional helper may be replaced/ignored | PASS | Replaced with shared Polars service; helper's excluded-timeout denominator documented, not reused blindly |
| CS4: show health of each integration and why | PASS | Official replay: two Healthy and three Unhealthy, all with reasons; `backend/tests/test_official_data.py` |
| CS4: SOLUTION_DESIGN.md, 1-2 pages' intent, problem/assumptions/approach/trade-offs/more time | PASS | Editable Markdown plus visually checked two-page `SOLUTION_DESIGN.pdf`; same content and embedded labeled architecture |
| CS4: working implementation and README run instructions/limits | PASS | Runnable frontend/backend, dependency manifests, local SQLite path, tests and known gaps in root README |
| CS4: roughly 3-4 focused hours; stop and state future work beyond 4-5 | PARTIAL | Existing platform is broader than the suggested timed MVP; no claim it was built within that budget. Design identifies excess scope and future priorities; this audit adds only compliance fixes |
| CS4: AI enhancement optional, plus signal, never a gate | PASS | Visible concise advisory Q&A/briefs, grounding, human control, safe fallback; core decisions never use OpenAI |
| CS4: language/stack/scope/thresholds are candidate choices | PASS | Next.js/FastAPI/PostgreSQL documented as choices; no unsupported mandatory stack or infrastructure claim |
| CS4: 30-45 minute panel walkthrough/demo and what-if defense | PASS | README 15-file review map; design rationale, boundary conditions, trade-offs and scope gaps; `docs/PRODUCT_WALKTHROUGH.md` |
| Guide p1: design, README and all necessary code in one ZIP | PASS | One project folder with source/tests/configuration/dependencies, Markdown design and supported PDF; archive integrity independently checked |
| Guide p2: design must be PDF/DOCX/PPTX; maximum 20 pages/slides | PASS | Two-page text-based, unencrypted PDF; not just Markdown, not scanned/image-only |
| Guide pp2-3: diagrams embedded and labeled; PDF diagrams as raster pictures, not vector graphics | PASS | One embedded PNG diagram, 1,800 x 620 pixels; all boxes/arrows labeled; no standalone image entries in ZIP |
| Guide p3: pictures >=100 px each side, <=6/document and <=8/submission | PASS | One qualifying embedded picture in the PDF; no other submitted pictures |
| Guide p2: root README.md; first ~100 lines include built product, requirement/file map, run/tests/trade-offs/gaps | PASS | README is 96 lines and contains all these items; hosted credential-free assessment and normal production authentication clearly distinguished |
| Guide p2: reviewer reads 15 files; list key files and omit generated/bulk data/images | PASS | README + PDF + 13 prioritized implementation/configuration files. All necessary source remains runnable; bulk generated logs, standalone screenshots, caches and build outputs excluded. Only the 8 KiB official input required by CS4 and a tiny digest manifest remain as fixtures |
| Guide p2: ZIP under 50 MB; no .png/.svg/.drawio/.doc/.ppt attachments | PASS | Archive inspection enforces size/extension exclusions; supported design PDF contains the diagram |
| Guide: specific archive basename/folder name | NOT APPLICABLE | No convention specified; retains `FDE_Brightline_HR_Case_Study.zip` with `brightline-hr/` root |
| Official numeric throughput, latency SLO, scale target, cloud account, deployment link or specific tech stack | NOT APPLICABLE | Not prescribed. Thresholds, scale path, live hosting and dependencies are candidate decisions, not invented official requirements |
| Official exact test framework, specific test count, external service prohibition, Copilot mandate or AI-assigned health | NOT APPLICABLE | None is stated in the supplied sources. Tests/security and advisory AI are delivered engineering choices |

## Delivered-product safeguards (our choices, not mandatory brief additions)

| Official requirement | Status | Evidence |
| --- | --- | --- |
| Responsible execution of optional AI enhancement | PASS | Bounded authorized fact/check catalog; untrusted telemetry; PII/secret minimization; no SQL/action/credential tools; prompt-abuse and no-state-change tests |
| Secure hosted evaluator access without manually entering a token | PASS | Explicit DEMO_MODE, fixed configured tenant, one-hour Secure/HttpOnly cookie, renewal, origin checks and capability allowlist; `backend/app/api/demo.py`, `frontend/src/components/demo-access.tsx` |
| Preserve real customer authentication and ingestion-key separation | PASS | DEMO_MODE defaults false; bearer reader/operator auth retained; ingestion credentials hash-only and ingestion-only |
| UNKNOWN, freshness, hysteresis, historical incidents and recovery | PASS | Policy/freshness modules and business tests; historical exact official replay never claims current health; explicit rebase preserves original input |
| File/API/synthetic input reuse and authorization | PASS | Same normalized ingestion; bounded preview/confirm file path; idempotency, tenant isolation and safe rejections tested |
| Portability and Vercel single-project deployment | PASS | Relative module/data paths, blank .env.example, pinned manifests and same-origin Services routing. New ZIP independently extracted and checked; no Git/history/local credential dependency |
| Current tests, migrations, build and secret exclusion | PASS | `docs/VERIFICATION.md` and packaged audit manifest record exact final check results |

## Candidate submission and conversation checklist

These are mandatory portal/user actions; they are not claims that this repository submitted itself.

1. Use desktop Chrome, Edge or Firefox, a working webcam/microphone, entire-screen sharing, a quiet room and uninterrupted time. Know the languages/frameworks/libraries/tools listed in README.
2. In **TalentStudio -> Case Study Technical Review -> New submission**, choose evaluation/case study, enter the actual stack, tick consent, create Draft, and upload this **single final ZIP**. There is no filename convention in the guide. Files cannot be appended afterward; a changed file or tech stack requires a new submission and confirmation.
3. Wait for processing and **Preliminary review complete**. Then open the submission and select **Start pushback conversation**. Verify camera/microphone and **Entire Screen** access first; consent/verification is required before the button enables.
4. Answer 4-7 questions aloud, one at a time; one changes a customer requirement. Default timer is five minutes/question. Use the keyboard only to correct transcription. Do not type prepared answers; copy/cut/paste are blocked. Name actual files/decisions and say what was not built.
5. Do not switch tabs/windows/apps during a question: two warnings, then the third switch ends the conversation. Stopping screen sharing/camera ends it immediately. Close distracting apps/notifications beforehand. Reload/close saves progress but may require permissions again. Camera clips and screen snapshots every 15 seconds are recorded for authorized reviewers.
6. Final review starts automatically when conversation ends; status becomes **Completed**. Scores are reviewer-only unless candidate access is enabled; a human panel decides. No numerical scoring rubric is provided in these two sources.
7. Missing portal permissions/microphone issues require administrator help. Failed extraction: re-export a text-based PDF or clean ZIP and create a new submission. Stuck review: wait, use Retry if offered, then contact administrator.

Portal upload, consent and spoken responses are pending candidate actions, not software/package blockers. No submission was created, consent accepted or recording started by this audit.

## Evidence and defense readiness

The brief explicitly evaluates ambiguity, design judgment, working execution, clear reasoning and response to challenge. It does **not** supply weighted scores for eight named dimensions. For the requested supplemental lens: problem/system thinking -> policy/evidence gates; architecture -> single data path and separate services; consulting -> calibration/sparse sample choices; execution/debugging -> tests and observed failure modes; communication -> short design/README; pushback -> explain freshness, cadence, latency-only failure and 100x traffic trade-offs; product/business -> actionable morning view and honestly labeled outcomes. Responsible AI/human collaboration is an optional plus, implemented without moving health decisions into the model. Actual spoken performance remains the candidate's responsibility.
