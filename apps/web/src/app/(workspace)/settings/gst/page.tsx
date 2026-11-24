"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { FormDialog, type FieldDef } from "@/components/form";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { label } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Reg = { id: string; gstin: string; legal_name: string; trade_name: string | null; state_code: string; registration_type: string; is_default: boolean; address: Record<string, string> };
type Series = { id: string; doc_type: string; financial_year: string; prefix: string; padding: number; next_value: number };

const REG_FIELDS: FieldDef[] = [
  { name: "gstin", label: "GSTIN", required: true, hint: "State code and PAN are derived from the GSTIN" },
  { name: "registration_type", label: "Registration type", type: "select", required: true, options: [{ value: "regular", label: "Regular" }, { value: "composition", label: "Composition (bill of supply)" }, { value: "sez_unit", label: "SEZ unit" }] },
  { name: "legal_name", label: "Legal name", required: true },
  { name: "trade_name", label: "Trade name" },
  { name: "address.line1", path: ["address", "line1"], label: "Principal place of business", colSpan: 2 },
  { name: "address.city", path: ["address", "city"], label: "City" },
  { name: "address.pincode", path: ["address", "pincode"], label: "PIN code" },
  { name: "is_default", label: "Default registration for new documents", type: "checkbox" },
];

export default function GstSettings() {
  const { can } = useSession();
  const toast = useToast();
  const regs = useQuery<Reg[]>("/tenant/gst-registrations");
  const series = useQuery<Series[]>("/tenant/number-series");
  const [edit, setEdit] = useState<Reg | "new" | null>(null);
  const [ser, setSer] = useState<Series | null>(null);
  const manage = can("core.gst.manage");
  if (regs.loading && !regs.data) return <Loading />;
  if (regs.error) return <ErrorState error={regs.error} />;
  return (
    <>
      <PageHeader title="GST & numbering" crumbs={[{ label: "Settings" }, { label: "GST" }]}
        actions={manage && <Button onClick={() => setEdit("new")}><Plus className="h-4 w-4" />Add GSTIN</Button>} />
      <Card>
        <CardHeader title="GST registrations" subtitle="Each GSTIN keeps its own invoice number series." />
        {!regs.data?.length ? <EmptyState title="No GST registration yet" description="Add your GSTIN to issue tax invoices." action={manage && <Button onClick={() => setEdit("new")}>Add GSTIN</Button>} /> : (
          <ul className="divide-y divide-line">
            {regs.data.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
                <div>
                  <p className="font-mono text-sm font-medium">{r.gstin} {r.is_default && <Badge tone="orange">default</Badge>}</p>
                  <p className="text-sm text-muted">{r.trade_name ?? r.legal_name} · State {r.state_code} · {label(r.registration_type)}</p>
                </div>
                {manage && <Button size="sm" variant="secondary" onClick={() => setEdit(r)}>Edit</Button>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="mt-6">
        <CardHeader title="Document number series" subtitle="Created automatically on first use each financial year. Numbers never go backwards." />
        {!series.data?.length ? <p className="px-5 py-4 text-sm text-muted">No series yet — they appear after the first document is numbered.</p> : (
          <table className="w-full text-sm">
            <thead className="bg-canvas text-left text-xs uppercase text-muted"><tr><th className="px-4 py-2">Document</th><th className="px-4 py-2">FY</th><th className="px-4 py-2">Prefix</th><th className="px-4 py-2">Next number</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {series.data.map((s) => (
                <tr key={s.id}><td className="px-4 py-2">{label(s.doc_type)}</td><td className="px-4 py-2">{s.financial_year}</td>
                  <td className="px-4 py-2 font-mono">{s.prefix}</td><td className="px-4 py-2 font-mono">{s.prefix}{String(s.next_value).padStart(s.padding, "0")}</td>
                  <td className="px-4 py-2 text-right">{manage && <Button size="sm" variant="ghost" onClick={() => setSer(s)}>Edit</Button>}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <FormDialog open={!!edit} onClose={() => setEdit(null)} title={edit === "new" ? "Add GST registration" : "Edit GST registration"} fields={REG_FIELDS}
        initial={edit === "new" || !edit ? { registration_type: "regular", address: {} } : edit}
        submit={async (v) => {
          if (edit === "new") await api.post("/tenant/gst-registrations", v); else await api.patch(`/tenant/gst-registrations/${(edit as Reg).id}`, v);
          toast.success("GST registration saved"); regs.reload();
        }} />
      <FormDialog open={!!ser} onClose={() => setSer(null)} title="Edit number series"
        fields={[{ name: "prefix", label: "Prefix", required: true, hint: "Max 12 chars; GST documents must stay ≤ 16 characters total" }, { name: "next_value", label: "Next value", type: "number" }]}
        initial={ser ?? {}} submit={async (v) => { await api.patch(`/tenant/number-series/${ser!.id}`, { prefix: v.prefix, next_value: Number(v.next_value) }); toast.success("Series updated"); series.reload(); }} />
    </>
  );
}
