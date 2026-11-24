"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { FormDialog } from "@/components/form";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { api, type Page } from "@/lib/api";
import { date, label, money } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type P = { id: string; number: string; account_id: string; account_name: string; method: string; reference: string | null; amount: string; status: string;
  received_on: string; notes: string | null; allocated: string; unallocated: string;
  allocations: { invoice_id: string; invoice_number: string; amount: string; reversed: boolean }[] };

export default function PaymentDetail() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const { can, writable } = useSession();
  const { data: p, error, loading, reload } = useQuery<P>(`/billing/payments/${id}`);
  const [alloc, setAlloc] = useState(false);
  const [refund, setRefund] = useState(false);
  const open = useQuery<Page<{ id: string; number: string; amount_due: string }>>(p ? `/billing/invoices?account_id=${p.account_id}&document_status=issued&payment_status=unpaid,partially_paid&limit=100` : null);
  if (loading && !p) return <Loading />;
  if (error || !p) return <ErrorState error={error} onRetry={reload} />;
  const w = writable("payments");
  return (
    <>
      <PageHeader title={<span className="flex items-center gap-2">Receipt {p.number} <StatusBadge status={p.status} /></span>}
        crumbs={[{ label: "Billing" }, { label: "Payments", href: "/billing/payments" }, { label: p.number }]}
        actions={<>
          {w && p.status === "succeeded" && Number(p.unallocated) > 0 && can("payments.payment.create") && <Button onClick={() => setAlloc(true)}>Allocate advance</Button>}
          {w && p.status === "succeeded" && can("payments.payment.refund") && <Button variant="danger" onClick={() => setRefund(true)}>Refund / reverse</Button>}
        </>} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="Details" />
          <dl className="divide-y divide-line text-sm">
            {[["Customer", <Link key="c" className="hover:text-brand" href={`/crm/accounts/${p.account_id}`}>{p.account_name}</Link>], ["Amount", money(p.amount)],
              ["Method", label(p.method)], ["Reference", p.reference ?? "—"], ["Received on", date(p.received_on)], ["Allocated", money(p.allocated)],
              ["Unallocated (advance)", money(p.unallocated)]].map(([k, v]) => (
              <div key={String(k)} className="flex justify-between px-5 py-2.5"><dt className="text-muted">{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
          {p.notes && <p className="border-t border-line px-5 py-3 text-sm">{p.notes}</p>}
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="Allocations" />
          <ul className="divide-y divide-line text-sm">
            {!p.allocations.length && <li className="px-5 py-4 text-muted">Not allocated to any invoice.</li>}
            {p.allocations.map((a, i) => (
              <li key={i} className="flex justify-between px-5 py-2.5">
                <Link className="hover:text-brand" href={`/billing/invoices/${a.invoice_id}`}>{a.invoice_number}</Link>
                <span className={a.reversed ? "text-muted line-through" : ""}>{money(a.amount)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <FormDialog open={alloc} onClose={() => setAlloc(false)} title="Allocate advance" submitLabel="Allocate"
        fields={[{ name: "invoice_id", label: "Invoice", type: "select", required: true, options: (open.data?.data ?? []).map((i) => ({ value: i.id, label: `${i.number} · due ${money(i.amount_due)}` })) },
          { name: "amount", label: "Amount (₹)", type: "money", required: true }]}
        initial={{ amount: p.unallocated }}
        submit={async (v) => { await api.post(`/billing/payments/${id}:allocate`, { allocations: [v] }); toast.success("Allocated"); reload(); }} />
      <FormDialog open={refund} onClose={() => setRefund(false)} title="Refund / reverse payment" submitLabel="Reverse payment"
        fields={[{ name: "reason", label: "Reason", type: "textarea", required: true }]} initial={{}}
        submit={async (v) => { await api.post(`/billing/payments/${id}:refund`, v); toast.success("Payment reversed"); reload(); }} />
    </>
  );
}
