"use client";
import { useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { api, time } from "@/lib/api";
import { OperationsAssistant } from "@/components/operations-assistant";
import { advisoryConfidence } from "@/lib/health-view";
import type {
  AIAudit,
  Detail,
  EnrichmentReport,
  Explanation,
  Incident,
  Investigation,
} from "@/types";

const questions = [
  ["why_unhealthy", "Why did this integration become unhealthy?"],
  ["previous_healthy", "What changed since the previous healthy period?"],
  ["error_driver", "Which error category is driving the incident?"],
  ["investigate_first", "What should an operator investigate first?"],
  ["escalation", "Summarize this incident for escalation."],
  ["error_or_latency", "Is this an error-rate issue, latency issue, or both?"],
];

function Audit({ audit }: { audit?: AIAudit | null }) {
  return audit ? (
    <details className="mt-4 border-t border-slate-200 pt-3 text-xs text-slate-500">
      <summary className="cursor-pointer font-medium">
        AI evidence and provenance
      </summary>
      <div className="mt-2 space-y-1 break-words leading-5">
        <p>
          Generated {time(audit.generated_at)} · Evidence window{" "}
          {time(audit.evidence_at)}
        </p>
        <p>
          Recorded health: {audit.health_state} · Current evidence:{" "}
          {audit.current_evidence_status} ·{" "}
          {audit.fallback_used ? "Deterministic fallback used" : audit.model}
        </p>
        {(audit.failure_category || audit.requested_model) && (
          <p>
            AI request:{" "}
            {audit.failure_category?.replaceAll("_", " ") ?? "Completed"}
            {audit.requested_model &&
              ` · Requested model ${audit.requested_model}`}
            {audit.duration_ms != null && ` · ${audit.duration_ms} ms`}
          </p>
        )}
        <p>
          Integration {audit.integration_id} · Tenant {audit.tenant_id}
        </p>
        <p>
          Incident {audit.incident_id ?? "No confirmed incident"} · Snapshot{" "}
          {audit.snapshot_id}
        </p>
        {!!audit.selected_fact_ids?.length && (
          <p>Selected facts: {audit.selected_fact_ids.join(", ")}</p>
        )}
        <p className="break-all font-mono text-[12px]">
          Evidence SHA-256 {audit.evidence_digest}
        </p>
      </div>
    </details>
  ) : null;
}

function Report({
  report,
  ai,
  audit,
}: {
  report: EnrichmentReport;
  ai: boolean;
  audit?: AIAudit | null;
}) {
  return (
    <div className="rounded-lg bg-slate-50 p-4">
      <p className="eyebrow mb-2">
        {ai
          ? "AI insight · Advisory"
          : "Deterministic explanation · AI unavailable"}
      </p>
      <p className="text-sm leading-6">{report.summary}</p>
      {ai && (
        <p className="mt-2 text-xs text-slate-500">
          Issue hypothesis: {report.likely_issue_category.replaceAll("_", " ")}{" "}
          · {advisoryConfidence(report.confidence)} advisory confidence
        </p>
      )}
      <p className="mt-4 text-xs font-semibold">What changed?</p>
      <p className="mt-1 text-xs leading-6 text-slate-600">
        {report.what_changed}
      </p>
      <p className="mt-4 text-xs font-semibold">Suggested investigation</p>
      <ol className="mt-2 list-decimal space-y-2 pl-5 text-xs leading-5 text-slate-600">
        {report.suggested_checks.map((check, i) => (
          <li key={i}>{check}</li>
        ))}
      </ol>
      <Audit audit={audit} />
    </div>
  );
}

export function IncidentAssistant({
  detail,
  operator,
}: {
  detail: Detail;
  operator: boolean;
}) {
  const [brief, setBrief] = useState<Explanation | null>(null);
  const [answer, setAnswer] = useState<Investigation | null>(null);
  const [topic, setTopic] = useState("why_unhealthy");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const cached = detail.enrichment?.audit ? detail.enrichment : null;
  const result = brief ?? cached;
  const snapshot = detail.snapshot;
  async function request(kind: "brief" | "investigate") {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy(kind);
    setError("");
    if (kind === "investigate") setAnswer(null);
    try {
      const path = `/api/integrations/${encodeURIComponent(detail.integration.id)}/${kind}`;
      if (kind === "brief") {
        const next = await api<Explanation>(path, "POST", current.signal);
        if (!current.signal.aborted) setBrief(next);
      } else {
        const next = await api<Investigation>(path, "POST", current.signal, {
          topic,
        });
        if (!current.signal.aborted) setAnswer(next);
      }
    } catch (failure) {
      if (!current.signal.aborted)
        setError(
          failure instanceof Error
            ? failure.message
            : "AI assistance is unavailable.",
        );
    } finally {
      if (!current.signal.aborted) setBusy("");
    }
  }
  return (
    <section
      id="ai-investigation"
      className="card scroll-mt-6 border-teal/30 p-5 md:p-6"
    >
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <p className="eyebrow">Human + AI investigation</p>
          <h2 className="mb-2 mt-2 text-lg font-semibold">AI incident brief</h2>
        </div>
        <button
          className="button-secondary self-start"
          disabled={!!busy || !snapshot || !operator}
          onClick={() => void request("brief")}
        >
          <Sparkles size={14} />
          {busy === "brief"
            ? "Generating brief…"
            : result
              ? "Refresh brief"
              : "Generate brief"}
        </button>
      </div>
      <p className="mb-4 text-xs leading-5 text-slate-500">
        Advisory analysis from observed telemetry. AI prioritizes known facts
        and read-only checks. You decide what to investigate; no actions are
        executed.
      </p>
      {error && (
        <p
          role="alert"
          className="mb-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-900"
        >
          {error} The deterministic decision remains available.
        </p>
      )}
      {result?.report ? (
        <Report
          report={result.report}
          ai={result.source.startsWith("openai:")}
          audit={result.audit}
        />
      ) : (
        <div className="rounded-lg bg-slate-50 p-4">
          <p className="eyebrow mb-2">
            Deterministic explanation · Available without AI
          </p>
          <p className="text-sm leading-6">
            {snapshot?.reason_text ??
              "Evaluate this integration before requesting a brief."}
          </p>
        </div>
      )}
      <div className="mt-5">
        <OperationsAssistant
          integrationId={detail.integration.id}
          incidents={detail.incidents}
          operator={operator}
        />
      </div>
      <details className="mt-5 border-t border-slate-100 pt-5">
        <summary className="cursor-pointer text-sm font-medium">
          Guided investigation topics
        </summary>
        <div className="mt-3">
          <h3 className="text-sm font-semibold">Investigate with AI</h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Ask about this incident. Answers use this integration’s evidence;
            you choose and carry out the next action.
          </p>
          <label
            className="mt-3 block text-xs font-medium"
            htmlFor="investigation-topic"
          >
            Investigation question
          </label>
          <select
            id="investigation-topic"
            className="filter-select mt-2 w-full max-w-full"
            value={topic}
            disabled={!!busy}
            onChange={(event) => {
              setTopic(event.target.value);
              setAnswer(null);
            }}
          >
            {questions.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <button
            className="button-secondary my-3"
            disabled={!!busy || !operator || !snapshot}
            onClick={() => void request("investigate")}
          >
            {busy === "investigate" ? "Investigating…" : "Investigate with AI"}
          </button>
          {answer && (
            <Report
              report={answer.report}
              ai={answer.source.startsWith("openai:")}
              audit={answer.audit}
            />
          )}
          {!operator && (
            <p className="text-xs text-slate-500">
              Connect an operator workspace token to request assistance.
            </p>
          )}
        </div>
      </details>
    </section>
  );
}

export function RecoverySummary({
  incident,
  integrationId,
  operator,
}: {
  incident: Incident;
  integrationId: string;
  operator: boolean;
}) {
  const [answer, setAnswer] = useState<Investigation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function summarize() {
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setError("");
    try {
      const result = await api<Investigation>(
        `/api/integrations/${encodeURIComponent(integrationId)}/investigate`,
        "POST",
        current.signal,
        { topic: "recovery", incident_id: incident.id },
      );
      if (!current.signal.aborted) setAnswer(result);
    } catch (failure) {
      if (!current.signal.aborted)
        setError(
          failure instanceof Error
            ? failure.message
            : "Recovery assistance unavailable.",
        );
    } finally {
      if (!current.signal.aborted) setBusy(false);
    }
  }
  return (
    <div className="mt-3 w-full">
      <button
        className="button-secondary"
        disabled={busy || !operator}
        onClick={() => void summarize()}
      >
        {busy ? "Summarizing…" : "Summarize recovery with AI"}
      </button>
      {error && (
        <p role="alert" className="mt-2 text-xs text-amber-800">
          {error} The deterministic recovery evidence above remains available.
        </p>
      )}
      {answer && (
        <div className="mt-3">
          <Report
            report={answer.report}
            ai={answer.source.startsWith("openai:")}
            audit={answer.audit}
          />
        </div>
      )}
    </div>
  );
}
