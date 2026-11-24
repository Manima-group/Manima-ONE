"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { DocLines, PrintButton, type DocTotals } from "@/components/documents";
import { ConfirmButton, ModuleBanner, PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, Dialog, ErrorState, Input, Loading, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { date, qty } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Line = { id: string; line_no: number; description: string; qty: string; received_qty: string; unit: string };
type PO = DocTotals & { id: string; number: string; status: string; vendor_name: string; vendor_gstin: string | null; order_date: string;
  expected_date: string | null; notes: string | null; approved_at: string | null; lines: (Line & never)[] };

export default function PODetail() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const { can, writable } = useSession();
  const { data: po, error, loading, reload } = useQuery<PO>(`/procurement/purchase-orders/${id}`);
  const [recv, setRecv] = useState(false);
  const [qtys, setQtys] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  if (loading && !po) return <Loading />;
  if (error || !po) return <ErrorState error={error} onRetry={reload} />;
  const w = writable("procurement");
  const act = async (a: string, msg: string) => { try { await api.post(`/procurement/purchase-orders/${id}:${a}`); toast.success(msg); reload(); } catch (e) { toast.error(e); } };
  const pending = (l: Line) => Number(l.qty) - Number(l.received_qty);
  return (
    <>
      <PageHeader title={<span className="flex items-center gap-2">{po.number} <StatusBadge status={po.status} /></span>}
        crumbs={[{ label: "Operations" }, { label: "Purchase orders", href: "/procurement/purchase-orders" }, { label: po.number }]}
        actions={<div className="no-print flex flex-wrap gap-2">
          <PrintButton />
          {w && po.status === "draft" && can("procurement.po.create") && <Button variant="secondary" onClick={() => act("submit", "Submitted for approval")}>Submit for approval</Button>}
          {w && ["draft", "pending_approval"].includes(po.status) && can("procurement.po.approve") && <Button onClick={() => act("approve", "PO approved")}>Approve</Button>}
          {w && po.status === "pending_approval" && can("procurement.po.approve") && <Button variant="secondary" onClick={() => act("reject", "Sent back to draft")}>Reject</Button>}
          {w && po.status === "approved" && can("procurement.po.create") && <Button variant="secondary" onClick={() => act("send", "PO sent to vendor")}>Send to vendor</Button>}
          {w && ["approved", "sent", "partially_received"].includes(po.status) && can("procurement.po.receive") && (
            <Button onClick={() => { setQtys(Object.fromEntries(po.lines.map((l: Line) => [l.id, String(pending(l))]))); setErr(null); setRecv(true); }}>Receive goods</Button>
          )}
          {w && ["draft", "pending_approval", "approved", "sent"].includes(po.status) && can("procurement.po.create") && (
            <ConfirmButton label="Cancel PO" variant="danger" size="md" confirm="Cancel this purchase order?" onConfirm={async () => { await api.post(`/procurement/purchase-orders/${id}:cancel`); reload(); }} />
          )}
        </div>} />
      <ModuleBanner module="procurement" />
      {po.status === "pending_approval" && <div className="mb-4"><Alert>Awaiting approval.</Alert></div>}
      <Card className="print-area">
        <div className="grid grid-cols-2 gap-4 border-b border-line p-5 text-sm sm:grid-cols-4">
          <div><p className="text-xs text-muted">Vendor</p><p className="font-medium">{po.vendor_name}</p>{po.vendor_gstin && <p className="text-xs text-muted">GSTIN {po.vendor_gstin}</p>}</div>
          <div><p className="text-xs text-muted">PO date</p><p>{date(po.order_date)}</p></div>
          <div><p className="text-xs text-muted">Expected</p><p>{date(po.expected_date)}</p></div>
          <div><p className="text-xs text-muted">Approved</p><p>{po.approved_at ? date(po.approved_at) : "—"}</p></div>
        </div>
        <DocLines lines={po.lines} totals={po} extraCol={{ header: "Received", render: (l) => qty(l.received_qty) }}
          footer={po.notes && <p className="max-w-md whitespace-pre-line text-muted">{po.notes}</p>} />
      </Card>
      <Dialog open={recv} onClose={() => setRecv(false)} title="Receive goods (GRN)" wide
        footer={<><Button variant="secondary" onClick={() => setRecv(false)}>Cancel</Button>
          <Button onClick={async () => {
            const lines = Object.entries(qtys).filter(([, q]) => Number(q) > 0).map(([line_id, q]) => ({ line_id, qty: q }));
            if (!lines.length) return setErr("Enter at least one quantity.");
            try { const r = await api.post<{ grn: string }>(`/procurement/purchase-orders/${id}/receipts`, { lines }, { idempotent: true }); toast.success(`Goods received (${r.grn})`, "Stock updated"); setRecv(false); reload(); }
            catch (e) { setErr((e as ApiError).message); }
          }}>Post receipt</Button></>}>
        {err && <div className="mb-3"><Alert tone="red">{err}</Alert></div>}
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-muted"><tr><th className="py-2">Item</th><th className="py-2 text-right">Ordered</th><th className="py-2 text-right">Received</th><th className="w-36 py-2 pl-4">Receive now</th></tr></thead>
          <tbody className="divide-y divide-line">
            {po.lines.map((l: Line) => (
              <tr key={l.id}>
                <td className="py-2">{l.description}</td><td className="py-2 text-right">{qty(l.qty)}</td><td className="py-2 text-right">{qty(l.received_qty)}</td>
                <td className="py-2 pl-4"><Input type="number" min="0" max={pending(l)} step="any" disabled={pending(l) <= 0} aria-label={`Receive ${l.description}`}
                  value={qtys[l.id] ?? ""} onChange={(e) => setQtys({ ...qtys, [l.id]: e.target.value })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Dialog>
    </>
  );
}
