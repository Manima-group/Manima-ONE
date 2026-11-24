"use client";

import Link from "next/link";
import { DataTable } from "@/components/data-table";
import { ModuleBanner, PageHeader } from "@/components/page";
import { StatusBadge } from "@/components/ui";
import { date, label, money } from "@/lib/format";

type Note = { id: string; number: string | null; invoice_id: string; invoice_number: string | null; account_name: string | null; reason: string; note_date: string; document_status: string; grand_total: string };

export function NotesList({ kind }: { kind: "credit_note" | "debit_note" }) {
  const title = kind === "credit_note" ? "Credit notes" : "Debit notes";
  return (
    <>
      <PageHeader title={title} crumbs={[{ label: "Billing" }, { label: title }]}
        subtitle={`Raise ${kind === "credit_note" ? "a credit" : "a debit"} note from an issued invoice's page.`} />
      <ModuleBanner module="invoicing" />
      <DataTable<Note> endpoint={`/billing/${kind === "credit_note" ? "credit-notes" : "debit-notes"}`} rowHref={(r) => `/billing/notes/${kind}/${r.id}`}
        filters={[{ key: "document_status", label: "Status", options: ["draft", "issued"].map((v) => ({ value: v, label: v })) }]}
        columns={[
          { key: "number", header: "Note", render: (r) => r.number ?? "Draft" },
          { key: "invoice_number", header: "Invoice", render: (r) => <Link className="hover:text-brand" href={`/billing/invoices/${r.invoice_id}`}>{r.invoice_number}</Link> },
          { key: "account_name", header: "Customer", render: (r) => r.account_name ?? "—" },
          { key: "reason", header: "Reason", render: (r) => label(r.reason) },
          { key: "note_date", header: "Date", render: (r) => date(r.note_date) },
          { key: "document_status", header: "Status", render: (r) => <StatusBadge status={r.document_status} /> },
          { key: "grand_total", header: "Amount", align: "right", render: (r) => money(r.grand_total) },
        ]} />
    </>
  );
}
