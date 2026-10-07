"use client";

import { useEffect, useState } from "react";
import { REFRESH_EVENT } from "./api";

/**
 * Fetch `fn` now and every `intervalMs`; also refetch on the global refresh event.
 * `fn` is re-captured whenever `deps` change (callers remount views via `key` on route change).
 */
export function usePoll<T>(fn: () => Promise<T>, deps: unknown[], intervalMs = 2000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const result = await fn();
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };
    load();
    const timer = setInterval(load, intervalMs);
    window.addEventListener(REFRESH_EVENT, load);
    return () => {
      cancelled = true;
      clearInterval(timer);
      window.removeEventListener(REFRESH_EVENT, load);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error };
}
