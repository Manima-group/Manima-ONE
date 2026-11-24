"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { FormDialog } from "@/components/form";
import { ConfirmButton, PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { date, dateTime, label } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type T = { id: string; legal_name: string; slug: string; status: string; plan: string | null; plan_key: string | null; subscription_status: string | null;
  trial_ends_at: string | null; created_at: string; members: number; modules: { key: string; name: string; state: string; changed_at: string }[];
  overrides: { feature_key: string; effect: string; reason: string; expires_at: string | null }[];
  members_list: { name: string; email: string; status: string; last_login_at: string | null }[] };

export default function TenantDetail() {
  const { id } = useParams<{ id: string }>();
  const { canPlatform } = useSession();
  const toast = useToast();
  const { data: t, error, loading, reload } = useQuery<T>(`/platform/tenants/${id}`);
  const plans = useQuery<{ key: string; name: string }[]>("/platform/plans");
  const [sub, setSub] = useState(false);
  const [ovr, setOvr] = useState<string | null>(null);
  if (loading && !t) return <Loading />;
  if (error || !t) return <ErrorState error={error} onRetry={reload} />;
  const overrides = Object.fromEntries(t.overrides.map((o) => [o.feature_key, o]));
  return (
    <>
      <PageHeader title={<span className="flex items-center gap-2">{t.legal_name} <StatusBadge status={t.status} /></span>} subtitle={`${t.slug} · created ${date(t.created_at)}`}
        crumbs={[{ label: "Platform" }, { label: "Tenants", href: "/admin/tenants" }, { label: t.legal_name }]}
        actions={canPlatform("platform.tenant.create") && (t.status === "active"
          ? <ConfirmButton label="Suspend" variant="danger" size="md" confirm="Suspend this tenant? Users keep read-only access to their data." onConfirm={async () => { await api.post(`/platform/tenants/${id}:suspend`, { reason: "suspended from admin" }); toast.success("Tenant suspended"); reload(); }} />
          : t.status === "suspended" && <Button onClick={async () => { await api.post(`/platform/tenants/${id}:reactivate`); toast.success("Tenant reactivated"); reload(); }}>Reactivate</Button>)} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="Subscription" action={canPlatform("platform.plan.manage") && <Button size="sm" variant="secondary" onClick={() => setSub(true)}>Change</Button>} />
          <dl className="divide-y divide-line text-sm">
            <div className="flex justify-between px-5 py-2.5"><dt className="text-muted">Plan</dt><dd>{t.plan ?? "—"}</dd></div>
            <div className="flex justify-between px-5 py-2.5"><dt className="text-muted">Status</dt><dd><StatusBadge status={t.subscription_status} /></dd></div>
            <div className="flex justify-between px-5 py-2.5"><dt className="text-muted">Trial ends</dt><dd>{date(t.trial_ends_at)}</dd></div>
            <div className="flex justify-between px-5 py-2.5"><dt className="text-muted">Users</dt><dd>{t.members}</dd></div>
          </dl>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="Modules & entitlement overrides" subtitle="Overrides grant a module outside the plan (e.g. trial) or revoke it." />
          <table className="w-full text-sm">
            <thead className="bg-canvas text-left text-xs uppercase text-muted"><tr><th className="px-4 py-2">Module</th><th className="px-4 py-2">Tenant state</th><th className="px-4 py-2">Override</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {t.modules.map((m) => (
                <tr key={m.key}>
                  <td className="px-4 py-2">{m.name}</td><td className="px-4 py-2"><StatusBadge status={m.state} /></td>
                  <td className="px-4 py-2">{overrides[m.key] ? <Badge tone={overrides[m.key].effect === "grant" ? "green" : "red"}>{overrides[m.key].effect}{overrides[m.key].expires_at ? ` until ${date(overrides[m.key].expires_at)}` : ""}</Badge> : "—"}</td>
                  <td className="px-4 py-2 text-right">{canPlatform("platform.override.manage") && (overrides[m.key]
                    ? <Button size="sm" variant="ghost" onClick={async () => { await api.del(`/platform/tenants/${id}/features/${m.key}`); toast.success("Override removed"); reload(); }}>Remove override</Button>
                    : <Button size="sm" variant="ghost" onClick={() => setOvr(m.key)}>Override</Button>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card className="lg:col-span-3">
          <CardHeader title="Users" subtitle="Identity metadata only — tenant business data is not visible to platform staff." />
          <ul className="divide-y divide-line text-sm">
            {t.members_list.map((u) => (
              <li key={u.email} className="flex justify-between px-5 py-2.5"><span>{u.name} <span className="text-muted">· {u.email}</span></span>
                <span className="flex items-center gap-3 text-xs text-muted">last sign-in {dateTime(u.last_login_at)} <StatusBadge status={u.status} /></span></li>
            ))}
          </ul>
        </Card>
      </div>
      <FormDialog open={sub} onClose={() => setSub(false)} title="Change subscription" submitLabel="Apply"
        fields={[
          { name: "plan_key", label: "Plan", type: "select", required: true, options: (plans.data ?? []).map((p) => ({ value: p.key, label: p.name })) },
          { name: "status", label: "Status", type: "select", required: true, options: ["trialing", "active", "past_due", "grace", "suspended", "cancelled"].map((s) => ({ value: s, label: label(s) })) },
          { name: "trial_days", label: "Trial days (if trialing)", type: "number" },
        ]}
        initial={{ plan_key: t.plan_key, status: t.subscription_status ?? "active" }}
        submit={async (v) => { await api.post(`/platform/tenants/${id}/subscription`, { ...v, trial_days: v.trial_days ? Number(v.trial_days) : null }); toast.success("Subscription updated"); reload(); }} />
      <FormDialog open={!!ovr} onClose={() => setOvr(null)} title={`Override: ${ovr}`} submitLabel="Save override"
        fields={[
          { name: "effect", label: "Effect", type: "select", required: true, options: [{ value: "grant", label: "Grant (e.g. trial)" }, { value: "revoke", label: "Revoke" }] },
          { name: "expires_at", label: "Expires", type: "datetime" },
          { name: "reason", label: "Reason", required: true, type: "textarea" },
        ]}
        initial={{ effect: "grant" }}
        submit={async (v) => { await api.put(`/platform/tenants/${id}/features/${ovr}`, v); toast.success("Override saved"); reload(); }} />
    </>
  );
}
