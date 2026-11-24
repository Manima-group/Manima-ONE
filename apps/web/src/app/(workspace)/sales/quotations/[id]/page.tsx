"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { DocLines, PrintButton } from "@/components/documents";
import { ConfirmButton, ModuleBanner, PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Badge, Button, Card, CardHeader, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { date, dateTime } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { DocTotals } from "@/components/documents";

type Q = DocTotals & { id: string; number: string | null; revision: number; status: string; approval_status: string; account_id: string; account_name: string;
  account_gstin: string | null; issue_date: string; valid_until: string; place_of_supply: string | null; terms: string | null; notes: string | null;
  sent_at: string | null; lines: never[]; revisions: { id: string; revision: number; status: string }[] };

export default function QuoteDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { can, writable } = useSession();
  const { data: q, error, loading, reload } = useQuery<Q>(`/sales/quotations/${id}`);
  if (loading && !q) return <Loading />;
  if (error || !q) return <ErrorState error={error} onRetry={reload} />;
  const w = writable("sales");
  const act = async (path: string, msg: string) => {
    try { await api.post(`/sales/quotations/${id}:${path}`); toast.success(msg); reload(); } catch (e) { toast.error(e); }
  };
  return (
    <>
      <PageHeader title={<span className="flex items-center gap-2">{q.number ?? "Draft quotation"}{q.revision > 1 && <Badge>rev {q.revision}</Badge>}<StatusBadge status={q.status} /></span>}
        crumbs={[{ label: "Sales" }, { label: "Quotations", href: "/sales/quotations" }, { label: q.number ?? "Draft" }]}
        actions={<div className="no-print flex flex-wrap gap-2">
          <PrintButton />
          {w && ["draft", "sent"].includes(q.status) && can("sales.quotation.update") && <Link href={`/sales/quotations/${id}/edit`}><Button variant="secondary">Edit</Button></Link>}
          {w && q.approval_status === "pending" && can("sales.quotation.approve") && <>
            <Button variant="secondary" onClick={() => act("reject-approval", "Discount rejected")}>Reject discount</Button>
            <Button onClick={() => act("approve", "Discount approved")}>Approve discount</Button>
          </>}
          {w && q.status === "draft" && can("sales.quotation.send") && <Button onClick={() => act("send", "Quotation sent")} disabled={["pending", "rejected"].includes(q.approval_status)}>Send to customer</Button>}
          {w && q.status === "sent" && can("sales.quotation.update") && <>
            <Button variant="secondary" onClick={() => act("decline", "Marked as declined")}>Customer declined</Button>
            <Button variant="secondary" onClick={() => act("accept", "Marked as accepted")}>Customer accepted</Button>
          </>}
          {w && ["sent", "accepted"].includes(q.status) && can("sales.order.create") && (
            <Button onClick={async () => { try { const so = await api.post<{ id: string }>(`/sales/quotations/${id}:convert`, {}, { idempotent: true }); toast.success("Sales order created"); router.push(`/sales/orders/${so.id}`); } catch (e) { toast.error(e); } }}>Convert to order</Button>
          )}
          {w && q.status === "draft" && !q.number && can("sales.quotation.delete") && (
            <ConfirmButton label="Delete" variant="danger" size="md" confirm="Delete this draft quotation?" onConfirm={async () => { await api.del(`/sales/quotations/${id}`); router.push("/sales/quotations"); }} />
          )}
        </div>} />
      <ModuleBanner module="sales" />
      {q.approval_status === "pending" && <div className="mb-4"><Alert>This quotation has a discount above your company limit and needs approval before it can be sent.</Alert></div>}
      {q.approval_status === "rejected" && <div className="mb-4"><Alert tone="red">The discount was rejected. Edit the quotation to lower the discount.</Alert></div>}
      <Card className="print-area">
        <div className="grid grid-cols-1 gap-4 border-b border-line p-5 text-sm sm:grid-cols-4">
          <div><p className="text-xs text-muted">Customer</p><Link href={`/crm/accounts/${q.account_id}`} className="font-medium hover:text-brand">{q.account_name}</Link>
            {q.account_gstin && <p className="text-xs text-muted">GSTIN {q.account_gstin}</p>}</div>
          <div><p className="text-xs text-muted">Date</p><p>{date(q.issue_date)}</p></div>
          <div><p className="text-xs text-muted">Valid until</p><p>{date(q.valid_until)}</p></div>
          <div><p className="text-xs text-muted">Place of supply</p><p>{q.place_of_supply ?? "—"}</p></div>
        </div>
        <DocLines lines={q.lines} totals={q} footer={<>
          {q.terms && <div className="max-w-md"><p className="text-xs font-medium text-muted">Terms</p><p className="whitespace-pre-line">{q.terms}</p></div>}
          {q.notes && <div className="mt-2 max-w-md"><p className="text-xs font-medium text-muted">Notes</p><p className="whitespace-pre-line">{q.notes}</p></div>}
        </>} />
      </Card>
      {q.revisions.length > 1 && (
        <Card className="no-print mt-6">
          <CardHeader title="Revisions" />
          <ul className="divide-y divide-line text-sm">
            {q.revisions.map((r) => (
              <li key={r.id} className="flex justify-between px-5 py-2.5"><Link className="hover:text-brand" href={`/sales/quotations/${r.id}`}>Revision {r.revision}</Link><StatusBadge status={r.status} /></li>
            ))}
          </ul>
        </Card>
      )}
      {q.sent_at && <p className="mt-3 text-xs text-muted">Sent {dateTime(q.sent_at)}</p>}
    </>
  );
}
