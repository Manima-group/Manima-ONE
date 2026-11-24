"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Plus } from "lucide-react";
import { DataTable } from "@/components/data-table";
import { FormDialog } from "@/components/form";
import { LEAD_FIELDS, LEAD_SOURCES, LEAD_STATUSES } from "@/features/fields";
import { ModuleBanner, PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Button, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { date, label, money } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useRouter } from "next/navigation";

type Lead = { id: string; name: string; company: string | null; email: string | null; phone: string | null; status: string; source: string; estimated_value: string; created_at: string; score: number };

function Leads() {
  const { can, writable } = useSession();
  const toast = useToast();
  const router = useRouter();
  const params = useSearchParams();
  const [openState, setOpen] = useState(false);
  const open = openState || !!params.get("new");
  const close = () => {
    setOpen(false);
    if (params.get("new")) router.replace("/crm/leads");
  };
  const [key, setKey] = useState(0);
  return (
    <>
      <PageHeader title="Leads" crumbs={[{ label: "CRM" }, { label: "Leads" }]}
        actions={can("crm.lead.create") && writable("crm") && <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" />New lead</Button>} />
      <ModuleBanner module="crm" />
      <DataTable<Lead> endpoint="/crm/leads" reloadKey={key} rowHref={(r) => `/crm/leads/${r.id}`} searchPlaceholder="Search name, company, email, phone"
        filters={[{ key: "status", label: "Status", options: [...LEAD_STATUSES, "converted"].map((s) => ({ value: s, label: label(s) })) },
          { key: "source", label: "Source", options: LEAD_SOURCES.map((s) => ({ value: s, label: label(s) })) }]}
        columns={[
          { key: "name", header: "Name" },
          { key: "company", header: "Company", render: (r) => r.company ?? "—" },
          { key: "contact", header: "Contact", render: (r) => <span className="text-muted">{r.email ?? r.phone ?? "—"}</span> },
          { key: "source", header: "Source", render: (r) => label(r.source) },
          { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "estimated_value", header: "Value", align: "right", render: (r) => money(r.estimated_value) },
          { key: "created_at", header: "Created", render: (r) => date(r.created_at) },
        ]} />
      <FormDialog open={open} onClose={close} title="New lead" fields={LEAD_FIELDS} initial={{ source: "manual", status: "new", score: 0 }}
        submit={async (v) => {
          const r = await api.post<{ id: string; duplicates: { name: string }[] }>("/crm/leads", v);
          toast.success("Lead created", r.duplicates.length ? `Possible duplicate of ${r.duplicates.map((d) => d.name).join(", ")}` : undefined);
          setKey((k) => k + 1);
          router.push(`/crm/leads/${r.id}`);
        }} />
    </>
  );
}

export default function LeadsPage() {
  return <Suspense><Leads /></Suspense>;
}
