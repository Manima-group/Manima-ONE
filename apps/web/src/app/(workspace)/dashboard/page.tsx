"use client";

import { FileText, Plus, ReceiptText, UserPlus, Wallet } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { PageHeader } from "@/components/page";
import { Alert, Button, Card, CardHeader, ErrorState, Loading, Stat } from "@/components/ui";
import { money } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Dash = {
  sales?: { this_month: string; invoices_this_month: number; trend: { month: string; total: string }[] };
  receivables?: { total: string; overdue: string; current: string; d1_30: string; d31_60: string; d61_90: string; d90_plus: string };
  quotations?: { open_count: number; open_value: string; pending_approval: number; win_rate: number | null };
  leads?: { by_status: Record<string, number>; new_this_month: number };
  pipeline?: { stage: string; count: number; value: string }[];
  inventory?: { stock_value: string; low_stock_items: number };
  procurement?: { open_po_count: number; open_po_value: string; pending_approval: number };
  orders?: Record<string, number>;
  my_tasks?: { open: number; overdue: number; due_today: number };
};

function Bars({ rows }: { rows: { label: string; value: number; display: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="flex h-44 items-end gap-3 px-5 pb-4 pt-6" role="img" aria-label="Monthly invoiced sales">
      {rows.map((r) => (
        <div key={r.label} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
          <span className="text-[10px] text-muted">{r.value ? r.display : ""}</span>
          <div className="w-full max-w-10 rounded-t bg-brand/85 transition-all" style={{ height: `${Math.max(2, (r.value / max) * 100)}%` }} title={`${r.label}: ${r.display}`} />
          <span className="text-[11px] text-muted">{r.label.split(" ")[0]}</span>
        </div>
      ))}
    </div>
  );
}

function Dashboard() {
  const { me, can, writable } = useSession();
  const welcome = useSearchParams().get("welcome");
  const { data, error, loading, reload } = useQuery<Dash>("/reports/dashboard");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const d = data!;
  const lead = d.leads?.by_status ?? {};
  return (
    <>
      <PageHeader title={`Hello, ${me?.user.name.split(" ")[0]}`} subtitle={me?.active_tenant?.display_name}
        actions={<>
          {can("crm.lead.create") && writable("crm") && <Link href="/crm/leads?new=1"><Button variant="secondary"><UserPlus className="h-4 w-4" />Lead</Button></Link>}
          {can("sales.quotation.create") && writable("sales") && <Link href="/sales/quotations/new"><Button variant="secondary"><FileText className="h-4 w-4" />Quotation</Button></Link>}
          {can("invoicing.invoice.create") && writable("invoicing") && <Link href="/billing/invoices/new"><Button variant="secondary"><ReceiptText className="h-4 w-4" />Invoice</Button></Link>}
          {can("payments.payment.create") && writable("payments") && <Link href="/billing/payments/new"><Button><Wallet className="h-4 w-4" />Record payment</Button></Link>}
        </>} />
      {welcome && (
        <div className="mb-5"><Alert>Your company is ready. Next: add your GST registration in <Link className="font-medium underline" href="/settings/gst">Settings → GST</Link>, then invite your team in <Link className="font-medium underline" href="/settings/employees">Employees</Link>.</Alert></div>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {d.sales && <Stat label="Invoiced this month" value={money(d.sales.this_month)} hint={`${d.sales.invoices_this_month} invoices`} tone="brand" />}
        {d.receivables && <Stat label="Outstanding" value={money(d.receivables.total)} hint={<>Overdue <span className="text-red-600">{money(d.receivables.overdue)}</span></>} />}
        {d.quotations && <Stat label="Open quotations" value={money(d.quotations.open_value)} hint={`${d.quotations.open_count} sent · win rate ${d.quotations.win_rate ?? "—"}%`} />}
        {d.leads && <Stat label="New leads this month" value={d.leads.new_this_month} hint={`${lead.qualified ?? 0} qualified · ${lead.new ?? 0} new`} />}
        {d.my_tasks && <Stat label="My open tasks" value={d.my_tasks.open} hint={<><span className="text-red-600">{d.my_tasks.overdue} overdue</span> · {d.my_tasks.due_today} due today</>} tone={d.my_tasks.overdue ? "red" : undefined} />}
        {d.inventory && <Stat label="Stock value" value={money(d.inventory.stock_value)} hint={<Link href="/inventory/stock?low=1" className="text-brand hover:underline">{d.inventory.low_stock_items} low-stock items</Link>} />}
        {d.procurement && <Stat label="Open purchase orders" value={money(d.procurement.open_po_value)} hint={`${d.procurement.open_po_count} open · ${d.procurement.pending_approval} awaiting approval`} />}
        {d.quotations && d.quotations.pending_approval > 0 && can("sales.quotation.approve") && (
          <Stat label="Approvals pending" value={d.quotations.pending_approval} hint={<Link href="/sales/quotations?approval=pending" className="text-brand hover:underline">Review discounts</Link>} tone="brand" />
        )}
      </div>
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        {d.sales && (
          <Card className="lg:col-span-2">
            <CardHeader title="Invoiced sales — last 6 months" />
            <Bars rows={d.sales.trend.map((t) => ({ label: t.month, value: Number(t.total), display: money(t.total).replace(".00", "") }))} />
          </Card>
        )}
        {d.receivables && (
          <Card>
            <CardHeader title="Receivables ageing" action={can("reports.receivables.read") && <Link href="/reports?tab=receivables" className="text-xs text-brand">Details</Link>} />
            <dl className="divide-y divide-line text-sm">
              {([["Not due", d.receivables.current], ["1–30 days", d.receivables.d1_30], ["31–60 days", d.receivables.d31_60], ["61–90 days", d.receivables.d61_90], ["90+ days", d.receivables.d90_plus]] as const).map(([l, v]) => (
                <div key={l} className="flex justify-between px-5 py-2.5"><dt className="text-muted">{l}</dt><dd className="tabular-nums">{money(v)}</dd></div>
              ))}
            </dl>
          </Card>
        )}
        {d.pipeline && (
          <Card className={d.sales ? "" : "lg:col-span-2"}>
            <CardHeader title="Pipeline by stage" action={<Link href="/crm/opportunities" className="text-xs text-brand">Open pipeline</Link>} />
            <dl className="divide-y divide-line text-sm">
              {d.pipeline.map((p) => (
                <div key={p.stage} className="flex justify-between px-5 py-2.5"><dt>{p.stage} <span className="text-muted">({p.count})</span></dt><dd className="tabular-nums">{money(p.value)}</dd></div>
              ))}
            </dl>
          </Card>
        )}
        {d.orders && (
          <Card>
            <CardHeader title="Sales orders" action={<Link href="/sales/orders" className="text-xs text-brand">View</Link>} />
            <dl className="divide-y divide-line text-sm">
              {["draft", "confirmed", "delivered", "cancelled"].map((s) => (
                <div key={s} className="flex justify-between px-5 py-2.5"><dt className="capitalize text-muted">{s}</dt><dd>{d.orders![s] ?? 0}</dd></div>
              ))}
            </dl>
          </Card>
        )}
        {d.my_tasks && (
          <Card>
            <CardHeader title="My work" />
            <div className="space-y-2 p-5 text-sm">
              <Link href="/workspace/tasks" className="flex items-center justify-between rounded-md border border-line px-3 py-2 hover:border-brand">
                <span>Assigned tasks</span><span className="font-semibold">{d.my_tasks.open}</span>
              </Link>
              {can("crm.lead.read_own", "crm.lead.read_all") && <Link href="/crm/leads" className="flex items-center justify-between rounded-md border border-line px-3 py-2 hover:border-brand"><span>My leads</span><Plus className="h-4 w-4 text-muted" /></Link>}
            </div>
          </Card>
        )}
      </div>
    </>
  );
}

export default function DashboardPage() {
  return <Suspense><Dashboard /></Suspense>;
}
