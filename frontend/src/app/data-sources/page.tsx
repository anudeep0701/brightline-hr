"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { LiveApiGuide } from "@/components/live-api-guide";
import { UploadCloud } from "lucide-react";
import { Shell } from "@/components/shell";
import { useDemoAccess, useDemoImport } from "@/lib/demo-context";
import { ErrorNotice, LoadingState } from "@/components/async-state";
import { api, setTenant, time, uploadFile } from "@/lib/api";
import { ingestionStatus, sourceName, uploadFormat } from "@/lib/onboarding";
import { useResource } from "@/lib/use-resource";
import type {
  DataSources,
  ImportResult,
  UploadPreview,
  Workspace,
} from "@/types";

export default function DataSourcesPage() {
  const demo = useDemoAccess();
  const demoImport = useDemoImport();
  const [scope, setScope] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const loader = useCallback(
    async (signal: AbortSignal) => {
      void scope;
      const [sources, workspace] = await Promise.all([
        api<DataSources>("/api/data-sources", "GET", signal),
        api<Workspace>("/api/workspace", "GET", signal),
      ]);
      return { sources, workspace };
    },
    [scope],
  );
  const { data, error, fetching, reload } = useResource(loader);
  function reset(next?: File | null) {
    controller.current?.abort();
    setFile(next ?? null);
    setPreview(null);
    setResult(null);
    setBusy("");
    setActionError("");
    setMessage("");
  }
  function changeScope(tenant?: string) {
    reset();
    if (tenant) setTenant(tenant);
    setScope((value) => value + 1);
  }
  async function submit(commit: boolean) {
    if (!file || (commit && !preview?.can_import)) return;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy(commit ? "import" : "preview");
    setActionError("");
    setMessage("");
    if (!commit) {
      setPreview(null);
      setResult(null);
    }
    try {
      const format = uploadFormat(file.name, file.size);
      if (commit) {
        const next = await uploadFile<ImportResult>(
          file,
          format,
          current.signal,
          preview!.file_digest,
        );
        if (!current.signal.aborted) {
          setResult(next);
          setPreview(null);
          setMessage(
            "Import complete. Evaluate current health after recent telemetry arrives; completed windows remain unchanged.",
          );
          await reload();
        }
      } else {
        const next = await uploadFile<UploadPreview>(
          file,
          format,
          current.signal,
        );
        if (!current.signal.aborted) {
          setPreview(next);
          setResult(null);
        }
      }
    } catch (failure) {
      if (!current.signal.aborted)
        setActionError(
          failure instanceof Error ? failure.message : "Import unavailable.",
        );
    } finally {
      if (!current.signal.aborted) setBusy("");
    }
  }
  async function evaluate() {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy("evaluate");
    setActionError("");
    try {
      const response = await api<{ created: number }>(
        "/api/evaluate",
        "POST",
        current.signal,
      );
      if (!current.signal.aborted) {
        setMessage(
          response.created
            ? "Current health evaluated. Open Integration health to inspect the evidence."
            : "This evaluation window is already recorded. New events will be included in the next scheduled window.",
        );
        await reload();
      }
    } catch (failure) {
      if (!current.signal.aborted)
        setActionError(
          failure instanceof Error
            ? failure.message
            : "Evaluation unavailable.",
        );
    } finally {
      if (!current.signal.aborted) setBusy("");
    }
  }
  const operator = (!demo || demoImport) && data?.workspace.role === "operator";
  const errors = preview?.validation_errors ?? result?.validation_errors ?? [];
  return (
    <Shell
      tenantName={data?.workspace.tenant_name}
      onAuth={() => changeScope()}
    >
      <p className="eyebrow mb-2">Customer onboarding / Telemetry</p>
      <h1 className="text-3xl font-semibold tracking-tight">
        Connect integration telemetry
      </h1>
      <p className="muted mt-2 mb-6">
        Start with historical logs for a pilot, or connect live requests for
        ongoing observation.
      </p>
      {(error || actionError) && (
        <ErrorNotice
          message={actionError || error}
          retained={!!data}
          retry={() => void reload()}
        />
      )}
      {demo && (
        <p className="mb-5 text-sm text-slate-600">
          Demo telemetry, file imports and Live API events share the same
          validation and health pipeline.{" "}
          {demoImport
            ? "Upload synthetic assessment logs only. Imports are tagged, limited to this workspace and capped at 3,000 records in total; the assessment owner can clear them."
            : "File import is disabled for this deployment; the owner can enable the scoped demo capability."}
        </p>
      )}
      {!data && !error && <LoadingState />}
      {data && (
        <>
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <label className="text-xs font-medium">
              Tenant{" "}
              <select
                className="filter-select ml-2"
                aria-label="Select tenant"
                disabled={!data.workspace.can_switch_tenants || !!busy}
                value={data.workspace.tenant_id}
                onChange={(event) => changeScope(event.target.value)}
              >
                {data.workspace.tenants.map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>
                    {tenant.name}
                  </option>
                ))}
              </select>
            </label>
            <Link className="text-sm font-medium text-teal" href="/">
              View integration health →
            </Link>
          </div>
          <div className="mb-6 grid gap-4 md:grid-cols-2">
            <a className="card p-5 hover:border-teal" href="#pilot-title">
              <p className="eyebrow mb-2">Pilot / Backfill</p>
              <h2 className="font-semibold">Upload historical logs</h2>
              <p className="muted mt-2">
                Start a pilot using existing CSV or JSON request logs.
              </p>
              <span className="mt-3 inline-block text-sm font-semibold text-teal">
                Upload logs ↓
              </span>
            </a>
            <a className="card p-5 hover:border-teal" href="#api-title">
              <p className="eyebrow mb-2">Production / Live API</p>
              <h2 className="font-semibold">Connect live telemetry</h2>
              <p className="muted mt-2">
                Continuously observe requests using an ingestion credential.
              </p>
              <span className="mt-3 inline-block text-sm font-semibold text-teal">
                Set up Live API ↓
              </span>
            </a>
          </div>
          <section
            className="card mb-6 scroll-mt-6 p-5"
            aria-labelledby="pilot-title"
          >
            <h2 id="pilot-title" className="font-semibold">
              Upload historical logs
            </h2>
            <p className="muted mt-2">
              Select logs → Validate → Confirm import → Evaluate health. No
              records are saved until you confirm.
            </p>
            <p className="mt-2 text-xs leading-5 text-slate-600">
              Required columns: timestamp, request_id, integration_id,
              http_status, latency_ms. Use registered integration IDs and
              timezone-aware timestamps. Tenant scope comes from your workspace.
              Older backfill is stored without rewriting completed health
              decisions.
            </p>
            <div className="my-4 flex flex-wrap items-center gap-3">
              <div
                className="relative w-full rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 p-6 text-center focus-within:border-teal"
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault();
                  if (operator && !busy)
                    reset(event.dataTransfer.files[0] ?? null);
                }}
              >
                <UploadCloud
                  size={24}
                  className="mx-auto mb-3 text-teal"
                  aria-hidden="true"
                />
                <label className="cursor-pointer text-sm font-semibold text-teal">
                  Select log file or drop it here
                  <input
                    key={scope}
                    aria-label="Request-log file"
                    type="file"
                    accept=".csv,.json,.ndjson,.jsonl"
                    disabled={!operator || !!busy}
                    className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
                    onChange={(event) => reset(event.target.files?.[0] ?? null)}
                  />
                </label>
                <p className="mt-2 text-xs text-slate-500">
                  CSV · JSON · NDJSON / JSONL · UTF-8 · Up to 1,000 records / 2
                  MiB
                </p>
                <p className="mt-3 break-all text-sm font-medium" role="status">
                  {file ? `Selected: ${file.name}` : "No file selected"}
                </p>
              </div>
              <button
                className="button-secondary"
                disabled={!file || !operator || !!busy}
                onClick={() => void submit(false)}
              >
                {busy === "preview" ? "Validating…" : "Validate file"}
              </button>
            </div>
            {!operator && (
              <p className="text-xs text-slate-500">
                {demo
                  ? "Demo access shows the onboarding flow and observed sources. Importing logs requires an authenticated customer workspace; the shared demo cannot accept uploads."
                  : "Connect an operator workspace token to validate or import. Ingestion keys are for the production API only."}
              </p>
            )}
            {preview && (
              <div
                className="rounded-lg border border-slate-200 p-4"
                aria-live="polite"
              >
                <h3 className="text-sm font-semibold">
                  Validation preview · No data imported
                </h3>
                <dl className="my-4 grid grid-cols-2 gap-3 text-xs md:grid-cols-5">
                  {[
                    ["Total records", preview.total_records],
                    ["Valid new records", preview.valid_records],
                    ["Duplicates", preview.duplicates],
                    ["Rejected records", preview.rejected_records],
                    ["Unknown integrations", preview.unknown_integrations],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt className="text-slate-500">{label}</dt>
                      <dd className="mt-1 text-lg font-semibold">{value}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mb-3 text-xs leading-5 text-slate-600">
                  Confirmation imports valid new rows only. Duplicates are
                  skipped; rejected rows are reported below. Tenant mismatches
                  or unknown integrations block the entire import. Fix scope or
                  register integrations, then validate again.
                </p>
                <button
                  className="button"
                  disabled={!preview.can_import || !!busy || !operator}
                  onClick={() => void submit(true)}
                >
                  {busy === "import"
                    ? "Importing…"
                    : `Confirm import of ${preview.valid_records} valid records`}
                </button>
              </div>
            )}
            {result && (
              <p className="mt-4 text-sm font-medium" role="status">
                Accepted {result.accepted} · Duplicates {result.duplicates} ·
                Rejected {result.rejected}. Final counts reflect validation at
                import time.
                {result.demo_import_batch_id && (
                  <>
                    {" "}
                    Demo batch: <code>{result.demo_import_batch_id}</code>.
                  </>
                )}
              </p>
            )}
            {!!errors.length && (
              <div className="mt-4 text-xs">
                <p className="font-semibold">
                  Validation problems (record numbers start at 1)
                </p>
                <ul className="mt-2 list-disc space-y-2 pl-5 text-slate-600">
                  {errors.slice(0, 10).map((problem) => (
                    <li key={problem.index}>
                      Record {problem.index + 1}:{" "}
                      {problem.code.replaceAll("_", " ")}
                      {problem.fields.length
                        ? ` — ${problem.fields.join(", ")}`
                        : ""}
                    </li>
                  ))}
                </ul>
                {errors.length > 10 && (
                  <p className="mt-2">
                    Showing 10 of {errors.length} problems. Correct the source
                    file and validate again.
                  </p>
                )}
              </div>
            )}
            {message && (
              <p className="mt-4 text-xs leading-5 text-teal" role="status">
                {message}
              </p>
            )}
            {result && (
              <button
                className="button-secondary mt-4"
                disabled={!!busy || !operator}
                onClick={() => void evaluate()}
              >
                {busy === "evaluate"
                  ? "Evaluating…"
                  : "Evaluate current health"}
              </button>
            )}
          </section>
          <LiveApiGuide />
          <section
            className="card mb-6 overflow-x-auto p-5"
            aria-labelledby="sources-title"
          >
            <div className="mb-4 flex justify-between gap-3">
              <h2 id="sources-title" className="font-semibold">
                Data arriving
              </h2>
              <button
                className="text-xs text-teal"
                disabled={fetching || !!busy}
                onClick={() => void reload()}
              >
                Reload
              </button>
            </div>
            <p className="muted mb-4">
              Confirm when requests last arrived and whether their timestamps
              are recent. Unknown source means older events have no recorded
              source; it does not imply a live connection.
            </p>
            <table className="w-full min-w-[760px] text-left text-xs">
              <thead className="text-slate-500">
                <tr>
                  {[
                    "Integration",
                    "Source",
                    "Last event received",
                    "Event timestamp",
                    "Last evaluated",
                    "Freshness",
                  ].map((label) => (
                    <th key={label} className="pb-3 pr-4 font-medium">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.sources.items.map((row) => (
                  <tr
                    key={row.integration_id}
                    className="border-t border-slate-100"
                  >
                    <td className="py-4 pr-4">
                      <Link
                        className="font-semibold hover:text-teal"
                        href={`/integrations/${encodeURIComponent(row.integration_id)}`}
                      >
                        {row.integration_name}
                      </Link>
                    </td>
                    <td className="pr-4">
                      {row.sources.length
                        ? row.sources
                            .map((source) => sourceName(source.source_type))
                            .join(" / ")
                        : "No data yet"}
                    </td>
                    <td className="pr-4">
                      {row.freshness.last_event_received_at
                        ? time(row.freshness.last_event_received_at)
                        : "None received"}
                    </td>
                    <td className="pr-4">
                      {row.freshness.last_event_at
                        ? time(row.freshness.last_event_at)
                        : "None observed"}
                    </td>
                    <td className="pr-4">
                      {time(row.freshness.last_evaluated_at)}
                    </td>
                    <td>{ingestionStatus(row.freshness)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.sources.items.length && (
              <p className="muted py-4">
                Register an integration before importing logs or connecting an
                exporter.
              </p>
            )}
          </section>
        </>
      )}
    </Shell>
  );
}
