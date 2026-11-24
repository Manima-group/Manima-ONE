"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { FormDialog, type FieldDef } from "@/components/form";
import { ModuleBanner, PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Button, Card, ErrorState, Loading, Select, Tabs } from "@/components/ui";
import { DataTable } from "@/components/data-table";
import { api, type Page } from "@/lib/api";
import { date, money } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Stage = { id: string; name: string; outcome: string; probability: number };
type Pipeline = { id: string; name: string; stages: Stage[] };
type Opp = { id: string; name: string; account_id: string; account_name: string; stage_id: string; stage_name: string; value: string;
  expected_close: string | null; status: string; version: number };

const FIELDS = (stages: Stage[]): FieldDef[] => [
  { name: "name", label: "Opportunity name", required: true, colSpan: 2 },
  { name: "account_id", label: "Customer", type: "remote", endpoint: "/crm/accounts", required: true },
  { name: "stage_id", label: "Stage", type: "select", required: true, options: stages.map((s) => ({ value: s.id, label: s.name })) },
  { name: "value", label: "Value (₹)", type: "money" },
  { name: "expected_close", label: "Expected close", type: "date" },
  { name: "owner_id", label: "Owner", type: "member", placeholder: "Me" },
];

export default function OpportunitiesPage() {
  const { can, writable } = useSession();
  const toast = useToast();
  const [view, setView] = useState("board");
  const [open, setOpen] = useState(false);
  const pipes = useQuery<Pipeline[]>("/crm/pipelines");
  const opps = useQuery<Page<Opp>>("/crm/opportunities?limit=200&status=open");
  if (pipes.loading && !pipes.data) return <Loading />;
  if (pipes.error) return <ErrorState error={pipes.error} />;
  const stages = pipes.data?.[0]?.stages ?? [];
  const canEdit = can("crm.opportunity.update") && writable("crm");
  const move = async (o: Opp, stage_id: string) => {
    try { await api.patch(`/crm/opportunities/${o.id}`, { stage_id, version: o.version }); opps.reload(); toast.success("Stage updated"); }
    catch (e) { toast.error(e); }
  };
  return (
    <>
      <PageHeader title="Pipeline" crumbs={[{ label: "CRM" }, { label: "Pipeline" }]}
        actions={can("crm.opportunity.create") && writable("crm") && <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" />New opportunity</Button>} />
      <ModuleBanner module="crm" />
      <div className="mb-4"><Tabs tabs={[{ key: "board", label: "Board" }, { key: "list", label: "All opportunities" }]} value={view} onChange={setView} /></div>
      {view === "board" ? (
        <div className="flex gap-4 overflow-x-auto pb-2">
          {stages.filter((s) => s.outcome === "open").map((s) => {
            const items = (opps.data?.data ?? []).filter((o) => o.stage_id === s.id);
            const total = items.reduce((a, o) => a + Number(o.value), 0);
            return (
              <div key={s.id} className="w-72 shrink-0">
                <div className="mb-2 flex items-baseline justify-between px-1">
                  <span className="text-sm font-semibold">{s.name} <span className="font-normal text-muted">({items.length})</span></span>
                  <span className="text-xs text-muted">{money(total)}</span>
                </div>
                <div className="space-y-2 rounded-lg bg-gray-100/70 p-2">
                  {!items.length && <p className="px-2 py-6 text-center text-xs text-muted">No deals</p>}
                  {items.map((o) => (
                    <Card key={o.id} className="p-3">
                      <p className="text-sm font-medium">{o.name}</p>
                      <Link href={`/crm/accounts/${o.account_id}`} className="text-xs text-muted hover:text-brand">{o.account_name}</Link>
                      <div className="mt-2 flex items-center justify-between text-xs">
                        <span className="font-semibold text-ink">{money(o.value)}</span>
                        <span className="text-muted">{o.expected_close ? date(o.expected_close) : ""}</span>
                      </div>
                      {canEdit && (
                        <Select className="mt-2 h-8 text-xs" value={o.stage_id} aria-label="Move to stage" onChange={(e) => move(o, e.target.value)}>
                          {stages.map((st) => <option key={st.id} value={st.id}>{st.outcome === "open" ? `Move: ${st.name}` : `Mark ${st.name}`}</option>)}
                        </Select>
                      )}
                    </Card>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <DataTable<Opp> endpoint="/crm/opportunities"
          filters={[{ key: "status", label: "Status", options: ["open", "won", "lost"].map((v) => ({ value: v, label: v })) }]}
          columns={[{ key: "name", header: "Opportunity", render: (r) => <span className="font-medium">{r.name}</span> },
            { key: "account_name", header: "Customer" }, { key: "stage_name", header: "Stage" },
            { key: "expected_close", header: "Expected close", render: (r) => date(r.expected_close) },
            { key: "value", header: "Value", align: "right", render: (r) => money(r.value) }]} />
      )}
      <FormDialog open={open} onClose={() => setOpen(false)} title="New opportunity" fields={FIELDS(stages)} initial={{ stage_id: stages[0]?.id, value: "0" }}
        submit={async (v) => { await api.post("/crm/opportunities", v); toast.success("Opportunity created"); opps.reload(); }} />
    </>
  );
}
