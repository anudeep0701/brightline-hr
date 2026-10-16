"use client";
import { useState } from "react";
import Link from "next/link";
import type { IntegrationRow } from "@/types";

export const demoScenarios = [
  {
    label: "Normal operations",
    id: "workday-payroll",
    scenario: "healthy",
    description:
      "Recent successful traffic with enough evidence for a healthy decision.",
  },
  {
    label: "Authentication outage",
    id: "slack-notifications",
    scenario: "authentication-outage",
    description:
      "Sustained authentication failures confirm an incident. Inspect the evidence, then request an AI brief.",
  },
  {
    label: "Latency degradation",
    id: "docusign",
    scenario: "latency-degradation",
    description: "Slow responses need attention even when requests succeed.",
  },
  {
    label: "Provider outage",
    id: "greenhouse-ats",
    scenario: "complete-outage",
    description:
      "Repeated bad windows confirm a failure; a single spike does not.",
  },
  {
    label: "Recovery",
    id: "adp-recovery",
    scenario: "recovery",
    description:
      "Consecutive healthy windows resolve an incident. Review the recovery condition and outcome.",
  },
];
export function DemoGuide({ items = [] }: { items?: IntegrationRow[] }) {
  const [selected, setSelected] = useState(1);
  const choice = demoScenarios[selected];
  const available = items.find((row) => row.integration.id === choice.id);
  return (
    <section
      id="demo-scenarios"
      className="card mb-6 scroll-mt-6 p-5"
      aria-labelledby="demo-title"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="demo-title" className="text-sm font-semibold">
          Explore demo scenario
        </h2>
        <span className="text-[11px] font-medium text-teal">
          Synthetic traffic · Real health pipeline
        </span>
      </div>
      <div
        className="my-3 flex flex-wrap gap-2"
        role="group"
        aria-label="Demo scenarios"
      >
        {demoScenarios.map((scenario, index) => (
          <button
            key={scenario.id}
            className={`button-secondary ${selected === index ? "border-teal bg-teal/5 ring-1 ring-teal" : ""}`}
            aria-pressed={selected === index}
            onClick={() => setSelected(index)}
          >
            {scenario.label}
          </button>
        ))}
      </div>
      <p className="text-sm leading-6 text-slate-600" aria-live="polite">
        {choice.description}
      </p>
      {available && (
        <Link
          className="mt-3 inline-flex text-xs font-semibold text-teal"
          href={`/integrations/${choice.id}`}
        >
          Explore {available.integration.name} →
        </Link>
      )}
      <p className="mt-3 text-xs text-slate-500">
        Traffic → Evidence → Incident → AI assistance → Human investigation →
        Recovery
      </p>
      <details
        className="mt-4 border-t border-slate-100 pt-3"
        open={!items.length || undefined}
      >
        <summary className="cursor-pointer text-xs font-semibold text-teal">
          Load demo scenario · Local setup
        </summary>
        <p className="mt-3 text-xs leading-5 text-slate-600">
          Stop npm run dev (Ctrl+C), then run the command below from the
          repository root. It creates a disposable demo database and starts the
          API on port 8000. Your connected database is not changed.
        </p>
        <code className="my-3 block overflow-x-auto rounded-lg bg-slate-50 p-3 text-xs">
          .venv/bin/python scripts/run_demo.py --scenario all
        </code>
        <p className="text-xs leading-5 text-slate-600">
          In a second terminal run <code>npm --prefix frontend run dev</code>,
          then open http://localhost:3000. The frontend must point to the local
          API on port 8000. Clear Workspace access if a saved-in-memory token
          belongs to your other database.
        </p>
        <p className="text-xs leading-5 text-slate-500">
          The all-scenario dataset includes healthy, unhealthy,
          insufficient-evidence and recovered integrations, with degradation
          visible in their history. To replay only this scenario, replace{" "}
          <code>all</code> with <code>{choice.scenario}</code>. Exploration
          links above open existing evidence; selecting a card does not generate
          traffic. Regenerate when telemetry ages out.
        </p>
      </details>
    </section>
  );
}
