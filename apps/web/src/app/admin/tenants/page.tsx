"use client";

import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { DataTable } from "@/components/data-table";
import { FormDialog } from "@/components/form";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Button, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { date } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type T = { id: string; legal_name: string; slug: string; status: string; plan: string | null; subscription_status: string | null; members: number; created_at: string };

export default function Tenants() {
  const { canPlatform } = useSession();
  const toast = useToast();
  const router = useRouter();
  const plans = useQuery<{ key: string; name: string }[]>("/platform/plans");
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<{ email: string; pw: string } | null>(null);
  return (
    <>
      <PageHeader title="Tenants" crumbs={[{ label: "Platform" }, { label: "Tenants" }]}
        actions={canPlatform("platform.tenant.create") && <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" />Create tenant</Button>} />
      {created && <div className="mb-4"><Alert tone="green">Tenant created. Owner {created.email} temporary password: <code>{created.pw}</code> — share securely; they should change it at first sign-in.</Alert></div>}
      <DataTable<T> endpoint="/platform/tenants" rowHref={(r) => `/admin/tenants/${r.id}`} searchPlaceholder="Search company or slug"
        filters={[{ key: "status", label: "Status", options: ["active", "suspended", "closing", "closed"].map((v) => ({ value: v, label: v })) }]}
        columns={[
          { key: "legal_name", header: "Company" },
          { key: "slug", header: "Slug", render: (r) => <code className="text-xs">{r.slug}</code> },
          { key: "plan", header: "Plan", render: (r) => <span>{r.plan ?? "—"} {r.subscription_status && <StatusBadge status={r.subscription_status} />}</span> },
          { key: "members", header: "Users", align: "right" as const, render: (r) => r.members },
          { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "created_at", header: "Created", render: (r) => date(r.created_at) },
        ]} />
      <FormDialog open={open} onClose={() => setOpen(false)} title="Create tenant (assisted onboarding)" submitLabel="Create tenant"
        fields={[
          { name: "legal_name", label: "Company legal name", required: true, colSpan: 2 },
          { name: "state_code", label: "State", type: "state" },
          { name: "plan_key", label: "Plan", type: "select", required: true, options: (plans.data ?? []).map((p) => ({ value: p.key, label: p.name })) },
          { name: "owner_name", label: "Owner name", required: true },
          { name: "owner_email", label: "Owner email", type: "email", required: true },
          { name: "owner_password", label: "Initial password (optional)", hint: "Leave empty to generate a temporary password" },
          { name: "trial_days", label: "Trial days (0 = active now)", type: "number" },
        ]}
        initial={{ plan_key: "growth", trial_days: "14" }}
        submit={async (v) => {
          const r = await api.post<{ id: string; owner_temp_password: string | null }>("/platform/tenants", { ...v, trial_days: Number(v.trial_days) || null, owner_password: v.owner_password || null });
          toast.success("Tenant created");
          if (r.owner_temp_password) setCreated({ email: String(v.owner_email), pw: r.owner_temp_password }); else router.push(`/admin/tenants/${r.id}`);
        }} />
    </>
  );
}
