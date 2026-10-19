"use client";
import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { api, time } from "@/lib/api";
import type { AssistantAnswer, AssistantQuestion, Incident } from "@/types";

export function AssistantFeedback({
  busy,
  error,
}: {
  busy: boolean;
  error: string;
}) {
  return (
    <>
      {busy && (
        <p role="status" className="mt-3 text-sm">
          Reviewing bounded telemetry evidence…
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"
        >
          {error} Health evidence remains available.
        </p>
      )}
    </>
  );
}

function EvidenceList({ evidence }: { evidence: AssistantAnswer["evidence"] }) {
  return (
    <ul className="mt-2 space-y-3">
      {evidence.map((ref) => (
        <li key={ref.id} className="break-words text-sm leading-6">
          <span className="font-medium">{ref.label}: </span>
          {ref.value}
          <div className="mt-1 text-xs text-slate-600">
            {ref.observed_at
              ? `Observed ${time(ref.observed_at)}`
              : "Workspace context"}
            {ref.integration_id && (
              <>
                {" "}
                ·{" "}
                <Link
                  className="font-medium text-teal underline"
                  href={`/integrations/${encodeURIComponent(ref.integration_id)}${ref.incident_id ? "#incident-timeline" : "#health-decision"}`}
                >
                  Inspect evidence
                </Link>
              </>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function AssistantResult({ result }: { result: AssistantAnswer }) {
  const primary = result.evidence.slice(0, 4);
  const extra = [
    ...(result.answer_evidence ?? []),
    ...result.evidence.slice(4),
    ...(result.additional_evidence ?? []),
  ].filter(
    (ref, i, all) =>
      !primary.some((item) => item.id === ref.id) &&
      all.findIndex((item) => item.id === ref.id) === i,
  );
  const priorities = result.priorities ?? [];
  return (
    <div
      className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4"
      aria-live="polite"
    >
      <p className="eyebrow mb-3">
        {result.availability === "LIVE"
          ? "AI analysis · Advisory"
          : result.availability === "REFUSED"
            ? "Scope and action boundary"
            : "AI unavailable · Deterministic evidence"}
      </p>
      <div className="space-y-3 text-sm leading-7 break-words">
        {(priorities.length ? result.summary : result.answer)
          .split(/\n\n/)
          .map((text, i) => (
            <p key={i}>{text}</p>
          ))}
      </div>
      {!!priorities.length && (
        <div className="mt-4">
          <h3 className="text-sm font-semibold">Priority actions</h3>
          <ol className="mt-3 space-y-3">
            {priorities.slice(0, 3).map((item, i) => (
              <li
                key={item.integration_id}
                className="rounded-lg border border-slate-200 bg-white p-3"
              >
                <p className="text-sm font-semibold">
                  <Link
                    className="text-teal underline"
                    href={`/integrations/${encodeURIComponent(item.integration_id)}`}
                  >
                    {i + 1}. {item.name}
                  </Link>
                  <span className="ml-2 text-xs font-medium">
                    {item.status.toLowerCase()}
                  </span>
                </p>
                <p className="mt-1 text-sm leading-6">{item.reason}</p>
                <p className="mt-2 text-sm">
                  <span className="font-semibold">First check: </span>
                  {item.next_check}
                </p>
              </li>
            ))}
          </ol>
        </div>
      )}
      {!priorities.length && !!result.recommended_checks.length && (
        <div className="mt-4">
          <h3 className="text-sm font-semibold">
            Suggested investigation · Human decides
          </h3>
          <ol className="mt-2 list-decimal space-y-2 pl-5 text-sm leading-6">
            {result.recommended_checks.slice(0, 3).map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ol>
        </div>
      )}
      {!!primary.length && (
        <div className="mt-5 border-t border-slate-200 pt-4">
          <h3 className="text-sm font-semibold">Supporting evidence</h3>
          <EvidenceList evidence={primary} />
        </div>
      )}
      {!!extra.length && (
        <details
          open={result.intent === "detail"}
          className="mt-4 border-t border-slate-200 pt-3"
        >
          <summary className="cursor-pointer text-sm font-medium text-teal">
            Show more evidence ({extra.length})
          </summary>
          <EvidenceList evidence={extra} />
        </details>
      )}
      <p className="mt-4 text-xs text-slate-600">
        Confidence: {result.confidence}
        {result.confidence === "low"
          ? " — limited recent evidence or AI unavailable"
          : " — advisory analysis"}{" "}
        · Health decisions remain deterministic.
      </p>
      <details
        open={result.intent === "detail"}
        className="mt-3 text-xs leading-6 text-slate-600"
      >
        <summary className="cursor-pointer font-medium">
          Limits and AI provenance
        </summary>
        <ul className="mt-2 list-disc pl-5">
          {result.limitations.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
        <p className="mt-2 break-words">
          Model requested: {result.audit.requested_model} ·{" "}
          {result.audit.failure_category?.replaceAll("_", " ") ??
            result.audit.model ??
            "No provider call"}{" "}
          · {result.audit.duration_ms} ms
          {result.audit.cache_hit ? " · Cached unchanged evidence" : ""}
        </p>
        <p className="break-all">
          Request {result.audit.request_id} · Generated{" "}
          {time(result.audit.generated_at)}
        </p>
        {!!result.methodology?.length && (
          <details open={result.intent === "detail"} className="mt-2">
            <summary className="cursor-pointer font-medium">
              How was this calculated?
            </summary>
            <ul className="list-disc pl-5">
              {result.methodology.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </details>
        )}
      </details>
    </div>
  );
}

export function OperationsAssistant({
  integrationId,
  incidents = [],
  operator,
}: {
  integrationId?: string;
  incidents?: Incident[];
  operator: boolean;
}) {
  const label = useId();
  const [question, setQuestion] = useState("");
  const [incident, setIncident] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<AssistantAnswer | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const prompts = integrationId
    ? [
        "What evidence supports this classification?",
        "Is this an error-rate problem or a latency problem?",
        "What should Ops investigate first?",
        "Has this incident recovered?",
      ]
    : [
        "What needs my attention right now?",
        "Which integrations are stale or missing telemetry?",
        "What changed in the last hour?",
        "What should Ops investigate first?",
        "Summarize today’s active incidents.",
      ];
  async function ask() {
    if (!question.trim() || busy || !operator) return;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setError("");
    setResult(null);
    const payload: AssistantQuestion = {
      question,
      scope: incident
        ? "incident"
        : integrationId
          ? "integration"
          : "workspace",
      ...(integrationId ? { integration_id: integrationId } : {}),
      ...(incident ? { incident_id: incident } : {}),
    };
    try {
      const next = await api<AssistantAnswer>(
        "/api/assistant/ask",
        "POST",
        current.signal,
        payload,
      );
      if (!current.signal.aborted) setResult(next);
    } catch (failure) {
      if (!current.signal.aborted)
        setError(
          failure instanceof Error
            ? failure.message
            : "Assistant unavailable. Retry shortly.",
        );
    } finally {
      if (!current.signal.aborted) setBusy(false);
    }
  }
  return (
    <section
      className="card mb-6 border-teal/30 p-5"
      aria-labelledby={`${label}-title`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2
            id={`${label}-title`}
            className="flex items-center gap-2 text-lg font-semibold"
          >
            <Sparkles size={18} />
            AI Operations Assistant
          </h2>
          <p className="mt-1 text-xs text-slate-600">
            {integrationId
              ? "Selected integration / incident"
              : "Current workspace"}{" "}
            · Advisory answers with cited evidence · No actions executed
          </p>
        </div>
        <span className="text-xs font-medium text-teal">
          Health decision: deterministic policy
        </span>
      </div>
      {integrationId && !!incidents.length && (
        <div className="mt-3">
          <label
            htmlFor={`${label}-scope`}
            className="block text-xs font-medium"
          >
            Evidence scope
          </label>
          <select
            id={`${label}-scope`}
            className="filter-select mt-1 w-full"
            disabled={busy}
            value={incident}
            onChange={(event) => {
              setIncident(event.target.value);
              setResult(null);
            }}
          >
            <option value="">Current integration evidence</option>
            {incidents.slice(0, 5).map((item) => (
              <option key={item.id} value={item.id}>
                {item.resolved_at ? "Resolved" : "Open"} incident ·{" "}
                {time(item.opened_at)}
              </option>
            ))}
          </select>
        </div>
      )}
      <form
        className="mt-4"
        onSubmit={(event) => {
          event.preventDefault();
          void ask();
        }}
      >
        <label htmlFor={`${label}-question`} className="text-sm font-medium">
          Ask about integration health
        </label>
        <textarea
          id={`${label}-question`}
          className="mt-2 block min-h-20 w-full rounded-lg border border-slate-300 bg-white p-3 text-sm leading-6"
          rows={2}
          maxLength={600}
          disabled={busy || !operator}
          placeholder={
            integrationId
              ? "Ask why, what changed, or what to investigate…"
              : "Ask what needs attention, what changed, or where evidence is missing…"
          }
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value);
            setResult(null);
            setError("");
          }}
        />
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <div
            role="group"
            aria-label="Suggested operational questions"
            className="flex flex-wrap gap-2"
          >
            {prompts.map((prompt) => (
              <button
                type="button"
                className="text-left text-xs font-medium text-teal underline underline-offset-2"
                key={prompt}
                disabled={busy || !operator}
                onClick={() => {
                  setQuestion(prompt);
                  setResult(null);
                  setError("");
                }}
              >
                {prompt}
              </button>
            ))}
          </div>
          <button
            type="submit"
            className="button"
            disabled={busy || !operator || !question.trim()}
          >
            {busy ? "Asking AI…" : "Ask AI"}
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-600">
          {question.length}/600 · No employee details or credentials.
          {!operator && " Connect an operator workspace to ask questions."}
        </p>
      </form>
      <AssistantFeedback busy={busy} error={error} />
      {result && <AssistantResult result={result} />}
    </section>
  );
}
