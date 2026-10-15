"use client";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import {
  Activity,
  LayoutDashboard,
  ShieldCheck,
  KeyRound,
  ArrowUpRight,
} from "lucide-react";
import { setToken } from "@/lib/api";
export function Shell({
  children,
  onAuth,
}: {
  children: ReactNode;
  onAuth: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="border-r border-slate-200 bg-white p-6 lg:fixed lg:inset-y-0 lg:w-[232px]">
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
          className="mt-4 flex items-center gap-3 rounded-lg bg-teal/10 px-3 py-3 text-sm font-semibold text-teal"
        >
          <LayoutDashboard size={18} />
          Integration health
        </Link>
        <div className="mt-7 hidden text-xs leading-6 text-slate-500 lg:block">
          One operational view across your connected systems.
        </div>
        <div className="mt-8 space-y-3 lg:absolute lg:bottom-7 lg:left-6 lg:right-6">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <ShieldCheck size={16} />
            Rule-based health decisions
          </div>
          <button
            onClick={() => setEditing(!editing)}
            className="flex items-center gap-2 text-xs font-medium text-ink"
          >
            <KeyRound size={15} />
            Workspace access <ArrowUpRight size={12} />
          </button>
        </div>
      </aside>
      <div className="lg:col-start-2">
        <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white/80 px-6 text-xs text-slate-500 md:px-10">
          <span>
            Workspace <span className="mx-2 text-slate-300">/</span>
            <span className="font-medium text-ink">Integration operations</span>
          </span>
          <span className="rounded border border-slate-200 px-2 py-1">
            Brightline HR · MVP
          </span>
        </header>
        {editing && (
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
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="rounded border px-3 py-2"
              placeholder="Leave blank for local demo"
            />
            <button className="button">Connect</button>
            <p className="text-xs text-slate-500">
              Held in memory for this session. Refreshing the page clears
              access.
            </p>
          </form>
        )}
        <main className="mx-auto max-w-[1500px] p-6 md:p-10">{children}</main>
      </div>
    </div>
  );
}
