"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ActivityPanel } from "@/components/activity-panel";
import { FormDialog, type FieldDef } from "@/components/form";
import { ConfirmButton, ModuleBanner, PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, CardHeader, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { date, label, money } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { LEAD_FIELDS } from "@/features/fields";

type Lead = Record<string, unknown> & {
  id: string; name: string; company: string | null; email: string | null; phone: string | null; status: string; source: string;
  estimated_value: string; score: number; notes: string | null; owner_id: string | null; converted_account_id: string | null;
  lost_reason: string | null; created_at: string; duplicates: { id: string; name: string; status: string }[];
};

const CONVERT: FieldDef[] = [
  { name: "account_name", label: "Customer name", hint: "Defaults to the lead's company" },
  { name: "existing_account_id", label: "…or link to existing customer", type: "remote", endpoint: "/crm/accounts" },
  { name: "create_opportunity", label: "Create an opportunity", type: "checkbox" },
  { name: "opportunity_value", label: "Opportunity value (₹)", type: "money", hidden: (v) => !v.create_opportunity },
];

export default function LeadDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { can, writable } = useSession();
  const { data: lead, error, loading, reload } = useQuery<Lead>(`/crm/leads/${id}`);
  const [edit, setEdit] = useState(false);
  const [convert, setConvert] = useState(false);
  if (loading && !lead) return <Loading />;
  if (error || !lead) return <ErrorState error={error} onRetry={reload} />;
  const w = writable("crm");
  const open = lead.status !== "converted";
  return (
    <>
      <PageHeader title={lead.name} subtitle={lead.company} crumbs={[{ label: "CRM" }, { label: "Leads", href: "/crm/leads" }, { label: lead.name }]}
        actions={w && open && <>
          {can("crm.lead.update") && <Button variant="secondary" onClick={() => setEdit(true)}>Edit</Button>}
          {can("crm.lead.convert") && <Button onClick={() => setConvert(true)}>Convert</Button>}
          {can("crm.lead.delete") && <ConfirmButton label="Delete" variant="danger" size="md" confirm="Delete this lead?"
            onConfirm={async () => { await api.del(`/crm/leads/${id}`); toast.success("Lead deleted"); router.push("/crm/leads"); }} />}
        </>} />
      <ModuleBanner module="crm" />
      {lead.duplicates.length > 0 && open && (
        <div className="mb-4"><Alert>Possible duplicates: {lead.duplicates.map((d, i) => <span key={d.id}>{i > 0 && ", "}<Link className="underline" href={`/crm/leads/${d.id}`}>{d.name}</Link> ({d.status})</span>)}</Alert></div>
      )}
      {lead.converted_account_id && (
        <div className="mb-4"><Alert tone="green">Converted. <Link className="font-medium underline" href={`/crm/accounts/${lead.converted_account_id}`}>Open customer</Link></Alert></div>
      )}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="Details" action={<StatusBadge status={lead.status} />} />
          <dl className="divide-y divide-line text-sm">
            {[["Email", lead.email], ["Phone", lead.phone], ["Source", label(lead.source)], ["Estimated value", money(lead.estimated_value)],
              ["Score", lead.score], ["Created", date(lead.created_at)], ["Lost reason", lead.lost_reason]].filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => (
              <div key={String(k)} className="flex justify-between gap-3 px-5 py-2.5"><dt className="text-muted">{k}</dt><dd className="text-right">{String(v)}</dd></div>
            ))}
          </dl>
          {lead.notes && <p className="whitespace-pre-line border-t border-line px-5 py-3 text-sm">{lead.notes}</p>}
        </Card>
        <div className="lg:col-span-2"><ActivityPanel relatedType="lead" relatedId={lead.id} /></div>
      </div>
      <FormDialog open={edit} onClose={() => setEdit(false)} title="Edit lead" fields={LEAD_FIELDS} initial={lead}
        submit={async (v) => { await api.patch(`/crm/leads/${id}`, v); toast.success("Lead updated"); reload(); }} />
      <FormDialog open={convert} onClose={() => setConvert(false)} title="Convert lead" fields={CONVERT} submitLabel="Convert"
        initial={{ create_opportunity: true, opportunity_value: lead.estimated_value, account_name: lead.company ?? lead.name }}
        submit={async (v) => {
          const r = await api.post<{ account_id: string }>(`/crm/leads/${id}:convert`, { ...v, existing_account_id: v.existing_account_id || null });
          toast.success("Lead converted");
          router.push(`/crm/accounts/${r.account_id}`);
        }} />
    </>
  );
}
