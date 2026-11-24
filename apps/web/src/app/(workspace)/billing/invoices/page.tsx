"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { DataTable } from "@/components/data-table";
import { ModuleBanner, PageHeader } from "@/components/page";
import { Badge, Button, StatusBadge } from "@/components/ui";
import { date, money } from "@/lib/format";
import { useSession } from "@/lib/session";

type Inv = { id: string; number: string | null; recipient_name: string; invoice_date: string; due_date: string | null; document_status: string;
  payment_status: string; grand_total: string; amount_due: string; overdue: boolean };

export default function InvoicesPage() {
  const { can, writable } = useSession();
  return (
    <>
      <PageHeader title="Invoices" crumbs={[{ label: "Billing" }, { label: "Invoices" }]}
        actions={can("invoicing.invoice.create") && writable("invoicing") && <Link href="/billing/invoices/new"><Button><Plus className="h-4 w-4" />New invoice</Button></Link>} />
      <ModuleBanner module="invoicing" />
      <DataTable<Inv> endpoint="/billing/invoices" rowHref={(r) => `/billing/invoices/${r.id}`} searchPlaceholder="Search number, customer, GSTIN"
        filters={[
          { key: "document_status", label: "Status", options: ["draft", "issued", "cancelled"].map((v) => ({ value: v, label: v })) },
          { key: "payment_status", label: "Payment", options: ["unpaid", "partially_paid", "paid", "overpaid"].map((v) => ({ value: v, label: v.replace("_", " ") })) },
          { key: "overdue", label: "Overdue", options: [{ value: "true", label: "Overdue only" }] },
        ]}
        columns={[
          { key: "number", header: "Invoice", render: (r) => r.number ?? "Draft" },
          { key: "recipient_name", header: "Customer" },
          { key: "invoice_date", header: "Date", render: (r) => date(r.invoice_date) },
          { key: "due_date", header: "Due", render: (r) => <span className={r.overdue ? "font-medium text-red-600" : ""}>{date(r.due_date)}</span> },
          { key: "status", header: "Status", render: (r) => <span className="flex gap-1"><StatusBadge status={r.document_status} />{r.document_status === "issued" && <StatusBadge status={r.payment_status} />}{r.overdue && <Badge tone="red">overdue</Badge>}</span> },
          { key: "grand_total", header: "Total", align: "right", render: (r) => money(r.grand_total) },
          { key: "amount_due", header: "Balance", align: "right", render: (r) => money(r.amount_due) },
        ]} />
    </>
  );
}
