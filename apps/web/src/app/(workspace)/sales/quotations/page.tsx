"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { DataTable } from "@/components/data-table";
import { ModuleBanner, PageHeader } from "@/components/page";
import { Badge, Button, StatusBadge } from "@/components/ui";
import { date, money } from "@/lib/format";
import { useSession } from "@/lib/session";

type Q = { id: string; number: string | null; revision: number; account_name: string; status: string; approval_status: string; issue_date: string; valid_until: string; grand_total: string };

function Quotations() {
  const { can, writable } = useSession();
  const approval = useSearchParams().get("approval");
  return (
    <>
      <PageHeader title="Quotations" crumbs={[{ label: "Sales" }, { label: "Quotations" }]}
        actions={can("sales.quotation.create") && writable("sales") && <Link href="/sales/quotations/new"><Button><Plus className="h-4 w-4" />New quotation</Button></Link>} />
      <ModuleBanner module="sales" />
      <DataTable<Q> endpoint="/sales/quotations" rowHref={(r) => `/sales/quotations/${r.id}`} searchPlaceholder="Search number or customer"
        extraParams={approval ? { status: "draft" } : undefined}
        filters={[{ key: "status", label: "Status", options: ["draft", "sent", "accepted", "rejected", "expired", "converted"].map((v) => ({ value: v, label: v })) }]}
        columns={[
          { key: "number", header: "Quotation", render: (r) => <>{r.number ?? "Draft"}{r.revision > 1 && <span className="text-xs text-muted"> · rev {r.revision}</span>}</> },
          { key: "account_name", header: "Customer" },
          { key: "issue_date", header: "Date", render: (r) => date(r.issue_date) },
          { key: "valid_until", header: "Valid until", render: (r) => date(r.valid_until) },
          { key: "status", header: "Status", render: (r) => <span className="flex gap-1"><StatusBadge status={r.status} />{r.approval_status === "pending" && <Badge tone="orange">approval</Badge>}</span> },
          { key: "grand_total", header: "Total", align: "right", render: (r) => money(r.grand_total) },
        ]} />
    </>
  );
}

export default function Page() {
  return <Suspense><Quotations /></Suspense>;
}
