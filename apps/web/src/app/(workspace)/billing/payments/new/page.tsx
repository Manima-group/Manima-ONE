"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { FormFields } from "@/components/form";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, CardHeader, Input } from "@/components/ui";
import { PAYMENT_METHODS } from "@/features/fields";
import { api, ApiError, type Page } from "@/lib/api";
import { date, label, money, today } from "@/lib/format";
import { useQuery } from "@/lib/hooks";

type Inv = { id: string; number: string; invoice_date: string; due_date: string; amount_due: string; grand_total: string };

export default function NewPayment() {
  const router = useRouter();
  const toast = useToast();
  const [v, setV] = useState<Record<string, unknown>>({ method: "upi", received_on: today(), amount: "" });
  const [allocState, setAllocState] = useState<{ account?: string; alloc: Record<string, string> }>({ alloc: {} });
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const account = v.account_id as string | undefined;
  const { data: open } = useQuery<Page<Inv>>(account ? `/billing/invoices?account_id=${account}&document_status=issued&payment_status=unpaid,partially_paid&limit=100&sort=due_date` : null);
  // Allocations are scoped to the selected customer; switching customer starts empty.
  const alloc = allocState.account === account ? allocState.alloc : {};
  const setAlloc = (next: Record<string, string>) => setAllocState({ account, alloc: next });
  const allocated = Object.values(alloc).reduce((a, x) => a + Number(x || 0), 0);

  const autoAllocate = () => {
    let left = Number(v.amount || 0);
    const next: Record<string, string> = {};
    for (const i of open?.data ?? []) {
      if (left <= 0) break;
      const take = Math.min(left, Number(i.amount_due));
      next[i.id] = take.toFixed(2);
      left -= take;
    }
    setAlloc(next);
  };

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      const allocations = Object.entries(alloc).filter(([, a]) => Number(a) > 0).map(([invoice_id, amount]) => ({ invoice_id, amount }));
      const p = await api.post<{ id: string }>("/billing/payments", { ...v, reference: v.reference || null, allocations }, { idempotent: true });
      toast.success("Payment recorded");
      router.push(`/billing/payments/${p.id}`);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Record payment" crumbs={[{ label: "Billing" }, { label: "Payments", href: "/billing/payments" }, { label: "New" }]} />
      <div className="space-y-5">
        {err && <Alert tone="red">{err.message}</Alert>}
        <Card>
          <CardHeader title="Payment" />
          <div className="p-5">
            <FormFields values={v} onChange={setV} errors={err?.fieldErrors() ?? {}} fields={[
              { name: "account_id", label: "Customer", type: "remote", endpoint: "/crm/accounts", required: true },
              { name: "amount", label: "Amount received (₹)", type: "money", required: true },
              { name: "method", label: "Method", type: "select", required: true, options: PAYMENT_METHODS.map((m) => ({ value: m, label: label(m) })) },
              { name: "received_on", label: "Received on", type: "date", required: true },
              { name: "reference", label: "Reference / UTR / cheque no." },
              { name: "notes", label: "Notes", type: "textarea" },
            ]} />
          </div>
        </Card>
        {account && (
          <Card>
            <CardHeader title="Allocate to invoices" subtitle={`Allocated ${money(allocated)} of ${money(Number(v.amount || 0))} — any remainder stays as an advance.`}
              action={<Button size="sm" variant="secondary" onClick={autoAllocate} disabled={!Number(v.amount)}>Auto-allocate (oldest first)</Button>} />
            {!open?.data.length ? <p className="px-5 py-4 text-sm text-muted">No open invoices for this customer.</p> : (
              <table className="w-full text-sm">
                <thead className="bg-canvas text-left text-xs uppercase text-muted"><tr><th className="px-4 py-2">Invoice</th><th className="px-4 py-2">Date</th><th className="px-4 py-2">Due</th><th className="px-4 py-2 text-right">Balance</th><th className="w-40 px-4 py-2">Allocate</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {open.data.map((i) => (
                    <tr key={i.id}>
                      <td className="px-4 py-2 font-medium">{i.number}</td><td className="px-4 py-2">{date(i.invoice_date)}</td><td className="px-4 py-2">{date(i.due_date)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{money(i.amount_due)}</td>
                      <td className="px-4 py-2"><Input type="number" step="0.01" min="0" max={i.amount_due} value={alloc[i.id] ?? ""} aria-label={`Allocate to ${i.number}`}
                        onChange={(e) => setAlloc({ ...alloc, [i.id]: e.target.value })} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => history.back()}>Cancel</Button>
          <Button onClick={submit} loading={busy} disabled={!account || !Number(v.amount) || allocated > Number(v.amount) + 0.001}>Save payment</Button>
        </div>
      </div>
    </>
  );
}
