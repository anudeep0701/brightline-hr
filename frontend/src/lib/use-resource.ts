"use client";
import { useCallback, useEffect, useRef, useState } from "react";

/** Poll with cancellation: old tenant/navigation responses never overwrite a new scope. */
export function useResource<T>(loader: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [fetching, setFetching] = useState(true);
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [checkedAt, setCheckedAt] = useState(0);
  const run = useRef<() => Promise<void>>(async () => {});
  useEffect(() => {
    let disposed = false;
    let controller: AbortController | null = null;
    setData(null);
    setError("");
    setLoadedAt(null);
    async function load() {
      if (disposed) return;
      controller?.abort();
      const current = new AbortController();
      controller = current;
      setFetching(true);
      setCheckedAt(Date.now());
      try {
        const next = await loader(current.signal);
        if (!disposed && !current.signal.aborted) {
          setData(next);
          setError("");
          setLoadedAt(Date.now());
        }
      } catch (e) {
        if (!disposed && !current.signal.aborted)
          setError(
            e instanceof Error ? e.message : "Unable to connect to telemetry.",
          );
      } finally {
        if (!disposed && !current.signal.aborted) setFetching(false);
      }
    }
    run.current = load;
    void load();
    const timer = setInterval(() => void load(), 60000);
    return () => {
      disposed = true;
      controller?.abort();
      clearInterval(timer);
    };
  }, [loader]);
  const reload = useCallback(() => run.current(), []);
  return { data, error, fetching, loadedAt, checkedAt, reload };
}
