import { useState, useCallback } from "react";

const API_BASE = "/api";

export function useApi() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchApi = useCallback(
    async <T>(path: string, options?: RequestInit): Promise<T | null> => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}${path}`, {
          headers: { "Content-Type": "application/json" },
          ...options,
        });
        if (!res.ok) {
          throw new Error(`${res.status}: ${res.statusText}`);
        }
        const data = await res.json();
        return data as T;
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Unknown error";
        setError(msg);
        return null;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const get = useCallback(
    <T>(path: string) => fetchApi<T>(path),
    [fetchApi]
  );

  const post = useCallback(
    <T>(path: string, body?: unknown) =>
      fetchApi<T>(path, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      }),
    [fetchApi]
  );

  return { get, post, loading, error };
}
