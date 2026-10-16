"use client";
import { useEffect, useState } from "react";
import { apiBaseUrl } from "@/lib/api";

export function LiveApiGuide() {
  const [copied, setCopied] = useState("");
  const [origin, setOrigin] = useState(apiBaseUrl);
  useEffect(() => {
    if (!apiBaseUrl) setOrigin(window.location.origin);
  }, []);
  const sample = `curl --fail-with-body -X POST '${origin || "https://<your-app-domain>"}/api/ingest' \\\n  -H "Authorization: Bearer $INGESTION_API_KEY" \\\n  -H 'Content-Type: application/json' \\\n  --data-binary @- <<'JSON'\n{ "events": [{\n  "timestamp": "<recent ISO-8601 timestamp with timezone>",\n  "request_id": "<stable tenant-unique request ID>",\n  "integration_id": "<registered integration ID>",\n  "http_status": 200, "latency_ms": 125\n}] }\nJSON`;
  return (
    <section
      id="api-title"
      className="card mb-6 scroll-mt-6 p-5"
      aria-labelledby="live-heading"
    >
      <p className="eyebrow mb-2">Production / Continuous observation</p>
      <h2 id="live-heading" className="font-semibold">
        Connect live telemetry
      </h2>
      <p className="muted mt-2">
        Continuously send request events using a tenant-scoped ingestion
        credential.
      </p>
      <ol className="my-5 grid gap-4 text-xs leading-5 md:grid-cols-4">
        <li>
          <strong>1. Obtain a credential</strong>
          <p className="mt-1 text-slate-600">
            Ask an administrator to register your integration and issue an
            ingestion credential. Store it privately in your exporter.
          </p>
        </li>
        <li>
          <strong>2. Send a test event</strong>
          <p className="mt-1 text-slate-600">
            Use a recent timestamp and the registered integration ID. This
            credential is separate from workspace access.
          </p>
        </li>
        <li>
          <strong>3. Verify connection</strong>
          <p className="mt-1 text-slate-600">
            Check accepted / rejected counts, then reload Data arriving below to
            confirm receipt.
          </p>
        </li>
        <li>
          <strong>4. Begin observation</strong>
          <p className="mt-1 text-slate-600">
            Send telemetry continuously, review health with Ops and calibrate
            policies in shadow mode.
          </p>
        </li>
      </ol>
      <details>
        <summary className="button-secondary w-fit cursor-pointer">
          Set up Live API · Request example
        </summary>
        <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
          <div>
            <dt className="font-semibold">Endpoint</dt>
            <dd className="mt-1 font-mono">POST /api/ingest</dd>
          </div>
          <div>
            <dt className="font-semibold">Authentication</dt>
            <dd className="mt-1">
              Authorization: Bearer &lt;ingestion credential&gt;
            </dd>
          </div>
        </dl>
        <p className="mt-4 text-xs leading-5">
          <strong>Required event fields:</strong> timestamp, request_id,
          integration_id, http_status, latency_ms.
        </p>
        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            Sample only · No saved credentials are displayed
          </p>
          <button
            className="button-secondary"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(sample);
                setCopied("Copied sample request");
              } catch {
                setCopied("Copy unavailable. Select the sample text below.");
              }
            }}
          >
            Copy sample request
          </button>
        </div>
        <p role="status" className="mt-2 text-xs text-teal">
          {copied}
        </p>
        <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-50 p-4 text-xs leading-6">
          {sample}
        </pre>
        <p className="mt-3 text-xs leading-5 text-slate-600">
          Optional: error_code, error_message, integration_name,
          integration_type. Up to 1,000 records per batch from the past seven
          days. Retry with the same request IDs; duplicates are safely skipped.
          Inspect validation_errors for rejected rows.
        </p>
      </details>
    </section>
  );
}
