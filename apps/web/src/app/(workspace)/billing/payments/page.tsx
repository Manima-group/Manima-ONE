"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { DataTable } from "@/components/data-table";
import { ModuleBanner, PageHeader } from "@/components/page";
import { Button, StatusBadge } from "@/components/ui";
import { PAYMENT_METHODS } from "@/features/fields";
import { date, label, money } from "@/lib/format";
import { useSession } from "@/lib/session";

type P = { id: string; number: string; account_name: string; method: string; reference: string | null; received_on: string; amount: string; unallocated: string; status: string };

export default function PaymentsPage() {
  const { can, writable } = useSession();
  return (
    <>
      <PageHeader title="Payments received" crumbs={[{ label: "Billing" }, { label: "Payments" }]}
        actions={can("payments.payment.create") && writable("payments") && <Link href="/billing/payments/new"><Button><Plus className="h-4 w-4" />Record payment</Button></Link>} />
      <ModuleBanner module="payments" />
      <DataTable<P> endpoint="/billing/payments" rowHref={(r) => `/billing/payments/${r.id}`} searchPlaceholder="Search receipt, reference, customer"
        filters={[{ key: "method", label: "Method", options: PAYMENT_METHODS.map((m) => ({ value: m, label: label(m) })) },
          { key: "status", label: "Status", options: [{ value: "succeeded", label: "Succeeded" }, { value: "refunded", label: "Refunded" }] }]}
        columns={[
          { key: "number", header: "Receipt" },
          { key: "account_name", header: "Customer" },
          { key: "received_on", header: "Date", render: (r) => date(r.received_on) },
          { key: "method", header: "Method", render: (r) => label(r.method) },
          { key: "reference", header: "Reference", render: (r) => r.reference ?? "—" },
          { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "unallocated", header: "Unallocated", align: "right", render: (r) => money(r.unallocated) },
          { key: "amount", header: "Amount", align: "right", render: (r) => money(r.amount) },
        ]} />
    </>
  );
}
