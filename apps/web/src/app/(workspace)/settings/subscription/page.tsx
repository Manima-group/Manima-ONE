"use client";

import { Check } from "lucide-react";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Badge, Button, Card, CardHeader, ErrorState, Loading, StatusBadge, cn } from "@/components/ui";
import { api } from "@/lib/api";
import { date, money } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Sub = {
  subscription: { status: string; trial_ends_at: string | null; current_period_end: string | null } | null;
  plan: { key: string; name: string; price_monthly: string; max_users: number | null } | null;
  usage: { seats_used: number; seats_limit: number | null };
  plans: { id: string; key: string; name: string; description: string; price_monthly: string; max_users: number | null; modules: string[] }[];
  pending_change: { to_plan_id: string; created_at: string } | null;
};

export default function Subscription() {
  const { can } = useSession();
  const toast = useToast();
  const { data, error, loading, reload } = useQuery<Sub>("/tenant/subscription");
  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorState error={error} onRetry={reload} />;
  const pct = data.usage.seats_limit ? Math.min(100, (data.usage.seats_used / data.usage.seats_limit) * 100) : 0;
  const pendingName = data.plans.find((p) => p.id === data.pending_change?.to_plan_id)?.name;
  return (
    <>
      <PageHeader title="Subscription" crumbs={[{ label: "Settings" }, { label: "Subscription" }]} />
      {pendingName && <div className="mb-4"><Alert>Plan change to <b>{pendingName}</b> requested on {date(data.pending_change!.created_at)} — awaiting confirmation by Manima.</Alert></div>}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card className="p-4"><p className="text-xs uppercase text-muted">Current plan</p><p className="mt-1 text-xl font-semibold">{data.plan?.name ?? "None"}</p>
          <p className="text-sm text-muted">{data.plan ? `${money(data.plan.price_monthly)} / month` : ""}</p></Card>
        <Card className="p-4"><p className="text-xs uppercase text-muted">Status</p><div className="mt-2"><StatusBadge status={data.subscription?.status} /></div>
          <p className="mt-1 text-sm text-muted">{data.subscription?.status === "trialing" ? `Trial ends ${date(data.subscription.trial_ends_at)}` : `Renews ${date(data.subscription?.current_period_end)}`}</p></Card>
        <Card className="p-4"><p className="text-xs uppercase text-muted">Users</p><p className="mt-1 text-xl font-semibold">{data.usage.seats_used} / {data.usage.seats_limit ?? "∞"}</p>
          {data.usage.seats_limit && <div className="mt-2 h-2 rounded-full bg-canvas"><div className="h-2 rounded-full bg-brand" style={{ width: `${pct}%` }} /></div>}</Card>
      </div>
      <Card className="mt-6">
        <CardHeader title="Plans" subtitle="Plan changes are confirmed by Manima billing; you'll see the change here once applied." />
        <div className="grid grid-cols-1 gap-4 p-5 md:grid-cols-3">
          {data.plans.map((p) => {
            const current = p.key === data.plan?.key;
            return (
              <div key={p.id} className={cn("rounded-lg border p-4", current ? "border-brand bg-brand-soft/40" : "border-line")}>
                <div className="flex items-center justify-between"><p className="font-semibold">{p.name}</p>{current && <Badge tone="orange">current</Badge>}</div>
                <p className="mt-1 text-2xl font-semibold">{money(p.price_monthly).replace(".00", "")}<span className="text-sm font-normal text-muted">/mo</span></p>
                <p className="mt-1 text-sm text-muted">{p.description}</p>
                <ul className="mt-3 space-y-1 text-sm">
                  <li className="flex gap-2"><Check className="h-4 w-4 text-brand" />{p.max_users ? `Up to ${p.max_users} users` : "Unlimited users"}</li>
                  {p.modules.map((m) => <li key={m} className="flex gap-2 capitalize"><Check className="h-4 w-4 text-brand" />{m.replace("_", " ")}</li>)}
                </ul>
                {!current && can("core.billing.read") && (
                  <Button className="mt-4 w-full" variant="outline" disabled={!!data.pending_change}
                    onClick={async () => { try { await api.post("/tenant/subscription:request-change", { plan_key: p.key }); toast.success("Plan change requested"); reload(); } catch (e) { toast.error(e); } }}>
                    Request {Number(p.price_monthly) > Number(data.plan?.price_monthly ?? 0) ? "upgrade" : "change"}
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    </>
  );
}
