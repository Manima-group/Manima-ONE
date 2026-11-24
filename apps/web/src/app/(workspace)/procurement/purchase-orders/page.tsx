"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { DataTable } from "@/components/data-table";
import { ModuleBanner, PageHeader } from "@/components/page";
import { Button, StatusBadge } from "@/components/ui";
import { date, money } from "@/lib/format";
import { useSession } from "@/lib/session";

type PO = { id: string; number: string; vendor_name: string; status: string; order_date: string; expected_date: string | null; grand_total: string };
const STATUSES = ["draft", "pending_approval", "approved", "sent", "partially_received", "received", "cancelled"];

export default function POsPage() {
  const { can, writable } = useSession();
  return (
    <>
      <PageHeader title="Purchase orders" crumbs={[{ label: "Operations" }, { label: "Purchase orders" }]}
        actions={can("procurement.po.create") && writable("procurement") && <Link href="/procurement/purchase-orders/new"><Button><Plus className="h-4 w-4" />New PO</Button></Link>} />
      <ModuleBanner module="procurement" />
      <DataTable<PO> endpoint="/procurement/purchase-orders" rowHref={(r) => `/procurement/purchase-orders/${r.id}`} searchPlaceholder="Search PO number or vendor"
        filters={[{ key: "status", label: "Status", options: STATUSES.map((s) => ({ value: s, label: s.replace(/_/g, " ") })) }]}
        columns={[
          { key: "number", header: "PO" }, { key: "vendor_name", header: "Vendor" },
          { key: "order_date", header: "Date", render: (r) => date(r.order_date) },
          { key: "expected_date", header: "Expected", render: (r) => date(r.expected_date) },
          { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "grand_total", header: "Total", align: "right", render: (r) => money(r.grand_total) },
        ]} />
    </>
  );
}
