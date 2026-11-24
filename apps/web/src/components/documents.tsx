"use client";

import { Plus, Printer, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { type ApiError, type Page } from "@/lib/api";
import { money, qty as fmtQty } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { GST_RATES } from "@/features/fields";
import { FormFields, type FieldDef } from "./form";
import { Alert, Button, Card, CardHeader, Input, Select } from "./ui";

type Item = { id: string; sku: string; name: string; price: string; purchase_price: string; gst_rate: string; unit: string; hsn_sac: string | null; type: string };
export type LineIn = { item_id: string | null; description: string; qty: string; rate: string; discount_pct: string; gst_rate: string; unit: string; hsn_sac?: string | null };

const blank = (): LineIn => ({ item_id: null, description: "", qty: "1", rate: "0", discount_pct: "0", gst_rate: "18", unit: "nos" });

export function linesFromDoc(lines: Record<string, unknown>[]): LineIn[] {
  return lines.map((l) => ({
    item_id: (l.item_id as string) ?? null, description: String(l.description ?? ""), qty: String(Number(l.qty)), rate: String(l.rate),
    discount_pct: String(Number(l.discount_pct)), gst_rate: String(Number(l.gst_rate)), unit: String(l.unit ?? "nos"), hsn_sac: (l.hsn_sac as string) ?? null,
  }));
}

export function DocEditor({ title, headerFields, initialHeader, initialLines, priceField = "price", onSubmit, submitLabel, discount = true }: {
  title: string; headerFields: FieldDef[]; initialHeader: Record<string, unknown>; initialLines?: LineIn[];
  priceField?: "price" | "purchase_price"; onSubmit: (header: Record<string, unknown>, lines: LineIn[]) => Promise<void>;
  submitLabel: string; discount?: boolean;
}) {
  const { data: items } = useQuery<Page<Item>>("/catalog/items?limit=200&active=true");
  const [header, setHeader] = useState<Record<string, unknown>>(initialHeader);
  const [lines, setLines] = useState<LineIn[]>(initialLines?.length ? initialLines : [blank()]);
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const byId = useMemo(() => new Map((items?.data ?? []).map((i) => [i.id, i])), [items]);

  const update = (i: number, patch: Partial<LineIn>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const pickItem = (i: number, id: string) => {
    const it = byId.get(id);
    if (!it) return update(i, { item_id: null });
    update(i, { item_id: it.id, description: it.name, rate: String(it[priceField]), gst_rate: String(Number(it.gst_rate)), unit: it.unit, hsn_sac: it.hsn_sac });
  };
  const calc = lines.map((l) => {
    const gross = Number(l.qty || 0) * Number(l.rate || 0);
    const taxable = gross * (1 - Number(l.discount_pct || 0) / 100);
    return { taxable, tax: (taxable * Number(l.gst_rate || 0)) / 100 };
  });
  const taxable = calc.reduce((a, c) => a + c.taxable, 0);
  const tax = calc.reduce((a, c) => a + c.tax, 0);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      const clean = Object.fromEntries(Object.entries(header).map(([k, v]) => [k, v === "" ? null : v]));
      await onSubmit(clean, lines.map((l) => ({ ...l, item_id: l.item_id || null })));
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }
  const fe = err?.fieldErrors() ?? {};

  return (
    <div className="space-y-5">
      {err && <Alert tone="red">{err.message}{err.details?.length > 1 && <ul className="mt-1 list-disc pl-5 text-xs">{err.details.map((d, i) => <li key={i}>{d.field}: {d.message ?? d.issue}</li>)}</ul>}</Alert>}
      <Card>
        <CardHeader title={title} />
        <div className="p-5"><FormFields fields={headerFields} values={header} onChange={setHeader} errors={fe} /></div>
      </Card>
      <Card>
        <CardHeader title="Line items" subtitle="Tax is computed on the server from the place of supply (CGST+SGST or IGST)." />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="bg-canvas text-left text-xs uppercase text-muted">
              <tr>
                <th className="px-3 py-2 w-56">Item</th><th className="px-3 py-2">Description</th><th className="px-3 py-2 w-24">Qty</th>
                <th className="px-3 py-2 w-32">Rate (₹)</th>{discount && <th className="px-3 py-2 w-20">Disc %</th>}
                <th className="px-3 py-2 w-24">GST %</th><th className="px-3 py-2 w-32 text-right">Taxable</th><th className="w-10" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {lines.map((l, i) => (
                <tr key={i}>
                  <td className="px-3 py-2">
                    <Select value={l.item_id ?? ""} onChange={(e) => pickItem(i, e.target.value)} aria-label={`Line ${i + 1} item`} invalid={!!fe[`lines.${i}.item_id`]}>
                      <option value="">Custom line…</option>
                      {(items?.data ?? []).map((it) => <option key={it.id} value={it.id}>{it.sku} · {it.name}</option>)}
                    </Select>
                  </td>
                  <td className="px-3 py-2"><Input value={l.description} onChange={(e) => update(i, { description: e.target.value })} aria-label={`Line ${i + 1} description`} invalid={!!fe[`lines.${i}.description`]} /></td>
                  <td className="px-3 py-2"><Input type="number" min="0" step="any" value={l.qty} onChange={(e) => update(i, { qty: e.target.value })} aria-label={`Line ${i + 1} quantity`} /></td>
                  <td className="px-3 py-2"><Input type="number" min="0" step="0.01" value={l.rate} onChange={(e) => update(i, { rate: e.target.value })} aria-label={`Line ${i + 1} rate`} /></td>
                  {discount && <td className="px-3 py-2"><Input type="number" min="0" max="100" step="0.01" value={l.discount_pct} onChange={(e) => update(i, { discount_pct: e.target.value })} aria-label={`Line ${i + 1} discount`} /></td>}
                  <td className="px-3 py-2">
                    <Select value={l.gst_rate} onChange={(e) => update(i, { gst_rate: e.target.value })} aria-label={`Line ${i + 1} GST rate`}>
                      {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
                    </Select>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{money(calc[i].taxable)}</td>
                  <td className="px-2 py-2">
                    <Button variant="ghost" size="icon" aria-label={`Remove line ${i + 1}`} disabled={lines.length === 1} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-start justify-between gap-4 border-t border-line p-4">
          <Button variant="secondary" size="sm" onClick={() => setLines((ls) => [...ls, blank()])}><Plus className="h-4 w-4" />Add line</Button>
          <dl className="w-64 space-y-1 text-sm">
            <div className="flex justify-between"><dt className="text-muted">Taxable value</dt><dd className="tabular-nums">{money(taxable)}</dd></div>
            <div className="flex justify-between"><dt className="text-muted">GST (estimate)</dt><dd className="tabular-nums">{money(tax)}</dd></div>
            <div className="flex justify-between border-t border-line pt-1 font-semibold"><dt>Total (approx.)</dt><dd className="tabular-nums">{money(Math.round(taxable + tax))}</dd></div>
          </dl>
        </div>
      </Card>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={() => history.back()}>Cancel</Button>
        <Button onClick={submit} loading={busy}>{submitLabel}</Button>
      </div>
    </div>
  );
}

type DocLine = { id: string; line_no: number; description: string; hsn_sac: string | null; qty: string; unit: string; rate: string; discount_pct: string;
  taxable_value: string; gst_rate: string; cgst: string; sgst: string; igst: string; total: string; delivered_qty?: string; received_qty?: string };

export type DocTotals = { subtotal?: string; discount_total?: string; taxable_total: string; cgst_total: string; sgst_total: string; igst_total: string;
  cess_total?: string; tax_total: string; round_off?: string; grand_total: string };

export function DocLines({ lines, totals, extraCol, footer }: {
  lines: DocLine[]; totals: DocTotals; extraCol?: { header: string; render: (l: DocLine) => React.ReactNode }; footer?: React.ReactNode;
}) {
  const intra = Number(totals.cgst_total) > 0 || Number(totals.igst_total) === 0;
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-canvas text-left text-xs uppercase text-muted">
            <tr>
              <th className="px-4 py-2">#</th><th className="px-4 py-2">Description</th><th className="px-4 py-2">HSN/SAC</th>
              <th className="px-4 py-2 text-right">Qty</th><th className="px-4 py-2 text-right">Rate</th><th className="px-4 py-2 text-right">Disc</th>
              <th className="px-4 py-2 text-right">Taxable</th><th className="px-4 py-2 text-right">GST</th>
              {extraCol && <th className="px-4 py-2 text-right">{extraCol.header}</th>}
              <th className="px-4 py-2 text-right">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {lines.map((l) => (
              <tr key={l.id}>
                <td className="px-4 py-2 text-muted">{l.line_no}</td>
                <td className="px-4 py-2">{l.description}</td>
                <td className="px-4 py-2 text-muted">{l.hsn_sac ?? "—"}</td>
                <td className="px-4 py-2 text-right tabular-nums">{fmtQty(l.qty)} {l.unit}</td>
                <td className="px-4 py-2 text-right tabular-nums">{money(l.rate)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{Number(l.discount_pct) ? `${Number(l.discount_pct)}%` : "—"}</td>
                <td className="px-4 py-2 text-right tabular-nums">{money(l.taxable_value)}</td>
                <td className="px-4 py-2 text-right text-xs tabular-nums">{Number(l.gst_rate)}%<br /><span className="text-muted">{money(Number(l.cgst) + Number(l.sgst) + Number(l.igst))}</span></td>
                {extraCol && <td className="px-4 py-2 text-right tabular-nums">{extraCol.render(l)}</td>}
                <td className="px-4 py-2 text-right font-medium tabular-nums">{money(l.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap justify-between gap-4 border-t border-line p-4">
        <div className="text-sm">{footer}</div>
        <dl className="w-72 space-y-1 text-sm">
          <Row k="Taxable value" v={totals.taxable_total} />
          {intra ? <><Row k="CGST" v={totals.cgst_total} /><Row k="SGST / UTGST" v={totals.sgst_total} /></> : <Row k="IGST" v={totals.igst_total} />}
          {Number(totals.cess_total ?? 0) > 0 && <Row k="Cess" v={totals.cess_total!} />}
          {totals.round_off !== undefined && Number(totals.round_off) !== 0 && <Row k="Round off" v={totals.round_off} />}
          <div className="flex justify-between border-t border-line pt-1.5 text-base font-semibold"><dt>Grand total</dt><dd className="tabular-nums">{money(totals.grand_total)}</dd></div>
        </dl>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex justify-between"><dt className="text-muted">{k}</dt><dd className="tabular-nums">{money(v)}</dd></div>;
}

export function PrintButton() {
  return <Button variant="secondary" onClick={() => window.print()}><Printer className="h-4 w-4" />Print / PDF</Button>;
}
