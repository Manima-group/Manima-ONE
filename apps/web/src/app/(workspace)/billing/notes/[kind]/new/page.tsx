"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { DocEditor, linesFromDoc } from "@/components/documents";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { ErrorState, Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { label, today } from "@/lib/format";
import { useQuery } from "@/lib/hooks";

function NewNote() {
  const { kind } = useParams<{ kind: "credit_note" | "debit_note" }>();
  const invoiceId = useSearchParams().get("invoice");
  const router = useRouter();
  const toast = useToast();
  const reasons = useQuery<Record<string, string[]>>("/billing/note-reasons");
  const inv = useQuery<{ id: string; number: string; lines: Record<string, unknown>[] }>(invoiceId ? `/billing/invoices/${invoiceId}` : null);
  if (!invoiceId) return <ErrorState error={{ message: "Open an issued invoice and choose Credit note or Debit note." }} />;
  if (reasons.loading || inv.loading || !inv.data || !reasons.data) return inv.error ? <ErrorState error={inv.error} /> : <Loading />;
  const path = kind === "credit_note" ? "credit-notes" : "debit-notes";
  return (
    <>
      <PageHeader title={`New ${label(kind).toLowerCase()} for ${inv.data.number}`}
        crumbs={[{ label: "Billing" }, { label: "Invoices", href: "/billing/invoices" }, { label: inv.data.number, href: `/billing/invoices/${invoiceId}` }, { label: label(kind) }]} />
      <DocEditor title={`${label(kind)} details`} discount={false}
        headerFields={[
          { name: "reason", label: "Reason", type: "select", required: true, options: reasons.data[kind].map((r) => ({ value: r, label: label(r) })) },
          { name: "note_date", label: "Date", type: "date" },
          { name: "description", label: "Description", type: "textarea" },
        ]}
        initialHeader={{ reason: reasons.data[kind][0], note_date: today() }}
        initialLines={kind === "credit_note" ? linesFromDoc(inv.data.lines) : undefined}
        submitLabel="Save draft"
        onSubmit={async (h, lines) => {
          const n = await api.post<{ id: string }>(`/billing/${path}`, { ...h, invoice_id: invoiceId, lines }, { idempotent: true });
          toast.success("Draft saved — issue it to apply to the invoice");
          router.push(`/billing/notes/${kind}/${n.id}`);
        }} />
    </>
  );
}

export default function Page() {
  return <Suspense><NewNote /></Suspense>;
}
