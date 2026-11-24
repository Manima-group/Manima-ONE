"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Badge, Button, Card, CardHeader, Checkbox, Dialog, ErrorState, Field, Input, Loading, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { date, money } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Plan = { id: string; key: string; name: string; description: string | null; price_monthly: string; max_users: number | null; active: boolean; modules: string[]; tenants: number };
type Change = { id: string; tenant: string; from_plan: string; to_plan: string; status: string; created_at: string; note: string | null };
type Form = { id?: string; key: string; name: string; description: string; price_monthly: string; max_users: string; active: boolean; modules: string[] };

export default function Plans() {
  const { canPlatform } = useSession();
  const toast = useToast();
  const plans = useQuery<Plan[]>("/platform/plans");
  const mods = useQuery<{ key: string; name: string; kind: string }[]>("/platform/modules");
  const changes = useQuery<Change[]>("/platform/plan-changes");
  const [f, setF] = useState<Form | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const manage = canPlatform("platform.plan.manage");
  if (plans.loading && !plans.data) return <Loading />;
  if (plans.error) return <ErrorState error={plans.error} />;
  const save = async () => {
    try {
      setErr(null);
      const body = { ...f!, max_users: f!.max_users ? Number(f!.max_users) : null, description: f!.description || null };
      if (f!.id) await api.patch(`/platform/plans/${f!.id}`, body); else await api.post("/platform/plans", body);
      toast.success("Plan saved"); setF(null); plans.reload();
    } catch (e) { setErr((e as ApiError).message); }
  };
  const decide = async (id: string, d: string) => { try { await api.post(`/platform/plan-changes/${id}:${d}`); toast.success(`Request ${d}d`); changes.reload(); plans.reload(); } catch (e) { toast.error(e); } };
  return (
    <>
      <PageHeader title="Subscription plans" crumbs={[{ label: "Platform" }, { label: "Plans" }]}
        actions={manage && <Button onClick={() => { setErr(null); setF({ key: "", name: "", description: "", price_monthly: "0", max_users: "", active: true, modules: [] }); }}><Plus className="h-4 w-4" />New plan</Button>} />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {plans.data!.map((p) => (
          <Card key={p.id} className="p-4">
            <div className="flex items-center justify-between"><p className="font-semibold">{p.name}</p>{!p.active && <Badge>inactive</Badge>}</div>
            <p className="text-xs text-muted">{p.key}</p>
            <p className="mt-2 text-2xl font-semibold">{money(p.price_monthly)}<span className="text-sm font-normal text-muted">/mo</span></p>
            <p className="text-sm text-muted">{p.max_users ? `${p.max_users} users` : "Unlimited users"} · {p.tenants} tenants</p>
            <div className="mt-2 flex flex-wrap gap-1">{p.modules.map((m) => <Badge key={m}>{m}</Badge>)}</div>
            {manage && <Button size="sm" variant="secondary" className="mt-3" onClick={() => { setErr(null); setF({ ...p, description: p.description ?? "", max_users: p.max_users ? String(p.max_users) : "" }); }}>Edit</Button>}
          </Card>
        ))}
      </div>
      <Card className="mt-6">
        <CardHeader title="Plan change requests" />
        {!changes.data?.length ? <p className="px-5 py-4 text-sm text-muted">No requests.</p> : (
          <ul className="divide-y divide-line text-sm">
            {changes.data.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-2.5">
                <span><b>{c.tenant}</b>: {c.from_plan} → {c.to_plan} <span className="text-xs text-muted">· {date(c.created_at)}</span></span>
                <span className="flex items-center gap-2"><StatusBadge status={c.status} />
                  {c.status === "requested" && manage && <><Button size="sm" onClick={() => decide(c.id, "approve")}>Approve</Button><Button size="sm" variant="ghost" onClick={() => decide(c.id, "reject")}>Reject</Button></>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Dialog open={!!f} onClose={() => setF(null)} title={f?.id ? "Edit plan" : "New plan"} wide
        footer={<><Button variant="secondary" onClick={() => setF(null)}>Cancel</Button><Button onClick={save}>Save plan</Button></>}>
        {f && <div className="space-y-4">
          {err && <Alert tone="red">{err}</Alert>}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Key" required hint="lowercase, e.g. growth"><Input value={f.key} disabled={!!f.id} onChange={(e) => setF({ ...f, key: e.target.value })} /></Field>
            <Field label="Name" required><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Price / month (₹)" required><Input type="number" value={f.price_monthly} onChange={(e) => setF({ ...f, price_monthly: e.target.value })} /></Field>
            <Field label="Max users" hint="Empty = unlimited"><Input type="number" value={f.max_users} onChange={(e) => setF({ ...f, max_users: e.target.value })} /></Field>
          </div>
          <Field label="Description"><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <Checkbox label="Active (available to tenants)" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} />
          <div><p className="mb-2 text-sm font-medium">Included modules</p>
            <div className="grid grid-cols-2 gap-2">{(mods.data ?? []).filter((m) => m.kind !== "core").map((m) => (
              <Checkbox key={m.key} label={m.name} checked={f.modules.includes(m.key)} onChange={(e) => setF({ ...f, modules: e.target.checked ? [...f.modules, m.key] : f.modules.filter((x) => x !== m.key) })} />
            ))}</div></div>
        </div>}
      </Dialog>
    </>
  );
}
