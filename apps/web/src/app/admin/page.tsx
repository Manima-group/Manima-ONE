"use client";

import Link from "next/link";
import { PageHeader } from "@/components/page";
import { Card, CardHeader, ErrorState, Loading, Stat, StatusBadge } from "@/components/ui";
import { date, money } from "@/lib/format";
import { useQuery } from "@/lib/hooks";

type D = { tenants: { total: number; by_status: Record<string, number> }; subscriptions: Record<string, number>; mrr: string; users: number;
  module_usage: Record<string, number>; signups_30d: { day: string; count: number }[]; pending_plan_changes: number;
  recent_tenants: { id: string; legal_name: string; status: string; plan: string | null; members: number; created_at: string }[] };

export default function AdminDashboard() {
  const { data: d, error, loading, reload } = useQuery<D>("/platform/dashboard");
  if (loading && !d) return <Loading />;
  if (error || !d) return <ErrorState error={error} onRetry={reload} />;
  const maxMod = Math.max(1, ...Object.values(d.module_usage));
  return (
    <>
      <PageHeader title="Platform dashboard" crumbs={[{ label: "Platform" }, { label: "Dashboard" }]} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Tenants" value={d.tenants.total} hint={`${d.tenants.by_status.active ?? 0} active · ${d.tenants.by_status.suspended ?? 0} suspended`} />
        <Stat label="MRR (active subs)" value={money(d.mrr)} tone="brand" />
        <Stat label="Users" value={d.users} hint={`${d.subscriptions.trialing ?? 0} tenants on trial`} />
        <Stat label="Plan change requests" value={d.pending_plan_changes} hint={<Link href="/admin/plans" className="text-brand hover:underline">Review</Link>} tone={d.pending_plan_changes ? "brand" : undefined} />
      </div>
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Recent tenants" action={<Link href="/admin/tenants" className="text-xs text-brand">All tenants</Link>} />
          <ul className="divide-y divide-line text-sm">
            {d.recent_tenants.map((t) => (
              <li key={t.id} className="flex items-center justify-between px-5 py-2.5">
                <div><Link href={`/admin/tenants/${t.id}`} className="font-medium hover:text-brand">{t.legal_name}</Link><p className="text-xs text-muted">{t.plan ?? "No plan"} · {t.members} users · {date(t.created_at)}</p></div>
                <StatusBadge status={t.status} />
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader title="Module adoption (tenants enabled)" />
          <div className="space-y-2 p-5">
            {Object.entries(d.module_usage).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <div key={k} className="flex items-center gap-3 text-sm">
                <span className="w-32 capitalize text-muted">{k.replace("_", " ")}</span>
                <div className="h-2 flex-1 rounded-full bg-canvas"><div className="h-2 rounded-full bg-brand" style={{ width: `${(v / maxMod) * 100}%` }} /></div>
                <span className="w-8 text-right tabular-nums">{v}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
