"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import {
  Activity,
  LayoutDashboard,
  ShieldCheck,
  KeyRound,
  ArrowUpRight,
} from "lucide-react";
import { setToken } from "@/lib/api";
import { useDemoAccess } from "@/lib/demo-context";
export function Shell({
  children,
  onAuth,
  tenantName,
}: {
  children: ReactNode;
  onAuth: () => void;
  tenantName?: string;
}) {
  const dataSourcesActive = usePathname() === "/data-sources";
  const demo = useDemoAccess();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="flex flex-wrap items-center justify-between gap-3 border-r border-b border-slate-200 bg-white p-4 lg:fixed lg:inset-y-0 lg:block lg:w-[232px] lg:border-b-0 lg:p-6">
        <Link
          href="/"
          className="flex items-center gap-2.5 text-xl font-bold tracking-tight"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-ink text-white">
            <Activity size={21} />
          </span>
          brightline<span className="text-xs text-teal">HR</span>
        </Link>
        <div className="mt-10 hidden text-[10px] font-bold uppercase tracking-[.2em] text-slate-400 lg:block">
          Operations workspace
        </div>
        <Link
          href="/"
          aria-current={!dataSourcesActive ? "page" : undefined}
          className={`mt-4 flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-semibold ${!dataSourcesActive ? "bg-teal/10 text-teal" : "text-slate-600 hover:bg-slate-50"}`}
        >
          <LayoutDashboard size={18} />
          Overview
        </Link>
        <Link
          href="/data-sources"
          aria-current={dataSourcesActive ? "page" : undefined}
          className={`mt-3 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${dataSourcesActive ? "bg-teal/10 text-teal" : "text-slate-600 hover:bg-slate-50"}`}
        >
          Data sources
        </Link>
        <div className="mt-7 hidden text-xs leading-6 text-slate-500 lg:block">
          One operational view across your connected systems.
        </div>
        <div className="lg:mt-8 lg:space-y-3 lg:absolute lg:bottom-7 lg:left-6 lg:right-6">
          <div className="hidden items-center gap-2 text-xs text-slate-500 lg:flex">
            <ShieldCheck size={16} />
            Evidence-based decisions
          </div>
          {demo ? (
            <span className="text-xs font-medium text-teal">
              Demo workspace · Synthetic telemetry
            </span>
          ) : (
            <button
              onClick={() => setEditing(!editing)}
              className="flex items-center gap-2 text-xs font-medium text-ink"
            >
              <KeyRound size={15} />
              Workspace access <ArrowUpRight size={12} />
            </button>
          )}
        </div>
      </aside>
      <div className="min-w-0 lg:col-start-2">
        <header className="flex h-12 items-center justify-between gap-3 md:h-16 border-b border-slate-200 bg-white/80 px-6 text-xs text-slate-500 md:px-10">
          <span className="min-w-0 truncate">
            Workspace <span className="mx-2 text-slate-300">/</span>
            <span className="font-medium text-ink">
              {tenantName ?? "Integration operations"}
            </span>
          </span>
          <span className="hidden shrink-0 rounded border border-slate-200 px-2 py-1 sm:inline">
            Observe · Advise · Human acts
          </span>
        </header>
        {editing && !demo && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setToken(value);
              setValue("");
              setEditing(false);
              onAuth();
            }}
            className="flex flex-wrap items-center gap-3 border-b bg-white p-5"
          >
            <label htmlFor="token" className="text-sm">
              Workspace bearer token
            </label>
            <input
              id="token"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="rounded border px-3 py-2"
              placeholder="Paste workspace token"
            />
            <button className="button">Connect</button>
            <p className="text-xs text-slate-500">
              Workspace token only; never an OpenAI key. Held in memory.
              Refreshing the page clears access.
            </p>
          </form>
        )}
        <main className="mx-auto max-w-[1500px] p-4 sm:p-6 md:p-10">
          {children}
        </main>
      </div>
    </div>
  );
}
