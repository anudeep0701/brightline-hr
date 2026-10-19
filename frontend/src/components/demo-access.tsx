"use client";

import { useEffect, useState, type ReactNode } from "react";
import { api, setDemoAccess } from "@/lib/api";
import { LoadingState } from "@/components/async-state";
import { DemoAccessContext, DemoImportContext } from "@/lib/demo-context";

export function DemoAccess({ children }: { children: ReactNode }) {
  const [state, setState] = useState<
    "loading" | "demo" | "workspace" | "error"
  >("loading");
  const [attempt, setAttempt] = useState(0);
  const [allowImport, setAllowImport] = useState(false);
  useEffect(() => {
    let disposed = false;
    let renewal: ReturnType<typeof setInterval> | undefined;
    const controller = new AbortController();
    async function open() {
      setState("loading");
      try {
        const config = await api<{
          demo_mode: boolean;
          demo_allow_file_import?: boolean;
        }>("/api/demo/session", "GET", controller.signal);
        if (!config.demo_mode) {
          setDemoAccess(false);
          if (!disposed) setState("workspace");
          return;
        }
        await api("/api/demo/session", "POST", controller.signal);
        if (disposed) return;
        setDemoAccess(true);
        setAllowImport(!!config.demo_allow_file_import);
        setState("demo");
        // Renew while visible. Every issued cookie still expires in one hour.
        renewal = setInterval(
          () => {
            if (document.visibilityState !== "visible") return;
            void api("/api/demo/session", "POST", controller.signal).catch(
              () => {
                if (!disposed) setState("error");
              },
            );
          },
          20 * 60 * 1000,
        );
      } catch {
        if (!disposed) setState("error");
      }
    }
    void open();
    return () => {
      disposed = true;
      controller.abort();
      clearInterval(renewal);
    };
  }, [attempt]);
  if (state === "loading")
    return (
      <main className="mx-auto max-w-xl p-8">
        <LoadingState label="Opening operations workspace…" />
      </main>
    );
  if (state === "error")
    return (
      <main className="mx-auto max-w-xl p-8">
        <div role="alert" className="card p-6">
          <h1 className="font-semibold">Workspace could not be opened</h1>
          <p className="my-3 text-sm text-slate-600">
            Check the connection and retry. If this persists, ask the deployment
            owner to verify the demo workspace configuration.
          </p>
          <button
            className="button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            Retry
          </button>
        </div>
      </main>
    );
  return (
    <DemoAccessContext.Provider value={state === "demo"}>
      <DemoImportContext.Provider value={state === "demo" && allowImport}>
        {children}
      </DemoImportContext.Provider>
    </DemoAccessContext.Provider>
  );
}
