export function ErrorNotice({
  message,
  retained,
  retry,
}: {
  message: string;
  retained?: boolean;
  retry: () => void;
}) {
  return (
    <div
      role="alert"
      className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"
    >
      <div>
        <p className="font-semibold">Telemetry could not be refreshed</p>
        <p className="mt-1">{message}</p>
        <p className="mt-1 text-xs">
          {retained
            ? "Showing the last fetched evidence. Check evaluation timestamps before acting."
            : "Check the backend connection or connect a workspace token using Workspace access."}
        </p>
      </div>
      <button className="button-secondary" onClick={retry}>
        Try again
      </button>
    </div>
  );
}
export function LoadingState({
  label = "Loading integration telemetry…",
}: {
  label?: string;
}) {
  return (
    <div role="status" className="card p-8">
      <p className="text-sm font-medium">{label}</p>
      <div aria-hidden="true" className="mt-6 space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-8 rounded bg-slate-100" />
        ))}
      </div>
    </div>
  );
}
