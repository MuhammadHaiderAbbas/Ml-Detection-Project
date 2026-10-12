import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> { data: T | undefined; error: Error | undefined; loading: boolean; reload: () => void }

/** Fetch on mount and whenever `deps` change. Keeps the previous data while refetching (no skeleton flash). */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[], opts: { pollMs?: number } = {}): ApiState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fnRef.current()
      .then((d) => { if (!cancelled) { setData(d); setError(undefined); } })
      .catch((e: Error) => { if (!cancelled) setError(e); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  useEffect(() => {
    if (!opts.pollMs) return;
    const id = window.setInterval(reload, opts.pollMs);
    return () => window.clearInterval(id);
  }, [opts.pollMs, reload]);

  return { data, error, loading, reload };
}
