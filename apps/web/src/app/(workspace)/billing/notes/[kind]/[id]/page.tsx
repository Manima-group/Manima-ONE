"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { DocLines, PrintButton, type DocTotals } from "@/components/documents";
import { ConfirmButton, PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Card, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { date, label } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Note = DocTotals & { id: string; note_type: string; number: string | null; invoice_id: string; invoice_number: string; account_name: string;
  reason: string; note_date: string; description: string | null; document_status: string; lines: never[] };

export default function NoteDetail() {
  const { kind, id } = useParams<{ kind: string; id: string }>();
  const path = kind === "credit_note" ? "credit-notes" : "debit-notes";
  const router = useRouter();
  const toast = useToast();
  const { can, writable } = useSession();
  const { data: n, error, loading, reload } = useQuery<Note>(`/billing/${path}/${id}`);
  if (loading && !n) return <Loading />;
  if (error || !n) return <ErrorState error={error} onRetry={reload} />;
  const draft = n.document_status === "draft";
  return (
    <>
      <PageHeader title={<span className="flex items-center gap-2">{label(kind)} {n.number ?? "(draft)"} <StatusBadge status={n.document_status} /></span>}
        crumbs={[{ label: "Billing" }, { label: kind === "credit_note" ? "Credit notes" : "Debit notes", href: `/billing/${path}` }, { label: n.number ?? "Draft" }]}
        actions={<div className="no-print flex gap-2">
          <PrintButton />
          {draft && writable("invoicing") && can("invoicing.note.create") && <ConfirmButton label="Delete" variant="danger" size="md" confirm="Delete this draft?" onConfirm={async () => { await api.del(`/billing/${path}/${id}`); router.push(`/billing/${path}`); }} />}
          {draft && writable("invoicing") && can("invoicing.note.issue") && (
            <ConfirmButton label="Issue" variant="primary" size="md" confirm="Issuing assigns a number and adjusts the invoice balance." onConfirm={async () => { await api.post(`/billing/${path}/${id}:issue`); toast.success("Issued"); reload(); }} />
          )}
        </div>} />
      <Card className="print-area">
        <div className="grid grid-cols-2 gap-4 border-b border-line p-5 text-sm sm:grid-cols-4">
          <div><p className="text-xs text-muted">Against invoice</p><Link className="font-medium hover:text-brand" href={`/billing/invoices/${n.invoice_id}`}>{n.invoice_number}</Link></div>
          <div><p className="text-xs text-muted">Customer</p><p>{n.account_name}</p></div>
          <div><p className="text-xs text-muted">Date</p><p>{date(n.note_date)}</p></div>
          <div><p className="text-xs text-muted">Reason</p><p>{label(n.reason)}</p></div>
        </div>
        <DocLines lines={n.lines} totals={n} footer={n.description && <p className="max-w-md whitespace-pre-line text-muted">{n.description}</p>} />
      </Card>
    </>
  );
}
