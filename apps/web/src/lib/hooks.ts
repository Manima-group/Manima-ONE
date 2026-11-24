"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

export function useQuery<T>(url: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [tick, setTick] = useState(0);
  // Loading is derived: true until the response for the current request key has settled.
  const key = url ? `${url}#${tick}#${JSON.stringify(deps)}` : null;
  const [settledKey, setSettledKey] = useState<string | null>(null);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!url || !key) return;
    const ctl = new AbortController();
    api
      .get<T>(url, { signal: ctl.signal })
      .then((d) => {
        setData(d);
        setError(null);
        setSettledKey(key);
      })
      .catch((e) => {
        if ((e as Error).name === "AbortError") return;
        setError(e as ApiError);
        setSettledKey(key);
      });
    return () => ctl.abort();
  }, [url, key]);

  return { data, error, loading: !!key && settledKey !== key, reload, setData };
}

export function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function useMutation<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  const run = useCallback(async (...args: A): Promise<R | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fnRef.current(...args);
    } catch (e) {
      setError(e as ApiError);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { run, busy, error, setError };
}
