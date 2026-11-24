"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { DocLines, PrintButton, type DocTotals } from "@/components/documents";
import { FormDialog } from "@/components/form";
import { ConfirmButton, ModuleBanner, PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, CardHeader, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { PAYMENT_METHODS } from "@/features/fields";
import { api } from "@/lib/api";
import { date, label, money, today } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Inv = DocTotals & { id: string; number: string | null; document_type: string; scenario: string; document_status: string; payment_status: string;
  account_id: string; recipient_name: string; recipient_gstin: string | null; billing_address: Record<string, string>; invoice_date: string; due_date: string | null;
  place_of_supply: string | null; reverse_charge: boolean; credit_total: string; debit_total: string; amount_paid: string; amount_due: string; overdue: boolean;
  sales_order_id: string | null; notes: string | null; terms: string | null; cancel_reason: string | null; lines: never[];
  supplier: { gstin: string; legal_name: string; trade_name: string | null; address: Record<string, string> } | null;
  payments: { payment_id: string; number: string; method: string; received_on: string; amount: string; reversed: boolean }[];
  notes_list: { id: string; note_type: string; number: string | null; grand_total: string; document_status: string; note_date: string }[] };

export default function InvoiceDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { can, writable } = useSession();
  const { data: inv, error, loading, reload } = useQuery<Inv>(`/billing/invoices/${id}`);
  const [pay, setPay] = useState(false);
  const [cancel, setCancel] = useState(false);
  if (loading && !inv) return <Loading />;
  if (error || !inv) return <ErrorState error={error} onRetry={reload} />;
  const w = writable("invoicing");
  const draft = inv.document_status === "draft";
  const issued = inv.document_status === "issued";
  const title = inv.document_type === "bill_of_supply" ? "Bill of supply" : "Tax invoice";
  return (
    <>
      <PageHeader title={<span className="flex items-center gap-2">{inv.number ?? "Draft invoice"} <StatusBadge status={inv.document_status} />{issued && <StatusBadge status={inv.payment_status} />}</span>}
        crumbs={[{ label: "Billing" }, { label: "Invoices", href: "/billing/invoices" }, { label: inv.number ?? "Draft" }]}
        actions={<div className="no-print flex flex-wrap gap-2">
          <PrintButton />
          {w && draft && can("invoicing.invoice.create") && <Link href={`/billing/invoices/${id}/edit`}><Button variant="secondary">Edit</Button></Link>}
          {w && draft && can("invoicing.invoice.create") && <ConfirmButton label="Delete" variant="danger" size="md" confirm="Delete this draft?" onConfirm={async () => { await api.del(`/billing/invoices/${id}`); router.push("/billing/invoices"); }} />}
          {w && draft && can("invoicing.invoice.issue") && (
            <ConfirmButton label="Issue invoice" variant="primary" size="md" title="Issue this invoice?"
              confirm="Issuing assigns the next GST invoice number. Issued invoices cannot be edited — corrections need a credit or debit note."
              onConfirm={async () => { await api.post(`/billing/invoices/${id}:issue`, {}, { idempotent: true }); toast.success("Invoice issued"); reload(); }} />
          )}
          {issued && Number(inv.amount_due) > 0 && can("payments.payment.create") && writable("payments") && <Button onClick={() => setPay(true)}>Record payment</Button>}
          {issued && w && can("invoicing.note.create") && <>
            <Link href={`/billing/notes/credit_note/new?invoice=${id}`}><Button variant="secondary">Credit note</Button></Link>
            <Link href={`/billing/notes/debit_note/new?invoice=${id}`}><Button variant="secondary">Debit note</Button></Link>
          </>}
          {issued && w && can("invoicing.invoice.cancel") && <Button variant="danger" onClick={() => setCancel(true)}>Cancel</Button>}
        </div>} />
      <ModuleBanner module="invoicing" />
      {inv.document_status === "cancelled" && <div className="mb-4"><Alert tone="red">Cancelled: {inv.cancel_reason}</Alert></div>}
      {inv.overdue && <div className="mb-4"><Alert tone="red">Overdue since {date(inv.due_date)} — {money(inv.amount_due)} outstanding.</Alert></div>}
      <Card className="print-area">
        <div className="flex flex-wrap justify-between gap-4 border-b border-line p-5">
          <div className="text-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-brand">{title}</p>
            {inv.supplier ? <>
              <p className="mt-1 font-semibold">{inv.supplier.trade_name ?? inv.supplier.legal_name}</p>
              <p className="text-muted">GSTIN {inv.supplier.gstin}</p>
              <p className="text-muted">{[inv.supplier.address?.line1, inv.supplier.address?.city, inv.supplier.address?.pincode].filter(Boolean).join(", ")}</p>
            </> : <p className="mt-1 text-sm text-red-600">No GST registration — add one in Settings → GST before issuing.</p>}
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
            <dt className="text-muted">Invoice no.</dt><dd className="font-medium">{inv.number ?? "—"}</dd>
            <dt className="text-muted">Date</dt><dd>{date(inv.invoice_date)}</dd>
            <dt className="text-muted">Due</dt><dd>{date(inv.due_date)}</dd>
            <dt className="text-muted">Place of supply</dt><dd>{inv.place_of_supply ?? "—"}</dd>
            <dt className="text-muted">Scenario</dt><dd className="uppercase">{inv.scenario}</dd>
            <dt className="text-muted">Reverse charge</dt><dd>{inv.reverse_charge ? "Yes" : "No"}</dd>
          </dl>
        </div>
        <div className="border-b border-line px-5 py-3 text-sm">
          <p className="text-xs text-muted">Bill to</p>
          <Link href={`/crm/accounts/${inv.account_id}`} className="font-medium hover:text-brand">{inv.recipient_name}</Link>
          {inv.recipient_gstin && <span className="text-muted"> · GSTIN {inv.recipient_gstin}</span>}
          {inv.billing_address?.city && <p className="text-muted">{[inv.billing_address.line1, inv.billing_address.city].filter(Boolean).join(", ")}</p>}
        </div>
        <DocLines lines={inv.lines} totals={inv} footer={<>
          {inv.terms && <p className="max-w-md whitespace-pre-line text-muted">{inv.terms}</p>}
          {issued && <dl className="mt-3 w-60 space-y-1">
            {Number(inv.credit_total) > 0 && <div className="flex justify-between"><dt className="text-muted">Credit notes</dt><dd>−{money(inv.credit_total)}</dd></div>}
            {Number(inv.debit_total) > 0 && <div className="flex justify-between"><dt className="text-muted">Debit notes</dt><dd>+{money(inv.debit_total)}</dd></div>}
            <div className="flex justify-between"><dt className="text-muted">Paid</dt><dd>{money(inv.amount_paid)}</dd></div>
            <div className="flex justify-between font-semibold"><dt>Balance due</dt><dd>{money(inv.amount_due)}</dd></div>
          </dl>}
        </>} />
      </Card>
      <div className="no-print mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Payments" />
          <ul className="divide-y divide-line text-sm">
            {!inv.payments.length && <li className="px-5 py-4 text-muted">No payments yet.</li>}
            {inv.payments.map((p) => (
              <li key={p.payment_id} className="flex justify-between px-5 py-2.5">
                <Link href={`/billing/payments/${p.payment_id}`} className="hover:text-brand">{p.number} · {label(p.method)} · {date(p.received_on)}</Link>
                <span className={p.reversed ? "text-muted line-through" : ""}>{money(p.amount)}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader title="Credit & debit notes" />
          <ul className="divide-y divide-line text-sm">
            {!inv.notes_list.length && <li className="px-5 py-4 text-muted">None.</li>}
            {inv.notes_list.map((n) => (
              <li key={n.id} className="flex justify-between px-5 py-2.5">
                <Link href={`/billing/notes/${n.note_type}/${n.id}`} className="hover:text-brand">{label(n.note_type)} {n.number ?? "(draft)"}</Link>
                <span className="flex items-center gap-2"><StatusBadge status={n.document_status} />{money(n.grand_total)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <FormDialog open={pay} onClose={() => setPay(false)} title={`Record payment for ${inv.number}`} submitLabel="Record payment"
        fields={[
          { name: "amount", label: "Amount (₹)", type: "money", required: true },
          { name: "method", label: "Method", type: "select", required: true, options: PAYMENT_METHODS.map((m) => ({ value: m, label: label(m) })) },
          { name: "received_on", label: "Received on", type: "date", required: true },
          { name: "reference", label: "Reference / UTR" },
          { name: "notes", label: "Notes", type: "textarea" },
        ]}
        initial={{ amount: inv.amount_due, method: "upi", received_on: today() }}
        submit={async (v) => {
          await api.post("/billing/payments", { ...v, account_id: inv.account_id, allocations: [{ invoice_id: inv.id, amount: v.amount }] }, { idempotent: true });
          toast.success("Payment recorded"); reload();
        }} />
      <FormDialog open={cancel} onClose={() => setCancel(false)} title="Cancel invoice" submitLabel="Cancel invoice"
        fields={[{ name: "reason", label: "Reason", type: "textarea", required: true }]} initial={{}}
        submit={async (v) => { await api.post(`/billing/invoices/${id}:cancel`, v); toast.success("Invoice cancelled"); reload(); }} />
    </>
  );
}
