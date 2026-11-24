"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api";

export type Membership = { tenant_id: string; slug: string; name: string; status: string; roles: string[] };
export type ModuleCap = { state: string; entitled: boolean; writable: boolean; reason: string | null };
export type Me = {
  user: { id: string; email: string; name: string; phone: string | null };
  platform_permissions: string[];
  memberships: Membership[];
  active_tenant: { id: string; slug: string; name: string; status: string; display_name: string; membership_id: string } | null;
  permissions: string[];
  capabilities: { modules: Record<string, ModuleCap>; permissions: string[] } | null;
};

type Ctx = {
  me: Me | null;
  loading: boolean;
  error: ApiError | null;
  refresh: () => Promise<Me | null>;
  setMe: (m: Me | null) => void;
  can: (...perms: string[]) => boolean;
  canPlatform: (perm: string) => boolean;
  moduleOn: (key: string) => boolean;
  writable: (key: string) => boolean;
  switchTenant: (id: string) => Promise<void>;
  logout: () => Promise<void>;
};

const SessionCtx = createContext<Ctx | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const refresh = useCallback(async () => {
    try {
      const m = await api.get<Me>("/me");
      setMe(m);
      setError(null);
      return m;
    } catch (e) {
      setMe(null);
      setError(e as ApiError);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let live = true;
    api
      .get<Me>("/me")
      .then((m) => live && (setMe(m), setError(null)))
      .catch((e) => live && (setMe(null), setError(e as ApiError)))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, []);

  const value = useMemo<Ctx>(() => {
    const perms = new Set(me?.permissions ?? []);
    const pperms = new Set(me?.platform_permissions ?? []);
    return {
      me,
      loading,
      error,
      refresh,
      setMe,
      can: (...p) => p.some((x) => perms.has(x)),
      canPlatform: (p) => pperms.has(p),
      moduleOn: (k) => {
        const c = me?.capabilities?.modules[k];
        return !!c && (c.state !== "disabled" || c.writable);
      },
      writable: (k) => !!me?.capabilities?.modules[k]?.writable,
      switchTenant: async (id) => {
        const m = await api.post<Me>("/session/switch-tenant", { tenant_id: id });
        setMe(m);
        // Full reload on purpose: drops every client cache of the previous tenant's data.
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        window.location.href = "/dashboard";
      },
      logout: async () => {
        try {
          await api.post("/auth/logout");
        } finally {
          setMe(null);
          // Full reload on purpose: no signed-in state may survive logout.
          // eslint-disable-next-line @next/next/no-location-assign-relative-destination
          window.location.href = "/login";
        }
      },
    };
  }, [me, loading, error, refresh]);

  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}

export function useSession() {
  const c = useContext(SessionCtx);
  if (!c) throw new Error("useSession outside SessionProvider");
  return c;
}
