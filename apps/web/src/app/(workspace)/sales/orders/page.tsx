"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { DataTable } from "@/components/data-table";
import { ModuleBanner, PageHeader } from "@/components/page";
import { Badge, Button, StatusBadge } from "@/components/ui";
import { date, money } from "@/lib/format";
import { useSession } from "@/lib/session";

type SO = { id: string; number: string; account_name: string; status: string; order_date: string; grand_total: string; invoice_id: string | null; customer_po: string | null };

export default function OrdersPage() {
  const { can, writable } = useSession();
  return (
    <>
      <PageHeader title="Sales orders" crumbs={[{ label: "Sales" }, { label: "Sales orders" }]}
        actions={can("sales.order.create") && writable("sales") && <Link href="/sales/orders/new"><Button><Plus className="h-4 w-4" />New order</Button></Link>} />
      <ModuleBanner module="sales" />
      <DataTable<SO> endpoint="/sales/orders" rowHref={(r) => `/sales/orders/${r.id}`} searchPlaceholder="Search number, customer, PO"
        filters={[{ key: "status", label: "Status", options: ["draft", "confirmed", "delivered", "cancelled"].map((v) => ({ value: v, label: v })) }]}
        columns={[
          { key: "number", header: "Order" },
          { key: "account_name", header: "Customer" },
          { key: "customer_po", header: "Customer PO", render: (r) => r.customer_po ?? "—" },
          { key: "order_date", header: "Date", render: (r) => date(r.order_date) },
          { key: "status", header: "Status", render: (r) => <span className="flex gap-1"><StatusBadge status={r.status} />{r.invoice_id && <Badge tone="green">invoiced</Badge>}</span> },
          { key: "grand_total", header: "Total", align: "right", render: (r) => money(r.grand_total) },
        ]} />
    </>
  );
}
