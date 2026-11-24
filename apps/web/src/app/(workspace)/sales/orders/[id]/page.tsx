"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { DocLines, PrintButton, type DocTotals } from "@/components/documents";
import { ConfirmButton, ModuleBanner, PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { date, dateTime, qty } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type SO = DocTotals & { id: string; number: string; status: string; account_id: string; account_name: string; order_date: string; expected_delivery: string | null;
  delivered_at: string | null; customer_po: string | null; quotation_id: string | null; invoice_id: string | null; place_of_supply: string | null; notes: string | null; lines: never[] };

export default function OrderDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { can, writable } = useSession();
  const { data: so, error, loading, reload } = useQuery<SO>(`/sales/orders/${id}`);
  if (loading && !so) return <Loading />;
  if (error || !so) return <ErrorState error={error} onRetry={reload} />;
  const w = writable("sales");
  const act = async (a: string, msg: string) => { try { await api.post(`/sales/orders/${id}:${a}`); toast.success(msg); reload(); } catch (e) { toast.error(e); } };
  return (
    <>
      <PageHeader title={<span className="flex items-center gap-2">{so.number} <StatusBadge status={so.status} /></span>}
        crumbs={[{ label: "Sales" }, { label: "Sales orders", href: "/sales/orders" }, { label: so.number }]}
        actions={<div className="no-print flex flex-wrap gap-2">
          <PrintButton />
          {w && so.status === "draft" && can("sales.order.update", "sales.order.create") && <Button onClick={() => act("confirm", "Order confirmed — stock reserved")}>Confirm & reserve stock</Button>}
          {w && so.status === "confirmed" && can("sales.order.update") && <Button onClick={() => act("deliver", "Order delivered — stock updated")}>Mark delivered</Button>}
          {so.status !== "cancelled" && !so.invoice_id && can("invoicing.invoice.create") && writable("invoicing") && (
            <Button variant="secondary" onClick={async () => { try { const inv = await api.post<{ id: string }>("/billing/invoices", { sales_order_id: id }, { idempotent: true }); toast.success("Draft invoice created"); router.push(`/billing/invoices/${inv.id}`); } catch (e) { toast.error(e); } }}>Create invoice</Button>
          )}
          {w && ["draft", "confirmed"].includes(so.status) && !so.invoice_id && can("sales.order.cancel") && (
            <ConfirmButton label="Cancel order" variant="danger" size="md" confirm="Cancel this order? Reserved stock will be released." onConfirm={async () => { await api.post(`/sales/orders/${id}:cancel`); toast.success("Order cancelled"); reload(); }} />
          )}
        </div>} />
      <ModuleBanner module="sales" />
      {so.invoice_id && <div className="mb-4"><Alert tone="green">Invoiced. <Link className="font-medium underline" href={`/billing/invoices/${so.invoice_id}`}>Open invoice</Link></Alert></div>}
      <Card className="print-area">
        <div className="grid grid-cols-2 gap-4 border-b border-line p-5 text-sm sm:grid-cols-5">
          <div><p className="text-xs text-muted">Customer</p><Link className="font-medium hover:text-brand" href={`/crm/accounts/${so.account_id}`}>{so.account_name}</Link></div>
          <div><p className="text-xs text-muted">Order date</p><p>{date(so.order_date)}</p></div>
          <div><p className="text-xs text-muted">Expected delivery</p><p>{date(so.expected_delivery)}</p></div>
          <div><p className="text-xs text-muted">Customer PO</p><p>{so.customer_po ?? "—"}</p></div>
          <div><p className="text-xs text-muted">Delivered</p><p>{so.delivered_at ? dateTime(so.delivered_at) : "—"}</p></div>
        </div>
        <DocLines lines={so.lines} totals={so} extraCol={{ header: "Delivered", render: (l) => qty(l.delivered_qty) }}
          footer={<>{so.quotation_id && <Link className="text-brand hover:underline" href={`/sales/quotations/${so.quotation_id}`}>From quotation</Link>}
            {so.notes && <p className="mt-2 whitespace-pre-line text-muted">{so.notes}</p>}</>} />
      </Card>
    </>
  );
}
